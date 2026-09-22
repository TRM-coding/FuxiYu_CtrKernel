"""Repository for deleted container restore snapshots."""

import datetime as dt
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from ..models.deleted_container_restore_snapshot import DeletedContainerRestoreSnapshot


def insert(
    snapshot: dict[str, Any],
    *,
    session: Session,
    mount_cleanup_id: int | None = None,
    removed_trigger: str = "api",
    removed_at: dt.datetime | None = None,
    mount_cleaned: bool = False,
) -> DeletedContainerRestoreSnapshot:
    row = DeletedContainerRestoreSnapshot(
        original_container_id=int(snapshot.get("container_id") or 0),
        container_name=str(snapshot.get("container_name") or ""),
        machine_id=snapshot.get("machine_id"),
        mount_cleanup_id=mount_cleanup_id,
        removed_trigger=str(removed_trigger or "api"),
        snapshot=snapshot,
        removed_at=removed_at or dt.datetime.utcnow(),
        mount_cleaned=bool(mount_cleaned),
    )
    session.add(row)
    session.flush()
    return row


def get_by_id(record_id: int, *, session: Session) -> DeletedContainerRestoreSnapshot | None:
    return session.get(DeletedContainerRestoreSnapshot, int(record_id))


def get_by_mount_cleanup_id(
    mount_cleanup_id: int,
    *,
    session: Session,
) -> DeletedContainerRestoreSnapshot | None:
    stmt = (
        select(DeletedContainerRestoreSnapshot)
        .where(DeletedContainerRestoreSnapshot.mount_cleanup_id == int(mount_cleanup_id))
        .order_by(DeletedContainerRestoreSnapshot.removed_at.desc(), DeletedContainerRestoreSnapshot.id.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def _removed_at_after_deferral(*, session: Session):
    """`removed_at + deferral_seconds` 的可移植表达（单位仍是 datetime）。

    挂载保留期按**业务正常时间**计：宕机/维护期用户无法恢复，那段不算数。

    必须在 SQL 里算，不能先按 removed_at 过滤再交给 Python 筛：本查询带 limit，
    而顺延大的行 removed_at 最老、恰好排在最前，会把窗口占满，让真正到期的年轻行
    永远进不来。两个方言的日期算术不同，故分支（与本仓 __init__ 自愈同一写法）。
    """

    row = DeletedContainerRestoreSnapshot
    deferral = func.coalesce(row.deferral_seconds, 0)
    if session.get_bind().dialect.name == "sqlite":
        # SQLite: datetime(removed_at, '+N seconds')
        return func.datetime(row.removed_at, func.printf("+%d seconds", deferral))
    # MySQL/MariaDB: DATE_ADD(removed_at, INTERVAL N SECOND) —— INTERVAL 是关键字，
    # 无法用 func 拼，故整段作为 text 传入（本查询不改表别名，列名即字面量）。
    return func.date_add(row.removed_at, text("INTERVAL COALESCE(deferral_seconds, 0) SECOND"))


def list_pending_mount_cleanup(
    cutoff: dt.datetime,
    limit: int = 100,
    *,
    session: Session,
) -> list[DeletedContainerRestoreSnapshot]:
    stmt = (
        select(DeletedContainerRestoreSnapshot)
        .where(
            DeletedContainerRestoreSnapshot.mount_cleaned.is_(False),
            _removed_at_after_deferral(session=session) < cutoff,
        )
        .order_by(DeletedContainerRestoreSnapshot.removed_at.asc(), DeletedContainerRestoreSnapshot.id.asc())
        .limit(limit)
    )
    return list(session.scalars(stmt).all())


def mark_mount_cleaned(record_id: int, *, session: Session) -> bool:
    row = get_by_id(record_id, session=session)
    if row is None:
        return False
    row.mount_cleaned = True
    session.flush()
    return True


def list_records(
    *,
    session: Session,
    limit: int = 20,
    offset: int = 0,
) -> list[DeletedContainerRestoreSnapshot]:
    stmt = (
        select(DeletedContainerRestoreSnapshot)
        .order_by(DeletedContainerRestoreSnapshot.removed_at.desc(), DeletedContainerRestoreSnapshot.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(session.scalars(stmt).all())


def count_records(*, session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(DeletedContainerRestoreSnapshot)) or 0)


def delete(record_id: int, *, session: Session) -> bool:
    row = get_by_id(record_id, session=session)
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


def add_deferral_seconds(machine_id: int, delta_seconds: int, *, session: Session) -> int:
    """该机器上**待清理**的已删快照的 deferral 累加 delta（挂载保留期的顺延平移）。

    只动 pending（mount_cleaned 为假）的行：已清理的记录不再被读，加了也只是噪音。
    整段累加即可，理由同 freeze_state——锚点 removed_at 只在机器可用时产生
    （删除路径要求机器在线）。
    """

    if not delta_seconds or delta_seconds <= 0:
        return 0
    result = session.execute(
        update(DeletedContainerRestoreSnapshot)
        .where(
            DeletedContainerRestoreSnapshot.machine_id == int(machine_id),
            DeletedContainerRestoreSnapshot.mount_cleaned.is_(False),
        )
        .values(
            deferral_seconds=(
                func.coalesce(DeletedContainerRestoreSnapshot.deferral_seconds, 0) + int(delta_seconds)
            )
        )
    )
    return result.rowcount or 0
