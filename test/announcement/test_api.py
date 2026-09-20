"""公告系统 API 层测试（A-01 ~ A-34）。"""

import json

import pytest
from sqlalchemy import select

from ...constant import AnnouncementStatus, AnnouncementTemplateCategory

pytestmark = pytest.mark.usefixtures("ensure_auth_users")
from ...extensions import session_scope
from ...models.announcement import Announcement, AnnouncementDraft, AnnouncementTemplate
from ...models.operation_log import OperationLog
from ...repositories import announcement_repo
from ..assertions import assert_json_error, assert_json_success
from ..factories import (
    create_container,
    create_machine,
    create_user,
)
from ..mocks import mock_operator_token


# ── 辅助函数 ──────────────────────────────────────────────────────────

def _patch_thread_inline(monkeypatch):
    """把批量发送的后台线程换成"start() 就地执行"。

    异步之后 POST 返回时信还没发（2026-09），要断言审计与终态就得让线程同步跑完。
    **测试库是 StaticPool 的单条 SQLite 连接**，真起线程会和测试会话抢同一条连接；
    就地执行同时也避开了这个。
    """
    import FuxiYu_CtrKernel.services.announcement_tasks as task_module

    class _InlineThread:
        def __init__(self, target=None, args=(), kwargs=None, **ignored):
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self):
            self._target(*self._args, **self._kwargs)

    monkeypatch.setattr(task_module.threading, "Thread", _InlineThread)


def _patch_thread_noop(monkeypatch):
    """把后台线程换成"什么都不做"：用来锁"发起即返回"的受理语义。"""
    import FuxiYu_CtrKernel.services.announcement_tasks as task_module

    class _NoopThread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

    monkeypatch.setattr(task_module.threading, "Thread", _NoopThread)


def _operator_headers():
    return {"token": "test-operator-token"}


def _make_operator():
    return create_user(operator=True)


def _make_announcement(user, **kw):
    with session_scope() as session:
        return announcement_repo.create_announcement(
            title=kw.pop("title", "公告"),
            content=kw.pop("content", "正文"),
            created_by=user.id,
            status=kw.pop("status", AnnouncementStatus.SENT),
            session=session,
            **kw,
        )


def _make_draft(user, **kw):
    with session_scope() as session:
        return announcement_repo.save_draft(
            title=kw.pop("title", "草稿"),
            content=kw.pop("content", "正文"),
            created_by=user.id,
            session=session,
            **kw,
        )


def _make_template(user, name="测试模板", category="custom"):
    with session_scope() as session:
        return announcement_repo.create_template(
            name=name,
            subject_template="主题{{key}}",
            body_template="正文{{key}}",
            created_by=user.id,
            category=category,
            session=session,
        )


# ══════════════════════════════════════════════════════════════════════
# Auth
# ══════════════════════════════════════════════════════════════════════


def test_a01_no_token(client):
    """A-01: 无 token → 401。"""
    resp = client.get("/api/announcements/templates")
    assert_json_error(resp, 401, "invalid_token")


def test_a02_user_permission(client, monkeypatch):
    """A-02: USER 权限 → 403。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]),
                        user_id=1, valid=False)
    resp = client.get("/api/announcements/templates")
    assert resp.status_code in (401, 403)


# ══════════════════════════════════════════════════════════════════════
# 元素定义
# ══════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════
# 模板 CRUD
# ══════════════════════════════════════════════════════════════════════


def test_a04_create_template_full(client, monkeypatch):
    """A-04: 完整字段创建模板 → 200。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    resp = client.post(
        "/api/announcements/templates",
        headers=_operator_headers(),
        json={
            "name": "新模板",
            "subject_template": "主题",
            "body_template": "正文",
            "description": "描述",
        },
    )
    payload = assert_json_success(resp)
    assert payload["template"]["name"] == "新模板"


def test_a05_create_template_missing_name(client, monkeypatch):
    """A-05: 缺 name → 400。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    resp = client.post(
        "/api/announcements/templates",
        headers=_operator_headers(),
        json={"subject_template": "s", "body_template": "b"},
    )
    assert_json_error(resp, 400, "missing_field")


def test_a06_list_templates(client, monkeypatch):
    """A-06: 获取模板列表。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    resp = client.get("/api/announcements/templates", headers=_operator_headers())
    assert_json_success(resp)


def test_a07_get_template_by_id(client, monkeypatch):
    """A-07: 获取存在的模板 → 200。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    user = _make_operator()
    t = _make_template(user)
    resp = client.get(f"/api/announcements/templates/{t.id}", headers=_operator_headers())
    payload = assert_json_success(resp)
    assert payload["template"]["id"] == t.id


def test_a08_get_template_not_found(client, monkeypatch):
    """A-08: 模板不存在 → 404。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    resp = client.get("/api/announcements/templates/999", headers=_operator_headers())
    assert_json_error(resp, 404)


