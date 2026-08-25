from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .common import SuccessMessageResponse


ImageStatus = Literal["draft", "ready", "disabled"]


#####################
# 镜像文件


class ImageFileContent(BaseModel):
    """镜像模板内容。最终 Dockerfile 由构建器临时拼接，不入库。"""

    base_image: str = Field(..., min_length=1, max_length=255, description="基础镜像，对应最终 Dockerfile 的 FROM。")
    dockerfile_body: str = Field(default="", description="用户业务 Dockerfile 片段，不包含平台注入片段。")
    pre_build: str | None = Field(default=None, description="可选 pre_build.sh 文件内容。")


#####################
# 创建镜像


class CreateImageRequest(ImageFileContent):
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class CreateImageResponse(SuccessMessageResponse):
    image_id: int


#####################
# 更新镜像


class UpdateImageRequest(BaseModel):
    image_id: int = Field(..., ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    base_image: str | None = Field(default=None, min_length=1, max_length=255)
    dockerfile_body: str | None = None
    pre_build: str | None = None
    status: ImageStatus | None = None


class UpdateImageResponse(SuccessMessageResponse):
    pass


#####################
# 删除镜像


class DeleteImageRequest(BaseModel):
    image_id: int = Field(..., ge=1)


class DeleteImageResponse(SuccessMessageResponse):
    pass


#####################
# 查询镜像


class ImageDetailRequest(BaseModel):
    image_id: int = Field(..., ge=1)


class ImageDetail(BaseModel):
    image_id: int
    name: str
    description: str | None = None
    status: ImageStatus
    base_image: str | None = None
    dockerfile_body: str | None = None
    pre_build: str | None = None
    created_by_user_id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ImageDetailResponse(BaseModel):
    success: int | bool = 1
    image: ImageDetail


class ImageBriefItem(BaseModel):
    image_id: int
    name: str
    description: str | None = None
    base_image: str | None = None
    status: ImageStatus
    created_by_user_id: int | None = None
    updated_at: str | None = None


class ListImageBriefResponse(BaseModel):
    success: int | bool = 1
    images: list[ImageBriefItem] = Field(default_factory=list)
    total_page: int = 0
    total_number: int = 0
