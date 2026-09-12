from typing import Any, Literal

from pydantic import BaseModel, Field

from .common import PageRequest, SuccessMessageResponse


MachineType = Literal["GPU", "CPU"]
MachineStatus = Literal["online", "offline"]


#####################
# 机器硬件信息


class NodeHardwareProfile(BaseModel):
    """Node 首连或 sys_snapshot 上报的宿主机硬件信息。"""

    cpu_core_number: int = Field(default=0, ge=0)
    gpu_number: int = Field(default=0, ge=0)
    gpu_type: str | None = None
    # GPU 三集合（决策）：gpu_list 事实（smi 枚举，sys_snapshot 更新）
    gpu_list: list[int] | None = None
    gpu_allow_list: list[int] | None = None
    memory_size_gb: int = Field(default=0, ge=0)
    disk_size_gb: int = Field(default=0, ge=0)


class MachineAllocationLimit(BaseModel):
    """Ctrl 对机器可分配资源的管理上限。"""

    max_shared_gb: int = Field(default=2, ge=0)
    max_cpu_core_number: int = Field(default=0, ge=0)
    max_gpu_number: int = Field(default=0, ge=0)
    max_memory_gb: int = Field(default=0, ge=0)
    # 容器磁盘可用上限（管理员维护）；与 disk_size_gb（显示用分区容量）无约束关系
    max_disk_size_gb: int | None = Field(default=None, ge=0)


#####################
# 注册机器（TOFU 接入）


class RegisterMachineByTrustAnchorRequest(BaseModel):
    """管理员只填最小信任锚，由注册流程完成建档。"""

    machine_name: str
    machine_ip: str
    machine_description: str = ""


class RegisterMachineResponse(SuccessMessageResponse):
    """TOFU 注册成功响应。"""

    uid: str
    certificate_fingerprint: str


class RegisterMachineWithProfileResponse(RegisterMachineResponse):
    """TOFU 建档一体响应：建档后返回 machine_id 与 Node 上报的硬件快照。"""

    machine_id: int
    hardware: dict | None = None


#####################
# 重新钉信任锚（对已登记机器的连接修复）


class RenewMachineTrustRequest(BaseModel):
    """对已登记机器重钉信任锚；只更新原行，不建档。"""

    machine_id: int = Field(..., ge=1)


class RenewMachineTrustResponse(SuccessMessageResponse):
    """重钉结果：新旧指纹与 uid 的处置方式都回给调用方。"""

    machine_id: int
    machine_name: str
    machine_ip: str
    certificate_fingerprint: str
    previous_certificate_fingerprint: str | None = None
    uid: str | None = None
    # uid 的三种处置：重发（对端丢牌）/ 采纳（库里本无）/ 不一致但保持不动
    uid_reissued: bool = False
    uid_adopted: bool = False
    uid_mismatch: bool = False


#####################
# 删除机器


class RemoveMachineRequest(BaseModel):
    machine_ids: list[int] = Field(default_factory=list)


class RemoveMachineResponse(SuccessMessageResponse):
    pass


#####################
# 更新机器


class MachineUpdateFields(BaseModel):
    """机器可更新字段。

    真实硬件字段后续主要由 Node 上报；管理员主要调整资源分配限制和管理字段。
    """

    machine_name: str | None = None
    machine_ip: str | None = None
    machine_type: MachineType | None = None
    machine_status: MachineStatus | None = None
    is_maintenance: bool | None = None
    machine_description: str | None = None
    cpu_core_number: int | None = Field(default=None, ge=0)
    gpu_number: int | None = Field(default=None, ge=0)
    gpu_type: str | None = None
    # GPU 三集合（决策）：gpu_allow_list 管理员许可集合（人工维护；空/None = 未配置按全量）
    gpu_allow_list: list[int] | None = None
    memory_size: int | None = Field(default=None, ge=0)
    disk_size: int | None = Field(default=None, ge=0)
    max_shared_gb: int | None = Field(default=None, ge=0)
    max_memory_gb: int | None = Field(default=None, ge=0)
    max_gpu_number: int | None = Field(default=None, ge=0)
    max_cpu_core_number: int | None = Field(default=None, ge=0)
    max_disk_size_gb: int | None = Field(default=None, ge=0)


class UpdateMachineRequest(BaseModel):
    machine_id: int = Field(..., ge=1)
    fields: MachineUpdateFields = Field(default_factory=MachineUpdateFields)


class UpdateMachineResponse(SuccessMessageResponse):
    pass


class SetMachineMaintenanceRequest(BaseModel):
    """独立设置机器维护开关。"""

    machine_id: int = Field(..., ge=1)
    is_maintenance: bool


