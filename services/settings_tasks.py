"""系统设置任务。

用于保存必须存在、但允许设置页后续编辑的系统级配置。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..extensions import session_scope
from ..repositories import system_setting_repo

IMAGE_PLATFORM_INJECTION_KEY = "image.platform_injection_content"
DEFAULT_IMAGE_PLATFORM_INJECTION_CONTENT = r"""USER root
SHELL ["/bin/sh", "-c"]
RUN set -eu; \
    if command -v apt-get >/dev/null 2>&1; then \
        apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends openssh-server passwd && rm -rf /var/lib/apt/lists/*; \
    elif command -v apk >/dev/null 2>&1; then \
        apk add --no-cache openssh; \
    elif command -v dnf >/dev/null 2>&1; then \
        dnf install -y openssh-server shadow-utils && dnf clean all; \
    else \
        echo "unsupported package manager for Fuxi platform image injection" >&2; exit 1; \
    fi; \
    mkdir -p /run/sshd
EXPOSE 22"""


@dataclass(frozen=True)
class SettingDefinition:
    key: str
    label: str
    group: str
    value_type: str
    default: object
    description: str
    unit: str | None = None
    min_value: int | None = None
    max_value: int | None = None
    multiline: bool = False


SETTING_DEFINITIONS: tuple[SettingDefinition, ...] = (
    SettingDefinition(
        key="container.cleanup_after_days",
        label="自动清理天数",
        group="容器清理",
        value_type="integer",
        default=7,
        description="容器长时间未 SSH 登录后的自动清理阈值。",
        unit="天",
        min_value=1,
    ),
    SettingDefinition(
        key="container.cleanup_interval_seconds",
        label="自动清理间隔",
        group="容器清理",
        value_type="integer",
        default=1200,
        description="自动清理长期未 SSH 登录容器的轮询间隔。",
        unit="秒",
        min_value=60,
    ),
    SettingDefinition(
        key="container.long_term_limit",
        label="长期容器上限",
        group="容器清理",
        value_type="integer",
        default=1,
        description="每个用户最多可设置的长期容器数量。",
        unit="个",
        min_value=0,
    ),
    SettingDefinition(
        key="container.cleanup_reminder_hours",
        label="清理提醒节点",
        group="容器清理",
        value_type="text",
        default="72,24,12",
        description="容器清理前邮件提醒节点，单位小时，逗号分隔。",
    ),
    SettingDefinition(
        key="container.disk_check_enabled",
        label="磁盘检测",
        group="磁盘策略",
        value_type="boolean",
        default=False,
        description="是否启用容器磁盘用量定期检测。",
    ),
    SettingDefinition(
        key="container.disk_check_interval_seconds",
        label="磁盘检测间隔",
        group="磁盘策略",
        value_type="integer",
        default=900,
        description="容器磁盘用量检测的轮询间隔。",
        unit="秒",
        min_value=60,
    ),
    SettingDefinition(
        key="container.disk_soft_limit_percent",
        label="磁盘软阈值",
        group="磁盘策略",
        value_type="integer",
        default=80,
        description="磁盘用量达到该百分比后进入提醒/预警区间。",
        unit="%",
        min_value=1,
        max_value=100,
    ),
    SettingDefinition(
        key="container.disk_hard_limit_percent",
        label="磁盘硬阈值",
        group="磁盘策略",
        value_type="integer",
        default=100,
        description="磁盘用量达到该百分比后触发硬限制策略。",
        unit="%",
        min_value=1,
        max_value=100,
    ),
    SettingDefinition(
        key="container.disk_response_enabled",
        label="磁盘超限响应",
        group="磁盘策略",
        value_type="boolean",
        default=False,
        description="是否启用冻结/升级等磁盘超限处置动作。",
    ),
    SettingDefinition(
        key="container.disk_freeze_escalation_days",
        label="冻结升级天数",
        group="磁盘策略",
        value_type="integer",
        default=7,
        description="磁盘超限冻结后进入升级清理的等待天数。",
        unit="天",
        min_value=1,
    ),
    SettingDefinition(
        key="container.disk_freeze_grace_days",
        label="冻结宽限天数",
        group="磁盘策略",
        value_type="integer",
        default=3,
        description="磁盘冻结后保留给用户处理的宽限期。",
        unit="天",
        min_value=1,
    ),
    SettingDefinition(
        key="container.disk_freeze_reset_percent",
        label="解冻恢复阈值",
        group="磁盘策略",
        value_type="integer",
        default=95,
        description="磁盘用量回落到该百分比以下后可解除冻结。",
        unit="%",
        min_value=1,
        max_value=100,
    ),
    SettingDefinition(
        key="container.mount_cleanup_enabled",
        label="已删容器目录清理",
        group="已删除容器",
        value_type="boolean",
        default=False,
        description="是否启用已删除容器 bind mount 目录的定期清理。",
    ),
    SettingDefinition(
        key="container.mount_cleanup_interval_seconds",
        label="目录清理间隔",
        group="已删除容器",
        value_type="integer",
        default=86400,
        description="已删除容器目录清理任务的轮询间隔。",
        unit="秒",
        min_value=3600,
    ),
    SettingDefinition(
        key="container.mount_cleanup_after_days",
        label="目录保留天数",
        group="已删除容器",
        value_type="integer",
        default=14,
        description="容器删除后 bind mount 目录的保留天数。",
        unit="天",
        min_value=1,
    ),
    SettingDefinition(
        key="announcement.max_recipients",
        label="单次最大发送对象",
        group="公告",
        value_type="integer",
        default=200,
        description="公告一次解析/发送允许的最大收件对象数。",
        unit="个",
        min_value=1,
    ),
    SettingDefinition(
        key="announcement.send_cooldown_seconds",
        label="发送冷却时间",
        group="公告",
        value_type="integer",
        default=60,
        description="公告重复发送之间的冷却时间。",
        unit="秒",
        min_value=0,
    ),
    SettingDefinition(
        key="announcement.batch_send_max",
        label="批量发送上限",
        group="公告",
        value_type="integer",
        default=20,
        description="草稿批量发送时单次处理的最大数量。",
        unit="条",
        min_value=1,
    ),
    SettingDefinition(
        key=IMAGE_PLATFORM_INJECTION_KEY,
        label="镜像平台注入",
        group="镜像",
        value_type="text",
        default=DEFAULT_IMAGE_PLATFORM_INJECTION_CONTENT,
        description="Ctrl 构建镜像前拼入最终 Dockerfile 的平台注入片段。",
        multiline=True,
    ),
)

_SETTING_BY_KEY = {definition.key: definition for definition in SETTING_DEFINITIONS}
DEPRECATED_SETTING_KEYS = (
    "node.request_pool_size",
    "node.parallel_enabled_machines",
    "node.parallel_enabled_containers",
    "node.parallel_enabled_ssh_refresh",
)


def _value_to_storage(value: object, value_type: str) -> str:
    if value_type == "boolean":
        return "true" if bool(value) else "false"
    return str(value)


def _parse_value(value: str | None, definition: SettingDefinition) -> object:
    raw = _value_to_storage(definition.default, definition.value_type) if value is None else str(value)
    if definition.value_type == "boolean":
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    if definition.value_type == "integer":
        try:
            return int(raw)
        except Exception:
            return int(definition.default)
    return raw


def _validate_value(key: str, value: object) -> str:
    definition = _SETTING_BY_KEY.get(key)
    if definition is None:
        raise ValueError(f"unknown setting key: {key}")

    if definition.value_type == "boolean":
        if isinstance(value, bool):
            return _value_to_storage(value, definition.value_type)
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return "true"
        if normalized in {"0", "false", "no", "off"}:
            return "false"
        raise ValueError(f"{key} must be boolean")

    if definition.value_type == "integer":
        try:
            number = int(value)
        except Exception as exc:
            raise ValueError(f"{key} must be integer") from exc
        if definition.min_value is not None and number < definition.min_value:
            raise ValueError(f"{key} must be >= {definition.min_value}")
        if definition.max_value is not None and number > definition.max_value:
            raise ValueError(f"{key} must be <= {definition.max_value}")
        return str(number)

    text = str(value)
    if definition.key == IMAGE_PLATFORM_INJECTION_KEY and not text.strip():
        raise ValueError(f"{key} cannot be empty")
    return text


def _serialize_setting(definition: SettingDefinition, stored_value: str | None) -> dict:
    value = _parse_value(stored_value, definition)
    return {
        "key": definition.key,
        "label": definition.label,
        "group": definition.group,
        "value_type": definition.value_type,
        "value": value,
        "default_value": _parse_value(None, definition),
        "description": definition.description,
        "unit": definition.unit,
        "min_value": definition.min_value,
        "max_value": definition.max_value,
        "multiline": definition.multiline,
    }


def seed_system_settings_defaults() -> None:
    """幂等写入必要系统设置。"""

    with session_scope() as session:
        system_setting_repo.delete_settings(
            keys=DEPRECATED_SETTING_KEYS,
            session=session,
        )
        for definition in SETTING_DEFINITIONS:
            system_setting_repo.seed_setting(
                key=definition.key,
                value=_value_to_storage(definition.default, definition.value_type),
                description=definition.description,
                session=session,
            )


def get_setting_value(key: str) -> str | None:
    with session_scope(commit=False) as session:
        return system_setting_repo.get_value(key, session=session)


def set_setting_value(key: str, value: str, description: str | None = None) -> None:
    """设置页写入配置；不存在时创建。"""

    stored = _validate_value(key, value)
    if description is None and key in _SETTING_BY_KEY:
        description = _SETTING_BY_KEY[key].description
    with session_scope() as session:
        ok = system_setting_repo.update_setting(
            key,
            value=stored,
            description=description,
            session=session,
        )
        if not ok:
            system_setting_repo.create_setting(
                key=key,
                value=stored,
                description=description,
                session=session,
            )


def list_settings() -> list[dict]:
    with session_scope(commit=False) as session:
        rows = {row.key: row.value for row in system_setting_repo.list_settings(session=session)}
    return [_serialize_setting(definition, rows.get(definition.key)) for definition in SETTING_DEFINITIONS]


def update_settings(values: dict[str, object]) -> list[dict]:
    if not isinstance(values, dict):
        raise ValueError("settings payload must be an object")
    for key, value in values.items():
        _validate_value(key, value)
    with session_scope() as session:
        for key, value in values.items():
            definition = _SETTING_BY_KEY[key]
            stored = _validate_value(key, value)
            ok = system_setting_repo.update_setting(
                key,
                value=stored,
                description=definition.description,
                session=session,
            )
            if not ok:
                system_setting_repo.create_setting(
                    key=key,
                    value=stored,
                    description=definition.description,
                    session=session,
                )
    return list_settings()


def get_int_setting(key: str, fallback: int) -> int:
    definition = _SETTING_BY_KEY.get(key)
    if definition is None:
        return int(fallback)
    value = get_setting_value(key)
    parsed = _parse_value(value, definition)
    try:
        return int(parsed)
    except Exception:
        return int(fallback)


def get_bool_setting(key: str, fallback: bool) -> bool:
    definition = _SETTING_BY_KEY.get(key)
    if definition is None:
        return bool(fallback)
    value = get_setting_value(key)
    return bool(_parse_value(value, definition))


def get_text_setting(key: str, fallback: str) -> str:
    definition = _SETTING_BY_KEY.get(key)
    if definition is None:
        return str(fallback)
    value = get_setting_value(key)
    parsed = _parse_value(value, definition)
    return str(parsed)


def get_container_cleanup_after_days() -> int:
    return get_int_setting("container.cleanup_after_days", 7)


def get_container_cleanup_interval_seconds() -> int:
    return get_int_setting("container.cleanup_interval_seconds", 1200)


def get_long_term_container_limit() -> int:
    return get_int_setting("container.long_term_limit", 1)


def get_container_cleanup_reminder_hours() -> str:
    return get_text_setting("container.cleanup_reminder_hours", "72,24,12")


def get_container_disk_check_enabled() -> bool:
    return get_bool_setting("container.disk_check_enabled", False)


def get_container_disk_check_interval_seconds() -> int:
    return get_int_setting("container.disk_check_interval_seconds", 900)


def get_container_disk_soft_limit_percent() -> int:
    return get_int_setting("container.disk_soft_limit_percent", 80)


def get_container_disk_hard_limit_percent() -> int:
    return get_int_setting("container.disk_hard_limit_percent", 100)


def get_container_disk_response_enabled() -> bool:
    return get_bool_setting("container.disk_response_enabled", False)


def get_container_disk_freeze_escalation_days() -> int:
    return get_int_setting("container.disk_freeze_escalation_days", 7)


def get_container_disk_freeze_grace_days() -> int:
    return get_int_setting("container.disk_freeze_grace_days", 3)


def get_container_disk_freeze_reset_percent() -> int:
    return get_int_setting("container.disk_freeze_reset_percent", 95)


def get_container_mount_cleanup_enabled() -> bool:
    return get_bool_setting("container.mount_cleanup_enabled", False)


def get_container_mount_cleanup_interval_seconds() -> int:
    return get_int_setting("container.mount_cleanup_interval_seconds", 86400)


def get_container_mount_cleanup_after_days() -> int:
    return get_int_setting("container.mount_cleanup_after_days", 14)


def get_announcement_max_recipients() -> int:
    return get_int_setting("announcement.max_recipients", 200)


def get_announcement_send_cooldown_seconds() -> int:
    return get_int_setting("announcement.send_cooldown_seconds", 60)


def get_announcement_batch_send_max() -> int:
    return get_int_setting("announcement.batch_send_max", 20)


def get_image_platform_injection_content() -> str:
    """读取镜像平台注入片段。"""

    return get_text_setting(IMAGE_PLATFORM_INJECTION_KEY, DEFAULT_IMAGE_PLATFORM_INJECTION_CONTENT)
