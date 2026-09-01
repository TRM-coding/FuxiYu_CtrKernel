"""系统设置 API。"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..schemas.settings import (
    ImagePlatformInjectionSettingResponse,
    SystemSettingsResponse,
    UpdateImagePlatformInjectionSettingRequest,
    UpdateImagePlatformInjectionSettingResponse,
    UpdateSystemSettingsRequest,
    UpdateSystemSettingsResponse,
)
from ..services import settings_tasks
from .deps import require_permission

router = APIRouter(prefix="/settings", tags=["settings"])


def _error(status_code: int, message: str, error_reason: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"success": 0, "message": message, "error_reason": error_reason},
    )


#####################
# 系统设置矩阵


@router.get("", response_model=SystemSettingsResponse)
def list_settings_api(
    _: int = Depends(require_permission("settings:manage")),
):
    """读取可运行时调整的系统设置矩阵。"""

    return {"success": 1, "settings": settings_tasks.list_settings()}


@router.post("", response_model=UpdateSystemSettingsResponse)
def update_settings_api(
    message: UpdateSystemSettingsRequest,
    _: int = Depends(require_permission("settings:manage")),
):
    """批量更新系统设置。"""

    try:
        settings = settings_tasks.update_settings(message.values)
    except ValueError as e:
        return _error(422, str(e), "invalid_setting")
    except Exception as e:
        return _error(500, f"failed to update settings: {e}", "update_failed")
    return {"success": 1, "message": "settings updated", "settings": settings}


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

    try:
        settings_tasks.set_setting_value(
            settings_tasks.IMAGE_PLATFORM_INJECTION_KEY,
            message.content,
            description="镜像构建时由 Ctrl 拼入最终 Dockerfile 的平台注入片段。",
        )
    except ValueError as e:
        return _error(422, str(e), "invalid_setting")
    except Exception as e:
        return _error(500, f"failed to update image platform injection: {e}", "update_failed")
    return {"success": 1, "message": "Image platform injection updated successfully"}
