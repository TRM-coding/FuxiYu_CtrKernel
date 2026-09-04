from enum import Enum

class MachineStatus(Enum):
    ONLINE = "online"
    OFFLINE = "offline"


class MachineTypes(Enum):
    GPU = "GPU"
    CPU = "CPU"

class ContainerStatus(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    BUILDING = "building"
    CREATING = "creating"
    STARTING = "starting"
    RESTARTING = "restarting"
    STOPPING = "stopping"
    FAILED = "failed"
    PAUSED = "paused"


class ContainerEffectiveStatus(Enum):
    """Transport/guard status = persisted container_status plus derived host state.

    container_status remains the DB fact for the container itself. effective_status
    is used by container API responses, frontend rendering, and operation guards.
    """
    HOST_OFFLINE = "host_offline"
    HOST_MAINTENANCE = "host_maintenance"
    STATUS_UNKNOWN = "status_unknown"


class ImageStatus(Enum):
    DRAFT = "draft"
    READY = "ready"
    DISABLED = "disabled"



class ROLE(Enum):
    ADMIN="ADMIN"
    COLLABORATOR="COLLABORATOR"
    ROOT="ROOT"

class AnnouncementStatus(Enum):
    SENDING = "sending"
    SENT = "sent"
    PARTIAL = "partial"
    FAILED = "failed"


class AnnouncementTargetType(Enum):
    MACHINE = "machine"
    CONTAINER = "container"
    USER = "user"


class AnnouncementTemplateCategory(Enum):
    SYSTEM = "system"
    CUSTOM = "custom"


class OperationType(str, Enum):
    """操作日志操作名枚举。唯一事实源：前端中文映射表与契约文档都以此为准。

    str 基类：直接存入 String 列时值为 "xxx" 而非 "OperationType.XXX"，
    且与字符串相等比较成立。"""
    # 机器
    ADD_MACHINE = "add_machine"
    REMOVE_MACHINE = "remove_machine"
    UPDATE_MACHINE = "update_machine"
    ADD_MACHINE_PERMISSION = "add_machine_permission"
    REMOVE_MACHINE_PERMISSION = "remove_machine_permission"
    # 容器
    CREATE_CONTAINER = "create_container"
    DELETE_CONTAINER = "delete_container"
    UNPAUSE_CONTAINER = "unpause_container"
    SET_LONG_TERM = "set_long_term"
    ADD_COLLABORATOR = "add_collaborator"
    REMOVE_COLLABORATOR = "remove_collaborator"
    UPDATE_COLLABORATOR_ROLE = "update_collaborator_role"
    START_CONTAINER = "start_container"
    STOP_CONTAINER = "stop_container"
    RESTART_CONTAINER = "restart_container"
    # 用户
    REGISTER_USER = "register_user"
    CHANGE_PASSWORD = "change_password"
    DELETE_USER = "delete_user"
    RESET_PASSWORD = "reset_password"
    # RBAC 权限组（管理动作，敏感审计）
    CREATE_RBAC_GROUP = "create_group"
    UPDATE_RBAC_GROUP_ENTITIES = "update_group_entities"
    UPDATE_USER_GROUPS = "update_user_groups"
    # 镜像
    CREATE_IMAGE = "create_image"
    UPDATE_IMAGE = "update_image"
    DELETE_IMAGE = "delete_image"
    # 定时任务（operator=系统）
    SEND_CLEANUP_REMINDER = "send_cleanup_reminder"
    PAUSE_CONTAINER = "pause_container"
    # 系统事件（非用户操作，仅审计记录；RBAC / 告警维度请勿把它当"操作"）
