"""Q06/Q07 回归：模板与草稿 / 公告解耦（2026-10 用户决策）。

决策要点：
- 模板选择只是把 subject/body **复制**成编辑器初值，草稿保存独立内容快照；
- 保存草稿不保留 template_id 关联，旧客户端的 template_id 输入被兼容忽略；
- 删除 / 改名 / 编辑模板既不阻止、也不改写已生成的草稿与公告；
- 旧库残留的 `announcement_drafts.template_id`（带外键）由启动自愈安全解除。

本轮只跑受控本地 SQLite，不触达真实数据库 / SMTP / 宿主操作。
"""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from ...constant import AnnouncementStatus
from ...extensions import session_scope
from ...repositories import announcement_repo
from ..assertions import assert_json_success
from ..factories import create_user
from ..mocks import mock_operator_token


_ANNOUNCEMENT_API = __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""])
_OPERATOR_HEADERS = {"token": "test-operator-token"}


def _make_template(user, *, name="模板", subject="模板主题", body="模板正文"):
    with session_scope() as session:
        return announcement_repo.create_template(
            name=name,
            subject_template=subject,
            body_template=body,
            created_by=user.id,
            session=session,
        )


def _make_announcement(user, *, template_id=None, title="公告", content="公告正文"):
    with session_scope() as session:
        return announcement_repo.create_announcement(
            title=title,
            content=content,
            created_by=user.id,
            status=AnnouncementStatus.SENT,
            template_id=template_id,
            session=session,
        )


def _install_legacy_draft_table(db_session, *, template_id, user_id):
    """把 announcement_drafts 还原成"旧库"形状：带 template_id 外键 + 一条引用行。"""

    db_session.execute(text("DROP TABLE announcement_drafts"))
    db_session.execute(text(
        "CREATE TABLE announcement_drafts ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " title VARCHAR(200) NOT NULL,"
        " content TEXT NOT NULL,"
        " raw_content TEXT NULL,"
        " created_by INTEGER NOT NULL REFERENCES users(id),"
        " targets TEXT NULL,"
        " template_id INTEGER NULL REFERENCES announcement_templates(id),"
        " created_at DATETIME NULL,"
        " updated_at DATETIME NULL"
        ")"
    ))
    db_session.execute(
        text(
            "INSERT INTO announcement_drafts (title, content, created_by, template_id)"
            " VALUES ('旧草稿', '旧正文', :user_id, :template_id)"
        ),
        {"user_id": user_id, "template_id": template_id},
    )
    db_session.commit()


# ══════════════════════════════════════════════════════════════════════
# Q06：模板删除不再被引用挡住
# ══════════════════════════════════════════════════════════════════════


def test_q06_delete_template_referenced_by_announcement_keeps_content(db_session):
    """公告引用模板时，删除模板成功且公告正文一字不变（只解除追溯引用）。"""

    user = create_user()
    template = _make_template(user)
    ann = _make_announcement(user, template_id=template.id)

    assert announcement_repo.delete_template(template.id, session=db_session) is True
    assert announcement_repo.get_template_by_id(template.id, session=db_session) is None

    refreshed = announcement_repo.get_announcement_by_id(ann.id, session=db_session)
    assert refreshed.content == "公告正文"
    assert refreshed.template_id is None, "追溯引用被解除，但不影响已生成内容"


def test_q06_legacy_sqlite_draft_reference_is_safely_detached(db_session):
    """旧 SQLite 库：草稿表残留 template_id 外键会挡住删除，启动自愈先解除引用。"""

    user = create_user()
    template = _make_template(user)
    _install_legacy_draft_table(db_session, template_id=template.id, user_id=user.id)

    # 复现：旧库的外键把模板删除挡住（这正是 Q06 的原始症状）
    with pytest.raises(IntegrityError):
        db_session.execute(
            text("DELETE FROM announcement_templates WHERE id = :template_id"),
            {"template_id": template.id},
        )
    db_session.rollback()

    from FuxiYu_CtrKernel import _ensure_announcement_schema

    _ensure_announcement_schema()
    _ensure_announcement_schema()  # 幂等：可重复执行

    columns = {
        column["name"]
        for column in inspect(db_session.get_bind()).get_columns("announcement_drafts")
    }
    if "template_id" in columns:
        remaining = db_session.execute(
            text("SELECT template_id FROM announcement_drafts")
        ).scalars().all()
        assert all(value is None for value in remaining), "残留引用必须全部解除"
    assert announcement_repo.delete_template(template.id, session=db_session) is True


