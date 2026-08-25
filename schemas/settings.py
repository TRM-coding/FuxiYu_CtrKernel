from pydantic import BaseModel, Field

from .common import SuccessMessageResponse


#####################
# 镜像注入模板设置


class ImagePlatformInjectionSettingResponse(BaseModel):
    success: int | bool = 1
    content: str = Field(..., description="Ctrl 构建镜像前拼入最终 Dockerfile 的平台注入片段。")


class UpdateImagePlatformInjectionSettingRequest(BaseModel):
    content: str = Field(..., min_length=1, description="新的平台注入片段内容。")


class UpdateImagePlatformInjectionSettingResponse(SuccessMessageResponse):
    pass