def test_a09_update_template_partial(client, monkeypatch):
    """A-09: 部分更新模板。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    user = _make_operator()
    t = _make_template(user, name="旧名")
    resp = client.put(
        f"/api/announcements/templates/{t.id}",
        headers=_operator_headers(),
        json={"name": "新名"},
    )
    assert_json_success(resp)


def test_a10_delete_system_template(client, monkeypatch):
    """A-10: 删除 system 模板 → 400。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    user = _make_operator()
    t = _make_template(user, name="系统模板", category="system")
    resp = client.delete(f"/api/announcements/templates/{t.id}", headers=_operator_headers())
    assert_json_error(resp, 400, "cannot_delete_system_template")


def test_a11_delete_custom_template(client, monkeypatch):
    """A-11: 删除 custom 模板 → 200。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    user = _make_operator()
    t = _make_template(user, category="custom")
    resp = client.delete(f"/api/announcements/templates/{t.id}", headers=_operator_headers())
    assert_json_success(resp)


# ══════════════════════════════════════════════════════════════════════
# 目标解析
# ══════════════════════════════════════════════════════════════════════


def test_a13_resolve_targets_mixed(client, monkeypatch):
    """A-13: 混合 targets → 200 + recipient_count>0。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    user = _make_operator()
    machine = create_machine()
    from ...repositories.machine_permission_repo import add_permission
    with session_scope() as session:
        add_permission(machine.id, user.id, session=session)

    resp = client.post(
        "/api/announcements/resolve-targets",
        headers=_operator_headers(),
        json={
            "targets": [
                {"type": "machine", "id": machine.id},
                {"type": "user", "id": user.id},
            ]
        },
    )
    payload = assert_json_success(resp)
    assert payload["recipient_count"] > 0


def test_a14_resolve_targets_empty(client, monkeypatch):
    """A-14: targets=[] → 400。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    resp = client.post(
        "/api/announcements/resolve-targets",
        headers=_operator_headers(),
        json={"targets": []},
    )
    assert_json_error(resp, 400, "empty_targets")


# ══════════════════════════════════════════════════════════════════════
# 公告（已发送）查询
# ══════════════════════════════════════════════════════════════════════


def test_a15_list_announcements(client, monkeypatch):
    """A-15: 列表查询 → 200。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    resp = client.get("/api/announcements/list", headers=_operator_headers())
    assert_json_success(resp)


def test_a16_list_announcements_filtered(client, monkeypatch):
    """A-16: 按状态过滤 → 仅两类。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    user = _make_operator()
    _make_announcement(user, status=AnnouncementStatus.SENT)
    _make_announcement(user, status=AnnouncementStatus.PARTIAL)
    _make_announcement(user, status=AnnouncementStatus.FAILED)

    resp = client.get("/api/announcements/list?status=sent&status=partial", headers=_operator_headers())
    payload = assert_json_success(resp)
    assert payload["total"] == 2


def test_a16b_announcements_status_by_ids(client, monkeypatch):
    """A-16b: 按 id 查进度 —— 只回自己那一批，且**不带正文**。

    批量发送/重发改成异步之后，前端每 3 秒轮询一次看进度。按 id 定位才稳：不受分页
    影响、不怕别人新发的公告挤进列表；出参也必须轻量（别每 3 秒把公告正文拖一遍）。
    """
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    user = _make_operator()
    mine = _make_announcement(user, status=AnnouncementStatus.SENDING, content="很长的正文" * 50)
    other = _make_announcement(user, status=AnnouncementStatus.SENT)

    resp = client.get(
        f"/api/announcements/status?ids={mine.id}", headers=_operator_headers()
    )
    payload = assert_json_success(resp)

    ids = [a["id"] for a in payload["announcements"]]
    assert ids == [mine.id], "只回请求里那一批，别人的公告不该混进来"
    row = payload["announcements"][0]
    assert row["status"] == "sending"
    assert row["source_draft_id"] == mine.source_draft_id, "前端靠它对回草稿"
    assert "content" not in row and "target_snapshot" not in row, "轮询出参要轻"


def test_a17_get_announcement_detail(client, monkeypatch):
    """A-17: 详情 → 200。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    user = _make_operator()
    ann = _make_announcement(user)
    resp = client.get(f"/api/announcements/{ann.id}", headers=_operator_headers())
    payload = assert_json_success(resp)
    assert payload["announcement"]["id"] == ann.id


