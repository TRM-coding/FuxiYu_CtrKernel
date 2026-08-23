from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from ..constant import OperationType
from ..schemas.machine import (
    AddMachinePermissionRequest,
    AddMachinePermissionResponse,
    AddMachineRequest,
    AddMachineResponse,
    ListMachineBriefRequest,
    ListMachineBriefResponse,
    ListMachinePermissionsResponse,
    MachineDetailResponse,
    MachineIdRequest,
    RegisterMachineByTrustAnchorRequest,
    RegisterMachineWithProfileResponse,
    RemoveMachineRequest,
    RemoveMachineResponse,
    SetMachineMaintenanceRequest,
    SetMachineMaintenanceResponse,
    UpdateMachineRequest,
    UpdateMachineResponse,
)
from ..services import machine_tasks as machine_service
from ..services.container_module import node_comms
from ..services.operation_log_tasks import write_operation_log as write_op_log
from .deps import require_current_user, require_operator, require_permission, require_resource

router = APIRouter(prefix="/machines", tags=["machines"])


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
    """返回 Ctrl 现有错误结构。"""

    payload: dict[str, Any] = {"success": 0, "message": message}
    if error_reason is not None:
        payload["error_reason"] = error_reason
    return JSONResponse(status_code=status_code, content=payload)


#####################
# 添加机器


@router.post("/add_machine", response_model=AddMachineResponse, status_code=201)
def add_machine_api(
    message: AddMachineRequest,
    operator_user_id: int = Depends(require_permission("machine:manage")),
):
    """人工添加机器；后续主建档入口会收敛到 register_machine。"""

    data = _model_data(message)
    try:
        success = machine_service.Add_machine(
            machine_name=data.get("machine_name", ""),
            machine_ip=data.get("machine_ip", ""),
            machine_type=data.get("machine_type", ""),
            machine_description=data.get("machine_description", ""),
            cpu_core_number=data.get("cpu_core_number", 0),
            gpu_number=data.get("gpu_number", 0),
            gpu_type=data.get("gpu_type", ""),
            memory_size=data.get("memory_size", 0),
            max_shared_gb=data.get("max_shared_gb", 2),
            disk_size=data.get("disk_size", 0),
            max_memory_gb=data.get("max_memory_gb", 0),
            max_gpu_number=data.get("max_gpu_number", 0),
            max_cpu_core_number=data.get("max_cpu_core_number", 0),
            operator_user_id=operator_user_id,
        )
    except IntegrityError as e:
        detail = str(e.orig) if hasattr(e, "orig") else str(e)
        return _error(409, f"Duplicate entry: {detail}", "duplicate_entry")
    except Exception as e:
        err_reason = getattr(e, "error_reason", None)
        if err_reason:
            return _error(422, str(e), err_reason)
        return _error(500, f"Internal error: {e}", "internal_error")

    if success:
        return {"success": 1, "message": "Machine created successfully"}
    return _error(500, "Failed to create machine", "create_failed")


#####################
# 注册机器


@router.post("/register_machine", response_model=RegisterMachineWithProfileResponse)
def register_machine_api(
    message: RegisterMachineByTrustAnchorRequest,
    _register: int = Depends(require_permission("machine:register")),
    operator_user_id: int = Depends(require_permission("machine:manage")),
):
    """TOFU 建档入口：首连 pin、下发 UID、采集硬件并创建机器记录。"""

    detail = {"name": message.machine_name, "ip": message.machine_ip, "trigger": "tofu_register"}
    try:
        result = node_comms.register_machine(
            message.machine_name,
            message.machine_ip,
            message.machine_description,
        )
    except Exception as e:
        err_reason = getattr(e, "error_reason", None)
        write_op_log(
            success=False,
            operator_user_id=operator_user_id,
            operation=OperationType.ADD_MACHINE,
            target_type="machine",
            target_id=0,
            detail=detail,
            error_reason=err_reason or str(e),
        )
        if err_reason:
            return _error(422, str(e), err_reason)
        return _error(500, f"Internal error: {e}", "internal_error")

    write_op_log(
        success=True,
        operator_user_id=operator_user_id,
        operation=OperationType.ADD_MACHINE,
        target_type="machine",
        target_id=result["machine_id"],
        detail={**detail, "uid": result["uid"]},
    )
    return {
        "success": 1,
        "message": "Machine enrolled successfully",
        "uid": result["uid"],
        "certificate_fingerprint": result["certificate_fingerprint"],
        "machine_id": result["machine_id"],
        "hardware": result.get("hardware"),
    }


#####################
# 删除机器


@router.post("/remove_machine", response_model=RemoveMachineResponse)
def remove_machine_api(
    message: RemoveMachineRequest,
    operator_user_id: int = Depends(require_permission("machine:manage")),
):
    """删除一组机器记录。"""

    success = machine_service.Remove_machine(
        machine_id=message.machine_ids,
        operator_user_id=operator_user_id,
    )
    if success:
        return {"success": 1, "message": "Machine(s) removed successfully"}
    return _error(500, "Failed to remove machine(s)", "remove_failed")


