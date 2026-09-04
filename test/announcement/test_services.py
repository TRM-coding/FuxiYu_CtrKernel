"""公告系统服务层测试。

元素快填在编辑时由前端完成，服务层不再参与变量渲染/预览。
"""

import json

import pytest

from ...constant import AnnouncementStatus, ROLE
from ...extensions import session_scope
from ...repositories import announcement_repo
from ...services.announcement_tasks import (
    TargetEntry,
    batch_send_drafts_service,
    convert_announcement_to_template_service,
    copy_announcement_as_draft_service,
    resend_announcement_service,
    resolve_recipients,
    send_draft_service,
)
from ..factories import (
    bind_user_container,
    create_container,
    create_container_graph,
    create_machine,
    create_user,
)


def _repo_save_draft(**kwargs):
    with session_scope() as session:
        return announcement_repo.save_draft(session=session, **kwargs)


def _repo_get_draft(draft_id: int):
    with session_scope(commit=False) as session:
        return announcement_repo.get_draft_by_id(draft_id, session=session)


def _repo_create_announcement(**kwargs):
    with session_scope() as session:
        return announcement_repo.create_announcement(session=session, **kwargs)


def _repo_get_announcement(announcement_id: int):
    with session_scope(commit=False) as session:
        return announcement_repo.get_announcement_by_id(announcement_id, session=session)


def _repo_create_template(**kwargs):
    with session_scope() as session:
        return announcement_repo.create_template(session=session, **kwargs)


# ══════════════════════════════════════════════════════════════════════
# 收件人解析
# ══════════════════════════════════════════════════════════════════════


def test_s01_resolve_pure_machine(db_session, monkeypatch):
    """S-01: 纯机器目标 → MachinePermission 用户列表。"""
    user = create_user(email="u1@bjtu.edu.cn", username="user1")
    machine = create_machine(machine_name="GPU-01", machine_ip="10.0.0.1")
    bind_user_container(create_container(machine=machine), user)
    from ...repositories.machine_permission_repo import add_permission
    with session_scope() as session:
        add_permission(machine.id, user.id, session=session)

    result = resolve_recipients([TargetEntry(type="machine", id=machine.id)])
    assert result.total_count >= 1
    assert any(r.user_id == user.id for r in result.recipients)


def test_s02_resolve_pure_container(db_session):
    """S-02: 纯容器目标 → 容器成员列表。"""
    root, machine, container = create_container_graph()
    root.email = "root@bjtu.edu.cn"
    root.username = "rootuser"
    db_session.commit()

    result = resolve_recipients([TargetEntry(type="container", id=container.id)])
    assert result.total_count >= 1
    assert any(r.user_id == root.id for r in result.recipients)
    assert result.summary[0].display_name == f"{container.name} (:{container.port})"


def test_s03_resolve_pure_user(db_session):
    """S-03: 纯用户目标。"""
    u1 = create_user(email="u1@bjtu.edu.cn", username="u1")
    u2 = create_user(email="u2@bjtu.edu.cn", username="u2")

    result = resolve_recipients(
        [TargetEntry(type="user", id=u1.id), TargetEntry(type="user", id=u2.id)]
    )
    assert result.total_count == 2
    emails = {r.email for r in result.recipients}
    assert "u1@bjtu.edu.cn" in emails
    assert "u2@bjtu.edu.cn" in emails


def test_s04_resolve_mixed_machine_and_user(db_session):
    """S-04: 混合目标 → 合并去重。"""
    user = create_user(email="shared@bjtu.edu.cn", username="shared")
    machine = create_machine()
    from ...repositories.machine_permission_repo import add_permission
    with session_scope() as session:
        add_permission(machine.id, user.id, session=session)

    result = resolve_recipients(
        [TargetEntry(type="machine", id=machine.id), TargetEntry(type="user", id=user.id)]
    )
    assert result.total_count == 1
    assert result.recipients[0].email == "shared@bjtu.edu.cn"


def test_s05_dedup_across_collections(db_session):
    """S-05: 同一用户通过 machine + user 命中 → email 不重复。"""
    user = create_user(email="dup@bjtu.edu.cn", username="dup")
    machine = create_machine()
    from ...repositories.machine_permission_repo import add_permission
    with session_scope() as session:
        add_permission(machine.id, user.id, session=session)

    result = resolve_recipients(
        [TargetEntry(type="machine", id=machine.id), TargetEntry(type="user", id=user.id)]
    )
    emails = [r.email for r in result.recipients]
    assert emails.count("dup@bjtu.edu.cn") == 1
    assert result.total_count == 1


