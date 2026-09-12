"""容器 SSH 登录时间仓储。"""

import datetime as dt

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..models.container_ssh_login import ContainerSSHLogin
from ..models.containers import Container


def get_by_machine_container(
    machine_id: int,
    container_id: int,
    *,
    session: Session,
    include_invalid: bool = False,
) -> ContainerSSHLogin | None:
    stmt = select(ContainerSSHLogin).where(
        ContainerSSHLogin.machine_id == int(machine_id),
        ContainerSSHLogin.container_id == int(container_id),
    )
    if not include_invalid:
        stmt = stmt.join(Container, Container.id == ContainerSSHLogin.container_id).where(
            Container.is_valid.is_(True)
        )
    return session.scalars(stmt).first()


def get_by_container(
    container_id: int,
    *,
    session: Session,
    include_invalid: bool = False,
) -> ContainerSSHLogin | None:
    stmt = select(ContainerSSHLogin).where(ContainerSSHLogin.container_id == int(container_id))
    if not include_invalid:
        stmt = stmt.join(Container, Container.id == ContainerSSHLogin.container_id).where(
            Container.is_valid.is_(True)
        )
    return session.scalars(stmt).first()


def list_all(*, session: Session, include_invalid: bool = False) -> list[ContainerSSHLogin]:
    stmt = select(ContainerSSHLogin)
    if not include_invalid:
        stmt = (
            stmt.join(Container, Container.id == ContainerSSHLogin.container_id)
            .where(Container.is_valid.is_(True))
        )
    return list(session.scalars(stmt).all())


def upsert_last_ssh_login_time(
    machine_id: int,
    container_id: int,
    last_ssh_login_time: str | None,
    *,
    session: Session,
) -> ContainerSSHLogin:
    record = get_by_machine_container(machine_id, container_id, session=session, include_invalid=True)
    if record is None:
        record = ContainerSSHLogin(machine_id=machine_id, container_id=container_id)
        session.add(record)
    elif record.last_ssh_login_time != last_ssh_login_time:
        # 值变化 = 真登录（新基准）：旧顺延清零——同值帧（Node 每 5s 推缓存旧时间）
        # 不清，否则顺延会在下一心跳被抹掉
        record.deferral_seconds = 0

    record.last_ssh_login_time = last_ssh_login_time
    record.updated_at = dt.datetime.utcnow()
    session.flush()
    return record


def add_deferral_seconds(machine_id: int, delta_seconds: int, *, session: Session) -> int:
    """该机器全部 ssh 登录记录的 deferral 累加 delta（不可用窗口关闭时的顺延平移）。

    旧行 deferral 可能为 NULL（列新增前的存量），coalesce 兜底为 0 再相加。
    """

    if not delta_seconds or delta_seconds <= 0:
        return 0
    result = session.execute(
        update(ContainerSSHLogin)
        .where(ContainerSSHLogin.machine_id == int(machine_id))
        .values(
            deferral_seconds=(
                func.coalesce(ContainerSSHLogin.deferral_seconds, 0) + int(delta_seconds)
            )
        )
    )
    return result.rowcount or 0
