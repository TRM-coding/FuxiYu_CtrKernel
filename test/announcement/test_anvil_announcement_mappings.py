"""Anvil 公告能力缺口映射的定向回归。

本文件只补 test-plan 中的 10 个计划 locator；不改变业务实现、模型、迁移或共享夹具。
"""

import datetime as dt
import json
import re

from sqlalchemy import select

from ...constant import AnnouncementStatus, AnnouncementTemplateCategory
from ...extensions import session_scope
from ...models.announcement import Announcement, AnnouncementTemplate
from ...models.operation_log import OperationLog
from ...repositories import announcement_repo
from ...services.announcement_tasks import (
    TargetEntry,
    start_batch_send_service,
    start_resend_service,
)
from ...utils.announcement_markdown import render_announcement_html
from ...utils.mail import send_batch
from ..assertions import assert_json_error, assert_json_success
from ..factories import create_user
from ..mocks import mock_operator_token

_OPERATOR_HEADERS = {"token": "test-operator-token"}


def _api_module():
    return __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""])


def _make_template(
    user_id: int,
    *,
    name: str = "anvil-template",
    subject: str = "主题",
    body: str = "正文",
    category: str = "custom",
    **kwargs,
):
    with session_scope() as session:
        return announcement_repo.create_template(
            name=name,
            subject_template=subject,
            body_template=body,
            created_by=user_id,
            category=category,
            session=session,
            **kwargs,
        )


def _make_draft(
    user_id: int,
    *,
    title: str = "草稿",
    content: str = "正文",
    raw_content: str | None = None,
    targets: str | None = None,
):
    with session_scope() as session:
        return announcement_repo.save_draft(
            title=title,
            content=content,
            raw_content=raw_content,
            targets=targets,
            created_by=user_id,
            session=session,
        )


def _make_announcement(
    user_id: int,
    *,
    title: str = "公告",
    content: str = "正文",
    raw_content: str | None = None,
    status: AnnouncementStatus = AnnouncementStatus.SENT,
    targets: str | None = None,
    target_snapshot: str | None = None,
    recipient_count: int = 0,
    template_id: int | None = None,
    source_draft_id: int | None = None,
):
    with session_scope() as session:
        return announcement_repo.create_announcement(
            title=title,
            content=content,
            raw_content=raw_content,
            created_by=user_id,
            status=status,
            targets=targets,
            target_snapshot=target_snapshot,
            recipient_count=recipient_count,
            template_id=template_id,
            source_draft_id=source_draft_id,
            session=session,
        )


def _announcement_snapshot(announcement: Announcement) -> dict:
    return {
        "id": announcement.id,
        "title": announcement.title,
        "content": announcement.content,
        "raw_content": announcement.raw_content,
        "created_by": announcement.created_by,
        "status": announcement.status,
        "targets": announcement.targets,
        "target_snapshot": announcement.target_snapshot,
        "recipient_count": announcement.recipient_count,
        "success_count": announcement.success_count,
        "fail_count": announcement.fail_count,
        "created_at": announcement.created_at,
        "sent_at": announcement.sent_at,
        "source_draft_id": announcement.source_draft_id,
        "template_id": announcement.template_id,
    }


def _draft_snapshot(draft) -> dict:
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


def _template_snapshot(template: AnnouncementTemplate) -> dict:
    return {
        "id": template.id,
        "name": template.name,
        "category": template.category,
        "description": template.description,
        "subject_template": template.subject_template,
        "body_template": template.body_template,
        "source_announcement_id": template.source_announcement_id,
        "created_by": template.created_by,
        "created_at": template.created_at,
        "updated_at": template.updated_at,
    }


def _get_log_by_id(log_id: int) -> OperationLog:
    with session_scope(commit=False) as session:
        log = session.get(OperationLog, log_id)
        assert log is not None
        return log


def _log_snapshot(log: OperationLog) -> dict:
    return {
        "success": log.success,
        "target_type": log.target_type,
        "target_id": log.target_id,
        "detail": dict(log.detail or {}),
    }


def _count_drafts_and_announcements() -> tuple[int, int]:
    with session_scope(commit=False) as session:
        _, draft_total = announcement_repo.list_drafts(session=session)
        _, announcement_total = announcement_repo.list_announcements(session=session)
    return draft_total, announcement_total


