"""公告系统服务层：收件人解析、发送、复用、转模板。

元素快填的内容由前端在编辑时直接插入，服务层不再参与变量渲染。
"""

import datetime as dt
import json
import logging
import threading

from sqlalchemy import select

from pydantic import BaseModel

from ..constant import AnnouncementStatus, AnnouncementTargetType
from ..extensions import session_scope
from ..models.containers import Container
from ..models.machine import Machine
from ..models.machine_permission import MachinePermission
from ..models.user import User
from ..models.usercontainer import UserContainer
from ..repositories import announcement_repo
from . import settings_tasks
from ..utils.mail import send_batch

logger = logging.getLogger(__name__)

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

    max_recipients = settings_tasks.get_announcement_max_recipients()
    if len(recipients_map) > max_recipients:
        raise ValueError("too_many_recipients")

    return ResolveResult(
        recipients=list(recipients_map.values()),
        summary=summaries,
        total_count=len(recipients_map),
    )

class _PreparedSend:
    """一次发送的"准备结果"：公告已建好（SENDING）、信件已备好，**只差发出去**。

    有了它，"快的一半"和"慢的一半"才能分开：准备不含任何 SMTP 动作，可以在请求
    线程里跑完并把校验错误立刻回给调用方；投递才进后台线程。
    """

    __slots__ = ("draft_id", "announcement_id", "title", "messages", "emails",
                 "recipient_count", "mail_type", "delete_draft")

    def __init__(self, *, draft_id, announcement_id, title, messages, emails, recipient_count,
                 mail_type="announcement", delete_draft=True):
        self.draft_id = draft_id
        self.announcement_id = announcement_id
        self.title = title
        self.messages = messages
        self.emails = emails
        self.recipient_count = recipient_count
        # 投递期需要的两处差异（发送 vs 重发）：审计的 mail_type、成功后是否删草稿
        self.mail_type = mail_type
        self.delete_draft = delete_draft


class _DraftSnapshot:
    """发送前从草稿里取出的字段（只读，避免长事务）。"""

    __slots__ = ("draft_id", "title", "content", "raw_content", "created_by", "template_id")

    def __init__(self, *, draft_id, title, content, raw_content, created_by, template_id):
        self.draft_id = draft_id
        self.title = title
        self.content = content
        self.raw_content = raw_content
        self.created_by = created_by
        self.template_id = template_id


def _load_draft_for_send(draft_id: int) -> _DraftSnapshot:
    """**只读**：取出发送所需字段。草稿不存在在这里就抛，晚一步都不行。"""
    with session_scope(commit=False) as session:
        draft = announcement_repo.get_draft_by_id(draft_id, session=session)
        if draft is None:
            raise ValueError("draft_not_found")
        return _DraftSnapshot(
            draft_id=draft_id,
            title=draft.title,
            content=draft.content,
            raw_content=draft.raw_content,
            created_by=draft.created_by,
            template_id=draft.template_id,
        )


def _create_sending_announcement(
    snapshot: _DraftSnapshot, resolve_result: ResolveResult, targets_json: str
) -> _PreparedSend:
    """**写**：建 SENDING 公告 + 备好信件。调用方必须已完成全部校验。"""
    with session_scope() as session:
        announcement = announcement_repo.create_announcement(
            title=snapshot.title,
            content=snapshot.content,
            raw_content=snapshot.raw_content or snapshot.content,
            created_by=snapshot.created_by,
            status=AnnouncementStatus.SENDING,
            targets=targets_json,
            target_snapshot=json.dumps([s.model_dump() for s in resolve_result.summary]),
            recipient_count=resolve_result.total_count,
            template_id=snapshot.template_id,
            source_draft_id=snapshot.draft_id,
            session=session,
        )
        emails = [r.email for r in resolve_result.recipients]
        return _PreparedSend(
            draft_id=snapshot.draft_id,
            announcement_id=announcement.id,
            title=announcement.title,
            messages=[
                {"to": email, "subject": announcement.title, "content": announcement.content}
                for email in emails
            ],
            emails=emails,
            recipient_count=resolve_result.total_count,
        )


def _resolve_targets_for_send(targets: list[TargetEntry]) -> tuple[ResolveResult, str]:
    """**只读**：空目标 / 超限在这里就抛。"""
    if not targets:
        raise ValueError("empty_targets")
    resolve_result = resolve_recipients(targets)
    return resolve_result, json.dumps([t.model_dump() for t in targets])


#### 发送的三步：读（校验）→ 写（建 SENDING）→ 投递（后台）
# 单条没有独立入口：批量与重发都直接组合这三步（2026-09 决策：不留同步版）。


