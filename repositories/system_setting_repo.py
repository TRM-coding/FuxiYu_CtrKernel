"""系统设置 repo。

repo 只接受显式 session，不提交事务。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.system_setting import SystemSetting


def get_by_key(key: str, *, session: Session) -> SystemSetting | None:
    return session.scalars(select(SystemSetting).where(SystemSetting.key == key)).first()


def get_value(key: str, *, session: Session) -> str | None:
    setting = get_by_key(key, session=session)
    return setting.value if setting is not None else None


def create_setting(
    *,
    key: str,
    value: str,
    description: str | None = None,
    session: Session,
) -> SystemSetting:
    setting = SystemSetting(key=key, value=value, description=description)
    session.add(setting)
    session.flush()
    return setting


def update_setting(
    key: str,
    *,
    value: str,
    description: str | None = None,
    session: Session,
) -> bool:
    setting = get_by_key(key, session=session)
    if setting is None:
        return False
    setting.value = value
    if description is not None:
        setting.description = description
    session.flush()
    return True


def seed_setting(
    *,
    key: str,
    value: str,
    description: str | None = None,
    session: Session,
) -> bool:
    """不存在才写入，避免覆盖设置页后续修改。"""

    if get_by_key(key, session=session) is not None:
        return False
    create_setting(key=key, value=value, description=description, session=session)
    return True
