"""系统设置任务。

用于保存必须存在、但允许设置页后续编辑的系统级配置。
"""

from __future__ import annotations

from ..config import AppConfig
from ..extensions import session_scope
from ..repositories import system_setting_repo

IMAGE_PLATFORM_INJECTION_KEY = "image.platform_injection_content"


def seed_system_settings_defaults() -> None:
    """幂等写入必要系统设置。"""

    with session_scope() as session:
        system_setting_repo.seed_setting(
            key=IMAGE_PLATFORM_INJECTION_KEY,
            value=AppConfig.IMAGE_PLATFORM_INJECTION_CONTENT,
            description="镜像构建时由 Ctrl 拼入最终 Dockerfile 的平台注入片段。",
            session=session,
        )


def get_setting_value(key: str) -> str | None:
    with session_scope(commit=False) as session:
        return system_setting_repo.get_value(key, session=session)


def set_setting_value(key: str, value: str, description: str | None = None) -> None:
    """设置页写入配置；不存在时创建。"""

    with session_scope() as session:
        ok = system_setting_repo.update_setting(
            key,
            value=value,
            description=description,
            session=session,
        )
        if not ok:
            system_setting_repo.create_setting(
                key=key,
                value=value,
                description=description,
                session=session,
            )


def get_image_platform_injection_content() -> str:
    """读取镜像平台注入片段。"""

    value = get_setting_value(IMAGE_PLATFORM_INJECTION_KEY)
    if value is None:
        return AppConfig.IMAGE_PLATFORM_INJECTION_CONTENT
    return value
