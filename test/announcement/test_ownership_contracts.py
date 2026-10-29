"""Q68 ownership contracts: no announcement/template creator, draft author stays."""

import datetime as dt
import json

from sqlalchemy import inspect

from ...constant import AnnouncementStatus
from ...extensions import session_scope
from ...models.announcement import Announcement, AnnouncementDraft, AnnouncementTemplate
from ...repositories import announcement_repo
from ...services import user_tasks
from ...services.announcement_tasks import (
    TargetEntry,
    convert_announcement_to_template_service,
    copy_announcement_as_draft_service,
    start_batch_send_service,
    start_resend_service,
)
from ..assertions import assert_json_success
from ..factories import create_user
from ..mocks import mock_operator_token

_OPERATOR_HEADERS = {"token": "test-operator-token"}
_ANNOUNCEMENT_VIEW_KEYS = {
    "id",
    "title",
    "content",
    "raw_content",
    "status",
    "targets",
    "target_snapshot",
    "recipient_count",
    "success_count",
    "fail_count",
    "created_at",
    "sent_at",
    "source_draft_id",
    "template_id",
}
_TEMPLATE_VIEW_KEYS = {
    "id",
    "name",
    "category",
    "description",
    "subject_template",
    "body_template",
    "source_announcement_id",
    "created_at",
    "updated_at",
}
_ANNOUNCEMENT_SCALARS = (
    "id",
    "title",
    "content",
    "raw_content",
    "status",
    "targets",
    "target_snapshot",
    "recipient_count",
    "success_count",
    "fail_count",
    "created_at",
    "sent_at",
    "source_draft_id",
    "template_id",
)
_TEMPLATE_SCALARS = (
    "id",
    "name",
    "category",
    "description",
    "subject_template",
    "body_template",
    "source_announcement_id",
    "created_at",
    "updated_at",
)


def _make_template(
    *,
    name="模板",
    subject="主题",
    body="正文",
    category="custom",
    description="模板描述",
    source_announcement_id=None,
    created_at=None,
):
    with session_scope() as session:
        template = announcement_repo.create_template(
            name=name,
            subject_template=subject,
            body_template=body,
            description=description,
            category=category,
            source_announcement_id=source_announcement_id,
            session=session,
        )
        if created_at is not None:
            template.created_at = created_at
            template.updated_at = created_at
            session.flush()
        return template


def _make_announcement(
    *,
    title="公告",
    content="正文",
    raw_content=None,
    status=AnnouncementStatus.SENT,
    targets=None,
    target_snapshot=None,
    recipient_count=0,
    source_draft_id=None,
    template_id=None,
    success_count=0,
    fail_count=0,
    sent_at=None,
    created_at=None,
):
    with session_scope() as session:
        announcement = announcement_repo.create_announcement(
            title=title,
            content=content,
            raw_content=raw_content,
            status=status,
            targets=targets,
            target_snapshot=target_snapshot,
            recipient_count=recipient_count,
            source_draft_id=source_draft_id,
            template_id=template_id,
            session=session,
        )
        announcement.success_count = success_count
        announcement.fail_count = fail_count
        announcement.sent_at = sent_at
        if created_at is not None:
            announcement.created_at = created_at
        session.flush()
        return announcement


def _make_draft(owner, *, title="草稿", content="正文", targets=None):
    with session_scope() as session:
        return announcement_repo.save_draft(
            title=title,
            content=content,
            targets=targets,
            created_by=owner.id,
            session=session,
        )


def _scalar_snapshot(model, fields):
    return {field: getattr(model, field) for field in fields}


def test_announcement_and_template_models_have_no_creator(db_session):
    bind = db_session.get_bind()
    inspector = inspect(bind)

    for table in ("announcements", "announcement_templates"):
        columns = {column["name"] for column in inspector.get_columns(table)}
        assert "created_by" not in columns
        assert not any(
            "created_by" in (fk.get("constrained_columns") or [])
            for fk in inspector.get_foreign_keys(table)
        )

    assert "creator" not in inspect(Announcement).relationships.keys()
    assert "creator" not in inspect(AnnouncementTemplate).relationships.keys()

    draft_columns = {
        column["name"] for column in inspector.get_columns("announcement_drafts")
    }
    assert "created_by" in draft_columns
    assert "creator" in inspect(AnnouncementDraft).relationships.keys()