def test_anvil_t01_template_readback_contract(db_session):
    """模板跨 session 读回：类型、默认分类、空值和创建者主键。"""
    owner = create_user()
    before = dt.datetime.utcnow()
    with session_scope() as session:
        minimal = announcement_repo.create_template(
            name="anvil-t01-minimal",
            subject_template="最小主题",
            body_template="最小正文",
            created_by=owner.id,
            session=session,
        )
        minimal_id = minimal.id
        full = announcement_repo.create_template(
            name="anvil-t01-full",
            subject_template="完整主题",
            body_template="完整正文",
            created_by=owner.id,
            description="完整描述",
            source_announcement_id=42,
            session=session,
        )
        full_id = full.id
    after = dt.datetime.utcnow()

    with session_scope(commit=False) as session:
        minimal = announcement_repo.get_template_by_id(minimal_id, session=session)
        full = announcement_repo.get_template_by_id(full_id, session=session)

        assert minimal is not None and full is not None
        assert isinstance(minimal.id, int) and isinstance(full.id, int)
        for template in (minimal, full):
            assert isinstance(template.name, str)
            assert isinstance(template.subject_template, str)
            assert isinstance(template.body_template, str)
            assert isinstance(template.created_by, int)
            assert template.created_by == owner.id
            assert template.creator is not None and template.creator.id == owner.id
            assert template.category == AnnouncementTemplateCategory.CUSTOM
            assert isinstance(template.created_at, dt.datetime)
            assert isinstance(template.updated_at, dt.datetime)
            assert before <= template.created_at <= after
            assert before <= template.updated_at <= after

        assert minimal.description is None
        assert minimal.source_announcement_id is None
        assert full.description == "完整描述"
        assert full.source_announcement_id == 42


def test_anvil_t02_api_template_detail_returns_editor_initial_values(client, monkeypatch):
    """模板详情返回编辑初值，且读取模板不新增草稿或公告。"""
    owner = create_user(operator=True)
    source_announcement = _make_announcement(owner.id, title="来源公告", content="来源正文")
    _make_draft(owner.id, title="既有草稿", content="既有正文")
    template = _make_template(
        owner.id,
        name="anvil-t02-template",
        subject="编辑主题 {{name}}",
        body="编辑正文 {{body}}",
        description="详情模板",
        source_announcement_id=source_announcement.id,
    )
    before_counts = _count_drafts_and_announcements()

    mock_operator_token(monkeypatch, _api_module(), user_id=owner.id)
    response = client.get(
        f"/api/announcements/templates/{template.id}",
        headers=_OPERATOR_HEADERS,
    )
    payload = assert_json_success(response)

    assert payload["template"]["subject_template"] == "编辑主题 {{name}}"
    assert payload["template"]["body_template"] == "编辑正文 {{body}}"
    assert payload["template"]["source_announcement_id"] == source_announcement.id
    assert _count_drafts_and_announcements() == before_counts


