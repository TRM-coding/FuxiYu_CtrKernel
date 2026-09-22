from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .common import SuccessMessageResponse


ImageStatus = Literal["draft", "ready", "disabled"]

# 可见范围三态。**唯一**决定可见性的东西（见 constant.ImageValidRange）：
# private = 只有创建者；everyone = 所有用户；custom = user_images 授权名单里的人。
ImageValidRange = Literal["private", "everyone", "custom"]


#####################
# 镜像文件


class ImageFileContent(BaseModel):
    """镜像模板内容。最终 Dockerfile 由构建器临时拼接，不入库。"""

    base_image: str = Field(..., min_length=1, max_length=255, description="基础镜像，对应最终 Dockerfile 的 FROM。")
    dockerfile_body: str = Field(default="", description="用户业务 Dockerfile 片段，不包含平台注入片段。")
    # 可空且**空即默认**（容器保持存活等你 SSH 进来）。空串按 None 归一，避免两种空值分叉。
    # 平台不使用镜像自带的 ENTRYPOINT/CMD，见 utils/Container.py 的说明。
    entrypoint: str | None = Field(
        default=None, max_length=255,
        description="容器启动命令。留空 = 平台默认（保持存活）。注意平台不跑镜像自带的 ENTRYPOINT/CMD。",
    )


#####################
# 创建镜像


class CreateImageRequest(ImageFileContent):
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    # 2026-09 决策：创建即带状态（不传默认草稿；此前恒 DRAFT 导致新建后需二次编辑才能置可用）
    status: ImageStatus | None = Field(default=None)


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
    entrypoint: str | None = Field(default=None, max_length=255)
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
# 可见范围


class SetImageValidRangeRequest(BaseModel):
    image_id: int = Field(..., ge=1)
    valid_range: ImageValidRange


class SetImageValidRangeResponse(SuccessMessageResponse):
    pass


class SetImageVisibleUsersRequest(BaseModel):
    image_id: int = Field(..., ge=1)
    # 整组替换（set 语义）：传 [] 即清空名单。仅在 valid_range=custom 时可调用。
    user_ids: list[int] = Field(default_factory=list)


class SetImageVisibleUsersResponse(SuccessMessageResponse):
    user_ids: list[int] = Field(default_factory=list)


#####################
# 查询镜像


class ImageDetailRequest(BaseModel):
    image_id: int = Field(..., ge=1)


class ImageDetail(BaseModel):
    image_id: int
    name: str
    description: str | None = None
    status: ImageStatus
    valid_range: ImageValidRange
    base_image: str | None = None
    dockerfile_body: str | None = None
    entrypoint: str | None = None
    created_by_user_id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    # 仅 custom 态返回（其它态名单存着但不生效，回显会画出与现实不符的勾选）
    visible_user_ids: list[int] | None = None


class ImageDetailResponse(BaseModel):
    success: int | bool = 1
    image: ImageDetail


class ImageBriefItem(BaseModel):
    image_id: int
    name: str
    description: str | None = None
    base_image: str | None = None
    status: ImageStatus
    valid_range: ImageValidRange
    created_by_user_id: int | None = None
    updated_at: str | None = None


class ListImageBriefResponse(BaseModel):
    success: int | bool = 1
    images: list[ImageBriefItem] = Field(default_factory=list)
    total_page: int = 0
    total_number: int = 0
