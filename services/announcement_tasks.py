"""公告系统服务层：收件人解析、发送、复用、转模板。

元素快填的内容由前端在编辑时直接插入，服务层不再参与变量渲染。
"""

import datetime as dt
import json

from sqlalchemy import select

from ..config import AppConfig
from pydantic import BaseModel

from ..constant import AnnouncementStatus, AnnouncementTargetType
from ..extensions import session_scope
from ..models.containers import Container
from ..models.machine import Machine
from ..models.machine_permission import MachinePermission
from ..models.user import User
from ..models.usercontainer import UserContainer
from ..repositories import announcement_repo
from ..utils.mail import send as send_mail, send_batch

# ══════════════════════════════════════════════════════════════════════
# Pydantic 数据模型
# ══════════════════════════════════════════════════════════════════════


class TargetEntry(BaseModel):
    """单条目标输入。"""

    type: str  # "machine" | "container" | "user"
    id: int


class RecipientEntry(BaseModel):
    user_id: int
    username: str
    email: str


class TargetSummaryEntry(BaseModel):
    type: str
    id: int
    display_name: str


class ResolveResult(BaseModel):
    recipients: list[RecipientEntry]
    summary: list[TargetSummaryEntry]
    total_count: int


class SendResult(BaseModel):
    draft_id: int | None
    announcement_id: int
    status: str
    recipient_count: int
    success_count: int
    fail_count: int
    failures: list[dict]


class BatchSendResult(BaseModel):
    total: int
    results: list[SendResult]


# ══════════════════════════════════════════════════════════════════════
# 收件人解析
# ══════════════════════════════════════════════════════════════════════


def resolve_recipients(targets: list[TargetEntry]) -> ResolveResult:
    """Resolve targets into unique recipients and display summaries."""

    recipients_map: dict[int, RecipientEntry] = {}
    summaries: list[TargetSummaryEntry] = []

    with session_scope(commit=False) as session:
        for entry in targets:
            users: list[User] = []

            if entry.type == AnnouncementTargetType.MACHINE.value:
                machine = session.get(Machine, int(entry.id))
                if machine is None:
                    continue
                user_ids = list(
                    session.scalars(
                        select(MachinePermission.user_id).where(MachinePermission.machine_id == int(entry.id))
                    ).all()
                )
                users = list(session.scalars(select(User).where(User.id.in_(user_ids))).all()) if user_ids else []
                summaries.append(
                    TargetSummaryEntry(
                        type=entry.type,
                        id=entry.id,
                        display_name=f"{machine.machine_name} ({machine.machine_ip})",
                    )
                )
            elif entry.type == AnnouncementTargetType.CONTAINER.value:
                container = session.get(Container, int(entry.id))
                if container is None:
                    continue
                user_ids = list(
                    session.scalars(
                        select(UserContainer.user_id).where(UserContainer.container_id == int(entry.id))
                    ).all()
                )
                users = list(session.scalars(select(User).where(User.id.in_(user_ids))).all()) if user_ids else []
                summaries.append(
                    TargetSummaryEntry(
                        type=entry.type,
                        id=entry.id,
                        display_name=f"{container.name} (:{container.port})",
                    )
                )
            elif entry.type == AnnouncementTargetType.USER.value:
                user = session.get(User, int(entry.id))
                if user is None:
                    continue
                users = [user]
                summaries.append(
                    TargetSummaryEntry(
                        type=entry.type,
                        id=entry.id,
                        display_name=f"{user.username} ({user.email})",
                    )
                )
            elif entry.type == "all":
                users = list(session.scalars(select(User)).all())
                summaries.append(TargetSummaryEntry(type="all", id=0, display_name="??"))

            for user in users:
                if user.id not in recipients_map:
                    recipients_map[user.id] = RecipientEntry(
                        user_id=user.id,
                        username=user.username,
                        email=user.email,
                    )

    max_recipients = getattr(AppConfig, "ANNOUNCEMENT_MAX_RECIPIENTS", 200)
    if len(recipients_map) > max_recipients:
        raise ValueError("too_many_recipients")

    return ResolveResult(
        recipients=list(recipients_map.values()),
        summary=summaries,
        total_count=len(recipients_map),
    )

