"""公告系统仓库层测试（R-01 ~ R-15）。"""

import json

from ...constant import AnnouncementStatus, AnnouncementTemplateCategory
from ...repositories import announcement_repo
from ..factories import create_user


# ── 辅助工厂 ──────────────────────────────────────────────────────────

def _make_user():
    return create_user()


def _make_template(user, name="测试模板", category="custom"):
    return announcement_repo.create_template(
        name=name,
        subject_template="主题模板",
        body_template="正文模板",
        created_by=user.id,
        category=category,
    )


def _make_draft(user, title="草稿", content="正文"):
    return announcement_repo.save_draft(title=title, content=content, created_by=user.id)


def _make_announcement(user, title="公告", content="正文", status=AnnouncementStatus.SENT):
    return announcement_repo.create_announcement(
        title=title, content=content, created_by=user.id, status=status
    )


# ── 公告 ──────────────────────────────────────────────────────────────


def test_r01_create_announcement(db_session):
    """R-01: 用必填字段创建 Announcement。"""
    user = _make_user()
    ann = announcement_repo.create_announcement(
        title="GPU 维护通知",
        content="您好，GPU 将维护。",
        created_by=user.id,
    )
    assert ann.id is not None
    assert ann.title == "GPU 维护通知"
    assert ann.status == AnnouncementStatus.SENDING  # 默认


def test_r02_get_announcement_by_id_exists(db_session):
    """R-02: 按存在 id 查询。"""
    user = _make_user()
    ann = _make_announcement(user)
    found = announcement_repo.get_announcement_by_id(ann.id)
    assert found is not None
    assert found.id == ann.id


def test_r03_get_announcement_by_id_not_exists(db_session):
    """R-03: 按不存在 id 查询返回 None。"""
    assert announcement_repo.get_announcement_by_id(999) is None


def test_r04_list_announcements_by_status(db_session):
    """R-04: 多状态过滤。"""
    user = _make_user()
    _make_announcement(user, title="SENT", status=AnnouncementStatus.SENT)
    _make_announcement(user, title="PARTIAL", status=AnnouncementStatus.PARTIAL)
    _make_announcement(user, title="FAILED", status=AnnouncementStatus.FAILED)

    rows, total = announcement_repo.list_announcements(status=["sent", "partial"])
    assert total == 2
    statuses = {r.status for r in rows}
    assert AnnouncementStatus.SENT in statuses
    assert AnnouncementStatus.PARTIAL in statuses


def test_r05_list_announcements_pagination(db_session):
    """R-05: 分页 + 倒序。"""
    user = _make_user()
    for i in range(15):
        _make_announcement(user, title=f"公告{i}")

    rows, total = announcement_repo.list_announcements(limit=10, offset=5)
    assert total == 15
    assert len(rows) == 10
    # 按 created_at 倒序：最新的在前
    assert rows[0].created_at >= rows[-1].created_at


def test_r06_update_announcement_status(db_session):
    """R-06: 更新状态 + 计数 + 时间。"""
    import datetime as dt

    user = _make_user()
    ann = _make_announcement(user, status=AnnouncementStatus.SENDING)

    now = dt.datetime.utcnow()
    updated = announcement_repo.update_announcement_status(
        ann.id, status=AnnouncementStatus.SENT, success_count=18, fail_count=2, sent_at=now
    )
    assert updated is not None
    assert updated.status == AnnouncementStatus.SENT
    assert updated.success_count == 18
    assert updated.fail_count == 2
    assert updated.sent_at == now


# ── 模板 ──────────────────────────────────────────────────────────────


def test_r07_create_template(db_session):
    """R-07: 完整字段创建模板。"""
    user = _make_user()
    t = announcement_repo.create_template(
        name="系统维护模板",
        subject_template="维护通知",
        body_template="您好...",
        created_by=user.id,
        description="用于系统维护通知",
        category="custom",
    )
    assert t.id is not None
    assert t.name == "系统维护模板"
    assert t.description == "用于系统维护通知"


def test_r08_update_template_partial(db_session):
    """R-08: 部分字段更新模板。"""
    user = _make_user()
    t = _make_template(user, name="旧名")
    updated = announcement_repo.update_template(t.id, name="新名")
    assert updated is not None
    assert updated.name == "新名"
    assert updated.subject_template == "主题模板"  # 未改动


def test_r09_delete_template_custom(db_session):
    """R-09: 删除 custom 模板成功。"""
    user = _make_user()
    t = _make_template(user, category="custom")
    assert announcement_repo.delete_template(t.id) is True
    assert announcement_repo.get_template_by_id(t.id) is None


def test_r10_delete_template_system(db_session):
    """R-10: 删除 system 模板被拒。"""
    user = _make_user()
    t = _make_template(user, name="系统模板", category="system")
    assert announcement_repo.delete_template(t.id) is False
    assert announcement_repo.get_template_by_id(t.id) is not None


# ── 草稿 ──────────────────────────────────────────────────────────────


def test_r11_save_draft_create(db_session):
    """R-11: 新建草稿（draft_id=None）。"""
    user = _make_user()
    draft = announcement_repo.save_draft(title="新草稿", content="正文", created_by=user.id)
    assert draft.id is not None
    assert draft.title == "新草稿"


def test_r12_save_draft_update(db_session):
    """R-12: 更新已有草稿。"""
    user = _make_user()
    draft = _make_draft(user, title="旧标题", content="旧正文")
    old_updated_at = draft.updated_at

    import time
    time.sleep(0.01)  # 确保时间戳变化

    updated = announcement_repo.save_draft(
        title="新标题",
        content="新正文",
        created_by=user.id,
        draft_id=draft.id,
    )
    assert updated.id == draft.id
    assert updated.title == "新标题"
    assert updated.content == "新正文"
    # updated_at 应刷新
    assert updated.updated_at is not None


def test_r13_get_draft_by_id(db_session):
    """R-13: 按 id 查草稿，存在/不存在。"""
    user = _make_user()
    draft = _make_draft(user)
    assert announcement_repo.get_draft_by_id(draft.id) is not None
    assert announcement_repo.get_draft_by_id(999) is None


def test_r14_list_drafts_by_creator(db_session):
    """R-14: 按创建者过滤草稿。"""
    user_a = _make_user()
    user_b = _make_user()
    _make_draft(user_a, title="A的草稿")
    _make_draft(user_b, title="B的草稿")

    rows, total = announcement_repo.list_drafts(created_by=user_a.id)
    assert total == 1
    assert rows[0].title == "A的草稿"


def test_r15_delete_draft(db_session):
    """R-15: 删除草稿。"""
    user = _make_user()
    draft = _make_draft(user)
    assert announcement_repo.delete_draft(draft.id) is True
    assert announcement_repo.get_draft_by_id(draft.id) is None
    # 再次删除
    assert announcement_repo.delete_draft(draft.id) is False
