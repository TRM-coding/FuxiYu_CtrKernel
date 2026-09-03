
from pydantic import BaseModel, Field
from ...constant import ROLE, ContainerStatus, ContainerEffectiveStatus
from ..machine_tasks import get_machine_reachable, is_machine_in_maintenance, is_machine_collect_error

#API Definition
####################################################
class container_bref_information(BaseModel):
    container_id: int # 加入这个 只是为了方便调取详细信息
    container_name:str
    container_image: str | None = None
    created_at: str | None = None
    machine_id:int
    machine_ip:str
    port:int
    port_mappings: list[dict] | None = None
    effective_status: str
    failed_reason: str | None = None
    failed_detail: str | None = None
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
    runtime_metrics: dict | None = None
    freeze_first_frozen_at: str | None = None
    freeze_grace_until: str | None = None
    freeze_days_frozen: int | None = None
    freeze_escalation_days: int | None = None
    # alloc 派生（机器上限 trim/许可交集后现算，出参补充；缺字段会被 pydantic extra=ignore
    # 静默丢弃 → 响应 null。曾漏在模型上（2026-09 双层 model 失配修复）
    gpu_chosen_list: list[int] | None = None
    alloc_cpu_number: int | None = None
    alloc_memory_gb: int | None = None
    alloc_gpu_number: int | None = None
    alloc_degraded: bool = False

class container_detail_information(BaseModel):
    container_id: int # 与上方结构对称
    container_name:str
    container_image:str
    created_at: str | None = None
    machine_id:int
    machine_ip:str
    effective_status: str
    failed_reason: str | None = None
    failed_detail: str | None = None
    memory_gb:int
    shared_gb:int
    gpu_number:int
    cpu_number:int
    port:int
    port_mappings: list[dict] | None = None
    owners:list[str]
    accounts:list[(str,ROLE)]
    is_long_term: bool = False
    long_term_container_can_enable: bool = True
    long_term_container_blocked_user_ids: list[int] = Field(default_factory=list)
    long_term_container_remaining_by_user: dict[int, int] = Field(default_factory=dict)
    disk_usage: dict | None = None
    runtime_metrics: dict | None = None
    freeze_state: dict | None = None
    # alloc/选择卡 派生字段（曾缺失被 extra=ignore 静默丢弃 → 响应 null，2026-09 修复）
    gpu_chosen_list: list[int] | None = None
    alloc_cpu_number: int | None = None
    alloc_memory_gb: int | None = None
    alloc_gpu_number: int | None = None
    alloc_degraded: bool = False
####################################################
# 派生状态定义


# 派生状态辅助函数
def _derive_effective_status(container_status, machine_id: int | None, *, container=None) -> str:
    """Return API/guard status from DB container state plus host conditions.

    优先级：容器 FAILED > 机器维护/离线/采集异常 > 容器轴 unknown 标记
    （status_unknown_since，仿机器 collect_error，2026-09-03）> 最后已知状态。
    """
    status_str = container_status.value if hasattr(container_status, 'value') else str(container_status)
    if str(status_str).lower() == ContainerStatus.FAILED.value:
        return status_str
    if machine_id is None:
        return status_str
    if is_machine_in_maintenance(machine_id):
        return ContainerEffectiveStatus.HOST_MAINTENANCE.value
    if not get_machine_reachable(machine_id):
        return ContainerEffectiveStatus.HOST_OFFLINE.value
    if is_machine_collect_error(machine_id):
        return ContainerEffectiveStatus.STATUS_UNKNOWN.value
    if container is not None and getattr(container, "status_unknown_since", None) is not None:
        return ContainerEffectiveStatus.STATUS_UNKNOWN.value
    return status_str
