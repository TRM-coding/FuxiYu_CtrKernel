"""容器 SSH 登录时间仓储。"""

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.container_ssh_login import ContainerSSHLogin


def get_by_machine_container(
    machine_id: int,
    container_id: int,
    *,
    session: Session,
) -> ContainerSSHLogin | None:
    stmt = select(ContainerSSHLogin).where(
        ContainerSSHLogin.machine_id == int(machine_id),
        ContainerSSHLogin.container_id == int(container_id),
    )
    return session.scalars(stmt).first()


def get_by_container(container_id: int, *, session: Session) -> ContainerSSHLogin | None:
    stmt = select(ContainerSSHLogin).where(ContainerSSHLogin.container_id == int(container_id))
    return session.scalars(stmt).first()


def list_all(*, session: Session) -> list[ContainerSSHLogin]:
    return list(session.scalars(select(ContainerSSHLogin)).all())


def upsert_last_ssh_login_time(
    machine_id: int,
    container_id: int,
    last_ssh_login_time: str | None,
    *,
    session: Session,
) -> ContainerSSHLogin:
    record = get_by_machine_container(machine_id, container_id, session=session)
    if record is None:
        record = ContainerSSHLogin(machine_id=machine_id, container_id=container_id)
        session.add(record)

    record.last_ssh_login_time = last_ssh_login_time
    record.updated_at = dt.datetime.utcnow()
    session.flush()
    return record
