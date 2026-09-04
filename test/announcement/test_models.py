"""公告系统模型层测试（M-01 ~ M-08）。"""

import json

import pytest
from sqlalchemy.exc import IntegrityError

from ...constant import AnnouncementStatus, AnnouncementTemplateCategory
from ...models.announcement import Announcement, AnnouncementDraft, AnnouncementTemplate
from ..factories import create_user


# ── M-01: Announcement 创建 ─────────────────────────────────────────────

def test_m01_announcement_create_full_fields(db_session):
    user = create_user()
    ann = Announcement(
        title="GPU-01 维护通知",
        content="您好，GPU-01 将于今晚维护。",
        raw_content="{{greeting}}，{{machine_name}} 将于今晚维护。",
        created_by=user.id,
        status=AnnouncementStatus.SENDING,
        targets='[{"type":"machine","id":1}]',
        target_snapshot='[{"type":"machine","id":1,"display_name":"GPU-01 (10.0.0.1)"}]',
        recipient_count=18,
        template_id=None,
        source_draft_id=5,
    )
    db_session.add(ann)
    db_session.commit()

    assert ann.id is not None
    assert ann.title == "GPU-01 维护通知"
    assert ann.content == "您好，GPU-01 将于今晚维护。"
    assert ann.raw_content == "{{greeting}}，{{machine_name}} 将于今晚维护。"
    assert ann.created_by == user.id
    assert ann.status == AnnouncementStatus.SENDING
    assert ann.recipient_count == 18
    assert ann.source_draft_id == 5


# ── M-02: AnnouncementDraft 创建 ────────────────────────────────────────

def test_m02_draft_create_full_fields(db_session):
    user = create_user()
    draft = AnnouncementDraft(
        title="草稿标题",
        content="正文内容",
        raw_content="{{greeting}} 正文",
        created_by=user.id,
        targets='[{"type":"user","id":1}]',
        template_id=None,
    )
    db_session.add(draft)
    db_session.commit()

    assert draft.id is not None
    assert draft.title == "草稿标题"
    assert draft.content == "正文内容"
    assert draft.created_by == user.id
    assert draft.creator.id == user.id


# ── M-03: AnnouncementTemplate 唯一名 ───────────────────────────────────

def test_m03_template_unique_name(db_session):
    user = create_user()
    t1 = AnnouncementTemplate(
        name="系统维护模板",
        subject_template="维护通知",
        body_template="您好...",
        created_by=user.id,
        category=AnnouncementTemplateCategory.CUSTOM,
    )
    db_session.add(t1)
    db_session.commit()

    t2 = AnnouncementTemplate(
        name="系统维护模板",  # 同名
        subject_template="另一主题",
        body_template="另一正文",
        created_by=user.id,
        category=AnnouncementTemplateCategory.CUSTOM,
    )
    db_session.add(t2)
    with pytest.raises(IntegrityError):
        db_session.commit()


# ── M-04: Announcement ↔ Template 关联 ─────────────────────────────────

def test_m04_announcement_template_relation(db_session):
    user = create_user()
    template = AnnouncementTemplate(
        name="模板",
        subject_template="主题",
        body_template="正文",
        created_by=user.id,
    )
    db_session.add(template)
    db_session.commit()

    ann = Announcement(
        title="公告",
        content="正文",
        created_by=user.id,
        status=AnnouncementStatus.SENT,
        template_id=template.id,
    )
    db_session.add(ann)
    db_session.commit()

    assert ann.template is not None
    assert ann.template.name == "模板"


# ── M-05: targets JSON 存取 ────────────────────────────────────────────

def test_m05_targets_json_roundtrip(db_session):
    user = create_user()
    targets_data = [{"type": "machine", "id": 1}, {"type": "user", "id": 5}]
    targets_json = json.dumps(targets_data)

    ann = Announcement(
        title="公告",
        content="正文",
        created_by=user.id,
        status=AnnouncementStatus.SENT,
        targets=targets_json,
    )
    db_session.add(ann)
    db_session.commit()

    loaded = json.loads(ann.targets)
    assert loaded == targets_data
    assert loaded[0]["type"] == "machine"
    assert loaded[1]["type"] == "user"


# ── M-06: Template.source_announcement_id ──────────────────────────────

def test_m06_template_source_announcement_id(db_session):
    user = create_user()
    # 可空
    t1 = AnnouncementTemplate(
        name="无来源模板",
        subject_template="主题",
        body_template="正文",
        created_by=user.id,
    )
    db_session.add(t1)
    db_session.commit()
    assert t1.source_announcement_id is None

    # 可设值
    t2 = AnnouncementTemplate(
        name="有来源模板",
        subject_template="主题",
        body_template="正文",
        created_by=user.id,
        source_announcement_id=42,
    )
    db_session.add(t2)
    db_session.commit()
    assert t2.source_announcement_id == 42


# ── M-07: Draft ↔ Template 关联 ────────────────────────────────────────

def test_m07_draft_template_relation(db_session):
    user = create_user()
    template = AnnouncementTemplate(
        name="模板",
        subject_template="主题",
        body_template="正文",
        created_by=user.id,
    )
    db_session.add(template)
    db_session.commit()

    draft = AnnouncementDraft(
        title="草稿",
        content="正文",
        created_by=user.id,
        template_id=template.id,
    )
    db_session.add(draft)
    db_session.commit()

    assert draft.template is not None
    assert draft.template.name == "模板"


# ── M-08: Announcement.source_draft_id ─────────────────────────────────

def test_m08_announcement_source_draft_id(db_session):
    user = create_user()
    draft = AnnouncementDraft(
        title="草稿",
        content="正文",
        created_by=user.id,
    )
    db_session.add(draft)
    db_session.commit()

    ann = Announcement(
        title="公告",
        content="正文",
        created_by=user.id,
        status=AnnouncementStatus.SENT,
        source_draft_id=draft.id,
    )
    db_session.add(ann)
    db_session.commit()

    assert ann.source_draft_id == draft.id