def test_anvil_t03_delete_template_preserves_announcement_and_draft_snapshots(db_session):
    """删除模板只解除追溯引用，保留主题/正文/目标/投递记录。"""
    owner = create_user()
    template = _make_template(owner.id, name="anvil-t03-template", subject="旧主题", body="旧正文")
    draft = _make_draft(
        owner.id,
        title="历史草稿",
        content="历史草稿正文",
        raw_content="历史草稿原文",
        targets=json.dumps([{"type": "user", "id": owner.id}]),
    )
    announcement = _make_announcement(
        owner.id,
        title="历史公告",
        content="历史公告正文",
        raw_content="历史公告原文",
        targets=json.dumps([{"type": "user", "id": owner.id}]),
        target_snapshot=json.dumps([{"type": "user", "id": owner.id, "display_name": "owner"}]),
        recipient_count=1,
        template_id=template.id,
        source_draft_id=draft.id,
    )

    send_batch(
        [{"to": owner.email, "subject": announcement.title, "content": announcement.content}],
        target_type="announcement",
        target_id=announcement.id,
        detail={"mail_type": "announcement", "name": announcement.title},
    )
    with session_scope(commit=False) as session:
        log = session.scalars(
            select(OperationLog)
            .where(
                OperationLog.target_type == "announcement",
                OperationLog.target_id == announcement.id,
            )
            .order_by(OperationLog.id.desc())
        ).first()
        assert log is not None
        log_id = log.id
        log_before = _log_snapshot(log)

    with session_scope(commit=False) as session:
        announcement_before = _announcement_snapshot(
            announcement_repo.get_announcement_by_id(announcement.id, session=session)
        )
        draft_before = _draft_snapshot(
            announcement_repo.get_draft_by_id(draft.id, session=session)
        )

    with session_scope() as session:
        assert announcement_repo.delete_template(template.id, session=session) is True

    with session_scope(commit=False) as session:
        assert announcement_repo.get_template_by_id(template.id, session=session) is None
        announcement_after = _announcement_snapshot(
            announcement_repo.get_announcement_by_id(announcement.id, session=session)
        )
        draft_after = _draft_snapshot(
            announcement_repo.get_draft_by_id(draft.id, session=session)
        )
        log_after = _log_snapshot(session.get(OperationLog, log_id))

    assert announcement_after["template_id"] is None
    assert {
        key: value for key, value in announcement_after.items() if key != "template_id"
    } == {
        key: value for key, value in announcement_before.items() if key != "template_id"
    }
    assert announcement_after["title"] == "历史公告"
    assert draft_after == draft_before
    assert log_after == log_before


def test_anvil_t04_api_template_list_rejects_non_integer_offset(client, monkeypatch):
    """非整数 offset 走既有 400 invalid_payload。"""
    owner = create_user(operator=True)
    mock_operator_token(monkeypatch, _api_module(), user_id=owner.id)
    response = client.get(
        "/api/announcements/templates?offset=not-a-number",
        headers=_OPERATOR_HEADERS,
    )
    assert_json_error(response, 400, "invalid_payload")


def test_anvil_t05_api_template_pagination_order_default_and_filtered_total(
    client, monkeypatch, db_session
):
    """默认 100/0、过滤 total 与互异 created_at 的真实排序切片。"""
    owner = create_user(operator=True)
    base = dt.datetime.utcnow() - dt.timedelta(minutes=10)
    rows = []
    for index in range(205):
        category = (
            AnnouncementTemplateCategory.CUSTOM
            if index < 120
            else AnnouncementTemplateCategory.SYSTEM
        )
        stamp = base - dt.timedelta(seconds=index)
        rows.append(
            AnnouncementTemplate(
                name=f"anvil-t05-{index:03d}",
                category=category,
                description=None,
                subject_template=f"主题 {index}",
                body_template=f"正文 {index}",
                source_announcement_id=None,
                created_by=owner.id,
                created_at=stamp,
                updated_at=stamp,
            )
        )
    db_session.add_all(rows)
    db_session.commit()

    expected = [template.id for template in rows]
    expected_custom = [
        template.id
        for template in rows
        if template.category == AnnouncementTemplateCategory.CUSTOM
    ]
    mock_operator_token(monkeypatch, _api_module(), user_id=owner.id)

    def _fetch(query: str = ""):
        response = client.get(
            f"/api/announcements/templates{query}",
            headers=_OPERATOR_HEADERS,
        )
        payload = assert_json_success(response)
        return payload, [template["id"] for template in payload["templates"]]

    default_payload, default_ids = _fetch()
    assert default_payload["total"] == 205
    assert len(default_ids) == 100
    assert default_ids == expected[:100]

    explicit_payload, explicit_ids = _fetch("?limit=100&offset=0")
    assert explicit_payload["total"] == 205
    assert explicit_ids == expected[:100]

    first_page, first_ids = _fetch("?limit=200&offset=0")
    assert first_page["total"] == 205
    assert len(first_ids) == 200
    assert first_ids == expected[:200]

    last_page, last_ids = _fetch("?limit=200&offset=200")
    assert last_page["total"] == 205
    assert len(last_ids) == 5
    assert last_ids == expected[200:]

    middle_page, middle_ids = _fetch("?limit=100&offset=100")
    assert middle_page["total"] == 205
    assert middle_ids == expected[100:200]

    custom_first, custom_first_ids = _fetch("?category=custom&limit=100&offset=0")
    assert custom_first["total"] == 120
    assert custom_first_ids == expected_custom[:100]

    custom_last, custom_last_ids = _fetch("?category=custom&limit=100&offset=100")
    assert custom_last["total"] == 120
    assert custom_last_ids == expected_custom[100:]