def test_a18_get_announcement_not_found(client, monkeypatch):
    """A-18: 不存在 → 404。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    resp = client.get("/api/announcements/999", headers=_operator_headers())
    assert_json_error(resp, 404)


# ══════════════════════════════════════════════════════════════════════
# 重发
# ══════════════════════════════════════════════════════════════════════


def test_a19_resend_sent(client, monkeypatch, db_session):
    """A-19: SENT 公告重发 → 200。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    user = _make_operator()
    ann = _make_announcement(
        user,
        title="公告",
        content="正文",
        status=AnnouncementStatus.SENT,
        targets=json.dumps([{"type": "user", "id": user.id}]),
    )
    resp = client.post(f"/api/announcements/{ann.id}/resend", headers=_operator_headers())
    assert_json_success(resp)
    log = db_session.scalars(select(OperationLog).where(OperationLog.operation == "send_mail")).one()
    assert log.operator_user_id == 1
    assert log.detail["mail_type"] == "announcement_resend"


def test_a20_resend_sending(client, monkeypatch):
    """A-20: SENDING 公告重发 → 409。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    user = _make_operator()
    ann = _make_announcement(
        user,
        title="公告",
        content="正文",
        status=AnnouncementStatus.SENDING,
        targets=json.dumps([{"type": "user", "id": user.id}]),
    )
    resp = client.post(f"/api/announcements/{ann.id}/resend", headers=_operator_headers())
    assert_json_error(resp, 409)


# ══════════════════════════════════════════════════════════════════════
# 复用为草稿
# ══════════════════════════════════════════════════════════════════════


def test_a21_copy_as_draft(client, monkeypatch):
    """A-21: 复用已发公告 → 200 + draft_id。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    user = _make_operator()
    ann = _make_announcement(user)
    resp = client.post(f"/api/announcements/{ann.id}/copy-as-draft", headers=_operator_headers())
    payload = assert_json_success(resp)
    assert payload["draft_id"] > 0


# ══════════════════════════════════════════════════════════════════════
# 转为模板
# ══════════════════════════════════════════════════════════════════════


def test_a22_convert_to_template(client, monkeypatch):
    """A-22: 转模板 → 200 + template_id，正文直接保存。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    user = _make_operator()
    ann = _make_announcement(
        user,
        title="GPU维护",
        content="您好，GPU-01 将于今晚维护。",
        raw_content="您好，GPU-01 将于今晚维护。",
        status=AnnouncementStatus.SENT,
    )
    resp = client.post(f"/api/announcements/{ann.id}/convert-to-template", headers=_operator_headers())
    payload = assert_json_success(resp)
    assert payload["template_id"] > 0
    assert payload["name"] == "来自公告: GPU维护"


# ══════════════════════════════════════════════════════════════════════
# 草稿 CRUD
# ══════════════════════════════════════════════════════════════════════


def test_a24_save_draft_create(client, monkeypatch):
    """A-24: draft_id=null 新建 → 200 + draft_id。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    resp = client.post(
        "/api/announcements/drafts/save",
        headers=_operator_headers(),
        json={"title": "新草稿", "content": "正文内容"},
    )
    payload = assert_json_success(resp)
    assert payload["draft_id"] > 0


def test_a25_save_draft_update(client, monkeypatch):
    """A-25: 已有 draft_id → 200 + 同 id。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    user = _make_operator()
    draft = _make_draft(user, title="旧标题")
    resp = client.post(
        "/api/announcements/drafts/save",
        headers=_operator_headers(),
        json={"draft_id": draft.id, "title": "新标题", "content": "新正文"},
    )
    payload = assert_json_success(resp)
    assert payload["draft_id"] == draft.id


def test_a26_list_drafts(client, monkeypatch):
    """A-26: 草稿列表 → 200。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    resp = client.get("/api/announcements/drafts", headers=_operator_headers())
    assert_json_success(resp)


def test_a27_get_draft_detail(client, monkeypatch):
    """A-27: 草稿详情 → 200。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    user = _make_operator()
    draft = _make_draft(user)
    resp = client.get(f"/api/announcements/drafts/{draft.id}", headers=_operator_headers())
    payload = assert_json_success(resp)
    assert payload["draft"]["id"] == draft.id


def test_a28_delete_draft(client, monkeypatch):
    """A-28: 删除草稿 → 200。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    user = _make_operator()
    draft = _make_draft(user)
    resp = client.delete(f"/api/announcements/drafts/{draft.id}", headers=_operator_headers())
    assert_json_success(resp)


