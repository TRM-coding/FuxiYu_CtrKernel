"""Announcement 仓库层：提供公告、模板、草稿的 CRUD 操作。

全部函数都通过 db.session 直接访问数据库，由调用方通过 Flask
应用上下文保证 session 可用。
"""

import datetime as dt

from ..constant import AnnouncementStatus, AnnouncementTemplateCategory
from ..extensions import db
from ..models.announcement import Announcement, AnnouncementDraft, AnnouncementTemplate


# ── 公告 ──────────────────────────────────────────────────────────────

def create_announcement(
    title: str,
    content: str,
    created_by: int,
    *,
    status: AnnouncementStatus = AnnouncementStatus.SENDING,
    raw_content: str | None = None,
    targets: str | None = None,
    target_snapshot: str | None = None,
    recipient_count: int = 0,
    template_id: int | None = None,
    source_draft_id: int | None = None,
) -> Announcement:
    """创建一条公告记录，初始状态为 SENDING。"""
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
    db.session.add(announcement)
    db.session.commit()
    return announcement


def get_announcement_by_id(announcement_id: int) -> Announcement | None:
    """按主键查询公告。"""
    return Announcement.query.get(announcement_id)


def list_announcements(
    *,
    status: list[str] | None = None,
    created_by: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Announcement], int]:
    """分页查询公告，支持按状态和创建者过滤。"""
    q = Announcement.query
    if status:
        q = q.filter(Announcement.status.in_(status))
    if created_by is not None:
        q = q.filter_by(created_by=created_by)

    total = q.count()
    rows = q.order_by(Announcement.created_at.desc()).offset(offset).limit(limit).all()
    return rows, total


def update_announcement_status(
    announcement_id: int,
    status: AnnouncementStatus,
    *,
    success_count: int | None = None,
    fail_count: int | None = None,
    sent_at: dt.datetime | None = None,
) -> Announcement | None:
    """更新公告状态与发送统计数据（仅非 None 字段）。"""
    ann = get_announcement_by_id(announcement_id)
    if ann is None:
        return None
    ann.status = status
    if success_count is not None:
        ann.success_count = success_count
    if fail_count is not None:
        ann.fail_count = fail_count
    if sent_at is not None:
        ann.sent_at = sent_at
    db.session.commit()
    return ann


def delete_announcement(announcement_id: int) -> bool:
    """物理删除公告。"""
    ann = get_announcement_by_id(announcement_id)
    if ann is None:
        return False
    db.session.delete(ann)
    db.session.commit()
    return True


# ── 模板 ──────────────────────────────────────────────────────────────

def create_template(
    name: str,
    subject_template: str,
    body_template: str,
    created_by: int,
    *,
    description: str | None = None,
    category: str = "custom",
    source_announcement_id: int | None = None,
) -> AnnouncementTemplate:
    """新建模板。"""
    template = AnnouncementTemplate(
        name=name,
        subject_template=subject_template,
        body_template=body_template,
        created_by=created_by,
        description=description,
        category=AnnouncementTemplateCategory(category),
        source_announcement_id=source_announcement_id,
    )
    db.session.add(template)
    db.session.commit()
    return template


def get_template_by_id(template_id: int) -> AnnouncementTemplate | None:
    """按主键查询模板。"""
    return AnnouncementTemplate.query.get(template_id)


def list_templates(
    *,
    category: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[AnnouncementTemplate], int]:
    """分页查询模板，支持按类别过滤。"""
    q = AnnouncementTemplate.query
    if category is not None:
        q = q.filter_by(category=AnnouncementTemplateCategory(category))

    total = q.count()
    rows = q.order_by(AnnouncementTemplate.created_at.desc()).offset(offset).limit(limit).all()
    return rows, total


def update_template(template_id: int, **fields) -> AnnouncementTemplate | None:
    """按主键更新模板允许的字段：
    name, description, subject_template, body_template, variables, category。
    """
    allowed = {"name", "description", "subject_template", "body_template", "category"}
    template = get_template_by_id(template_id)
    if template is None:
        return None
    for key, value in fields.items():
        if key in allowed and value is not None:
            if key == "category":
                value = AnnouncementTemplateCategory(value)
            setattr(template, key, value)
    db.session.commit()
    return template


def delete_template(template_id: int) -> bool:
    """删除模板（仅允许 CUSTOM 类别；SYSTEM 不可删）。"""
    template = get_template_by_id(template_id)
    if template is None:
        return False
    if template.category == AnnouncementTemplateCategory.SYSTEM:
        return False
    db.session.delete(template)
    db.session.commit()
    return True


# ── 草稿 ──────────────────────────────────────────────────────────────

def save_draft(
    title: str,
    content: str,
    created_by: int,
    *,
    draft_id: int | None = None,
    raw_content: str | None = None,
    targets: str | None = None,
    template_id: int | None = None,
) -> AnnouncementDraft:
    """幂等保存草稿：draft_id 存在则更新，否则新建。"""
    if draft_id is not None:
        draft = get_draft_by_id(draft_id)
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
        db.session.add(draft)
    db.session.commit()
    return draft


def get_draft_by_id(draft_id: int) -> AnnouncementDraft | None:
    """按主键查询草稿。"""
    return AnnouncementDraft.query.get(draft_id)


def list_drafts(
    *,
    created_by: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AnnouncementDraft], int]:
    """分页查询草稿，支持按创建者过滤。"""
    q = AnnouncementDraft.query
    if created_by is not None:
        q = q.filter_by(created_by=created_by)

    total = q.count()
    rows = q.order_by(AnnouncementDraft.updated_at.desc()).offset(offset).limit(limit).all()
    return rows, total


def delete_draft(draft_id: int) -> bool:
    """物理删除草稿。"""
    draft = get_draft_by_id(draft_id)
    if draft is None:
        return False
    db.session.delete(draft)
    db.session.commit()
    return True