def _deliver_prepared_send(prepared: _PreparedSend, *, operator_user_id: int | None) -> SendResult:
    """慢后半段：发信 → 落终态与计数 → 删草稿。**后台线程走这里**。

    逐封节奏在 `utils/mail._send_batch_smtp` 里（同连接内 0.8s 间隔，避免服务商限速）——
    异步化**不改变**它：批量仍然是一条连接顺序发，只是不再占着请求线程。
    """
    results = send_batch(
        prepared.messages, target_type="announcement", target_id=prepared.announcement_id,
        operator_user_id=operator_user_id,
        detail={"mail_type": prepared.mail_type, "name": prepared.title,
                **({"draft_id": prepared.draft_id} if prepared.delete_draft else {})},
        # 逐封间隔由设置给（服务商风控那条），不在传输层写死
        interval_seconds=settings_tasks.get_announcement_mail_interval_seconds(),
    )
    success = 0
    fail = 0
    failures: list[dict] = []
    for i, result in enumerate(results):
        if result.get("ok"):
            success += 1
        else:
            fail += 1
            failures.append({"email": prepared.emails[i], "error": result.get("error", "unknown")})

    if fail == 0:
        new_status = AnnouncementStatus.SENT
    elif success == 0:
        new_status = AnnouncementStatus.FAILED
    else:
        new_status = AnnouncementStatus.PARTIAL

    with session_scope() as session:
        announcement_repo.update_announcement_status(
            prepared.announcement_id,
            status=new_status,
            success_count=success,
            fail_count=fail,
            sent_at=dt.datetime.utcnow(),
            session=session,
        )
        # 只有发成功了才删草稿——失败的草稿留着，用户可以直接重发（重发没有草稿，跳过）
        if prepared.delete_draft:
            announcement_repo.delete_draft(prepared.draft_id, session=session)

    return SendResult(
        draft_id=prepared.draft_id,
        announcement_id=prepared.announcement_id,
        status=new_status.value,
        recipient_count=prepared.recipient_count,
        success_count=success,
        fail_count=fail,
        failures=failures,
    )


# ══════════════════════════════════════════════════════════════════════
# 批量发送（异步）：发起即返回，前端轮询公告状态看进度
#
# 没有同步版：发送是分钟级的活，任何"等结果"的入口都会把超时问题带回来
# （2026-09 决策：同步入口一律不留）。
# ══════════════════════════════════════════════════════════════════════


class BatchSendAccepted(BaseModel):
    """异步批量发送的受理回执：这一批建了哪些公告（前端拿 ids 轮询）。"""

    total: int
    announcement_ids: list[int]


# ── 发信闸门 ────────────────────────────────────────────────────────────
#
# 只是**串行锁**：同一时刻只允许一次投递在发。它不是冷却——公告之间没有冷却
# （2026-09 决策：有意义的只有**逐封**间隔，见 announcement.mail_interval_seconds）。
# 留着它是为了别让两批（或批量与重发）同时开两条 SMTP 连接猛发：
# 多条并发连接正是服务商风控最敏感的形状。
#
# 闸门放在**投递层**：批量的每一条、重发，全都经过它，谁也别想绕过。
_send_gate = threading.Lock()


def _deliver_with_slot(prepared: _PreparedSend, *, operator_user_id: int | None) -> SendResult:
    """占住发送槽位 → 投递。**所有真实发信都必须走这里。**"""
    with _send_gate:
        return _deliver_prepared_send(prepared, operator_user_id=operator_user_id)


def start_batch_send_service(
    draft_ids: list[int],
    targets: list[TargetEntry],
    *, operator_user_id: int | None = None,
) -> BatchSendAccepted:
    """异步批量发送：同步段只做"准备"，发信丢给**一个**后台线程顺序跑。

    ★ 为什么必须异步：一批最多 20 条草稿、每条最多 200 个收件人，而每封之间还有 0.8s
      的固定间隔——同步跑是分钟级，任何前端超时都会先松手，用户看到"失败"而信其实
      正在一封封发出去（2026-09 实测）。

    ★ 为什么是**一个**线程、顺序发：SMTP 连接要复用，逐封节奏也必须连续；并发开会
      同时占用多条连接、把服务商的风控吵醒。

    ★ 校验（草稿存在、目标非空、批量上限）全在同步段做完 —— 错误立刻 400，
      不会留下一堆"发送中"的空公告。
    """
    max_batch = settings_tasks.get_announcement_batch_send_max()
    if len(draft_ids) > max_batch:
        raise ValueError("batch_too_large")
    if not targets:
        raise ValueError("empty_targets")

    # 全部校验**先做完、再动笔**：否则第 N 条草稿不存在时，前 N-1 条已经建好了
    # SENDING 公告——它们永远发不出去，却会一直显示"发送中"（2026-09 测试抓到的真 bug）。
    resolve_result, targets_json = _resolve_targets_for_send(targets)
    snapshots = [_load_draft_for_send(did) for did in draft_ids]

    prepared = [
        _create_sending_announcement(snapshot, resolve_result, targets_json)
        for snapshot in snapshots
    ]

    thread = threading.Thread(
        target=_deliver_batch_in_background,
        args=(prepared, operator_user_id),
        name="announcement-batch-send",
        daemon=True,
    )
    thread.start()
    logger.info(
        "announcement batch accepted: drafts=%s announcements=%s recipients_per_draft=%s",
        draft_ids, [p.announcement_id for p in prepared],
        prepared[0].recipient_count if prepared else 0,
    )
    return BatchSendAccepted(total=len(prepared), announcement_ids=[p.announcement_id for p in prepared])