def test_a29_delete_draft_not_found(client, monkeypatch):
    """A-29: 删除不存在草稿 → 404。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    resp = client.delete("/api/announcements/drafts/999", headers=_operator_headers())
    assert_json_error(resp, 404)


# ══════════════════════════════════════════════════════════════════════
# 批量发送
# ══════════════════════════════════════════════════════════════════════


def test_a30_batch_send(client, monkeypatch, db_session):
    """A-30: draft_ids + targets → 受理回执（total + announcement_ids），发信在后台线程。

    异步语义（2026-09）：POST 回来时**还没发信**。这里把线程换成就地执行，
    以便断言审计与终态；"发起即返回"的形状由 a30b 单独锁。
    """
    _patch_thread_inline(monkeypatch)
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    user = _make_operator()
    d1 = _make_draft(user, title="d1")
    d2 = _make_draft(user, title="d2")

    resp = client.post(
        "/api/announcements/drafts/batch-send",
        headers=_operator_headers(),
        json={
            "draft_ids": [d1.id, d2.id],
            "targets": [{"type": "user", "id": user.id}],
        },
    )
    payload = assert_json_success(resp)
    assert payload["total"] == 2
    assert len(payload["announcement_ids"]) == 2
    logs = db_session.scalars(select(OperationLog).where(OperationLog.operation == "send_mail")).all()
    assert len(logs) == 2
    assert all(log.operator_user_id == 1 for log in logs)
    assert {log.detail["name"] for log in logs} == {"d1", "d2"}


def test_a30b_batch_send_returns_accepted_without_waiting(client, monkeypatch, db_session):
    """A-30b: 发起即返回 —— 返回时公告还是 SENDING，信还没发。

    这条锁的是异步本身：此前批量发送是同步跑完（分钟级），任何前端超时都会先松手，
    用户看到"失败"而信其实发出去了（2026-09 用户反馈）。
    """
    _patch_thread_noop(monkeypatch)
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    user = _make_operator()
    draft = _make_draft(user, title="d1")

    resp = client.post(
        "/api/announcements/drafts/batch-send",
        headers=_operator_headers(),
        json={"draft_ids": [draft.id], "targets": [{"type": "user", "id": user.id}]},
    )
    payload = assert_json_success(resp)

    assert payload["total"] == 1
    assert len(payload["announcement_ids"]) == 1
    announcement = announcement_repo.get_announcement_by_id(
        payload["announcement_ids"][0], session=db_session
    )
    assert announcement.status == AnnouncementStatus.SENDING, "线程还没跑，公告应当停在 SENDING"
    assert announcement.source_draft_id == draft.id, "前端靠它把结果对回草稿"
    logs = db_session.scalars(select(OperationLog).where(OperationLog.operation == "send_mail")).all()
    assert logs == [], "返回时不该已经发过信"


def test_a31_batch_send_empty_targets(client, monkeypatch):
    """A-31: targets 为空 → 400。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    resp = client.post(
        "/api/announcements/drafts/batch-send",
        headers=_operator_headers(),
        json={"draft_ids": [1], "targets": []},
    )
    assert_json_error(resp, 400, "empty_targets")


def test_a32_batch_send_too_many_recipients(client, monkeypatch):
    """A-32: >200 收件人 → 400。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    user = _make_operator()
    draft = _make_draft(user)
    targets = [{"type": "user", "id": create_user().id} for _ in range(250)]

    resp = client.post(
        "/api/announcements/drafts/batch-send",
        headers=_operator_headers(),
        json={"draft_ids": [draft.id], "targets": targets},
    )
    assert_json_error(resp, 400, "too_many_recipients")


def test_a33_batch_send_nonexistent_draft(client, monkeypatch):
    """A-33: draft_ids 含不存在 id → 404（**改**：不再"200 + 该条 error"）。

    异步之后校验必须在同步段做完：坏草稿不能先建一堆 SENDING 公告、再丢进线程里
    悄无声息地失败——那样前端只会看到一堆永远"发送中"的空公告。
    """
    _patch_thread_noop(monkeypatch)
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    user = _make_operator()
    d1 = _make_draft(user)

    resp = client.post(
        "/api/announcements/drafts/batch-send",
        headers=_operator_headers(),
        json={
            "draft_ids": [d1.id, 9999],
            "targets": [{"type": "user", "id": user.id}],
        },
    )
    assert_json_error(resp, 404, "draft_not_found")

    # 好草稿也不能被"半途建出来"：校验先于任何写库
    with session_scope(commit=False) as session:
        stuck = announcement_repo.list_announcements_by_status(
            AnnouncementStatus.SENDING, session=session
        )
    assert stuck == [], "校验失败时不该留下 SENDING 公告"


def test_a34_batch_send_too_large(client, monkeypatch):
    """A-34: >20 条 draft → 400。"""
    mock_operator_token(monkeypatch, __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]))
    resp = client.post(
        "/api/announcements/drafts/batch-send",
        headers=_operator_headers(),
        json={
            "draft_ids": list(range(25)),
            "targets": [{"type": "user", "id": 1}],
        },
    )
    assert_json_error(resp, 400, "batch_too_large")
