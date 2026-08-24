# 容器展示态派生：宿主机不可达时覆盖为 host_offline（仅展示，DB 状态不动）

from pydantic import BaseModel, Field
from ...constant import ROLE, ContainerStatus
from ..machine_tasks import get_machine_reachable, is_machine_in_maintenance, is_machine_collect_error

#API Definition
####################################################
class container_bref_information(BaseModel):
    container_id: int # 加入这个 只是为了方便调取详细信息
    container_name:str
    machine_id:int
    machine_ip:str
    port:int
    container_status:str
    display_status: str | None = None  # 派生展示态（如 host_offline），DB 不落库
    accounts: list[dict] = Field(default_factory=list)
    is_long_term: bool = False
    long_term_container_can_enable: bool = True
    long_term_container_blocked_user_ids: list[int] = Field(default_factory=list)
    long_term_container_remaining_by_user: dict[int, int] = Field(default_factory=dict)
    last_ssh_login_time: str | None = None
    cleanup_after_days: int | None = None
    cleanup_at: str | None = None
    seconds_until_cleanup: int | None = None
    cleanup_status: str | None = None
    disk_total_gb: float | None = None
    disk_limit_gb: float | None = None
    disk_usage_percent: float | None = None
    freeze_first_frozen_at: str | None = None
    freeze_grace_until: str | None = None
    freeze_days_frozen: int | None = None
    freeze_escalation_days: int | None = None

class container_detail_information(BaseModel):
    container_id: int # 与上方结构对称
    container_name:str
    container_image:str
    machine_id:int
    machine_ip:str
    container_status:str
    memory_gb:int
    shared_gb:int
    gpu_number:int
    cpu_number:int
    port:int
    owners:list[str]
    accounts:list[(str,ROLE)]
    is_long_term: bool = False
    long_term_container_can_enable: bool = True
    long_term_container_blocked_user_ids: list[int] = Field(default_factory=list)
    long_term_container_remaining_by_user: dict[int, int] = Field(default_factory=dict)
    disk_usage: dict | None = None
    freeze_state: dict | None = None
####################################################
# 派生状态定义

DISPLAY_STATUS_HOST_OFFLINE = "host_offline"
DISPLAY_STATUS_HOST_MAINTENANCE = "host_maintenance"
DISPLAY_STATUS_UNKNOWN = "status_unknown"

# 派生状态辅助函数
def _derive_display_status(container_status, machine_id: int | None) -> str:
    """由"容器 DB 状态 + 机器轴条件"派生展示态。

    规则（优先级降序）：failed 是终态诊断不覆盖；宿主机不可达 → host_offline；
    维护 → host_maintenance；采集异常（collect_error_at，契约 C1）→ status_unknown
    （Node 无法采集容器状态，DB 保持最后已知值，不写容器诊断）；否则原状态。
    """
    status_str = container_status.value if hasattr(container_status, 'value') else str(container_status)
    if str(status_str).lower() == ContainerStatus.FAILED.value:
        return status_str
    if machine_id is None:
        return status_str
    if is_machine_in_maintenance(machine_id):
        return DISPLAY_STATUS_HOST_MAINTENANCE
    if not get_machine_reachable(machine_id):
        return DISPLAY_STATUS_HOST_OFFLINE
    if is_machine_collect_error(machine_id):
        return DISPLAY_STATUS_UNKNOWN
    return status_str