def test_announcement_and_template_api_views_omit_creator(client, monkeypatch):
    operator = create_user(operator=True)
    base = dt.datetime(2026, 1, 1, 12, 0, 0)
    templates = [
        _make_template(
            name=f"q68-api-template-{index}",
            description=f"description-{index}",
            created_at=base + dt.timedelta(seconds=index),
        )
        for index in range(3)
    ]
    announcements = [
        _make_announcement(
            title=f"q68-api-announcement-{index}",
            content=f"api content {index}",
            raw_content=f"api raw {index}",
            targets=json.dumps([{"type": "user", "id": operator.id}]),
            target_snapshot=json.dumps(
                [{"type": "user", "id": operator.id, "display_name": operator.username}]
            ),
            recipient_count=1,
            success_count=1,
            fail_count=0,
            created_at=base + dt.timedelta(seconds=index),
        )
        for index in range(3)
    ]
    mock_operator_token(
        monkeypatch,
        __import__("FuxiYu_CtrKernel.api.announcement_api", fromlist=[""]),
        user_id=operator.id,
    )

    template_detail = assert_json_success(
        client.get(f"/api/announcements/templates/{templates[0].id}", headers=_OPERATOR_HEADERS)
    )
    template_list = assert_json_success(
        client.get("/api/announcements/templates?limit=2&offset=1", headers=_OPERATOR_HEADERS)
    )
    announcement_detail = assert_json_success(
        client.get(f"/api/announcements/{announcements[0].id}", headers=_OPERATOR_HEADERS)
    )
    announcement_list = assert_json_success(
        client.get("/api/announcements/list?limit=2&offset=1", headers=_OPERATOR_HEADERS)
    )

    assert set(template_detail) == {"success", "template"}
    assert set(template_list) == {"success", "templates", "total"}
    assert set(announcement_detail) == {"success", "announcement"}
    assert set(announcement_list) == {
        "success",
        "announcements",
        "total",
        "sent_count",
        "partial_count",
        "failed_count",
    }
    assert set(template_detail["template"]) == _TEMPLATE_VIEW_KEYS
    assert set(announcement_detail["announcement"]) == _ANNOUNCEMENT_VIEW_KEYS
    assert all(set(row) == _TEMPLATE_VIEW_KEYS for row in template_list["templates"])
    assert all(
        set(row) == _ANNOUNCEMENT_VIEW_KEYS for row in announcement_list["announcements"]
    )
    assert template_list["total"] == 3
    assert announcement_list["total"] == 3
    assert [row["id"] for row in template_list["templates"]] == [
        templates[1].id,
        templates[0].id,
    ]
    assert [row["id"] for row in announcement_list["announcements"]] == [
        announcements[1].id,
        announcements[0].id,
    ]
    assert announcement_list["sent_count"] == 3
    assert announcement_list["partial_count"] == 0
    assert announcement_list["failed_count"] == 0
    assert template_detail["template"]["name"] == "q68-api-template-0"
    assert announcement_detail["announcement"]["title"] == "q68-api-announcement-0"
    assert announcement_detail["announcement"]["raw_content"] == "api raw 0"


def test_delete_author_keeps_announcements_and_templates(
    db_session, monkeypatch, inline_send_thread
):
    author = create_user(email="q68-author@example.invalid")
    target = create_user(email="q68-target@example.invalid")
    author_draft = _make_draft(author, title="author draft")
    template = _make_template(
        name="q68-kept-template",
        subject="kept subject",
        body="kept body",
        description="kept description",
    )
    targets = json.dumps([TargetEntry(type="user", id=target.id).model_dump()])
    sent_at = dt.datetime.utcnow()
    announcement = _make_announcement(
        title="q68-kept-announcement",
        content="kept content",
        raw_content="kept raw",
        targets=targets,
        target_snapshot=json.dumps(
            [{"type": "user", "id": target.id, "display_name": target.username}]
        ),
        recipient_count=1,
        source_draft_id=author_draft.id,
        template_id=template.id,
        success_count=1,
        fail_count=0,
        sent_at=sent_at,
    )
    with session_scope() as session:
        stored_template = announcement_repo.get_template_by_id(template.id, session=session)
        stored_template.source_announcement_id = announcement.id
    other_draft = _make_draft(target, title="other draft")

    with session_scope(commit=False) as session:
        announcement_before = _scalar_snapshot(
            announcement_repo.get_announcement_by_id(announcement.id, session=session),
            _ANNOUNCEMENT_SCALARS,
        )
        template_before = _scalar_snapshot(
            announcement_repo.get_template_by_id(template.id, session=session),
            _TEMPLATE_SCALARS,
        )

    monkeypatch.setattr(
        user_tasks.usercontainer_repo,
        "remove_user_from_all_containers",
        lambda user_id, **kwargs: {"ok": True},
    )
    assert user_tasks.Delete_user(author.id) is True

    with session_scope(commit=False) as session:
        announcement_after = _scalar_snapshot(
            announcement_repo.get_announcement_by_id(announcement.id, session=session),
            _ANNOUNCEMENT_SCALARS,
        )
        template_after = _scalar_snapshot(
            announcement_repo.get_template_by_id(template.id, session=session),
            _TEMPLATE_SCALARS,
        )
        assert announcement_repo.get_draft_by_id(author_draft.id, session=session) is None
        assert announcement_repo.get_draft_by_id(other_draft.id, session=session) is not None
    assert announcement_after == announcement_before
    assert template_after == template_before
    assert announcement_after["template_id"] == template.id
    assert announcement_after["source_draft_id"] == author_draft.id
    assert announcement_after["sent_at"] == sent_at
    assert announcement_after["recipient_count"] == 1
    assert announcement_after["success_count"] == 1
    assert announcement_after["fail_count"] == 0

    captured = []

    def _capture(messages, **kwargs):
        captured.append([dict(message) for message in messages])
        return [{"ok": True, "to": [message["to"]]} for message in messages]

    monkeypatch.setattr("FuxiYu_CtrKernel.utils.mail._send_batch_smtp", _capture)

    start_resend_service(announcement.id)
    with session_scope(commit=False) as session:
        resent = announcement_repo.get_announcement_by_id(announcement.id, session=session)
        assert resent.title == "q68-kept-announcement"
        assert resent.content == "kept content"
        assert resent.raw_content == "kept raw"
        assert resent.targets == targets
        assert resent.status == AnnouncementStatus.SENT
    assert len(captured) == 1 and len(captured[0]) == 1
    assert captured[0][0]["to"] == target.email
    assert captured[0][0]["subject"] == "q68-kept-announcement"
    assert captured[0][0]["content"] == "kept content"


