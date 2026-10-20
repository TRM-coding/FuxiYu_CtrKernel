"""Q08 回归：草稿是每个操作员的私有编辑区。

决策要点（2026-10）：
- 列表、按 id 读取、按 id 更新、删除、批量发送都必须按所属者校验；
- 一般管理权限（operator）不能读写/删除/发送别人的草稿；
- 越权失败不得改动任何数据；边界沿用现有匿名认证 / 公告管理 RBAC，不新增权限层。

本轮只跑受控本地 SQLite，不触达真实数据库 / SMTP / 宿主操作。
"""

import json

import pytest

from ...constant import AnnouncementStatus
from ...extensions import session_scope
from ...repositories import announcement_repo
from ...services.announcement_tasks import TargetEntry, start_batch_send_service
from ..assertions import assert_json_error, assert_json_success
from ..factories import create_user


def _save_draft(user, *, title="草稿", content="正文", raw_content=None, targets=None):
    with session_scope() as session:
        return announcement_repo.save_draft(
            title=title,
            content=content,
            raw_content=raw_content,
            targets=targets,
            created_by=user.id,
            session=session,
        )


def _get_draft(draft_id):
    with session_scope(commit=False) as session:
        return announcement_repo.get_draft_by_id(draft_id, session=session)


def _draft_snapshot(draft):
    """完整草稿字段快照：越权失败不得改动其中任何一项。"""

    return {
        "id": draft.id,
        "title": draft.title,
        "content": draft.content,
        "raw_content": draft.raw_content,
        "created_by": draft.created_by,
        "targets": draft.targets,
        "created_at": draft.created_at,
        "updated_at": draft.updated_at,
    }


def _announcements_snapshot():
    """全部公告的完整快照：越权发送失败不得新增或改写任何公告。"""

    with session_scope(commit=False) as session:
        rows, total = announcement_repo.list_announcements(session=session)
        return total, tuple(
            (
                row.id,
                row.title,
                row.content,
                row.raw_content,
                row.created_by,
                row.status,
                row.targets,
                row.target_snapshot,
                row.recipient_count,
                row.success_count,
                row.fail_count,
                row.created_at,
                row.sent_at,
                row.source_draft_id,
                row.template_id,
            )
            for row in rows
        )


def _act_as_tokens(monkeypatch, users_by_token: dict[str, int]) -> None:
    """让认证依赖按 cookie 里的 token 解析出不同操作员（保持既有认证/ RBAC 边界）。"""

    from ...repositories import authentications_repo
    from ...services import rbac_service

    valid_tokens = set(users_by_token)
    monkeypatch.setattr(authentications_repo, "is_token_valid", lambda token, **kw: token in valid_tokens)
    monkeypatch.setattr(
        authentications_repo,
        "get_user_id_by_token",
        lambda token, **kw: users_by_token.get(token),
    )
    monkeypatch.setattr(rbac_service, "_has_entity_direct", lambda user_id, entity: True)


def _use_operator(client, token: str) -> None:
    """把当前请求身份切到指定 token（认证仍走既有 cookie → deps 解析路径）。"""

    client.cookies.clear()
    client.cookies.set("auth_token", token)


# ══════════════════════════════════════════════════════════════════════
# 仓储层
# ══════════════════════════════════════════════════════════════════════


def test_q08_repo_read_and_delete_are_owner_scoped(db_session):
    owner = create_user()
    other = create_user()
    draft = _save_draft(owner)

    assert announcement_repo.get_draft_by_id(draft.id, session=db_session, created_by=other.id) is None
    assert announcement_repo.delete_draft(draft.id, session=db_session, created_by=other.id) is False
    assert announcement_repo.get_draft_by_id(draft.id, session=db_session) is not None

    assert announcement_repo.delete_draft(draft.id, session=db_session, created_by=owner.id) is True
    assert announcement_repo.get_draft_by_id(draft.id, session=db_session) is None


def test_q08_repo_update_other_operators_draft_rejected_and_unchanged(db_session):
    owner = create_user()
    other = create_user()
    draft = _save_draft(owner, title="原草稿", content="原正文")

    with pytest.raises(ValueError, match="draft_not_found"):
        announcement_repo.save_draft(
            title="被篡改",
            content="被篡改",
            created_by=other.id,
            draft_id=draft.id,
            session=db_session,
        )

    stored = announcement_repo.get_draft_by_id(draft.id, session=db_session)
    assert stored.title == "原草稿"
    assert stored.content == "原正文"
    assert stored.created_by == owner.id


def test_q08_repo_list_only_returns_own_drafts(db_session):
    owner = create_user()
    other = create_user()
    _save_draft(owner, title="owner 的草稿")
    _save_draft(other, title="other 的草稿")

    rows, total = announcement_repo.list_drafts(created_by=owner.id, session=db_session)
    assert total == 1
    assert rows[0].title == "owner 的草稿"


# ══════════════════════════════════════════════════════════════════════
# 服务层：发送是草稿读取路径之一
# ══════════════════════════════════════════════════════════════════════


