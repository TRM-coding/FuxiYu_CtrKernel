from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

try:  # Pydantic v2
    from pydantic import ConfigDict, field_validator
except ImportError:  # pragma: no cover
    ConfigDict = None
    field_validator = None
    from pydantic import validator

from .common import ApiErrorResponse, SuccessMessageResponse


def _blank_to_none(value):
    """将前端可选筛选条件里的空字符串视为未传。"""

    return None if value == "" else value


def _blank_to_zero(value):
    """将创建容器的可选 owner 空值归一为 0，由 API 边界再归一为当前用户。"""

    return 0 if value in ("", None) else value


class _CompatBaseModel(BaseModel):
    if ConfigDict is not None:
        model_config = ConfigDict(populate_by_name=True, extra="ignore")
    else:  # pragma: no cover
        class Config:
            allow_population_by_field_name = True
            populate_by_name = True
            extra = "ignore"


#####################
# 容器创建


class ContainerConfigInput(_CompatBaseModel):
    """创建容器时的配置块，兼容旧版大写字段。

    无 image 字段：镜像只能由 image_id 指定（平台据此渲染 Dockerfile 并注入平台设施），
    调用方自带的镜像名一律不采信。旧客户端仍会发 IMAGE，由 extra="ignore" 静默丢弃。
    """

    gpu_list: list[int] = Field(default_factory=list, alias="GPU_LIST")
    cpu_number: int = Field(default=0, ge=0, alias="CPU_NUMBER")
    memory: int = Field(default=0, ge=0, alias="MEMORY")
    name: str = Field(default="", alias="NAME")
    shared_memory: int = Field(default=0, ge=0, alias="SHARED_MEM")


class CreateContainerRequest(_CompatBaseModel):
    """创建容器请求。

    优先使用 container 配置块；顶层大写字段保留给旧调用兼容。
    image_id 必填（API 边界校验，不在这里用 Field(...) 表达，否则会返回 422
    而不是本仓库统一的 400 + error_reason）。
    """

    owner_user_id: int = Field(default=0, ge=0)
    machine_id: int = Field(default=0, ge=0)
    image_id: int | None = Field(default=None, ge=1)
    container: ContainerConfigInput | None = None
    public_key: str | None = None
    GPU_LIST: list[int] = Field(default_factory=list)
    CPU_NUMBER: int = Field(default=0, ge=0)
    MEMORY: int = Field(default=0, ge=0)
    NAME: str = ""
    SHARED_MEM: int = Field(default=0, ge=0)

    if field_validator is not None:
        _normalize_blank_owner = field_validator("owner_user_id", mode="before")(_blank_to_zero)
    else:  # pragma: no cover
        _normalize_blank_owner = validator("owner_user_id", pre=True, allow_reuse=True)(_blank_to_zero)


class CreateContainerResponse(SuccessMessageResponse):
    pass


#####################
# 容器删除


class DeleteContainerRequest(_CompatBaseModel):
    container_id: int = Field(..., ge=1)


class DeleteContainerResponse(SuccessMessageResponse):
    pass


#####################
# 长驻容器


class ListDeletedContainersRequest(_CompatBaseModel):
    page_number: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1)


class DeletedContainerRecord(_CompatBaseModel):
    deleted_id: int | str
    original_container_id: int | None = None
    container_name: str | None = None
    # 镜像标签由容器行推导（归属标识 + 构建版本戳），与容器列表同一口径。
    # 字段名与容器列表的出参保持一致，避免前端出现"这里叫 image、那里叫 container_image"
    # 的双口径——也杜绝了"从快照 JSON 里读内嵌副本"的消费方式。
    container_image: str | None = None
    image_id: int | None = None
    machine_id: int | None = None
    machine_name: str | None = None
    machine_ip: str | None = None
    mount_path: str | None = None
    mount_cleanup_id: int | None = None
    removed_at: str | None = None
    removed_trigger: str | None = None
    cleaned_at: str | None = None
    mount_cleaned: bool = False
    cleanup_escalation: bool = False
    data_recoverable: bool = False
    snapshot: dict[str, Any] = Field(default_factory=dict)


class ListDeletedContainersResponse(_CompatBaseModel):
    success: int | bool = 1
    records: list[DeletedContainerRecord | dict[str, Any]] = Field(default_factory=list)
    total_page: int = 0
    total_number: int = 0


class CleanDeletedContainerMountRequest(_CompatBaseModel):
    deleted_id: int | None = Field(default=None, ge=1)
    mount_cleanup_id: int | None = Field(default=None, ge=1)


class CleanDeletedContainerMountResponse(SuccessMessageResponse):
    deleted_id: int | None = None
    mount_cleanup_id: int | None = None