def test_q06_edit_or_rename_template_does_not_touch_generated_content(db_session):
    """改名/编辑模板不改写已生成草稿与公告——它们是独立内容快照。"""

    user = create_user()
    template = _make_template(user, subject="旧主题", body="旧正文")

    with session_scope() as session:
        draft = announcement_repo.save_draft(
            title="旧主题", content="旧正文", created_by=user.id, session=session
        )
        draft_id = draft.id
    ann = _make_announcement(user, template_id=template.id, content="旧正文")

    announcement_repo.update_template(
        template.id,
        name="新模板名",
        subject_template="新主题",
        body_template="新正文",
        session=db_session,
    )

    with session_scope(commit=False) as session:
        stored = announcement_repo.get_draft_by_id(draft_id, session=session)
        assert stored.title == "旧主题"
        assert stored.content == "旧正文"
    refreshed = announcement_repo.get_announcement_by_id(ann.id, session=db_session)
    assert refreshed.content == "旧正文"

    # 删除模板后草稿仍可重开、内容不变
    assert announcement_repo.delete_template(template.id, session=db_session) is True
    with session_scope(commit=False) as session:
        assert announcement_repo.get_draft_by_id(draft_id, session=session).content == "旧正文"


# ══════════════════════════════════════════════════════════════════════
# Q07：模板选择是复制初值，保存草稿不保留关联
# ══════════════════════════════════════════════════════════════════════


def test_q07_save_draft_ignores_template_id_input(client, monkeypatch, db_session):
    """旧客户端仍传 template_id 时被兼容忽略：既不落库，也不出现在出参里。"""

    user = create_user(operator=True)
    mock_operator_token(monkeypatch, _ANNOUNCEMENT_API, user_id=user.id)
    template = _make_template(user)

    resp = client.post(
        "/api/announcements/drafts/save",
        headers=_OPERATOR_HEADERS,
        json={
            "title": "草稿标题",
            "content": "用户编辑后的正文",
            "raw_content": "用户编辑后的正文",
            "template_id": template.id,
        },
    )
    draft_id = assert_json_success(resp)["draft_id"]

    detail = client.get(f"/api/announcements/drafts/{draft_id}", headers=_OPERATOR_HEADERS)
    draft_view = assert_json_success(detail)["draft"]
    assert "template_id" not in draft_view, "草稿出参不再暴露模板关联"

    with session_scope(commit=False) as session:
        stored = announcement_repo.get_draft_by_id(draft_id, session=session)
        assert not hasattr(stored, "template_id")

    # 再次保存（带另一个 template_id）也仍是同一份独立快照
    again = client.post(
        "/api/announcements/drafts/save",
        headers=_OPERATOR_HEADERS,
        json={
            "draft_id": draft_id,
            "title": "草稿标题",
            "content": "第二次编辑的正文",
            "template_id": template.id,
        },
    )
    assert_json_success(again)
    detail = client.get(f"/api/announcements/drafts/{draft_id}", headers=_OPERATOR_HEADERS)
    assert assert_json_success(detail)["draft"]["content"] == "第二次编辑的正文"


def test_q07_reopening_draft_never_replays_template_over_edited_content(client, monkeypatch, db_session):
    """选模板 → 编辑 → 保存 → 改模板 → 删模板 → 重开：拿到的是用户快照。"""

    user = create_user(operator=True)
    mock_operator_token(monkeypatch, _ANNOUNCEMENT_API, user_id=user.id)
    template = _make_template(user, subject="模板主题", body="模板初值")

    saved = assert_json_success(client.post(
        "/api/announcements/drafts/save",
        headers=_OPERATOR_HEADERS,
        json={
            "title": "模板主题",
            # 编辑器在模板初值之上继续编辑后的结果
            "content": "模板初值 + 用户补充的内容",
            "raw_content": "模板初值 + 用户补充的内容",
            "template_id": template.id,
        },
    ))

    # 模板此后被改正文
    with session_scope() as session:
        announcement_repo.update_template(
            template.id, body_template="模板被改成了别的内容", session=session
        )
    # 再被删除
    with session_scope() as session:
        assert announcement_repo.delete_template(template.id, session=session) is True

    detail = client.get(
        f"/api/announcements/drafts/{saved['draft_id']}", headers=_OPERATOR_HEADERS
    )
    assert assert_json_success(detail)["draft"]["content"] == "模板初值 + 用户补充的内容"
