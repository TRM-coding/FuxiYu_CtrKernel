from typing import Any

from pydantic import BaseModel, Field


class OperationLogListQuery(BaseModel):
    """操作日志查询参数。"""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1)
    operator_user_id: int | None = None
    operation: str | None = None
    target_type: str | None = None
    success: bool | None = None
    start: str | None = None
    end: str | None = None
    tz_offset_minutes: int | None = None


class OperationLogItem(BaseModel):
    """操作日志条目。字段保持宽松，兼容 repo serialize 输出。"""

    id: int | None = None
    operator_user_id: int | None = None
    operation: str | None = None
    target_type: str | None = None
    target_id: int | None = None
    target_name: str | None = None
    root_owner: str | None = None
    detail: dict[str, Any] | None = None
    success: bool | int | None = None
    error_reason: str | None = None
    created_at: str | None = None


class OperationLogListResponse(BaseModel):
    success: int | bool = 1
    logs: list[OperationLogItem | dict[str, Any]]
    total_pages: int


class OperationLogStatsResponse(BaseModel):
    success: int | bool = 1
    total: int | None = None
    succeeded: int | None = None
    failed: int | None = None
    by_day: list[dict[str, Any]] | dict[str, Any] | None = None
    by_operation: list[dict[str, Any]] | dict[str, Any] | None = None
    by_target_type: list[dict[str, Any]] | dict[str, Any] | None = None
    by_error_reason: list[dict[str, Any]] | dict[str, Any] | None = None
