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
    """创建容器时的配置块，兼容旧版大写字段。"""

    gpu_list: list[int] = Field(default_factory=list, alias="GPU_LIST")
    cpu_number: int = Field(default=0, ge=0, alias="CPU_NUMBER")
    memory: int = Field(default=0, ge=0, alias="MEMORY")
    name: str = Field(default="", alias="NAME")
    image: str = Field(default="", alias="IMAGE")
    shared_memory: int = Field(default=0, ge=0, alias="SHARED_MEM")


class CreateContainerRequest(_CompatBaseModel):
    """创建容器请求。

    优先使用 container 配置块；顶层大写字段保留给旧调用兼容。
    """

    user_name: str = ""
    machine_id: int = Field(default=0, ge=0)
    container: ContainerConfigInput | None = None
    public_key: str | None = None
    GPU_LIST: list[int] = Field(default_factory=list)
    CPU_NUMBER: int = Field(default=0, ge=0)
    MEMORY: int = Field(default=0, ge=0)
    NAME: str = ""
    image: str = ""
    SHARED_MEM: int = Field(default=0, ge=0)


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
    machine_id: int | None = Field(default=None, ge=0)
    container_name: str = ""

    if field_validator is not None:
        _normalize_blank_machine_id = field_validator("machine_id", mode="before")(_blank_to_none)
    else:  # pragma: no cover
        _normalize_blank_machine_id = validator("machine_id", pre=True, allow_reuse=True)(_blank_to_none)


class ContainerStatusResponse(_CompatBaseModel):
    container_status: str | None = None


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
    machine_id: int | None = None
    machine_ip: str | None = None
    port: int | None = None
    container_status: str | None = None
    display_status: str | None = None
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
    freeze_first_frozen_at: str | None = None
    freeze_grace_until: str | None = None
    freeze_days_frozen: int | None = None
    freeze_escalation_days: int | None = None


class ContainerDetailInformation(_CompatBaseModel):
    container_id: int | None = None
    container_name: str | None = None
    container_image: str | None = None
    machine_id: int | None = None
    machine_ip: str | None = None
    container_status: str | None = None
    display_status: str | None = None
    memory_gb: int | None = None
    shared_gb: int | None = None
    gpu_number: int | None = None
    cpu_number: int | None = None
    port: int | None = None
    owners: list[str] = Field(default_factory=list)
    accounts: list[ContainerAccountEntry] = Field(default_factory=list)
    is_long_term: bool = False
    long_term_container_can_enable: bool = True
    long_term_container_blocked_user_ids: list[int] = Field(default_factory=list)
    long_term_container_remaining_by_user: dict[int, int] = Field(default_factory=dict)
    disk_usage: dict[str, Any] | None = None
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