def test_anvil_a01_announcement_readback_contract(db_session):
    """公告跨 session 读回：默认计数、可空列、target_snapshot 与 source_draft_id。"""
    owner = create_user()
    before = dt.datetime.utcnow()
    with session_scope() as session:
        minimal = Announcement(
            title="最小公告",
            content="最小正文",
            created_by=owner.id,
            status=AnnouncementStatus.SENDING,
        )
        session.add(minimal)
        session.flush()
        minimal_id = minimal.id

        sent_at = dt.datetime.utcnow()
        full = Announcement(
            title="完整公告",
            content="完整正文",
            raw_content="完整原文",
            created_by=owner.id,
            status=AnnouncementStatus.PARTIAL,
            targets='[{"type":"user","id":1}]',
            target_snapshot='[{"type":"user","id":1,"display_name":"u"}]',
            recipient_count=2,
            success_count=1,
            fail_count=1,
            sent_at=sent_at,
            source_draft_id=987,
            template_id=None,
        )
        session.add(full)
        session.flush()
        full_id = full.id
    after = dt.datetime.utcnow()

    with session_scope(commit=False) as session:
        minimal = announcement_repo.get_announcement_by_id(minimal_id, session=session)
        full = announcement_repo.get_announcement_by_id(full_id, session=session)

        assert minimal is not None and full is not None
        for announcement in (minimal, full):
            assert isinstance(announcement.title, str)
            assert isinstance(announcement.content, str)
            assert isinstance(announcement.created_by, int)
            assert announcement.created_by == owner.id
            assert announcement.creator is not None and announcement.creator.id == owner.id
            assert isinstance(announcement.status, AnnouncementStatus)
            assert isinstance(announcement.created_at, dt.datetime)
            assert before <= announcement.created_at <= after

        assert minimal.recipient_count == 0
        assert minimal.success_count == 0
        assert minimal.fail_count == 0
        assert minimal.targets is None
        assert minimal.target_snapshot is None
        assert minimal.raw_content is None
        assert minimal.sent_at is None
        assert minimal.source_draft_id is None
        assert minimal.template_id is None

        assert full.recipient_count == 2
        assert full.success_count == 1
        assert full.fail_count == 1
        assert full.targets == '[{"type":"user","id":1}]'
        assert full.target_snapshot == '[{"type":"user","id":1,"display_name":"u"}]'
        assert full.raw_content == "完整原文"
        assert full.source_draft_id == 987
        assert full.template_id is None
        assert isinstance(full.sent_at, dt.datetime)
        assert abs((full.sent_at - sent_at).total_seconds()) < 1


def test_anvil_a02_batch_send_persists_target_snapshot(db_session, inline_send_thread):
    """批量发送受理后，持久化公告保留当次 target_snapshot 与收件人数。"""
    owner = create_user(email="anvil-a02@bjtu.edu.cn")
    draft = _make_draft(owner.id, title="快照公告", content="快照正文")

    accepted = start_batch_send_service(
        [draft.id],
        [TargetEntry(type="user", id=owner.id)],
    )
    assert accepted.total == 1

    with session_scope(commit=False) as session:
        announcement = announcement_repo.get_announcement_by_id(
            accepted.announcement_ids[0], session=session
        )
        assert announcement is not None
        snapshot = json.loads(announcement.target_snapshot)

        assert isinstance(snapshot, list) and len(snapshot) == 1
        assert snapshot[0]["type"] == "user"
        assert snapshot[0]["id"] == owner.id
        assert owner.username in snapshot[0]["display_name"]
        assert owner.email in snapshot[0]["display_name"]
        assert announcement.recipient_count == 1
        assert announcement.source_draft_id == draft.id
        assert announcement.status == AnnouncementStatus.SENT


