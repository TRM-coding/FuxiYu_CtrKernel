"""ContainerDiskFreezeState 仓储层。"""

import datetime as dt

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..models.container_disk_freeze_state import ContainerDiskFreezeState
from ..models.containers import Container


def get(
    container_id: int,
    *,
    session: Session,
    include_invalid: bool = False,
) -> ContainerDiskFreezeState | None:
    """获取冻结状态，无记录返回 None。

    默认只对有效容器可见（软删容器的冻结记录不对外暴露）；
    写路径（upsert / grace / reset）显式 include_invalid=True——它们操作记录本身，
    不关心容器当前有效性。
    """

    if include_invalid:
        return session.get(ContainerDiskFreezeState, int(container_id))
    stmt = (
        select(ContainerDiskFreezeState)
        .join(Container, Container.id == ContainerDiskFreezeState.container_id)
        .where(
            ContainerDiskFreezeState.container_id == int(container_id),
            Container.is_valid.is_(True),
        )
    )
    return session.scalars(stmt).first()


def upsert_first_frozen(container_id: int, *, session: Session) -> ContainerDiskFreezeState:
    """记录首次冻结时间；已有记录时不改 first_frozen_at。"""

    container_id = int(container_id)
    existing = get(container_id, session=session, include_invalid=True)
    if existing is not None:
        return existing

    row = ContainerDiskFreezeState(
        container_id=container_id,
        first_frozen_at=dt.datetime.utcnow(),
    )
    session.add(row)
    session.flush()
    return row


def set_grace(container_id: int, grace_days: int, *, session: Session) -> bool:
    """设置宽限期；无冻结记录时返回 False。"""

    row = get(container_id, session=session, include_invalid=True)
    if row is None:
        return False
    row.grace_until = dt.datetime.utcnow() + dt.timedelta(days=int(grace_days))
    session.flush()
    return True


def clear_grace(container_id: int, *, session: Session) -> bool:
    """清除宽限期。"""

    row = get(container_id, session=session, include_invalid=True)
    if row is None or row.grace_until is None:
        return False
    row.grace_until = None
    session.flush()
    return True


def reset(container_id: int, *, session: Session) -> bool:
    """删除冻结记录，返回是否确实删除了记录。"""

    row = get(container_id, session=session, include_invalid=True)
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


def add_deferral_seconds(machine_id: int, delta_seconds: int, *, session: Session) -> int:
    """该机器上全部冻结态的 deferral 累加 delta（不可用窗口关闭时的顺延平移）。

    单条 UPDATE 而非读-改-写：并发关闭不会互相覆盖。冻结态按 container_id 建键，
    故经 containers 关联到机器。

    整段累加即可，不需要按锚点裁重叠——锚点（first_frozen_at）只在机器可用时产生
    （置位点在 _evaluate_limits 的管辖范畴门禁之后），所以与锚点重叠的窗口必然起点更晚。
    若将来出现"机器不可用时也置锚点"的路径，这里会静默过度宽恕（方向朝用户），
    届时需要改成按重叠时长计算。
    """

    if not delta_seconds or delta_seconds <= 0:
        return 0
    result = session.execute(
        update(ContainerDiskFreezeState)
        .where(
            ContainerDiskFreezeState.container_id.in_(
                select(Container.id).where(Container.machine_id == int(machine_id))
            )
        )
        .values(
            deferral_seconds=(
                func.coalesce(ContainerDiskFreezeState.deferral_seconds, 0) + int(delta_seconds)
            )
        )
    )
    return result.rowcount or 0
