"""Announcement repository.

Repo functions only receive an explicit SQLAlchemy session and never commit or
rollback. Transaction boundaries live in service/tasks or API dependencies.
"""

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..constant import AnnouncementStatus, AnnouncementTemplateCategory
from ..models.announcement import Announcement, AnnouncementDraft, AnnouncementTemplate


#####################
# 公告


def create_announcement(
    title: str,
    content: str,
    created_by: int,
    *,
    session: Session,
    status: AnnouncementStatus = AnnouncementStatus.SENDING,
    raw_content: str | None = None,
    targets: str | None = None,
    target_snapshot: str | None = None,
    recipient_count: int = 0,
    template_id: int | None = None,
    source_draft_id: int | None = None,
) -> Announcement:
    announcement = Announcement(
        title=title,
        content=content,
        created_by=created_by,
        status=status,
        raw_content=raw_content,
        targets=targets,
        target_snapshot=target_snapshot,
        recipient_count=recipient_count,
        template_id=template_id,
        source_draft_id=source_draft_id,
    )
    session.add(announcement)
    session.flush()
    return announcement


def get_announcement_by_id(announcement_id: int, *, session: Session) -> Announcement | None:
    return session.get(Announcement, int(announcement_id))


def list_announcements(
    *,
    session: Session,
    status: list[str] | None = None,
    created_by: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Announcement], int]:
    stmt = select(Announcement)
    if status:
        stmt = stmt.where(Announcement.status.in_(status))
    if created_by is not None:
        stmt = stmt.where(Announcement.created_by == created_by)

    total = int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = list(
        session.scalars(
            stmt.order_by(Announcement.created_at.desc()).offset(offset).limit(limit)
        ).all()
    )
    return rows, total


def count_announcements_by_status(status: AnnouncementStatus, *, session: Session) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(Announcement).where(Announcement.status == status)
        )
        or 0
    )


def update_announcement_status(
    announcement_id: int,
    status: AnnouncementStatus,
    *,
    session: Session,
    success_count: int | None = None,
    fail_count: int | None = None,
    sent_at: dt.datetime | None = None,
) -> Announcement | None:
    ann = get_announcement_by_id(announcement_id, session=session)
    if ann is None:
        return None
    ann.status = status
    if success_count is not None:
        ann.success_count = success_count
    if fail_count is not None:
        ann.fail_count = fail_count
    if sent_at is not None:
        ann.sent_at = sent_at
    session.flush()
    return ann


def delete_announcement(announcement_id: int, *, session: Session) -> bool:
    ann = get_announcement_by_id(announcement_id, session=session)
    if ann is None:
        return False
    session.delete(ann)
    session.flush()
    return True


#####################
# 模板


def create_template(
    name: str,
    subject_template: str,
    body_template: str,
    created_by: int,
    *,
    session: Session,
    description: str | None = None,
    category: str = "custom",
    source_announcement_id: int | None = None,
) -> AnnouncementTemplate:
    template = AnnouncementTemplate(
        name=name,
        subject_template=subject_template,
        body_template=body_template,
        created_by=created_by,
        description=description,
        category=AnnouncementTemplateCategory(category),
        source_announcement_id=source_announcement_id,
    )
    session.add(template)
    session.flush()
    return template


def get_template_by_id(template_id: int, *, session: Session) -> AnnouncementTemplate | None:
    return session.get(AnnouncementTemplate, int(template_id))


def list_templates(
    *,
    session: Session,
    category: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[AnnouncementTemplate], int]:
    stmt = select(AnnouncementTemplate)
    if category is not None:
        stmt = stmt.where(AnnouncementTemplate.category == AnnouncementTemplateCategory(category))

    total = int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = list(
        session.scalars(
            stmt.order_by(AnnouncementTemplate.created_at.desc()).offset(offset).limit(limit)
        ).all()
    )
    return rows, total


def update_template(template_id: int, *, session: Session, **fields) -> AnnouncementTemplate | None:
    allowed = {"name", "description", "subject_template", "body_template", "category"}
    template = get_template_by_id(template_id, session=session)
    if template is None:
        return None
    for key, value in fields.items():
        if key in allowed and value is not None:
            if key == "category":
                value = AnnouncementTemplateCategory(value)
            setattr(template, key, value)
    session.flush()
    return template


def delete_template(template_id: int, *, session: Session) -> bool:
    template = get_template_by_id(template_id, session=session)
    if template is None:
        return False
    if template.category == AnnouncementTemplateCategory.SYSTEM:
        return False
    session.delete(template)
    session.flush()
    return True


#####################
# 草稿


def save_draft(
    title: str,
    content: str,
    created_by: int,
    *,
    session: Session,
    draft_id: int | None = None,
    raw_content: str | None = None,
    targets: str | None = None,
    template_id: int | None = None,
) -> AnnouncementDraft:
    if draft_id is not None:
        draft = get_draft_by_id(draft_id, session=session)
        if draft is None:
            raise ValueError("draft_not_found")
        draft.title = title
        draft.content = content
        if raw_content is not None:
            draft.raw_content = raw_content
        if targets is not None:
            draft.targets = targets
        if template_id is not None:
            draft.template_id = template_id
        draft.updated_at = dt.datetime.utcnow()
    else:
        draft = AnnouncementDraft(
            title=title,
            content=content,
            created_by=created_by,
            raw_content=raw_content,
            targets=targets,
            template_id=template_id,
        )
        session.add(draft)
    session.flush()
    return draft


def get_draft_by_id(draft_id: int, *, session: Session) -> AnnouncementDraft | None:
    return session.get(AnnouncementDraft, int(draft_id))


def list_drafts(
    *,
    session: Session,
    created_by: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AnnouncementDraft], int]:
    stmt = select(AnnouncementDraft)
    if created_by is not None:
        stmt = stmt.where(AnnouncementDraft.created_by == created_by)

    total = int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = list(
        session.scalars(
            stmt.order_by(AnnouncementDraft.updated_at.desc()).offset(offset).limit(limit)
        ).all()
    )
    return rows, total


def delete_draft(draft_id: int, *, session: Session) -> bool:
    draft = get_draft_by_id(draft_id, session=session)
    if draft is None:
        return False
    session.delete(draft)
    session.flush()
    return True
