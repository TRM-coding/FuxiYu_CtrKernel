"""RBAC 权限矩阵 API。"""

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..constant import OperationType
from ..schemas.rbac import (
    CreateRbacGroupRequest,
    CreateRbacGroupResponse,
    RbacMatrixResponse,
    UpdateRbacGroupEntitiesRequest,
    UpdateRbacGroupEntitiesResponse,
)
from ..services import rbac_service
from ..services.operation_log_tasks import write_operation_log as write_op_log
from .deps import require_permission

router = APIRouter(prefix="/rbac", tags=["rbac"])

logger = logging.getLogger("FuxiYu_CtrKernel.api.rbac_api")


def _log_failure(*, operation, target_id, operator_user_id, error_reason, exc=None, detail=None):
    """失败双写：op-log（审计）+ ctrl 日志（调试，带层级归因与"差在哪"的 why）。

    层归因约定：service ValueError = 业务校验层（layer=service）；
    FastAPI 422 = 入参校验层（layer=validation，带 RequestValidationError detail）。
    """
    why = getattr(exc, "detail", "") if exc is not None else ""
    merged_detail = dict(detail or {})
    if why:
        merged_detail["why"] = why
    write_op_log(
        success=False,
        operator_user_id=operator_user_id,
        operation=operation,
        target_type="rbac_group",
        target_id=target_id,
        detail=merged_detail,
        error_reason=error_reason,
    )
    logger.warning(
        "rbac %s FAILED: operator=%s layer=service reason=%s why=%s detail=%s",
        operation,
        operator_user_id,
        error_reason,
        why or "-",
        merged_detail,
    )


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
    operator_user_id: int = Depends(require_permission("rbac:manage")),
):
    """替换某个权限组持有的 auth_entity 集合。"""

    try:
        group = rbac_service.update_group_entities(group_id, message.entity_codes)
    except ValueError as e:
        reason = str(e)
        _log_failure(
            operation=OperationType.UPDATE_RBAC_GROUP_ENTITIES,
            target_id=group_id,
            operator_user_id=operator_user_id,
            error_reason=reason,
            exc=e,
            detail={"group_id": group_id, "requested_entities": message.entity_codes},
        )
        if reason == "group_not_found":
            return _error(404, "rbac group not found", reason)
        if reason.startswith("unknown_auth_entities:"):
            return _error(400, "unknown auth entity", "unknown_auth_entity")
        return _error(400, "invalid rbac update", "invalid_rbac_update")
    write_op_log(
        success=True,
        operator_user_id=operator_user_id,
        operation=OperationType.UPDATE_RBAC_GROUP_ENTITIES,
        target_type="rbac_group",
        target_id=group_id,
        detail={
            "name": group["name"],
            "entities": group["entity_codes"],
            "locked_entities": group.get("locked_entity_codes") or [],
        },
    )
    return {"success": 1, "message": "rbac group updated", "group": group}


@router.post("/groups", response_model=CreateRbacGroupResponse, status_code=201)
def create_rbac_group_api(
    message: CreateRbacGroupRequest,
    operator_user_id: int = Depends(require_permission("rbac:manage")),
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
        _log_failure(
            operation=OperationType.CREATE_RBAC_GROUP,
            target_id=0,
            operator_user_id=operator_user_id,
            error_reason=reason,
            exc=e,
            detail={"name": message.name, "requested_entities": message.entity_codes},
        )
        if reason == "group_exists":
            return _error(409, "rbac group already exists", reason)
        if reason == "invalid_group_name":
            return _error(400, "invalid rbac group name", reason)
        if reason.startswith("unknown_auth_entities:"):
            return _error(400, "unknown auth entity", "unknown_auth_entity")
        return _error(400, "invalid rbac group", "invalid_rbac_group")
    write_op_log(
        success=True,
        operator_user_id=operator_user_id,
        operation=OperationType.CREATE_RBAC_GROUP,
        target_type="rbac_group",
        target_id=group["id"],
        detail={
            "name": group["name"],
            "description": group.get("description") or "",
            "entities": group["entity_codes"],
        },
    )
    return {"success": 1, "message": "rbac group created", "group": group}