class ResurrectContainerRequest(_CompatBaseModel):
    """恢复容器请求。

    `content_source` 是**可选的内容来源**（`snapshot` / `template`），只在响应里回了
    `requires_choice=True`（后端没有恢复、交回两份内容）之后才需要带上。

    ⚠ 它必须在这里显式声明：`_CompatBaseModel` 是 `extra="ignore"`，没声明的字段会被
    **静默丢弃** —— 曾经漏过一次，表现为"传了 template 也永远走快照"，而且不报错。
    """

    deleted_id: int = Field(..., ge=1)
    content_source: str | None = None


class DockerfileSectionDiff(_CompatBaseModel):
    """差异里的一个 Dockerfile 分段（基础镜像 / 业务片段）。

    分段呈现是刻意的：两份完整的 Dockerfile 摊在一起，用户很难看出到底哪一块不一样。

    没有平台注入段：它两侧都取当下的系统设置，按构造恒等（见 models/containers.py）。
    """

    name: str
    changed: bool


class RestoreContentPreview(_CompatBaseModel):
    """二选一时给出的一份内容（完整 Dockerfile 文本）。"""

    dockerfile: str = ""


class ResurrectContainerResponse(SuccessMessageResponse):
    """恢复容器的响应。**同一个接口承担两件事**（design D14）：

    - 正常恢复 → `container_id` 有值。
    - 存在二选一 → `requires_choice=True`，并带上两份内容与分段差异；**此时没有恢复**，
      调用方选完再带 `content_source` 调一次。

    容器留痕只在这个响应里交出去 —— 没有"谁都能调一下就把配方读走"的独立查询接口。
    """

    container_id: int | None = None
    requires_choice: bool = False
    snapshot: RestoreContentPreview | None = None
    template: RestoreContentPreview | None = None
    sections: list[DockerfileSectionDiff] = Field(default_factory=list)


class SetLongTermContainerRequest(_CompatBaseModel):
    container_id: int = Field(..., ge=1)
    is_long_term: bool


class SetLongTermContainerResponse(_CompatBaseModel):
    success: int | bool = 1
    container_id: int
    is_long_term: bool
    long_term_container_can_enable: bool = True
    long_term_container_blocked_user_ids: list[int] = Field(default_factory=list)
    long_term_container_remaining_by_user: dict[int, int] = Field(default_factory=dict)


#####################
# 容器通用操作


class ContainerIdRequest(_CompatBaseModel):
    container_id: int = Field(..., ge=1)


class ContainerOperationResponse(SuccessMessageResponse):
    pass


#####################
# 容器权限


class CollaboratorRequest(_CompatBaseModel):
    container_id: int = Field(..., ge=1)
    user_id: int = Field(..., ge=1)
    role: str = "COLLABORATOR"


class UpdateRoleRequest(_CompatBaseModel):
    container_id: int = Field(..., ge=1)
    user_id: int = Field(..., ge=1)
    updated_role: str = "COLLABORATOR"


#####################
# 容器状态查询


class ContainerStatusRequest(_CompatBaseModel):
    # 查询键与鉴权键统一为 container_id；前端心跳仍会附传 machine_id/container_name，
    # 由 extra="ignore" 忽略，不再参与查询，避免按任意 name+machine 探测他人容器。
    container_id: int | None = Field(default=None, ge=1)


class ContainerStatusResponse(_CompatBaseModel):
    effective_status: str | None = None
    failed_reason: str | None = None
    failed_detail: str | None = None
    runtime_metrics: dict[str, Any] | None = None


#####################
# SSH 登录时间


class RefreshLastSshLoginTimeRequest(_CompatBaseModel):
    container_id: int = Field(..., ge=1)


class RefreshLastSshLoginTimeResponse(_CompatBaseModel):
    success: int | bool = 1
    container_id: int
    container_name: str
    last_ssh_login_time: str | None = None
    cleanup_after_days: int | None = None
    cleanup_at: str | None = None
    seconds_until_cleanup: int | None = None
    cleanup_status: str | None = None


#####################
# 容器详情与列表


class ListAllContainerBrefInformationRequest(_CompatBaseModel):
    machine_id: int | None = Field(default=None, ge=0)
    user_id: int | None = Field(default=None, ge=0)
    container_search: str | None = Field(
        default=None,
        description="容器搜索关键词；匹配 container_id、container_name、port、machine_ip。",
    )
    page_number: int = Field(default=0, ge=0)
    page_size: int = Field(default=10, ge=1)

    if field_validator is not None:
        _normalize_blank_ids = field_validator("machine_id", "user_id", mode="before")(_blank_to_none)
    else:  # pragma: no cover
        _normalize_blank_ids = validator("machine_id", "user_id", pre=True, allow_reuse=True)(_blank_to_none)


