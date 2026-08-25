"""系统设置 API。"""

from fastapi import APIRouter, Depends

from ..schemas.settings import (
    ImagePlatformInjectionSettingResponse,
    UpdateImagePlatformInjectionSettingRequest,
    UpdateImagePlatformInjectionSettingResponse,
)
from ..services import settings_tasks
from .deps import require_permission

router = APIRouter(prefix="/settings", tags=["settings"])


#####################
# 镜像注入模板设置


@router.get(
    "/image_platform_injection",
    response_model=ImagePlatformInjectionSettingResponse,
)
def get_image_platform_injection_api(
    _: int = Depends(require_permission("settings:manage")),
):
    """读取镜像平台注入片段。"""

    return {
        "success": 1,
        "content": settings_tasks.get_image_platform_injection_content(),
    }


@router.post(
    "/image_platform_injection",
    response_model=UpdateImagePlatformInjectionSettingResponse,
)
def update_image_platform_injection_api(
    message: UpdateImagePlatformInjectionSettingRequest,
    _: int = Depends(require_permission("settings:manage")),
):
    """更新镜像平台注入片段。"""

    settings_tasks.set_setting_value(
        settings_tasks.IMAGE_PLATFORM_INJECTION_KEY,
        message.content,
        description="镜像构建时由 Ctrl 拼入最终 Dockerfile 的平台注入片段。",
    )
    return {"success": 1, "message": "Image platform injection updated successfully"}