def test_anvil_a03_resend_after_template_deleted_uses_saved_content(
    db_session, monkeypatch, inline_send_thread
):
    """模板删除后的重发只使用公告已保存内容。"""
    owner = create_user(email="anvil-a03@bjtu.edu.cn")
    template = _make_template(owner.id, name="anvil-a03-template", subject="旧主题", body="旧正文")
    content = "# 重发公告\n\n正文 **重点**"
    announcement = _make_announcement(
        owner.id,
        title="重发公告",
        content=content,
        raw_content=content,
        status=AnnouncementStatus.SENT,
        targets=json.dumps([{"type": "user", "id": owner.id}]),
        target_snapshot=json.dumps(
            [{"type": "user", "id": owner.id, "display_name": owner.username}]
        ),
        recipient_count=1,
        template_id=template.id,
        source_draft_id=123,
    )

    with session_scope() as session:
        assert announcement_repo.delete_template(template.id, session=session) is True

    with session_scope(commit=False) as session:
        before = _announcement_snapshot(
            announcement_repo.get_announcement_by_id(announcement.id, session=session)
        )
    assert before["template_id"] is None

    captured = []

    def _capture(messages, **kwargs):
        captured.append([dict(message) for message in messages])
        return [{"ok": True, "to": [message["to"]]} for message in messages]

    monkeypatch.setattr("FuxiYu_CtrKernel.utils.mail._send_batch_smtp", _capture)
    accepted_id = start_resend_service(announcement.id)

    assert accepted_id == announcement.id
    assert len(captured) == 1 and len(captured[0]) == 1
    sent_message = captured[0][0]
    assert sent_message["content"] == content
    assert sent_message["subject"] == "重发公告"
    assert "<h1" in sent_message["html_content"]

    with session_scope(commit=False) as session:
        after = _announcement_snapshot(
            announcement_repo.get_announcement_by_id(announcement.id, session=session)
        )
    assert after["status"] == AnnouncementStatus.SENT
    assert after["template_id"] is None
    for key in (
        "title",
        "content",
        "raw_content",
        "targets",
        "target_snapshot",
        "recipient_count",
        "source_draft_id",
    ):
        assert after[key] == before[key]


def test_anvil_a04_plain_and_markdown_use_same_renderer_call(
    db_session, monkeypatch, inline_send_thread
):
    """同一发送入口对纯文本与 Markdown 调用同一个 renderer。"""
    owner = create_user(email="anvil-a04@bjtu.edu.cn")
    plain = "第一行\n第二行\n\n第三行"
    markdown = "# 维护通知\n\n今晚 **维护**。"
    plain_draft = _make_draft(owner.id, title="纯文本", content=plain)
    markdown_draft = _make_draft(owner.id, title="Markdown", content=markdown)

    import FuxiYu_CtrKernel.services.announcement_tasks as tasks

    render_calls = []

    def _recording_render(source):
        render_calls.append(source)
        return render_announcement_html(source)

    monkeypatch.setattr(tasks, "render_announcement_html", _recording_render)

    captured = []

    def _capture(messages, **kwargs):
        captured.append([dict(message) for message in messages])
        return [{"ok": True, "to": [message["to"]]} for message in messages]

    monkeypatch.setattr("FuxiYu_CtrKernel.utils.mail._send_batch_smtp", _capture)
    accepted = start_batch_send_service(
        [plain_draft.id, markdown_draft.id],
        [TargetEntry(type="user", id=owner.id)],
    )

    assert render_calls == [plain, markdown]
    sent_messages = [message for batch in captured for message in batch]
    assert len(sent_messages) == 2
    by_content = {message["content"]: message for message in sent_messages}
    assert by_content[plain]["html_content"] == render_announcement_html(plain)
    assert by_content[markdown]["html_content"] == render_announcement_html(markdown)
    assert re.search(r"<br\s*/?>", by_content[plain]["html_content"])
    assert "<h1" in by_content[markdown]["html_content"]
    assert "<strong>" in by_content[markdown]["html_content"]

    with session_scope(commit=False) as session:
        persisted = [
            announcement_repo.get_announcement_by_id(announcement_id, session=session)
            for announcement_id in accepted.announcement_ids
        ]
    assert {announcement.content for announcement in persisted} == {plain, markdown}


