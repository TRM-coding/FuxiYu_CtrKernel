from enum import Enum

class MachineStatus(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    MAINTENANCE = "maintenance"


class MachineTypes(Enum):
    GPU = "GPU"
    CPU = "CPU"
    PHYSICAL = "PHYSICAL"  # 新增：兼容数据库中已有的 'PHYSICAL' 值


class ContainerStatus(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    MAINTENANCE = "maintenance"


class ROLE(Enum):
    ADMIN="admin"
    COLLABORATOR="collaborator"
    ROOT="root"