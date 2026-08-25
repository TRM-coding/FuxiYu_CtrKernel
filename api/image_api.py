"""镜像模板 API。"""

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from ..schemas.image import (
    CreateImageRequest,
    CreateImageResponse,
    DeleteImageRequest,
    DeleteImageResponse,
    ImageDetailResponse,
    ListImageBriefResponse,
    UpdateImageRequest,
    UpdateImageResponse,
)
from ..services import image_tasks as image_service
from .deps import require_current_user, require_permission, require_resource

router = APIRouter(prefix="/images", tags=["images"])


def _model_data(model, *, exclude_none: bool = False) -> dict[str, Any]:
    """兼容 Pydantic v1/v2 的模型转 dict。"""

    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_none=exclude_none)
    if hasattr(model, "dict"):
        try:
            return model.dict(exclude_none=exclude_none)
        except TypeError:
            return model.dict()
    if isinstance(model, dict):
        return model
    return dict(getattr(model, "__dict__", {}))


def _error(status_code: int, message: str, error_reason: str | None = None) -> JSONResponse:
    payload: dict[str, Any] = {"success": 0, "message": message}
    if error_reason is not None:
        payload["error_reason"] = error_reason
    return JSONResponse(status_code=status_code, content=payload)


#####################
# 创建镜像


@router.post("/create_image", response_model=CreateImageResponse, status_code=201)
def create_image_api(
    message: CreateImageRequest,
    operator_user_id: int = Depends(require_permission("image:edit")),
):
    """创建镜像模板。"""

    data = _model_data(message)
    try:
        image_id = image_service.Create_image(
            name=data["name"],
            description=data.get("description"),
            base_image=data["base_image"],
            dockerfile_body=data.get("dockerfile_body") or "",
            pre_build=data.get("pre_build"),
            operator_user_id=operator_user_id,
        )
    except IntegrityError as exc:
        detail = str(exc.orig) if hasattr(exc, "orig") else str(exc)
        return _error(409, f"Duplicate entry: {detail}", "duplicate_entry")
    except Exception as exc:
        reason = getattr(exc, "error_reason", None)
        return _error(400 if reason else 500, str(exc), reason or "create_failed")
    return {"success": 1, "message": "Image created successfully", "image_id": image_id}


#####################
# 更新镜像


@router.post("/update_image", response_model=UpdateImageResponse)
def update_image_api(
    message: UpdateImageRequest,
    operator_user_id: int = Depends(require_permission("image:edit")),
    _: int = Depends(require_resource("image", "image_id")),
):
    """更新镜像模板。"""

    data = _model_data(message, exclude_none=True)
    try:
        ok = image_service.Update_image(operator_user_id=operator_user_id, **data)
    except IntegrityError as exc:
        detail = str(exc.orig) if hasattr(exc, "orig") else str(exc)
        return _error(409, f"Duplicate entry: {detail}", "duplicate_entry")
    except Exception as exc:
        reason = getattr(exc, "error_reason", None)
        return _error(400 if reason else 500, str(exc), reason or "update_failed")
    if not ok:
        return _error(404, "image not found", "image_not_found")
    return {"success": 1, "message": "Image updated successfully"}


#####################
# 删除镜像


@router.post("/delete_image", response_model=DeleteImageResponse)
def delete_image_api(
    message: DeleteImageRequest,
    operator_user_id: int = Depends(require_permission("image:manage")),
    _: int = Depends(require_resource("image", "image_id")),
):
    """删除镜像模板。"""

    ok = image_service.Delete_image(
        image_id=message.image_id,
        operator_user_id=operator_user_id,
    )
    if not ok:
        return _error(404, "image not found", "image_not_found")
    return {"success": 1, "message": "Image deleted successfully"}


#####################
# 查询镜像


@router.get("/get_image_detail_information", response_model=ImageDetailResponse)
def get_image_detail_information_api(
    image_id: int = Query(..., ge=1),
    _: int = Depends(require_permission("image:view")),
    __: int = Depends(require_resource("image", "image_id")),
):
    """查询镜像模板详情，包含基础镜像、业务 Dockerfile 片段与 pre_build.sh。"""

    image = image_service.Get_image_detail(image_id)
    if image is None:
        return _error(404, "image not found", "image_not_found")
    return {"success": 1, "image": image}


@router.get("/list_image_bref_information", response_model=ListImageBriefResponse)
def list_image_bref_information_api(
    page_number: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1),
    image_search: str | None = Query(default=None),
    viewer_user_id: int = Depends(require_current_user),
    _: int = Depends(require_permission("image:view")),
):
    """分页查询镜像模板概要。"""

    result = image_service.List_image_bref_information(
        page_number=page_number,
        page_size=page_size,
        image_search=(image_search or "").strip() or None,
        viewer_user_id=viewer_user_id,
    )
    return {"success": 1, **result}