def send_draft_service(
    draft_id: int,
    targets: list[TargetEntry],
) -> SendResult:
    """将单条草稿发送给 targets 指定的收件人集合。

    内部流程：查草稿 → 解析收件人 → 创建公告(SENDING) →
    send_batch 批量发送（复用连接）→ 更新状态+计数 → 删除草稿。

    元素快填在编辑时已完成，此处不再做变量渲染。
    """
    # 1. 查草稿，先取出发送所需字段，避免发送邮件时长事务占用。
    with session_scope(commit=False) as session:
        draft = announcement_repo.get_draft_by_id(draft_id, session=session)
        if draft is None:
            raise ValueError("draft_not_found")
        draft_title = draft.title
        draft_content = draft.content
        draft_raw_content = draft.raw_content
        draft_created_by = draft.created_by
        draft_template_id = draft.template_id

    # 2. 校验并解析收件人
    if not targets:
        raise ValueError("empty_targets")
    resolve_result = resolve_recipients(targets)
    targets_json = json.dumps([t.model_dump() for t in targets])

    # 3. 公告内容即草稿当前内容（编辑时已包含元素快填结果）
    content = draft_content

    # 4. 创建公告（SENDING）
    with session_scope() as session:
        announcement = announcement_repo.create_announcement(
            title=draft_title,
            content=content,
            raw_content=draft_raw_content or content,
            created_by=draft_created_by,
            status=AnnouncementStatus.SENDING,
            targets=targets_json,
            target_snapshot=json.dumps([s.model_dump() for s in resolve_result.summary]),
            recipient_count=resolve_result.total_count,
            template_id=draft_template_id,
            source_draft_id=draft_id,
            session=session,
        )
        announcement_id = announcement.id
        announcement_title = announcement.title
        announcement_content = announcement.content

    # 5. 批量发送邮件（复用 SMTP 连接）
    messages = [
        {"to": r.email, "subject": announcement_title, "content": announcement_content}
        for r in resolve_result.recipients
    ]
    results = send_batch(messages)
    success = 0
    fail = 0
    failures: list[dict] = []
    for i, result in enumerate(results):
        recipient = resolve_result.recipients[i]
        if result.get("ok"):
            success += 1
        else:
            fail += 1
            failures.append({"email": recipient.email, "error": result.get("error", "unknown")})

    # 6. 更新公告状态与统计
    if fail == 0:
        new_status = AnnouncementStatus.SENT
    elif success == 0:
        new_status = AnnouncementStatus.FAILED
    else:
        new_status = AnnouncementStatus.PARTIAL

    with session_scope() as session:
        announcement_repo.update_announcement_status(
            announcement_id,
            status=new_status,
            success_count=success,
            fail_count=fail,
            sent_at=dt.datetime.utcnow(),
            session=session,
        )

        # 7. 删除已发送的草稿
        announcement_repo.delete_draft(draft_id, session=session)

    return SendResult(
        draft_id=draft_id,
        announcement_id=announcement_id,
        status=new_status.value,
        recipient_count=resolve_result.total_count,
        success_count=success,
        fail_count=fail,
        failures=failures,
    )


# ══════════════════════════════════════════════════════════════════════
# 批量发送草稿
# ══════════════════════════════════════════════════════════════════════


def batch_send_drafts_service(
    draft_ids: list[int],
    targets: list[TargetEntry],
) -> BatchSendResult:
    """批量发送草稿：所有被勾选的草稿发给同一组收件人。

    单条失败不影响后续。
    """
    max_batch = getattr(AppConfig, "ANNOUNCEMENT_BATCH_SEND_MAX", 20)
    if len(draft_ids) > max_batch:
        raise ValueError("batch_too_large")
    if not targets:
        raise ValueError("empty_targets")

    # 预校验 targets（too_many_recipients 对外返回 400，不进入 per-draft 容错循环）
    resolve_recipients(targets)

    results: list[SendResult] = []
    for did in draft_ids:
        try:
            results.append(send_draft_service(did, targets=targets))
        except Exception as exc:
            results.append(
                SendResult(
                    draft_id=did,
                    announcement_id=0,
                    status="error",
                    recipient_count=0,
                    success_count=0,
                    fail_count=0,
                    failures=[{"error": str(exc)}],
                )
            )

    return BatchSendResult(total=len(draft_ids), results=results)


# ══════════════════════════════════════════════════════════════════════
# 删除公告
# ══════════════════════════════════════════════════════════════════════


