"""RBAC 权限矩阵 API。"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..schemas.rbac import (
    CreateRbacGroupRequest,
    CreateRbacGroupResponse,
    RbacMatrixResponse,
    UpdateRbacGroupEntitiesRequest,
    UpdateRbacGroupEntitiesResponse,
)
from ..services import rbac_service
from .deps import require_permission

router = APIRouter(prefix="/rbac", tags=["rbac"])


def _error(status_code: int, message: str, error_reason: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"success": 0, "message": message, "error_reason": error_reason},
    )


@router.get("/matrix", response_model=RbacMatrixResponse)
def get_rbac_matrix_api(
    _: int = Depends(require_permission("rbac:manage")),
):
    """读取 auth_group × auth_entity 权限矩阵。"""

    matrix = rbac_service.list_rbac_matrix()
    return {"success": 1, **matrix}


@router.post("/groups/{group_id}/entities", response_model=UpdateRbacGroupEntitiesResponse)
def update_rbac_group_entities_api(
    group_id: int,
    message: UpdateRbacGroupEntitiesRequest,
    _: int = Depends(require_permission("rbac:manage")),
):
    """替换某个权限组持有的 auth_entity 集合。"""

    try:
        group = rbac_service.update_group_entities(group_id, message.entity_codes)
    except ValueError as e:
        reason = str(e)
        if reason == "group_not_found":
            return _error(404, "rbac group not found", reason)
        if reason.startswith("unknown_auth_entities:"):
            return _error(400, "unknown auth entity", "unknown_auth_entity")
        return _error(400, "invalid rbac update", "invalid_rbac_update")
    return {"success": 1, "message": "rbac group updated", "group": group}


@router.post("/groups", response_model=CreateRbacGroupResponse, status_code=201)
def create_rbac_group_api(
    message: CreateRbacGroupRequest,
    _: int = Depends(require_permission("rbac:manage")),
):
    """创建新的权限组，并写入初始 auth_entity 集合。"""

    try:
        group = rbac_service.create_group(
            name=message.name,
            description=message.description,
            entity_codes=message.entity_codes,
        )
    except ValueError as e:
        reason = str(e)
        if reason == "group_exists":
            return _error(409, "rbac group already exists", reason)
        if reason == "invalid_group_name":
            return _error(400, "invalid rbac group name", reason)
        if reason.startswith("unknown_auth_entities:"):
            return _error(400, "unknown auth entity", "unknown_auth_entity")
        return _error(400, "invalid rbac group", "invalid_rbac_group")
    return {"success": 1, "message": "rbac group created", "group": group}