def _deliver_batch_in_background(prepared: list[_PreparedSend], operator_user_id: int | None) -> None:
    """后台线程体：顺序投递这一批（每条各自等自己的发送槽位）。

    单条失败不拖垮整批，但必须收尾成 FAILED。
    """
    for item in prepared:
        try:
            _deliver_with_slot(item, operator_user_id=operator_user_id)
        except Exception:
            # 关键：**任何异常都要把这条公告收尾**，否则它会永远停在 SENDING，
            # 而 announcement_still_sending 守卫会让它永久无法重发（2026-09 设计）。
            logger.exception("announcement delivery failed: announcement=%s", item.announcement_id)
            _settle_announcement_failed(item.announcement_id)


def _settle_announcement_failed(announcement_id: int) -> None:
    with session_scope() as session:
        announcement_repo.update_announcement_status(
            announcement_id,
            status=AnnouncementStatus.FAILED,
            session=session,
        )


def settle_stuck_sending_announcements() -> int:
    """启动期收尾：把遗留的 SENDING 公告判为 FAILED，返回处理条数。

    ★ 为什么必须有：异步发送跑在**进程内**的后台线程里，Ctrl 一重启那条线程就凭空
      消失，公告永远停在 SENDING——而 `announcement_still_sending` 守卫会让它永久
      无法重发（草稿也还占着）。收尾成 FAILED 之后用户可以直接重发。
    """
    settled = 0
    with session_scope() as session:
        stuck = announcement_repo.list_announcements_by_status(
            AnnouncementStatus.SENDING, session=session
        )
        for announcement in stuck:
            announcement_repo.update_announcement_status(
                announcement.id,
                status=AnnouncementStatus.FAILED,
                session=session,
            )
            settled += 1
    if settled:
        logger.warning(
            "settled %d announcement(s) stuck in SENDING (process restarted mid-send)", settled
        )
    return settled


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


def _prepare_resend(announcement_id: int) -> _PreparedSend:
    """重发的同步前半段：校验 → 沿用原 targets 解析收件人 → 置回 SENDING。

    与"发送草稿"共用投递层（`_deliver_prepared_send`），只是不删草稿、审计记 resend。
    """
    with session_scope(commit=False) as session:
        ann = announcement_repo.get_announcement_by_id(announcement_id, session=session)
        if ann is None:
            raise ValueError("announcement_not_found")
        if ann.status == AnnouncementStatus.SENDING:
            raise ValueError("announcement_still_sending")
        ann_id = ann.id
        ann_title = ann.title
        ann_content = ann.content
        ann_targets = ann.targets

    raw_targets = json.loads(ann_targets) if ann_targets else []
    targets = [TargetEntry(**t) for t in raw_targets]
    resolve_result, _ = _resolve_targets_for_send(targets)
    emails = [r.email for r in resolve_result.recipients]

    with session_scope() as session:
        announcement_repo.update_announcement_status(
            ann_id, status=AnnouncementStatus.SENDING, session=session
        )

    return _PreparedSend(
        # 重发没有草稿（SendResult.draft_id 为 None，与旧行为一致）
        draft_id=None,
        announcement_id=ann_id,
        title=ann_title,
        messages=[
            {"to": email, "subject": ann_title, "content": ann_content} for email in emails
        ],
        emails=emails,
        recipient_count=resolve_result.total_count,
        mail_type="announcement_resend",
        delete_draft=False,
    )


def start_resend_service(announcement_id: int, *, operator_user_id: int | None = None) -> int:
    """异步重发：置回 SENDING、丢一个线程去排队投递，立刻返回公告 id（前端轮询它）。

    ★ 为什么重发也要异步：它和批量发送是**同一种行为**（发一批邮件，逐封 0.8s），
      而且要排同一个发送槽位——同步跑的话，等待冷却的时间会直接压在请求上，
      前端照样会超时（2026-09 用户澄清冷却语义时一并改掉）。
    """
    prepared = _prepare_resend(announcement_id)
    threading.Thread(
        target=_deliver_batch_in_background,
        args=([prepared], operator_user_id),
        name="announcement-resend",
        daemon=True,
    ).start()
    logger.info("announcement resend accepted: announcement=%s", prepared.announcement_id)
    return prepared.announcement_id


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
