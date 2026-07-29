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