def delete_announcement_service(announcement_id: int) -> bool:
    """删除单条已发送公告。"""
    with session_scope() as session:
        return announcement_repo.delete_announcement(announcement_id, session=session)


def batch_delete_announcements_service(announcement_ids: list[int]) -> dict:
    """批量删除公告，返回 {deleted: N, not_found: N}。"""
    deleted = 0
    not_found = 0
    with session_scope() as session:
        for aid in announcement_ids:
            if announcement_repo.delete_announcement(aid, session=session):
                deleted += 1
            else:
                not_found += 1
    return {"deleted": deleted, "not_found": not_found}


# ══════════════════════════════════════════════════════════════════════
# 重发
# ══════════════════════════════════════════════════════════════════════


def resend_announcement_service(announcement_id: int) -> SendResult:
    """对已发送公告重新发送邮件，沿用原 targets。"""
    with session_scope() as session:
        ann = announcement_repo.get_announcement_by_id(announcement_id, session=session)
        if ann is None:
            raise ValueError("announcement_not_found")
        if ann.status == AnnouncementStatus.SENDING:
            raise ValueError("announcement_still_sending")
        ann_id = ann.id
        ann_title = ann.title
        ann_content = ann.content
        ann_targets = ann.targets

        # 更新为 SENDING
        announcement_repo.update_announcement_status(
            ann_id,
            status=AnnouncementStatus.SENDING,
            session=session,
        )

    # 解析原 targets
    raw_targets = json.loads(ann_targets) if ann_targets else []
    targets = [TargetEntry(**t) for t in raw_targets]
    resolve_result = resolve_recipients(targets)

    # 发送（复用 SMTP 连接）
    messages = [
        {"to": r.email, "subject": ann_title, "content": ann_content}
        for r in resolve_result.recipients
    ]
    results = send_batch(messages)
    success = 0
    fail = 0
    failures: list[dict] = []
    for i, result in enumerate(results):
        recipient = resolve_result.recipients[i]
        if result.get("ok"):
            success += 1
        else:
            fail += 1
            failures.append({"email": recipient.email, "error": result.get("error", "unknown")})

    # 更新状态
    if fail == 0:
        new_status = AnnouncementStatus.SENT
    elif success == 0:
        new_status = AnnouncementStatus.FAILED
    else:
        new_status = AnnouncementStatus.PARTIAL

    with session_scope() as session:
        announcement_repo.update_announcement_status(
            ann_id,
            status=new_status,
            success_count=success,
            fail_count=fail,
            sent_at=dt.datetime.utcnow(),
            session=session,
        )

    return SendResult(
        draft_id=None,
        announcement_id=ann_id,
        status=new_status.value,
        recipient_count=resolve_result.total_count,
        success_count=success,
        fail_count=fail,
        failures=failures,
    )


# ══════════════════════════════════════════════════════════════════════
# 复用为草稿
# ══════════════════════════════════════════════════════════════════════


def copy_announcement_as_draft_service(
    announcement_id: int, *, created_by: int
) -> "AnnouncementDraft":
    """将已发送公告的内容复制为一条新草稿。"""
    with session_scope() as session:
        ann = announcement_repo.get_announcement_by_id(announcement_id, session=session)
        if ann is None:
            raise ValueError("announcement_not_found")

        return announcement_repo.save_draft(
            title=ann.title,
            content=ann.raw_content or ann.content,
            raw_content=ann.raw_content,
            created_by=created_by,
            targets=ann.targets,
            template_id=ann.template_id,
            session=session,
        )


# ══════════════════════════════════════════════════════════════════════
# 转为模板
# ══════════════════════════════════════════════════════════════════════


def convert_announcement_to_template_service(
    announcement_id: int, *, created_by: int
) -> "AnnouncementTemplate":
    """从已发送公告内容直接生成新模板（纯文字，不含变量）。"""
    with session_scope() as session:
        ann = announcement_repo.get_announcement_by_id(announcement_id, session=session)
        if ann is None:
            raise ValueError("announcement_not_found")

        return announcement_repo.create_template(
            name=f"来自公告: {ann.title}",
            subject_template=ann.title,
            body_template=ann.raw_content or ann.content,
            created_by=created_by,
            source_announcement_id=ann.id,
            session=session,
        )
