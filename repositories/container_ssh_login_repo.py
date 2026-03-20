import datetime as dt
from ..extensions import db
from ..models.container_ssh_login import ContainerSSHLogin


def get_by_machine_container(machine_id: int, container_id: int) -> ContainerSSHLogin | None:
    return ContainerSSHLogin.query.filter_by(machine_id=machine_id, container_id=container_id).first()


def upsert_last_ssh_login_time(
    machine_id: int,
    container_id: int,
    last_ssh_login_time: str | None,
    *,
    commit: bool = True,
) -> ContainerSSHLogin:
    record = get_by_machine_container(machine_id, container_id)
    if record is None:
        record = ContainerSSHLogin(machine_id=machine_id, container_id=container_id)
        db.session.add(record)

    record.last_ssh_login_time = last_ssh_login_time
    record.updated_at = dt.datetime.utcnow()

    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return record

