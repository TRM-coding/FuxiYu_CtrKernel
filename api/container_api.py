"""容器系统 API 路由。"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from ..config import AppConfig
from ..constant import OperationType, ROLE
from ..extensions import session_scope
from ..repositories import containers_repo
from ..services import container_tasks as container_service
from ..services.operation_log_tasks import write_operation_log as write_op_log
from ..utils.Container import Container_info
from ..utils.parsers import parse_bool
from ..schemas.container import (
    CollaboratorRequest,
    ContainerDetailResponse,
    ContainerIdRequest,
    ContainerOperationResponse,
    ContainerStatusRequest,
    ContainerStatusResponse,
    CreateContainerRequest,
    CreateContainerResponse,
    DeleteContainerRequest,
    DeleteContainerResponse,
    ListAllContainerBrefInformationRequest,
    ListAllContainerBrefInformationResponse,
    RefreshLastSshLoginTimeRequest,
    RefreshLastSshLoginTimeResponse,
    SetLongTermContainerRequest,
    SetLongTermContainerResponse,
    UpdateRoleRequest,
)
from .deps import require_current_user, require_permission, require_resource, require_machine_of_container

router = APIRouter(prefix="/containers", tags=["containers"])

REASON_STATUS_MAP = {
    "container_exists": 409,
    "invalid_payload": 400,
    "invalid_signature": 401,
    "invalid_json": 400,
    "invalid_config": 400,
    "docker_init_failed": 502,
    "docker_check_failed": 502,
    "unexpected_response": 502,
    "not_found": 404,
    "duplicate_entry": 409,
    "create_failed": 500,
    "delete_failed": 500,
    "start_failed": 500,
    "stop_failed": 500,
    "restart_failed": 500,
    "container_offline": 400,
    "node_endpoint_not_found": 502,
    "container_not_found": 404,
    "machine_permission_denied": 403,
    "container_permission_denied": 403,
    "insufficient_permission": 403,
    "long_term_limit_reached": 409,
}


def _error(status_code: int, message: str, error_reason: str | None = None) -> JSONResponse:
    payload: dict[str, Any] = {"success": 0, "message": message}
    if error_reason is not None:
        payload["error_reason"] = error_reason
    return JSONResponse(status_code=status_code, content=payload)


def _dump_model(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return value


def _payload_data(payload: Any) -> dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump(exclude_none=True)
    if hasattr(payload, "dict"):
        return payload.dict(exclude_none=True)
    return dict(payload)


def _log_failure(*, operation, target_type, target_id, operator_user_id, error_reason, detail=None):
    write_op_log(
        success=False,
        operator_user_id=operator_user_id,
        operation=operation,
        target_type=target_type,
        target_id=target_id,
        detail=detail or {},
        error_reason=error_reason,
    )


def _machine_id_or_none(value: Any) -> int | None:
    if value in ("", None):
        return None
    try:
        return int(value)
    except Exception:
        return None


def _user_id_or_none(value: Any) -> int | None:
    if value in ("", None):
        return None
    try:
        return int(value)
    except Exception:
        return None


def _refresh_disk_async(container_id: int) -> None:
    """异步刷新单个容器磁盘用量。"""

    try:
        du = container_service.get_container_disk_usage(container_id, timeout=20.0)
        if isinstance(du, dict) and du.get("container"):
            from ..repositories import containers_repo as repo

            with session_scope(commit=False) as session:
                c = repo.get_by_id(container_id, session=session)
                if not c:
                    return
                container_pk = c.id
            cd = du["container"]
            overlay = int(cd.get("overlay_rw_bytes") or 0)
            bind = int(cd.get("bind_mount_bytes") or 0)
            total = int(cd.get("total_bytes") or 0)
            # 容器磁盘上限统一以 machine.max_disk_size_gb 现算派生（2026-09-01 决策），
            # 不再落库 disk_limit_bytes 机器级拷贝。
            with session_scope() as session:
                repo.update_container(
                    container_pk,
                    disk_overlay_rw_bytes=overlay,
                    disk_bind_mount_bytes=bind,
                    disk_total_bytes=total,
                    disk_checked_at=datetime.utcnow(),
                    session=session,
                )
    except Exception as e:
        print(f"[ssh-refresh] async disk refresh failed for container {container_id}: {e}")


@router.post("/create_container", response_model=CreateContainerResponse)
def create_container_api(
    request: Request,
    payload: CreateContainerRequest = Body(default_factory=CreateContainerRequest),
    operator_user_id: int = Depends(require_permission("container:create")),
    _res: int = Depends(require_resource("machine", "machine_id")),
):
    """创建容器。

    主体判定在 API 边界：owner 缺失/0/自己 → 自己（一般操作）；
    代建（owner≠自己）须持有 container:manage 且 owner 对该机器有权限。
    """

    data = _payload_data(payload)
    machine_id = int(data.get("machine_id", 0) or 0)
    owner_user_id = int(data.get("owner_user_id") or 0) or operator_user_id
    image_id = int(data.get("image_id") or 0) or None
    if owner_user_id != operator_user_id:
        # 代建门禁（API 边界）：切换主体须 container:manage，且 owner 对该机器有权限
        from ..services.rbac_service import user_has_entity, user_has_resource
        if not user_has_entity(operator_user_id, "container:manage"):
            return _error(
                403,
                "creating container for another user requires container:manage",
                "insufficient_permission",
            )
        if not user_has_resource(owner_user_id, "machine", machine_id):
            return _error(
                403,
                f"owner user {owner_user_id} has no access to machine {machine_id}",
                "machine_permission_denied",
            )

    container_raw = data.get("container") or {}
    if not container_raw:
        container_raw = {
            "GPU_LIST": data.get("GPU_LIST", []),
            "CPU_NUMBER": data.get("CPU_NUMBER", 0),
            "MEMORY": data.get("MEMORY", 0),
            "NAME": data.get("NAME", ""),
            "image": data.get("image", ""),
        }

    public_key = data.get("public_key") or None
    image_build = None
    try:
        if image_id is not None:
            from ..services import image_tasks as image_service
            from ..services.rbac_service import user_has_resource

            if not user_has_resource(operator_user_id, "image", image_id):
                return _error(403, "image access denied", "image_access_denied")
            image_build = image_service.build_image_payload(image_id)
            if image_build is None:
                return _error(404, f"image {image_id} not found", "image_not_found")
            container_raw["image"] = image_build["image_tag"]

        gpu_list = container_raw.get("GPU_LIST") or container_raw.get("gpu_list") or []
        cpu_number = int(container_raw.get("CPU_NUMBER") or container_raw.get("cpu_number") or 0)
        memory = int(container_raw.get("MEMORY") or container_raw.get("memory") or 0)
        shared_memory = int(
            container_raw.get("SHARED_MEM")
            or container_raw.get("shared_memory")
            or container_raw.get("SHARED_MEMORY")
            or 0
        )
        name = container_raw.get("NAME") or container_raw.get("name") or ""
        image = container_raw.get("image") or container_raw.get("IMAGE") or ""
        container_obj = Container_info(
            gpu_list=gpu_list,
            cpu_number=cpu_number,
            memory=memory,
            name=name,
            image=image,
            shared_memory=shared_memory,
        )
    except Exception as e:
        return _error(400, f"Invalid container payload: {e}", "invalid_payload")

    try:
        if not container_service.Create_container(
            owner_user_id=owner_user_id,
            machine_id=machine_id,
            container=container_obj,
            public_key=public_key,
            operator_user_id=operator_user_id,
            image_build=image_build,
        ):
            _log_failure(
                operation=OperationType.CREATE_CONTAINER,
                target_type="container",
                target_id=0,
                operator_user_id=operator_user_id,
                error_reason="create_failed",
                detail={"machine_id": machine_id, "name": name},
            )
            return _error(500, "Failed to create container", "create_failed")
    except IntegrityError as e:
        detail = str(e.orig) if hasattr(e, "orig") else str(e)
        _log_failure(
            operation=OperationType.CREATE_CONTAINER,
            target_type="container",
            target_id=0,
            operator_user_id=operator_user_id,
            error_reason="duplicate_entry",
            detail={"machine_id": machine_id, "name": name},
        )
        return _error(409, f"Duplicate entry: {detail}", "duplicate_entry")
    except container_service.NodeServiceError as e:
        reason = getattr(e, "reason", None)
        _log_failure(
            operation=OperationType.CREATE_CONTAINER,
            target_type="container",
            target_id=0,
            operator_user_id=operator_user_id,
            error_reason=reason,
            detail={"machine_id": machine_id, "name": name},
        )
        return _error(REASON_STATUS_MAP.get(reason, 500), str(e), reason)
    except Exception as e:
        reason = getattr(e, "reason", None) or getattr(e, "error_reason", None)
        _log_failure(
            operation=OperationType.CREATE_CONTAINER,
            target_type="container",
            target_id=0,
            operator_user_id=operator_user_id,
            error_reason=reason or "internal_error",
            detail={"machine_id": machine_id, "name": name},
        )
        return _error(REASON_STATUS_MAP.get(reason, 500), f"Internal error: {e}", reason or "internal_error")

    return {"success": 1, "message": "Create container request sent"}


@router.post("/delete_container", response_model=DeleteContainerResponse)
def delete_container_api(
    request: Request,
    payload: DeleteContainerRequest = Body(default_factory=DeleteContainerRequest),
    operator_user_id: int = Depends(require_permission("container:operation")),
    _res: int = Depends(require_resource("container:admin", "container_id")),
    _machine: int = Depends(require_machine_of_container("container_id")),
):
    """删除容器。"""

    data = _payload_data(payload)
    container_id = int(data.get("container_id", 0) or 0)
    try:
        if not container_service.remove_container(container_id=container_id, operator_user_id=operator_user_id):
            _log_failure(
                operation=OperationType.DELETE_CONTAINER,
                target_type="container",
                target_id=container_id,
                operator_user_id=operator_user_id,
                error_reason="delete_failed",
                detail={"container_id": container_id},
            )
            return _error(500, "Failed to delete container", "delete_failed")
    except container_service.NodeServiceError as e:
        reason = getattr(e, "reason", None)
        _log_failure(
            operation=OperationType.DELETE_CONTAINER,
            target_type="container",
            target_id=container_id,
            operator_user_id=operator_user_id,
            error_reason=reason,
            detail={"container_id": container_id},
        )
        return _error(REASON_STATUS_MAP.get(reason, 500), str(e), reason)
    except Exception as e:
        reason = getattr(e, "reason", None) or getattr(e, "error_reason", None)
        _log_failure(
            operation=OperationType.DELETE_CONTAINER,
            target_type="container",
            target_id=container_id,
            operator_user_id=operator_user_id,
            error_reason=reason or "internal_error",
            detail={"container_id": container_id},
        )
        return _error(REASON_STATUS_MAP.get(reason, 500), f"Internal error: {e}", reason or "internal_error")
    return {"success": 1, "message": "Container deleted successfully"}


@router.post("/set_long_term_container", response_model=SetLongTermContainerResponse)
def set_long_term_container_api(
    request: Request,
    payload: SetLongTermContainerRequest = Body(default_factory=SetLongTermContainerRequest),
    operator_user_id: int = Depends(require_permission("container:operation")),
    _res: int = Depends(require_resource("container:root", "container_id")),
    _machine: int = Depends(require_machine_of_container("container_id")),
):
    """设置长驻容器。"""

    data = _payload_data(payload)
    try:
        container_id = int(data.get("container_id"))
    except Exception:
        return _error(400, "invalid container_id", "invalid_payload")
    is_long_term = parse_bool(data.get("is_long_term"))
    if is_long_term is None:
        return _error(400, "is_long_term must be boolean", "invalid_payload")

    try:
        result = container_service.set_long_term_container(
            container_id=container_id,
            is_long_term=is_long_term,
            operator_user_id=operator_user_id,
        )
    except container_service.NodeServiceError as e:
        reason = getattr(e, "reason", None)
        _log_failure(
            operation=OperationType.SET_LONG_TERM,
            target_type="container",
            target_id=container_id,
            operator_user_id=operator_user_id,
            error_reason=reason,
            detail={"container_id": container_id, "is_long_term": is_long_term},
        )
        return _error(REASON_STATUS_MAP.get(reason, 500), str(e), reason)
    except Exception as e:
        reason = getattr(e, "reason", None) or getattr(e, "error_reason", None)
        _log_failure(
            operation=OperationType.SET_LONG_TERM,
            target_type="container",
            target_id=container_id,
            operator_user_id=operator_user_id,
            error_reason=reason or "internal_error",
            detail={"container_id": container_id, "is_long_term": is_long_term},
        )
        return _error(REASON_STATUS_MAP.get(reason, 500), f"Internal error: {e}", reason or "internal_error")
    return {"success": 1, **result}


@router.post("/start_container", response_model=ContainerOperationResponse)
def start_container_api(
    request: Request,
    payload: ContainerIdRequest = Body(default_factory=ContainerIdRequest),
    operator_user_id: int = Depends(require_permission("container:operation")),
    _res: int = Depends(require_resource("container:admin", "container_id")),
    _machine: int = Depends(require_machine_of_container("container_id")),
):
    """启动容器。"""

    data = _payload_data(payload)
    container_id = int(data.get("container_id", 0) or 0)
    try:
        if not container_service.start_container(container_id=container_id, operator_user_id=operator_user_id):
            _log_failure(
                operation=OperationType.START_CONTAINER,
                target_type="container",
                target_id=container_id,
                operator_user_id=operator_user_id,
                error_reason="start_failed",
                detail={"container_id": container_id},
            )
            return _error(500, "Failed to start container", "start_failed")
    except container_service.NodeServiceError as e:
        reason = getattr(e, "reason", None)
        _log_failure(
            operation=OperationType.START_CONTAINER,
            target_type="container",
            target_id=container_id,
            operator_user_id=operator_user_id,
            error_reason=reason,
            detail={"container_id": container_id},
        )
        return _error(REASON_STATUS_MAP.get(reason, 500), str(e), reason)
    except Exception as e:
        reason = getattr(e, "reason", None) or getattr(e, "error_reason", None)
        _log_failure(
            operation=OperationType.START_CONTAINER,
            target_type="container",
            target_id=container_id,
            operator_user_id=operator_user_id,
            error_reason=reason or "internal_error",
            detail={"container_id": container_id},
        )
        return _error(REASON_STATUS_MAP.get(reason, 500), f"Internal error: {e}", reason or "internal_error")
    return {"success": 1, "message": "Container start request sent"}


@router.post("/stop_container", response_model=ContainerOperationResponse)
def stop_container_api(
    request: Request,
    payload: ContainerIdRequest = Body(default_factory=ContainerIdRequest),
    operator_user_id: int = Depends(require_permission("container:operation")),
    _res: int = Depends(require_resource("container:admin", "container_id")),
    _machine: int = Depends(require_machine_of_container("container_id")),
):
    """停止容器。"""

    data = _payload_data(payload)
    container_id = int(data.get("container_id", 0) or 0)
    try:
        if not container_service.stop_container(container_id=container_id, operator_user_id=operator_user_id):
            _log_failure(
                operation=OperationType.STOP_CONTAINER,
                target_type="container",
                target_id=container_id,
                operator_user_id=operator_user_id,
                error_reason="stop_failed",
                detail={"container_id": container_id},
            )
            return _error(500, "Failed to stop container", "stop_failed")
    except container_service.NodeServiceError as e:
        reason = getattr(e, "reason", None)
        _log_failure(
            operation=OperationType.STOP_CONTAINER,
            target_type="container",
            target_id=container_id,
            operator_user_id=operator_user_id,
            error_reason=reason,
            detail={"container_id": container_id},
        )
        return _error(REASON_STATUS_MAP.get(reason, 500), str(e), reason)
    except Exception as e:
        reason = getattr(e, "reason", None) or getattr(e, "error_reason", None)
        _log_failure(
            operation=OperationType.STOP_CONTAINER,
            target_type="container",
            target_id=container_id,
            operator_user_id=operator_user_id,
            error_reason=reason or "internal_error",
            detail={"container_id": container_id},
        )
        return _error(REASON_STATUS_MAP.get(reason, 500), f"Internal error: {e}", reason or "internal_error")
    return {"success": 1, "message": "Container stop request sent"}


@router.post("/restart_container", response_model=ContainerOperationResponse)
def restart_container_api(
    request: Request,
    payload: ContainerIdRequest = Body(default_factory=ContainerIdRequest),
    operator_user_id: int = Depends(require_permission("container:operation")),
    _res: int = Depends(require_resource("container:admin", "container_id")),
    _machine: int = Depends(require_machine_of_container("container_id")),
):
    """重启容器。"""

    data = _payload_data(payload)
    container_id = int(data.get("container_id", 0) or 0)
    try:
        if not container_service.restart_container(container_id=container_id, operator_user_id=operator_user_id):
            _log_failure(
                operation=OperationType.RESTART_CONTAINER,
                target_type="container",
                target_id=container_id,
                operator_user_id=operator_user_id,
                error_reason="restart_failed",
                detail={"container_id": container_id},
            )
            return _error(500, "Failed to restart container", "restart_failed")
    except container_service.NodeServiceError as e:
        reason = getattr(e, "reason", None)
        _log_failure(
            operation=OperationType.RESTART_CONTAINER,
            target_type="container",
            target_id=container_id,
            operator_user_id=operator_user_id,
            error_reason=reason,
            detail={"container_id": container_id},
        )
        return _error(REASON_STATUS_MAP.get(reason, 500), str(e), reason)
    except Exception as e:
        reason = getattr(e, "reason", None) or getattr(e, "error_reason", None)
        _log_failure(
            operation=OperationType.RESTART_CONTAINER,
            target_type="container",
            target_id=container_id,
            operator_user_id=operator_user_id,
            error_reason=reason or "internal_error",
            detail={"container_id": container_id},
        )
        return _error(REASON_STATUS_MAP.get(reason, 500), f"Internal error: {e}", reason or "internal_error")
    return {"success": 1, "message": "Container restart request sent"}


@router.post("/add_collaborator", response_model=ContainerOperationResponse, status_code=201)
def add_collaborator_api(
    request: Request,
    payload: CollaboratorRequest = Body(default_factory=CollaboratorRequest),
    operator_user_id: int = Depends(require_permission("container:operation")),
    _res: int = Depends(require_resource("container:root", "container_id")),
    _machine: int = Depends(require_machine_of_container("container_id")),
):
    """添加协作者。"""

    data = _payload_data(payload)
    user_id = data.get("user_id", "")
    container_id = int(data.get("container_id", 0) or 0)
    role = data.get("role", "COLLABORATOR")
    try:
        if not container_service.add_collaborator(
            container_id=container_id,
            user_id=user_id,
            role=ROLE(role),
            operator_user_id=operator_user_id,
        ):
            return _error(500, "Failed to add collaborator", "add_collaborator_failed")
    except container_service.NodeServiceError as e:
        reason = getattr(e, "reason", None)
        if reason == "container_offline":
            return _error(400, str(e), reason)
        return _error(REASON_STATUS_MAP.get(reason, 500), str(e), reason)
    except Exception as e:
        return _error(500, f"Internal error: {e}", "internal_error")
    return {"success": 1, "message": "Collaborator added successfully"}


@router.post("/remove_collaborator", response_model=ContainerOperationResponse)
def remove_collaborator_api(
    request: Request,
    payload: CollaboratorRequest = Body(default_factory=CollaboratorRequest),
    operator_user_id: int = Depends(require_permission("container:operation")),
    _res: int = Depends(require_resource("container:root", "container_id")),
    _machine: int = Depends(require_machine_of_container("container_id")),
):
    """移除协作者。"""

    data = _payload_data(payload)
    container_id = int(data.get("container_id", 0) or 0)
    user_id = data.get("user_id", "")
    try:
        if not container_service.remove_collaborator(
            container_id=container_id,
            user_id=user_id,
            operator_user_id=operator_user_id,
        ):
            return _error(500, "Failed to remove collaborator", "remove_collaborator_failed")
    except container_service.NodeServiceError as e:
        reason = getattr(e, "reason", None)
        if reason == "container_offline":
            return _error(400, str(e), reason)
        return _error(REASON_STATUS_MAP.get(reason, 500), str(e), reason)
    except Exception as e:
        return _error(500, f"Internal error: {e}", "internal_error")
    return {"success": 1, "message": "Collaborator removed successfully"}


@router.post("/update_role", response_model=ContainerOperationResponse)
def update_role_api(
    request: Request,
    payload: UpdateRoleRequest = Body(default_factory=UpdateRoleRequest),
    operator_user_id: int = Depends(require_permission("container:operation")),
    _res: int = Depends(require_resource("container:root", "container_id")),
    _machine: int = Depends(require_machine_of_container("container_id")),
):
    """更新协作者角色。"""

    data = _payload_data(payload)
    container_id = int(data.get("container_id", 0) or 0)
    user_id = data.get("user_id", "")
    updated_role = data.get("updated_role", "COLLABORATOR")
    try:
        if not container_service.update_role(
            container_id=container_id,
            user_id=user_id,
            updated_role=ROLE(updated_role),
            operator_user_id=operator_user_id,
        ):
            return _error(500, "Failed to update role", "update_role_failed")
    except container_service.NodeServiceError as e:
        reason = getattr(e, "reason", None)
        if reason == "container_offline":
            return _error(400, str(e), reason)
        return _error(REASON_STATUS_MAP.get(reason, 500), str(e), reason)
    except Exception as e:
        return _error(500, f"Internal error: {e}", "internal_error")
    return {"success": 1, "message": "Role updated successfully"}


@router.post("/unpause_container", response_model=ContainerOperationResponse)
def unpause_container_api(
    request: Request,
    payload: ContainerIdRequest = Body(default_factory=ContainerIdRequest),
    operator_user_id: int = Depends(require_permission("container:manage")),
    _machine: int = Depends(require_machine_of_container("container_id")),
):
    """恢复暂停容器（manage）。"""

    data = _payload_data(payload)
    container_id = int(data.get("container_id", 0) or 0)
    try:
        if container_service.unpause_container(container_id=container_id, operator_user_id=operator_user_id):
            return {"success": 1, "message": "Container unpaused"}
        return _error(500, "Failed to unpause container", "unpause_failed")
    except container_service.NodeServiceError as e:
        reason = getattr(e, "reason", None)
        return _error(REASON_STATUS_MAP.get(reason, 500), str(e), reason)
    except Exception as e:
        return _error(500, f"Internal error: {e}", "internal_error")


@router.post("/get_container_detail_information", response_model=ContainerDetailResponse)
def get_container_detail_information_api(
    request: Request,
    payload: ContainerIdRequest = Body(default_factory=ContainerIdRequest),
    operator_user_id: int = Depends(require_permission("container:view")),
    _res: int = Depends(require_resource("container:collaborator", "container_id")),
    _machine: int = Depends(require_machine_of_container("container_id")),
):
    """查询容器详情。"""

    data = _payload_data(payload)
    container_id = int(data.get("container_id", 0) or 0)
    try:
        container_info = container_service.get_container_detail_information(container_id=container_id)
    except ValueError:
        return _error(404, "Container not found", "container_not_found")
    return {"success": 1, "container_info": _dump_model(container_info)}


@router.post("/container_status", response_model=ContainerStatusResponse)
def container_status_api(
    request: Request,
    payload: ContainerStatusRequest = Body(default_factory=ContainerStatusRequest),
    operator_user_id: int = Depends(require_permission("container:view")),
    _res: int = Depends(require_resource("container:collaborator", "container_id")),
    _machine: int = Depends(require_machine_of_container("container_id")),
):
    """查询容器状态（与其他 getter 同构：view + 容器角色 + 机器）。

    查询与鉴权统一以 container_id 为键（前端心跳本就传该字段）；name+machine
    不再作为查询载体，杜绝「用自己可访问的 container_id 过资源检查、再按任意
    name+machine 探测他人容器状态」的错位。
    """

    data = _payload_data(payload)
    container_id = _machine_id_or_none(data.get("container_id"))
    if container_id is None:
        return {"container_status": None}
    try:
        with session_scope(commit=False) as session:
            container = containers_repo.get_by_id(container_id, session=session)
            if not container:
                return {"container_status": None}
            from ..services.container_module.node_comms import get_cached_container_runtime_metrics
            return {
                "container_status": container.container_status.value,
                "failed_reason": getattr(container, "failed_reason", None),
                "failed_detail": getattr(container, "failed_detail", None),
                "runtime_metrics": get_cached_container_runtime_metrics(container.machine_id, container.name),
            }
    except Exception as e:
        return _error(500, str(e), "internal_error")


@router.post("/get_container_operation_logs")
def get_container_operation_logs_api(
    request: Request,
    payload: ContainerIdRequest = Body(default_factory=ContainerIdRequest),
    operator_user_id: int = Depends(require_permission("container:view")),
    _res: int = Depends(require_resource("container:collaborator", "container_id")),
    _machine: int = Depends(require_machine_of_container("container_id")),
):
    """该容器的操作历史（能看容器的即可看其事件；operator 全量仍走 /admin/operation_logs）。"""

    from ..repositories import operation_log_repo
    from ..repositories import user_repo

    data = _payload_data(payload)
    container_id = int(data.get("container_id", 0) or 0)
    try:
        with session_scope(commit=False) as session:
            container = containers_repo.get_by_id(container_id, session=session)
            # 容器 id 复用区分（2026-09）：SQLite 删除后 id 可复用，op log 不级联删除，
            # 旧容器日志早于当前容器 created_at——按时间锚过滤，新容器只看自己的历史。
            # created_at 为 NULL 的旧容器（未回填）不过滤，回退旧行为。
            created_after = container.created_at.isoformat() if (container and container.created_at) else None
            rows, _ = operation_log_repo.list_logs(
                session=session,
                page=1,
                page_size=50,
                target_type="container",
                target_id=container_id,
                start=created_after,
            )
            logs = []
            for row in rows:
                item = operation_log_repo.serialize(row)
                username = None
                if item.get("operator_user_id") is not None:
                    username = user_repo.get_name_by_id(item["operator_user_id"], session=session)
                item["operator_username"] = username
                logs.append(item)
    except Exception as e:
        return _error(500, f"failed to list container operation logs: {e}", "internal_error")
    return {"success": 1, "logs": logs}


@router.post("/refresh_last_ssh_login_time", response_model=RefreshLastSshLoginTimeResponse)
def refresh_last_ssh_login_time_api(
    request: Request,
    payload: RefreshLastSshLoginTimeRequest = Body(default_factory=RefreshLastSshLoginTimeRequest),
    operator_user_id: int = Depends(require_permission("container:view")),
    _res: int = Depends(require_resource("container:collaborator", "container_id")),
    _machine: int = Depends(require_machine_of_container("container_id")),
):
    """刷新容器最近 SSH 登录时间。"""

    data = _payload_data(payload)
    container_id = _machine_id_or_none(data.get("container_id", 0))
    if container_id is None:
        return _error(400, "invalid container_id", "invalid_payload")

    with session_scope(commit=False) as session:
        container = containers_repo.get_by_id(container_id, session=session)
    if not container:
        return _error(404, "Container not found", "container_not_found")
    try:
        last_time = container_service.get_container_last_ssh_login_time(container.id)
        cleanup_days = int(getattr(AppConfig, "CONTAINER_CLEANUP_AFTER_DAYS", 7) or 7)
        cleanup_info = container_service.build_cleanup_info(last_time, cleanup_days)
        threading.Thread(
            target=_refresh_disk_async,
            args=(container.id,),
            daemon=True,
        ).start()
    except container_service.NodeServiceError as e:
        reason = getattr(e, "reason", None)
        return _error(REASON_STATUS_MAP.get(reason, 500), str(e), reason)
    except Exception as e:
        reason = getattr(e, "reason", None) or getattr(e, "error_reason", None)
        return _error(REASON_STATUS_MAP.get(reason, 500), f"Internal error: {e}", reason or "internal_error")

    return {
        "success": 1,
        "container_id": container.id,
        "container_name": container.name,
        "last_ssh_login_time": last_time,
        "cleanup_after_days": cleanup_info.get("cleanup_after_days"),
        "cleanup_at": cleanup_info.get("cleanup_at"),
        "seconds_until_cleanup": cleanup_info.get("seconds_until_cleanup"),
        "cleanup_status": cleanup_info.get("cleanup_status"),
    }


@router.post("/list_all_container_bref_information", response_model=ListAllContainerBrefInformationResponse)
def list_all_containers_bref_information_api(
    request: Request,
    payload: ListAllContainerBrefInformationRequest = Body(default_factory=ListAllContainerBrefInformationRequest),
    request_user_id: int = Depends(require_permission("container:view")),
):
    """分页查询容器摘要。"""

    data = _payload_data(payload)
    machine_id = _machine_id_or_none(data.get("machine_id", ""))
    user_id = _user_id_or_none(data.get("user_id", ""))
    container_search = str(data.get("container_search") or "").strip() or None
    page_number = int(data.get("page_number", 0) or 0)
    page_size = int(data.get("page_size", 10) or 10)

    try:
        result = container_service.list_all_container_bref_information(
            machine_id=machine_id,
            request_user_id=request_user_id,
            page_number=page_number,
            page_size=page_size,
            user_id=user_id,
            container_search=container_search,
            viewer_user_id=request_user_id,
        )
        containers_info = result.get("containers", [])
        total_page = result.get("total_page", 1)
        total_number = result.get("total_number", len(containers_info))
        long_term_container_remaining = result.get("long_term_container_remaining")
        long_term_container_limit = result.get("long_term_container_limit")
    except Exception as e:
        reason = getattr(e, "reason", None) or getattr(e, "error_reason", None) or "list_failed"
        return _error(REASON_STATUS_MAP.get(reason, 500), f"Failed to list containers: {e}", reason)

    out = [_dump_model(c) for c in containers_info]
    payload_out: dict[str, Any] = {
        "success": 1,
        "containers_info": out,
        "total_page": total_page,
        "total_number": total_number,
    }
    if user_id is not None:
        payload_out["long_term_container_remaining"] = long_term_container_remaining
        payload_out["long_term_container_limit"] = long_term_container_limit
    return payload_out
