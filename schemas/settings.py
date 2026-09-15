from typing import Any

from pydantic import BaseModel, Field

from .common import SuccessMessageResponse


class SettingItem(BaseModel):
    key: str
    label: str
    group: str
    value_type: str
    value: Any
    default_value: Any
    description: str | None = None
    unit: str | None = None
    min_value: int | None = None
    max_value: int | None = None
    multiline: bool = False


class SystemSettingsResponse(BaseModel):
    success: int | bool = 1
    settings: list[SettingItem | dict[str, Any]]


class UpdateSystemSettingsRequest(BaseModel):
    values: dict[str, Any] = Field(..., description="按 setting key 写入的新值。")


class UpdateSystemSettingsResponse(SystemSettingsResponse):
    message: str = "settings updated"


#####################
# 镜像注入模板设置


class ImagePlatformInjectionSettingResponse(BaseModel):
    success: int | bool = 1
    content: str = Field(..., description="Ctrl 构建镜像前拼入最终 Dockerfile 的平台注入片段。")


class UpdateImagePlatformInjectionSettingRequest(BaseModel):
    content: str = Field(..., min_length=1, description="新的平台注入片段内容。")


class UpdateImagePlatformInjectionSettingResponse(SuccessMessageResponse):
    pass
