from enum import Enum

class MachineStatus(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    MAINTENANCE = "maintenance"


class MachineTypes(Enum):
    GPU = "GPU"
    CPU = "CPU"

class ContainerStatus(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    CREATING = "creating"
    STARTING = "starting"
    STOPPING = "stopping"
    FAILED = "failed"
    PAUSED = "paused"



class ROLE(Enum):
    ADMIN="ADMIN"
    COLLABORATOR="COLLABORATOR"
    ROOT="ROOT"

class PERMISSION(Enum):
    USER="user"
    OPERATOR="operator"


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
    # 定时任务（operator=系统）
    SEND_CLEANUP_REMINDER = "send_cleanup_reminder"
    PAUSE_CONTAINER = "pause_container"
    REMOVE_CONTAINER = "remove_container"  # 磁盘超硬限，系统自动删除（区别于用户删除 delete_container）