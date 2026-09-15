from typing import Any

from pydantic import BaseModel, Field


class ApiErrorResponse(BaseModel):
    """统一错误响应，用于 FastAPI Swagger responses。"""

    success: int | bool = 0
    message: str
    error_reason: str | None = None


class SuccessMessageResponse(BaseModel):
    """只表达操作是否成功和提示文案的通用响应。"""

    success: int | bool = 1
    message: str


class PageRequest(BaseModel):
    """分页请求；当前 Ctrl 约定 page_number 从 0 开始。"""

    page_number: int = Field(default=0, ge=0)
    page_size: int = Field(default=10, ge=1)


class IdRequest(BaseModel):
    """单个数据库对象 id 请求。"""

    id: int = Field(..., ge=1)


class EmptyObject(BaseModel):
    """占位空对象，避免 Swagger 显示为任意 JSON。"""

    pass


class FreeFormObject(BaseModel):
    """少数迁移期字段还未稳定时使用的自由对象。"""

    value: dict[str, Any] = Field(default_factory=dict)
