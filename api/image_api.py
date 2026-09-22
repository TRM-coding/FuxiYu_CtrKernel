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
    SetImageValidRangeRequest,
    SetImageValidRangeResponse,
    SetImageVisibleUsersRequest,
    SetImageVisibleUsersResponse,
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
            # entrypoint 是配方的第四段（渲染成最终 Dockerfile 的最后一行）。
            # 此前这里漏了它：schema 收、service 存，但 create 这条路从不转发，
            # 前端填了也被静默丢掉（2026-09 补）。
            entrypoint=data.get("entrypoint"),
            status=data.get("status") or None,
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
    # **归属闸**：编辑（含改 Dockerfile）只能动自己建的模板。资源通配者（image:manage）
    # 照旧放行——通配判定在 user_has_resource 的第 0 步，不看这里用的是哪条口径。
    _: int = Depends(require_resource("image:owner", "image_id")),
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
# 可见范围（两个入口：三态开关 + CUSTOM 名单）


@router.post("/set_image_valid_range", response_model=SetImageValidRangeResponse)
def set_image_valid_range_api(
    message: SetImageValidRangeRequest,
    operator_user_id: int = Depends(require_permission("image:edit")),
    _: int = Depends(require_resource("image:owner", "image_id")),
):
    """设置可见范围三态：private（只有自己）/ everyone（所有人）/ custom（名单）。"""

    try:
        ok = image_service.Set_image_valid_range(
            image_id=message.image_id,
            valid_range=message.valid_range,
            operator_user_id=operator_user_id,
        )
    except Exception as exc:
        reason = getattr(exc, "error_reason", None)
        return _error(400 if reason else 500, str(exc), reason or "set_valid_range_failed")
    if not ok:
        return _error(404, "image not found", "image_not_found")
    return {"success": 1, "message": "Image valid range updated"}


@router.post("/set_image_visible_users", response_model=SetImageVisibleUsersResponse)
def set_image_visible_users_api(
    message: SetImageVisibleUsersRequest,
    operator_user_id: int = Depends(require_permission("image:edit")),
    _: int = Depends(require_resource("image:owner", "image_id")),
):
    """整组替换 CUSTOM 名单（set 语义，传 [] 即清空）。

    ★ 仅在 valid_range=custom 时可调用：非 custom 态一律 400（not_custom_range）。
      名单生不生效由 valid_range 决定，允许在别的态下改名单，等于让人改一个看不到效果的
      东西——用户会以为"我加了人怎么还是所有人可见"。前端在非 custom 态不提供这个能力，
      这里是 API 直调的兜底。
    """

    try:
        settled = image_service.Set_image_visible_users(
            image_id=message.image_id,
            user_ids=message.user_ids,
            operator_user_id=operator_user_id,
        )
    except Exception as exc:
        reason = getattr(exc, "error_reason", None)
        return _error(400 if reason else 500, str(exc), reason or "set_visible_users_failed")
    if settled is None:
        return _error(404, "image not found", "image_not_found")
    return {"success": 1, "message": "Image visible users updated", "user_ids": settled}


#####################
# 查询镜像


@router.get("/get_image_detail_information", response_model=ImageDetailResponse)
def get_image_detail_information_api(
    image_id: int = Query(..., ge=1),
    # ★ 详情要 **image:edit** 而不是 image:view（2026-09 决策）：这一层是"读完整 Dockerfile"
    #   的能力闸，而 image:edit 默认只在运维组里——反批量抓取 Dockerfile 的防线就落在这里，
    #   不在资源层（资源层管的是"哪些模板"，见 require_resource 那条）。
    _: int = Depends(require_permission("image:edit")),
    __: int = Depends(require_resource("image", "image_id")),
):
    """查询镜像模板详情，包含基础镜像与业务 Dockerfile 片段。"""

    image = image_service.Get_image_detail(image_id)
    if image is None:
        return _error(404, "image not found", "image_not_found")
    return {"success": 1, "image": image}


@router.get("/list_image_bref_information", response_model=ListImageBriefResponse)
def list_image_bref_information_api(
    page_number: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1),
    image_search: str | None = Query(default=None),
    mine_only: bool = Query(default=False),
    viewer_user_id: int = Depends(require_current_user),
    _: int = Depends(require_permission("image:view")),
):
    """分页查询镜像模板概要。"""

    result = image_service.List_image_bref_information(
        page_number=page_number,
        page_size=page_size,
        image_search=(image_search or "").strip() or None,
        viewer_user_id=viewer_user_id,
        mine_only=mine_only,
    )
    return {"success": 1, **result}