def test_batch_send_and_resend_do_not_require_creator(db_session, inline_send_thread):
    owner = create_user(email="q68-send@example.invalid")
    targets = json.dumps([TargetEntry(type="user", id=owner.id).model_dump()])
    draft = _make_draft(owner, title="q68-send-title", content="q68-send-body", targets=targets)

    accepted = start_batch_send_service([draft.id], [TargetEntry(type="user", id=owner.id)])
    assert accepted.total == 1
    announcement_id = accepted.announcement_ids[0]

    with session_scope(commit=False) as session:
        announcement = announcement_repo.get_announcement_by_id(announcement_id, session=session)
        assert announcement.title == "q68-send-title"
        assert announcement.content == "q68-send-body"
        assert announcement.raw_content == "q68-send-body"
        assert announcement.targets == targets
        assert announcement.source_draft_id == draft.id
        assert not hasattr(announcement, "created_by")
        assert not hasattr(announcement, "creator")

    start_resend_service(announcement_id)
    with session_scope(commit=False) as session:
        resent = announcement_repo.get_announcement_by_id(announcement_id, session=session)
        assert resent.status == AnnouncementStatus.SENT
        assert resent.title == "q68-send-title"
        assert resent.content == "q68-send-body"
        assert resent.raw_content == "q68-send-body"
        assert resent.targets == targets
        assert resent.source_draft_id == draft.id


def test_copy_announcement_as_draft_assigns_current_operator(db_session):
    owner = create_user()
    copier = create_user()
    targets = json.dumps([{"type": "user", "id": owner.id}])
    announcement = _make_announcement(
        title="q68-copy-title",
        content="q68-copy-body",
        raw_content="q68-copy-raw",
        targets=targets,
    )

    draft = copy_announcement_as_draft_service(announcement.id, created_by=copier.id)
    assert draft.created_by == copier.id
    assert draft.title == "q68-copy-title"
    assert draft.content == "q68-copy-raw"
    assert draft.raw_content == "q68-copy-raw"
    assert draft.targets == targets

    with session_scope(commit=False) as session:
        copier_rows, copier_total = announcement_repo.list_drafts(
            created_by=copier.id, session=session
        )
        owner_rows, owner_total = announcement_repo.list_drafts(
            created_by=owner.id, session=session
        )
    assert copier_total == 1 and copier_rows[0].id == draft.id
    assert owner_total == 0 and owner_rows == []

    fallback_announcement = _make_announcement(
        title="q68-copy-fallback-title",
        content="q68-copy-fallback-body",
        raw_content=None,
    )
    fallback_draft = copy_announcement_as_draft_service(
        fallback_announcement.id, created_by=copier.id
    )
    assert fallback_draft.created_by == copier.id
    assert fallback_draft.content == "q68-copy-fallback-body"
    assert fallback_draft.raw_content is None


def test_convert_announcement_to_template_without_creator(db_session):
    announcement = _make_announcement(
        title="q68-convert-title",
        content="q68-convert-body",
        raw_content="q68-convert-raw",
    )

    template = convert_announcement_to_template_service(announcement.id)
    assert template.subject_template == "q68-convert-title"
    assert template.body_template == "q68-convert-raw"
    assert template.source_announcement_id == announcement.id
    assert not hasattr(template, "created_by")
    assert not hasattr(template, "creator")