#####################
# 更新机器


@router.post("/update_machine", response_model=UpdateMachineResponse)
def update_machine_api(
    message: UpdateMachineRequest,
    operator_user_id: int = Depends(require_permission("machine:manage")),
):
    """更新机器管理字段或资源分配限制。"""

    fields = _model_data(message.fields, exclude_none=True)
    try:
        success = machine_service.Update_machine(
            machine_id=message.machine_id,
            operator_user_id=operator_user_id,
            **fields,
        )
    except Exception as e:
        err_reason = getattr(e, "error_reason", None)
        if err_reason:
            return _error(422, str(e), err_reason)
        return _error(500, f"Internal error: {e}", "internal_error")

    if success:
        return {"success": 1, "message": "Machine updated successfully"}
    return _error(500, "Failed to update machine", "update_failed")


#####################
# 设置机器维护开关


@router.post("/set_maintenance", response_model=SetMachineMaintenanceResponse)
def set_machine_maintenance_api(
    message: SetMachineMaintenanceRequest,
    operator_user_id: int = Depends(require_permission("machine:manage")),
):
    """独立切换维护模式；不改写真实在线/离线状态。"""

    try:
        success = machine_service.Set_maintenance(
            machine_id=message.machine_id,
            is_maintenance=message.is_maintenance,
            operator_user_id=operator_user_id,
        )
    except Exception as e:
        err_reason = getattr(e, "error_reason", None)
        if err_reason:
            return _error(422, str(e), err_reason)
        return _error(500, f"Internal error: {e}", "internal_error")

    if success:
        return {"success": 1, "message": "Machine maintenance updated successfully"}
    return _error(404, "Machine not found", "machine_not_found")


#####################
# 查询机器详情


@router.post("/get_detail_information", response_model=MachineDetailResponse)
def get_detail_information_api(
    message: MachineIdRequest,
    _: int = Depends(require_permission("machine:view")),
    __: int = Depends(require_resource("machine", "machine_id")),
):
    """查询机器详情（view 权限 AND 机器资源访问权）。"""

    machine_info = machine_service.Get_detail_information(machine_id=message.machine_id)
    if not machine_info:
        return _error(404, "Machine not found", "machine_not_found")
    return _model_data(machine_info)


#####################
# 查询机器概要列表


@router.post("/list_all_machine_bref_information", response_model=ListMachineBriefResponse)
def list_all_machine_bref_information_api(
    message: ListMachineBriefRequest,
    user_id: int = Depends(require_permission("machine:view")),
):
    """分页查询机器概要。"""

    machines_info, total_pages = machine_service.List_all_machine_bref_information(
        page_number=message.page_number,
        page_size=message.page_size,
        user_id=user_id,
        machine_search=(message.machine_search or "").strip() or None,
    )
    machines = []
    for machine in machines_info:
        machine_type = machine.machine_type.value if hasattr(machine.machine_type, "value") else machine.machine_type
        machine_status = machine.machine_status.value if hasattr(machine.machine_status, "value") else machine.machine_status
        machines.append(
            {
                "machine_id": getattr(machine, "id", None),
                "machine_name": machine.machine_name,
                "machine_ip": machine.machine_ip,
                "machine_type": machine_type,
                "machine_status": machine_status,
                "is_maintenance": bool(getattr(machine, "is_maintenance", False)),
                "display_status": getattr(machine, "display_status", machine_status),
            }
        )
    return {"machines": machines, "total_pages": total_pages}


#####################
# 添加机器权限


@router.post("/add_machine_permission", response_model=AddMachinePermissionResponse)
def add_machine_permission_api(
    message: AddMachinePermissionRequest,
    operator_user_id: int = Depends(require_permission("machine:manage")),
):
    """给用户添加机器权限。"""

    try:
        machine_service.Add_machine_permission(
            message.machine_id,
            message.user_id,
            operator_user_id=operator_user_id,
        )
    except ValueError as e:
        reason = str(e)
        status = 404 if reason in ("machine_not_found", "user_not_found") else 400
        return _error(status, reason, reason)
    return {"success": 1, "message": "machine permission added"}


#####################
# 查询机器权限


@router.get("/list_machine_permissions", response_model=ListMachinePermissionsResponse)
def list_machine_permissions_api(
    machine_id: int = Query(..., ge=1),
    _: int = Depends(require_permission("machine:manage")),
):
    """查询机器授权用户 id 列表（管理面信息）。"""

    user_ids = machine_service.List_machine_permissions(machine_id)
    return {"success": 1, "machine_id": machine_id, "user_ids": user_ids}