def test_s06_too_many_recipients(db_session, app):
    """S-06: 收件人超过上限 → ValueError。"""
    targets = []
    for _ in range(250):
        u = create_user()
        targets.append(TargetEntry(type="user", id=u.id))

    with pytest.raises(ValueError, match="too_many_recipients"):
        resolve_recipients(targets)


# ══════════════════════════════════════════════════════════════════════
# 草稿发送（纯文字，无变量渲染）
# ══════════════════════════════════════════════════════════════════════


def test_s10_send_draft_all_success(db_session, monkeypatch):
    """S-10: mock mail 全成功 → status=SENT, 草稿删除。"""
    user = create_user(email="u@bjtu.edu.cn")
    draft = _repo_save_draft(title="维护通知", content="您好，GPU-01 将于今晚维护。", created_by=user.id)

    result = send_draft_service(draft.id, targets=[TargetEntry(type="user", id=user.id)])
    assert result.status == "sent"
    assert result.success_count == 1
    assert result.fail_count == 0
    assert _repo_get_draft(draft.id) is None

    ann = _repo_get_announcement(result.announcement_id)
    assert ann is not None
    assert ann.status == AnnouncementStatus.SENT
    # 内容应直接使用草稿内容，不做变量渲染
    assert ann.content == "您好，GPU-01 将于今晚维护。"


def test_s11_send_draft_partial_failure(db_session, monkeypatch):
    """S-11: mock mail 部分失败 → status=PARTIAL。"""
    u1 = create_user(email="u1@bjtu.edu.cn")
    u2 = create_user(email="u2@bjtu.edu.cn")
    draft = _repo_save_draft(title="通知", content="正文", created_by=u1.id)

    call_count = [0]

    def _mock_send_batch(messages, **kwargs):
        results = []
        for i, m in enumerate(messages):
            to = m.get("to", "")
            recips = [to] if isinstance(to, str) else list(to)
            if i == 0:
                results.append({"ok": True, "to": recips})
            else:
                results.append({"ok": False, "error": "simulated failure", "to": recips})
        return results

    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.announcement_tasks.send_batch", _mock_send_batch
    )

    result = send_draft_service(
        draft.id,
        targets=[TargetEntry(type="user", id=u1.id), TargetEntry(type="user", id=u2.id)],
    )
    assert result.status == "partial"
    assert result.success_count == 1
    assert result.fail_count == 1


def test_s12_send_draft_all_failure(db_session, monkeypatch):
    """S-12: mock mail 全失败 → status=FAILED。"""
    u1 = create_user(email="u1@bjtu.edu.cn")
    draft = _repo_save_draft(title="通知", content="正文", created_by=u1.id)

    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.announcement_tasks.send_batch",
        lambda messages, **kw: [{"ok": False, "error": "fail", "to": [m["to"]] if isinstance(m["to"], str) else m["to"]} for m in messages],
    )

    result = send_draft_service(draft.id, targets=[TargetEntry(type="user", id=u1.id)])
    assert result.status == "failed"
    assert result.success_count == 0


def test_s13_send_draft_empty_targets(db_session):
    """S-13: targets 为空 → ValueError。"""
    user = create_user()
    draft = _repo_save_draft(title="通知", content="正文", created_by=user.id)

    with pytest.raises(ValueError, match="empty_targets"):
        send_draft_service(draft.id, targets=[])


def test_s14_send_draft_not_found(db_session):
    """S-14: draft 不存在 → ValueError。"""
    user = create_user()
    with pytest.raises(ValueError, match="draft_not_found"):
        send_draft_service(999, targets=[TargetEntry(type="user", id=user.id)])


# ══════════════════════════════════════════════════════════════════════
# 批量发送
# ══════════════════════════════════════════════════════════════════════


def test_s15_batch_send_three_drafts(db_session, monkeypatch):
    """S-15: 批量发送 3 条 → 3 条结果。"""
    user = create_user(email="u@bjtu.edu.cn")
    d1 = _repo_save_draft(title="d1", content="c1", created_by=user.id)
    d2 = _repo_save_draft(title="d2", content="c2", created_by=user.id)
    d3 = _repo_save_draft(title="d3", content="c3", created_by=user.id)

    result = batch_send_drafts_service(
        [d1.id, d2.id, d3.id],
        targets=[TargetEntry(type="user", id=user.id)],
    )
    assert result.total == 3
    assert len(result.results) == 3
    assert all(r.status == "sent" for r in result.results)


