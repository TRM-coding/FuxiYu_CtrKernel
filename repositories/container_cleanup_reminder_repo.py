"""容器清理提醒记录仓储。

`reminder_key` 是**状态位**，不是"某次发送的记录"：它记的是该 (容器, 收件人) 已经
提醒到的**最深档位**。所以这里的读写都是"取/置当前档位"：

- `was_sent(cid, "24h", email)`：当前档位**正好**是 24h 吗？是就别再发
- `mark_sent(cid, "24h", cleanup_at, email)`：把档位推进到 24h（无行则建行）
- `reset_to_never(cid)`：周期变更，档位打回 NEVER，让新周期重新提醒一遍

档位随时间单调加深（NEVER → 72h → 24h → 12h），所以"是否正好等于想发的那一级"
就足够判重，**不需要任何时间戳参与比较**。这正是最初的成因：旧实现拿 `cleanup_at`
当身份，而顺延会让它每轮扫描都前移，精确匹配必然落空、每轮重发。
"""

import datetime as dt

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models.container_cleanup_reminder import NEVER_REMINDED, ContainerCleanupReminder


def _get_row(
    container_id: int,
    recipient_email: str,
    *,
    session: Session,
) -> ContainerCleanupReminder | None:
    stmt = select(ContainerCleanupReminder).where(
        ContainerCleanupReminder.container_id == int(container_id),
        ContainerCleanupReminder.recipient_email == recipient_email,
    )
    return session.scalars(stmt).first()


def mark_sent(
    container_id: int,
    reminder_key: str,
    cleanup_at: dt.datetime,
    recipient_email: str,
    *,
    session: Session,
) -> bool:
    """把该收件人的提醒档位推进到 `reminder_key`；返回是否真的推进了。

    `cleanup_at` 仅作审计（本次报出的到期时刻），不参与判重。
    """

    row = _get_row(container_id, recipient_email, session=session)
    if row is None:
        session.add(ContainerCleanupReminder(
            container_id=int(container_id),
            reminder_key=str(reminder_key),
            cleanup_at=cleanup_at,
            recipient_email=recipient_email,
        ))
        session.flush()
        return True
    if row.reminder_key == str(reminder_key):
        return False
    row.reminder_key = str(reminder_key)
    row.cleanup_at = cleanup_at
    row.sent_at = dt.datetime.utcnow()
    session.flush()
    return True


def was_sent(
    container_id: int,
    reminder_key: str,
    recipient_email: str,
    *,
    session: Session,
) -> bool:
    """该收件人的当前档位是否**正好**是 `reminder_key`。"""

    row = _get_row(container_id, recipient_email, session=session)
    return row is not None and row.reminder_key == str(reminder_key)


def reset_to_never(container_id: int, *, session: Session) -> int:
    """周期变更：该容器全部收件人的档位打回 NEVER。

    调用点是"周期变了"的唯一知情人（`container_ssh_login_repo.upsert_last_ssh_login_time`
    里"值变化 = 真登录"那一支），与 deferral 清零同判据、同时刻、同事务。
    调度器不再自己猜周期变没变——它曾经拿 `cleanup_at` 当判据，而那个值每轮都在漂。
    """

    result = session.execute(
        update(ContainerCleanupReminder)
        .where(ContainerCleanupReminder.container_id == int(container_id))
        .values(reminder_key=NEVER_REMINDED)
    )
    session.flush()
    return int(result.rowcount or 0)