class ContainerAccountEntry(_CompatBaseModel):
    user_id: int | None = None
    username: str | None = None
    role: str | None = None


class ContainerBriefInformation(_CompatBaseModel):
    container_id: int | None = None
    container_name: str | None = None
    container_image: str | None = None
    # 镜像模板归属（逻辑真源）；container_image 只是本次实跑制品的展示快照
    image_id: int | None = None
    # 容器创建时间（2026-09）：id 在 SQLite 删除后可复用，created_at 作新旧区分锚
    created_at: str | None = None
    machine_id: int | None = None
    machine_ip: str | None = None
    port: int | None = None
    effective_status: str | None = None
    # 展示派生：机器实际缩水 trim 后，容器申请超上限时展示砍后值（容器 DB 不动）
    alloc_cpu_number: int | None = None
    alloc_memory_gb: int | None = None
    alloc_gpu_number: int | None = None
    alloc_degraded: bool = False
    # GPU 三集合（决策）：容器分配锁定的物理卡集合
    gpu_chosen_list: list[int] | None = None
    # 端口映射（docker 自动分配回填）：[{container_port, host_port, protocol}]
    port_mappings: list[dict[str, Any]] | None = None
    failed_reason: str | None = None
    failed_detail: str | None = None
    accounts: list[dict[str, Any]] = Field(default_factory=list)
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
    runtime_metrics: dict[str, Any] | None = None
    freeze_first_frozen_at: str | None = None
    freeze_grace_until: str | None = None
    freeze_days_frozen: int | None = None
    freeze_escalation_days: int | None = None


class ContainerDetailInformation(_CompatBaseModel):
    container_id: int | None = None
    container_name: str | None = None
    container_image: str | None = None
    # 镜像模板归属（逻辑真源）；container_image 只是本次实跑制品的展示快照
    image_id: int | None = None
    # 容器创建时间（2026-09）：id 在 SQLite 删除后可复用，created_at 作新旧区分锚
    created_at: str | None = None
    # 完整 Dockerfile：由**该容器自己的配方留痕**现场渲染（`base_image` + `dockerfile_body`
    # + 当下的平台注入）。无留痕的存量容器回落为当前模板渲染；无归属且无留痕则为 None。
    image_dockerfile: str | None = None
    # 该容器实际跑的启动命令（容器行留痕）。None = 平台默认（保持存活等 SSH）。
    # 与 image_id / container_image 同一个口径：容器行记的是它自己那一份。
    entrypoint: str | None = None
    machine_id: int | None = None
    machine_ip: str | None = None
    effective_status: str | None = None
    failed_reason: str | None = None
    failed_detail: str | None = None
    memory_gb: int | None = None
    shared_gb: int | None = None
    gpu_number: int | None = None
    cpu_number: int | None = None
    port: int | None = None
    # 展示派生：机器实际缩水 trim 后，容器申请超上限时展示砍后值（容器 DB 不动）
    alloc_cpu_number: int | None = None
    alloc_memory_gb: int | None = None
    alloc_gpu_number: int | None = None
    alloc_degraded: bool = False
    # GPU 三集合（决策）：容器分配锁定的物理卡集合
    gpu_chosen_list: list[int] | None = None
    # 端口映射（docker 自动分配回填）：[{container_port, host_port, protocol}]
    port_mappings: list[dict[str, Any]] | None = None
    owners: list[str] = Field(default_factory=list)
    accounts: list[ContainerAccountEntry] = Field(default_factory=list)
    is_long_term: bool = False
    long_term_container_can_enable: bool = True
    long_term_container_blocked_user_ids: list[int] = Field(default_factory=list)
    long_term_container_remaining_by_user: dict[int, int] = Field(default_factory=dict)
    last_ssh_login_time: str | None = None
    cleanup_after_days: int | None = None
    cleanup_at: str | None = None
    seconds_until_cleanup: int | None = None
    cleanup_status: str | None = None
    disk_usage: dict[str, Any] | None = None
    runtime_metrics: dict[str, Any] | None = None
    freeze_state: dict[str, Any] | None = None


class ContainerDetailResponse(_CompatBaseModel):
    success: int | bool = 1
    container_info: ContainerDetailInformation | dict[str, Any]


class ListAllContainerBrefInformationResponse(_CompatBaseModel):
    success: int | bool = 1
    containers_info: list[ContainerBriefInformation | dict[str, Any]] = Field(default_factory=list)
    total_page: int = 0
    total_number: int = 0
    long_term_container_remaining: int | None = None
    long_term_container_limit: int | None = None


#####################
# 通用响应


class ContainerErrorResponse(ApiErrorResponse):
    pass