def test_s16_batch_send_too_large(db_session):
    """S-16: 超过 20 条 → ValueError。"""
    with pytest.raises(ValueError, match="batch_too_large"):
        batch_send_drafts_service(list(range(25)), targets=[TargetEntry(type="user", id=1)])


# ══════════════════════════════════════════════════════════════════════
# 重发
# ══════════════════════════════════════════════════════════════════════


def test_s17_resend_from_sent(db_session, monkeypatch):
    """S-17: 从 SENT 状态重发。"""
    user = create_user(email="u@bjtu.edu.cn")
    ann = _repo_create_announcement(
        title="公告",
        content="正文",
        created_by=user.id,
        status=AnnouncementStatus.SENT,
        targets=json.dumps([TargetEntry(type="user", id=user.id).model_dump()]),
        target_snapshot="[]",
        recipient_count=1,
    )

    result = resend_announcement_service(ann.id)
    assert result.status == "sent"
    assert result.announcement_id == ann.id
    assert result.draft_id is None


def test_s18_resend_sending_idempotent(db_session):
    """S-18: SENDING 状态重发 → ValueError。"""
    user = create_user()
    ann = _repo_create_announcement(
        title="公告",
        content="正文",
        created_by=user.id,
        status=AnnouncementStatus.SENDING,
        targets=json.dumps([TargetEntry(type="user", id=user.id).model_dump()]),
    )

    with pytest.raises(ValueError, match="announcement_still_sending"):
        resend_announcement_service(ann.id)


# ══════════════════════════════════════════════════════════════════════
# 复用为草稿
# ══════════════════════════════════════════════════════════════════════


def test_s19_copy_as_draft_content_match(db_session):
    """S-19: 复用后 draft 内容一致。"""
    user = create_user()
    targets_json = json.dumps([TargetEntry(type="user", id=user.id).model_dump()])
    ann = _repo_create_announcement(
        title="公告标题",
        content="纯文本公告正文，无变量",
        raw_content="纯文本公告正文，无变量",
        created_by=user.id,
        status=AnnouncementStatus.SENT,
        targets=targets_json,
        target_snapshot="[]",
    )

    draft = copy_announcement_as_draft_service(ann.id, created_by=user.id)
    assert draft.title == "公告标题"
    assert draft.content == "纯文本公告正文，无变量"
    assert draft.targets == targets_json


def test_s20_copy_as_draft_template_ref(db_session):
    """S-20: 原公告有 template_id → draft.template_id 相同。"""
    user = create_user()
    template = _repo_create_template(
        name="模板", subject_template="主题", body_template="正文", created_by=user.id
    )
    ann = _repo_create_announcement(
        title="公告", content="正文", created_by=user.id, template_id=template.id
    )

    draft = copy_announcement_as_draft_service(ann.id, created_by=user.id)
    assert draft.template_id == template.id


# ══════════════════════════════════════════════════════════════════════
# 转为模板（纯文字，不提取变量）
# ══════════════════════════════════════════════════════════════════════

def test_s21_convert_to_template_preserves_content(db_session):
    """模板直接保存公告全文，不提取变量。"""
    user = create_user()
    ann = _repo_create_announcement(
        title="GPU 维护",
        content="您好，GPU-01 将于今晚维护。",
        raw_content="您好，GPU-01 将于今晚维护。",
        created_by=user.id,
    )

    template = convert_announcement_to_template_service(ann.id, created_by=user.id)
    assert template.body_template == "您好，GPU-01 将于今晚维护。"
    assert template.subject_template == "GPU 维护"


def test_s22_convert_to_template_name(db_session):
    """title="GPU维护" → name="来自公告: GPU维护"。"""
    user = create_user()
    ann = _repo_create_announcement(
        title="GPU维护",
        content="正文",
        created_by=user.id,
    )

    template = convert_announcement_to_template_service(ann.id, created_by=user.id)
    assert template.name == "来自公告: GPU维护"


def test_s23_convert_to_template_source_tracked(db_session):
    """转换后 source_announcement_id 指向原公告。"""
    user = create_user()
    ann = _repo_create_announcement(
        title="测试",
        content="正文",
        created_by=user.id,
    )

    template = convert_announcement_to_template_service(ann.id, created_by=user.id)
    assert template.source_announcement_id == ann.id