class SetMachineMaintenanceResponse(SuccessMessageResponse):
    pass


#####################
# 查询机器详情


class MachineIdRequest(BaseModel):
    machine_id: int = Field(..., ge=1)


class MachineStatusRequest(BaseModel):
    machine_id: int = Field(..., ge=1)


class MachineStatusResponse(BaseModel):
    machine_status: MachineStatus | None = None
    is_maintenance: bool = False
    runtime_snapshot: dict[str, Any] | None = None


class MachineDetailResponse(NodeHardwareProfile, MachineAllocationLimit):
    machine_name: str = ""
    machine_ip: str = ""
    machine_type: MachineType = "CPU"
    machine_status: MachineStatus = "offline"
    is_maintenance: bool = False
    machine_description: str | None = None
    containers: list[int] = Field(default_factory=list)
    runtime_snapshot: dict[str, Any] | None = None


#####################
# 查询机器概要列表


class ListMachineBriefRequest(PageRequest):
    machine_search: str | None = Field(
        default=None,
        description="机器搜索关键词；匹配 machine_id、machine_name、machine_ip。",
    )


class MachineBriefItem(BaseModel):
    machine_id: int
    machine_name: str
    machine_ip: str
    machine_type: MachineType
    machine_status: MachineStatus
    is_maintenance: bool = False
    runtime_snapshot: dict[str, Any] | None = None


class ListMachineBriefResponse(BaseModel):
    machines: list[MachineBriefItem]
    total_pages: int


#####################
# 机器权限


class AddMachinePermissionRequest(BaseModel):
    machine_id: int = Field(..., ge=1)
    user_id: int = Field(..., ge=1)


class AddMachinePermissionResponse(SuccessMessageResponse):
    pass


class RemoveMachinePermissionRequest(BaseModel):
    machine_id: int = Field(..., ge=1)
    user_id: int = Field(..., ge=1)


class RemoveMachinePermissionResponse(SuccessMessageResponse):
    pass


class ListMachinePermissionsResponse(BaseModel):
    success: int | bool = 1
    machine_id: int
    user_ids: list[int]


#####################
# WSS sys_snapshot


class MachineRuntimeSnapshot(BaseModel):
    """Node WSS sys_snapshot payload 里的动态系统状态。"""

    usage_percent: float | None = Field(default=None, ge=0)


class SysSnapshotCpu(BaseModel):
    """sys_snapshot.payload.cpu。"""

    cores: int = Field(default=0, ge=0)
    physical_cores: int | None = Field(default=None, ge=0)
    usage_percent: float | None = Field(default=None, ge=0)


class SysSnapshotMemory(BaseModel):
    """sys_snapshot.payload.memory。"""

    total_gb: float | None = Field(default=None, ge=0)
    used_gb: float | None = Field(default=None, ge=0)
    available_gb: float | None = Field(default=None, ge=0)
    usage_percent: float | None = Field(default=None, ge=0)


class SysSnapshotGpu(BaseModel):
    """sys_snapshot.payload.gpu[]，vendor-aware 便于后续支持 AMD/Intel。"""

    vendor: str
    index: int | None = Field(default=None, ge=0)
    name: str | None = None
    memory_used_gb: float | None = Field(default=None, ge=0)
    memory_gb: float | None = Field(default=None, ge=0)
    utilization_gpu_percent: float | None = Field(default=None, ge=0)
    memory_usage_percent: float | None = Field(default=None, ge=0)


class SysSnapshotDisk(BaseModel):
    """sys_snapshot.payload.disk。"""

    total_gb: float | None = Field(default=None, ge=0)
    used_gb: float | None = Field(default=None, ge=0)
    free_gb: float | None = Field(default=None, ge=0)
    percent: float | None = Field(default=None, ge=0)


class SysSnapshotPayload(BaseModel):
    """Node 推送的 sys_snapshot 业务 payload。"""

    hostname: str | None = None
    platform: str | None = None
    cpu: SysSnapshotCpu
    memory: SysSnapshotMemory = Field(default_factory=SysSnapshotMemory)
    gpu: list[SysSnapshotGpu | dict[str, Any]] = Field(default_factory=list)
    disk: SysSnapshotDisk | dict[str, Any] = Field(default_factory=dict)
    collected_at: str | None = None


class SysSnapshotMessage(BaseModel):
    """Node -> Ctrl 的 sys_snapshot 帧。

    实际外层由 snapshot_batch 携带 node_uid；单帧保持 type/topic/payload 结构。
    """

    type: Literal["snapshot"] = "snapshot"
    topic: Literal["sys_snapshot"] = "sys_snapshot"
    payload: SysSnapshotPayload | dict[str, Any]
