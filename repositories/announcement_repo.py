"""Announcement repository.

Repo functions only receive an explicit SQLAlchemy session and never commit or
rollback. Transaction boundaries live in service/tasks or API dependencies.
"""

import datetime as dt

from sqlalchemy import func, inspect, select, text, update
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


def list_announcements_by_ids(announcement_ids: list[int], *, session: Session) -> list[Announcement]:
    """按 id 取公告（批量发送的进度轮询用：只认自己那一批，不扫列表）。"""

    if not announcement_ids:
        return []
    return list(
        session.scalars(select(Announcement).where(Announcement.id.in_(announcement_ids))).all()
    )


def list_announcements_by_status(status: AnnouncementStatus, *, session: Session) -> list[Announcement]:
    """按状态取全部公告（启动期收尾遗留的 SENDING 用）。"""

    return list(session.scalars(select(Announcement).where(Announcement.status == status)).all())


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
    # 2026-10 决策（Q06）：模板生命周期与已生成内容解耦——删除模板不得被"谁引用过它"
    # 挡住，也不得反过来改写草稿/公告正文。草稿早已不保留关联（见 save_draft）；
    # 公告上的 template_id 只剩历史追溯，删除前先把指向本模板的引用解除，之后外键
    # 不再挡路（对旧库尤其重要：那里的外键约束是真的）。
    _detach_template_references(template_id, session=session)
    session.delete(template)
    session.flush()
    return True


def _detach_template_references(template_id: int, *, session: Session) -> int:
    """把指向该模板的持久引用清空（幂等），返回解除的行数。

    - `announcements.template_id` 走 ORM（新模型仍有这一追溯列）；
    - 旧库的 `announcement_drafts.template_id` 已不在新模型里，只有物理列还在时才用
      raw SQL 清，否则会因 no such column 报错。

    反射必须走 **session 自己的连接**（`session.connection()`），不能走
    `inspect(engine)`：测试库是 StaticPool 的单条 SQLite 连接，反射另开一次
    engine.connect() 会在归还连接时把本事务里刚做的 UPDATE 一起回滚掉。
    """

    detached = int(
        session.execute(
            update(Announcement)
            .where(Announcement.template_id == template_id)
            .values(template_id=None)
        ).rowcount
        or 0
    )
    inspector = inspect(session.connection())
    if inspector.has_table("announcement_drafts"):
        columns = {column["name"] for column in inspector.get_columns("announcement_drafts")}
        if "template_id" in columns:
            detached += int(
                session.execute(
                    text(
                        "UPDATE announcement_drafts SET template_id = NULL"
                        " WHERE template_id = :template_id"
                    ),
                    {"template_id": template_id},
                ).rowcount
                or 0
            )
    return detached


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
) -> AnnouncementDraft:
    """新建或更新草稿；更新只认属于 `created_by` 的草稿。

    草稿是每个操作员的私有编辑区（Q08）：更新按 (draft_id, created_by) 定位，别人的
    草稿当作不存在（`draft_not_found`），既不泄露存在性也不改动数据。

    这里**没有** template_id 参数（Q06/Q07）：模板选择是编辑器侧的一次性初值复制，
    草稿落库的是独立内容快照，不与模板保持持久关联。
    """

    if draft_id is not None:
        draft = get_draft_by_id(draft_id, session=session, created_by=created_by)
        if draft is None:
            raise ValueError("draft_not_found")
        draft.title = title
        draft.content = content
        if raw_content is not None:
            draft.raw_content = raw_content
        if targets is not None:
            draft.targets = targets
        draft.updated_at = dt.datetime.utcnow()
    else:
        draft = AnnouncementDraft(
            title=title,
            content=content,
            created_by=created_by,
            raw_content=raw_content,
            targets=targets,
        )
        session.add(draft)
    session.flush()
    return draft


def get_draft_by_id(
    draft_id: int, *, session: Session, created_by: int | None = None
) -> AnnouncementDraft | None:
    """按 id 取草稿；给了 `created_by` 就只认该操作员的草稿（Q08 私有语义）。

    `created_by=None` 只给不面向请求的内部路径用；API 与发送路径一律显式传操作员。
    """

    draft = session.get(AnnouncementDraft, int(draft_id))
    if draft is None:
        return None
    if created_by is not None and draft.created_by != created_by:
        return None
    return draft


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


def delete_draft(
    draft_id: int, *, session: Session, created_by: int | None = None
) -> bool:
    """删除草稿；给了 `created_by` 就只能删自己的（Q08）。"""

    draft = get_draft_by_id(draft_id, session=session, created_by=created_by)
    if draft is None:
        return False
    session.delete(draft)
    session.flush()
    return True
