"""公告系统 ORM 模型。

三张新表：
- announcements          已发送公告
- announcement_templates 信件级模板
- announcement_drafts    草稿（发送界面的待发送内容载体）
"""

import datetime as dt

from ..constant import AnnouncementStatus, AnnouncementTemplateCategory
from ..extensions import db


class Announcement(db.Model):
    __tablename__ = "announcements"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    raw_content = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    status = db.Column(
        db.Enum(AnnouncementStatus, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        index=True,
    )
    targets = db.Column(db.Text, nullable=True)
    target_snapshot = db.Column(db.Text, nullable=True)
    recipient_count = db.Column(db.Integer, default=0)
    success_count = db.Column(db.Integer, default=0)
    fail_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow)
    sent_at = db.Column(db.DateTime, nullable=True)
    source_draft_id = db.Column(db.Integer, nullable=True)
    template_id = db.Column(db.Integer, db.ForeignKey("announcement_templates.id"), nullable=True)

    creator = db.relationship("User")
    template = db.relationship("AnnouncementTemplate", foreign_keys=[template_id])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Announcement {self.id} title={self.title!r} status={self.status}>"


class AnnouncementTemplate(db.Model):
    __tablename__ = "announcement_templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    category = db.Column(
        db.Enum(AnnouncementTemplateCategory, values_callable=lambda obj: [e.value for e in obj]),
        default=AnnouncementTemplateCategory.CUSTOM,
        nullable=False,
    )
    description = db.Column(db.String(500), nullable=True)
    subject_template = db.Column(db.String(200), nullable=False)
    body_template = db.Column(db.Text, nullable=False)
    source_announcement_id = db.Column(db.Integer, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)

    creator = db.relationship("User")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AnnouncementTemplate {self.id} name={self.name!r} category={self.category}>"


class AnnouncementDraft(db.Model):
    __tablename__ = "announcement_drafts"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    raw_content = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    targets = db.Column(db.Text, nullable=True)
    template_id = db.Column(db.Integer, db.ForeignKey("announcement_templates.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)

    creator = db.relationship("User")
    template = db.relationship("AnnouncementTemplate", foreign_keys=[template_id])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AnnouncementDraft {self.id} title={self.title!r}>"