def test_q08_batch_send_rejects_other_operators_draft_without_side_effects(db_session):
    owner = create_user(email="owner@bjtu.edu.cn")
    other = create_user()
    draft = _save_draft(owner, title="owner 的草稿", content="owner 的正文")

    with pytest.raises(ValueError, match="draft_not_found"):
        start_batch_send_service(
            [draft.id],
            [TargetEntry(type="user", id=owner.id)],
            operator_user_id=other.id,
        )

    # 失败不改数据：草稿仍在，也没有半途建出 SENDING 公告
    assert _get_draft(draft.id) is not None
    with session_scope(commit=False) as session:
        assert announcement_repo.list_announcements_by_status(
            AnnouncementStatus.SENDING, session=session
        ) == []


# ══════════════════════════════════════════════════════════════════════
# API 层：两个操作员的隔离
# ══════════════════════════════════════════════════════════════════════


def test_q08_api_two_operator_isolation(client, monkeypatch, db_session):
    owner = create_user()
    other = create_user()
    _act_as_tokens(monkeypatch, {"token-owner": owner.id, "token-other": other.id})
    owner_targets = json.dumps([{"type": "user", "id": owner.id}])
    draft = _save_draft(
        owner,
        title="owner 的草稿",
        content="owner 的正文",
        raw_content="{{greeting}} owner 的正文",
        targets=owner_targets,
    )

    # 一条已经由该草稿产生的历史公告：越权操作不能顺手改写或新增公告。
    with session_scope() as session:
        announcement = announcement_repo.create_announcement(
            title="既有公告",
            content="既有正文",
            raw_content="既有原文",
            created_by=owner.id,
            status=AnnouncementStatus.SENT,
            targets=owner_targets,
            target_snapshot=json.dumps([{"type": "user", "id": owner.id, "name": owner.username}]),
            recipient_count=1,
            source_draft_id=draft.id,
            session=session,
        )
        announcement_id = announcement.id

    draft_before = _draft_snapshot(_get_draft(draft.id))
    announcements_before = _announcements_snapshot()
    assert announcements_before[0] == 1

    def assert_unchanged():
        assert _draft_snapshot(_get_draft(draft.id)) == draft_before
        assert _announcements_snapshot() == announcements_before

    # 列表隔离
    _use_operator(client, "token-other")
    listed_other = assert_json_success(client.get("/api/announcements/drafts"))
    assert listed_other["total"] == 0
    _use_operator(client, "token-owner")
    listed_owner = assert_json_success(client.get("/api/announcements/drafts"))
    assert listed_owner["total"] == 1

    # 读取隔离：完整草稿与关联公告都不变
    _use_operator(client, "token-other")
    assert_json_error(client.get(f"/api/announcements/drafts/{draft.id}"), 404)
    assert_unchanged()

    # 更新隔离：失败不改数据
    assert_json_error(
        client.post(
            "/api/announcements/drafts/save",
            json={"draft_id": draft.id, "title": "被篡改", "content": "被篡改"},
        ),
        404,
        "draft_not_found",
    )
    assert_unchanged()

    # 删除隔离：失败不改数据
    assert_json_error(client.delete(f"/api/announcements/drafts/{draft.id}"), 404)
    assert_unchanged()

    # 发送隔离：别人的 draft_id 发不出去，也不留下半成品
    assert_json_error(
        client.post(
            "/api/announcements/drafts/batch-send",
            json={"draft_ids": [draft.id], "targets": [{"type": "user", "id": owner.id}]},
        ),
        404,
        "draft_not_found",
    )
    assert_unchanged()
    with session_scope(commit=False) as session:
        assert announcement_repo.list_announcements_by_status(
            AnnouncementStatus.SENDING, session=session
        ) == []

    # 所属者自己的路径仍然可用，且读回的是完整快照与稳定 owner 主键
    _use_operator(client, "token-owner")
    detail = assert_json_success(client.get(f"/api/announcements/drafts/{draft.id}"))
    draft_view = detail["draft"]
    assert draft_view["id"] == draft.id
    assert draft_view["title"] == "owner 的草稿"
    assert draft_view["content"] == "owner 的正文"
    assert draft_view["raw_content"] == "{{greeting}} owner 的正文"
    assert draft_view["targets"] == owner_targets
    assert draft_view["created_by"] == owner.id
    assert isinstance(draft_view["created_by"], int)
    assert "template_id" not in draft_view
    assert _announcements_snapshot() == announcements_before
    assert _get_draft(draft.id).id == draft.id

    assert_json_success(
        client.post(
            "/api/announcements/drafts/save",
            json={"draft_id": draft.id, "title": "owner 改过", "content": "owner 改过"},
        )
    )
    stored = _get_draft(draft.id)
    assert stored.title == "owner 改过"
    assert stored.content == "owner 改过"
    assert stored.created_by == owner.id
    with session_scope(commit=False) as session:
        linked = announcement_repo.get_announcement_by_id(announcement_id, session=session)
        assert linked is not None
        assert linked.source_draft_id == draft.id
        assert linked.content == "既有正文"