def test_anvil_a05_send_and_resend_do_not_write_html_into_draft_or_template(
    db_session, monkeypatch, inline_send_thread
):
    """发送/重发期间，HTML 不写回草稿或模板，也不进入审计。"""
    owner = create_user(email="anvil-a05@bjtu.edu.cn")
    content = "# 不写回\n\n正文 **重点**"
    template = _make_template(
        owner.id,
        name="anvil-a05-template",
        subject="模板主题",
        body="模板正文",
    )
    draft = _make_draft(
        owner.id,
        title="不写回草稿",
        content=content,
        raw_content=content,
        targets=json.dumps([{"type": "user", "id": owner.id}]),
    )
    draft_id = draft.id
    template_id = template.id

    with session_scope(commit=False) as session:
        draft_before = _draft_snapshot(
            announcement_repo.get_draft_by_id(draft_id, session=session)
        )
        template_before = _template_snapshot(
            announcement_repo.get_template_by_id(template_id, session=session)
        )

    captured = []
    draft_at_send = []
    template_at_send = []

    def _capture(messages, **kwargs):
        call_index = len(captured)
        captured.append([dict(message) for message in messages])
        with session_scope(commit=False) as session:
            current_draft = announcement_repo.get_draft_by_id(draft_id, session=session)
            current_template = announcement_repo.get_template_by_id(
                template_id, session=session
            )
            assert current_template is not None
            template_at_send.append(_template_snapshot(current_template))
            if call_index == 0:
                assert current_draft is not None
                draft_at_send.append(_draft_snapshot(current_draft))
            else:
                assert current_draft is None
        return [{"ok": True, "to": [message["to"]]} for message in messages]

    monkeypatch.setattr("FuxiYu_CtrKernel.utils.mail._send_batch_smtp", _capture)
    accepted = start_batch_send_service(
        [draft_id],
        [TargetEntry(type="user", id=owner.id)],
    )
    announcement_id = accepted.announcement_ids[0]

    assert draft_at_send == [draft_before]
    assert template_at_send == [template_before]

    with session_scope(commit=False) as session:
        sent_announcement = announcement_repo.get_announcement_by_id(
            announcement_id, session=session
        )
        assert sent_announcement is not None
        assert sent_announcement.content == content
        assert sent_announcement.raw_content == content
        assert announcement_repo.get_draft_by_id(draft_id, session=session) is None
        assert (
            _template_snapshot(
                announcement_repo.get_template_by_id(template_id, session=session)
            )
            == template_before
        )
        announcement_before_resend = _announcement_snapshot(sent_announcement)

    start_resend_service(announcement_id)

    assert draft_at_send == [draft_before]
    assert template_at_send == [template_before, template_before]

    with session_scope(commit=False) as session:
        resent_announcement = announcement_repo.get_announcement_by_id(
            announcement_id, session=session
        )
        assert resent_announcement is not None
        announcement_after_resend = _announcement_snapshot(resent_announcement)
        assert (
            _template_snapshot(
                announcement_repo.get_template_by_id(template_id, session=session)
            )
            == template_before
        )
        drafts, draft_total = announcement_repo.list_drafts(session=session)

    assert draft_total == 0
    assert drafts == []
    assert announcement_after_resend["status"] == AnnouncementStatus.SENT
    for key in (
        "title",
        "content",
        "raw_content",
        "targets",
        "target_snapshot",
        "source_draft_id",
    ):
        assert announcement_after_resend[key] == announcement_before_resend[key]

    sent_messages = [message for batch in captured for message in batch]
    assert len(sent_messages) == 2
    assert all(message["content"] == content for message in sent_messages)
    assert all("<h1" in message["html_content"] for message in sent_messages)
    assert all("<strong>" in message["html_content"] for message in sent_messages)

    with session_scope(commit=False) as session:
        logs = list(
            session.scalars(
                select(OperationLog)
                .where(
                    OperationLog.target_type == "announcement",
                    OperationLog.target_id == announcement_id,
                )
                .order_by(OperationLog.id)
            ).all()
        )
    assert len(logs) == 2
    audit_text = json.dumps([log.detail for log in logs], ensure_ascii=False)
    assert "html_content" not in audit_text
    assert "<h1>" not in audit_text
    assert "<strong>" not in audit_text
