import logging
from sqlalchemy.exc import IntegrityError
from flask import jsonify, request
from flask import current_app
from . import api_bp
from ..services import container_tasks as container_service
from ..utils.Container import Container_info
from ..constant import ROLE, OperationType
from ..services.operation_log_tasks import write_operation_log as write_op_log
from ..utils.parsers import parse_bool
from ..repositories import containers_repo, authentications_repo, user_repo
from ..schemas.user_schema import user_schema, users_schema

logger = logging.getLogger(__name__)

# map known error_reason strings to HTTP status codes so we can surface them to clients
REASON_STATUS_MAP = {
    'container_exists': 409,
    'invalid_payload': 400,
    'invalid_signature': 401,
    'invalid_json': 400,
    'invalid_config': 400,
    'docker_init_failed': 502,
    'docker_check_failed': 502,
    'unexpected_response': 502,
    'not_found': 404,
    'duplicate_entry': 409,
    'create_failed': 500,
    'delete_failed': 500,
    'start_failed': 500,
    'stop_failed': 500,
    'restart_failed': 500,
    'container_offline': 400,
    'node_endpoint_not_found': 502,
    'container_not_found': 404,
    'machine_permission_denied': 403,
    'container_permission_denied': 403,
    'long_term_limit_reached': 409,
}


def _log_failure(*, operation, target_type, target_id, operator_user_id, error_reason, detail=None):
    """蓝图层失败补记：task 层直接上抛/返回 False 的失败在这里统一记一条。

    .log 与 op-log 同源：error 级落日志文件，success=False 落操作日志表。
    """
    logger.error("operation failed: op=%s target=%s/%s user=%s reason=%s detail=%s",
                 getattr(operation, 'value', operation), target_type, target_id,
                 operator_user_id, error_reason, detail or {})
    write_op_log(success=False, operator_user_id=operator_user_id, operation=operation,
                 target_type=target_type, target_id=target_id,
                 detail=detail or {}, error_reason=error_reason)


@api_bp.post("/containers/create_container")
def create_container_api():
    '''
    通信数据格式：
    发送格式：
    {
        "user_name",
        "machine_id",
        "container":{
            "GPU_LIST":list[int],
            "CPU_NUMBER":int,
            "MEMORY":int,
            "NAME":str,
            "image":str
        },
        "public_key"
    }
    返回格式：
    {
        "success": [0|1],
        "message": "xxxx",
        ["error_reason": "xxxx"]
    }
    '''
    token = request.cookies.get("auth_token", "")
    if (not authentications_repo.is_token_valid(token)):
        return jsonify({"success": 0, "message": "invalid or missing token", "error_reason": "invalid_token"}), 401
    data = request.get_json() or {}
    owner_name = data.get("user_name", "")
    machine_id = data.get("machine_id", 0)
    operator_user_id = authentications_repo.get_user_id_by_token(token)

    # 似乎是一些结构问题
    container_raw = data.get("container") or {}
    # fallback to top-level keys for backward compatibility
    if not container_raw:
        container_raw = {
            "GPU_LIST": data.get("GPU_LIST", []),
            "CPU_NUMBER": data.get("CPU_NUMBER", 0),
            "MEMORY": data.get("MEMORY", 0),
            "NAME": data.get("NAME", ""),
            "image": data.get("image", ""),
        }

    public_key = data.get("public_key", None)
    if public_key == '':  # treat empty string as None
        public_key = None
    # 这里纯粹只是为了增加报错信息的友好性
    try:
        gpu_list = container_raw.get("GPU_LIST") or container_raw.get("gpu_list") or []
        cpu_number = int(container_raw.get("CPU_NUMBER") or container_raw.get("cpu_number") or 0)
        memory = int(container_raw.get("MEMORY") or container_raw.get("memory") or 0)
        # support shared memory in GB: accept only SHARED_MEM/shared_memory/SHARED_MEMORY
        shared_memory = int(container_raw.get("SHARED_MEM") or container_raw.get("shared_memory") or container_raw.get("SHARED_MEMORY") or 0)
        name = container_raw.get("NAME") or container_raw.get("name") or ""
        image = container_raw.get("image") or container_raw.get("IMAGE") or ""

        # construct Container_info instance expected by service layer
        container_obj = Container_info(gpu_list=gpu_list, cpu_number=cpu_number, memory=memory, name=name, image=image, shared_memory=shared_memory)

    except Exception as e:
        return jsonify({"success": 0, "message": f"Invalid container payload: {str(e)}", "error_reason": "invalid_payload"}), 400
    try:
        if not container_service.Create_container(owner_name=owner_name,
                        machine_id=machine_id,
                        container=container_obj,
                        public_key=public_key,
                        operator_user_id=operator_user_id):
            _log_failure(operation=OperationType.CREATE_CONTAINER, target_type="container", target_id=0,
                         operator_user_id=operator_user_id, error_reason="create_failed",
                         detail={"machine_id": machine_id, "name": name})
            return jsonify({"success": 0, "message": "Failed to create container", "error_reason": "create_failed"}), 500
    except IntegrityError as e:
        _log_failure(operation=OperationType.CREATE_CONTAINER, target_type="container", target_id=0,
                     operator_user_id=operator_user_id, error_reason="duplicate_entry",
                     detail={"machine_id": machine_id, "name": name})
        return jsonify({"success": 0, "message": f"Duplicate entry: {str(e.orig) if hasattr(e, 'orig') else str(e)}", "error_reason": "duplicate_entry"}), 409
    except container_service.NodeServiceError as e:
        _log_failure(operation=OperationType.CREATE_CONTAINER, target_type="container", target_id=0,
                     operator_user_id=operator_user_id, error_reason=getattr(e, 'reason', None),
                     detail={"machine_id": machine_id, "name": name})
        status = REASON_STATUS_MAP.get(getattr(e, 'reason', None), 500)
        return jsonify({"success": 0, "message": str(e), "error_reason": getattr(e, 'reason', None)}), status
    except Exception as e:
        # try to preserve any error_reason set on lower-level exceptions
        reason = getattr(e, 'reason', None) or getattr(e, 'error_reason', None)
        status = REASON_STATUS_MAP.get(reason, 500)
        payload = {"success": 0, "message": f"Internal error: {str(e)}"}
        if reason:
            payload['error_reason'] = reason
        _log_failure(operation=OperationType.CREATE_CONTAINER, target_type="container", target_id=0,
                     operator_user_id=operator_user_id, error_reason=reason or "internal_error",
                     detail={"machine_id": machine_id, "name": name})
        return jsonify(payload), status
    return jsonify({"success": 1, "message": "Create container request sent"}), 200
    
    
@api_bp.post("/containers/delete_container")
def delete_container_api():
    '''
    通信数据格式：
    发送格式：
    {
        "container_id"
    }
    返回格式：
    {
        "success": [0|1],
        "message": "xxxx",
        ["error_reason": "xxxx"]
    }
    '''
    token = request.cookies.get("auth_token", "")
    if (not authentications_repo.is_token_valid(token)):
        return jsonify({"success": 0, "message": "invalid or missing token", "error_reason": "invalid_token"}), 401
    data = request.get_json() or {}
    container_id = data.get("container_id", 0)
    request_user_id = authentications_repo.get_user_id_by_token(token)
    try:
        if not container_service.remove_container(container_id=container_id, operator_user_id=request_user_id):
            _log_failure(operation=OperationType.DELETE_CONTAINER, target_type="container", target_id=container_id,
                         operator_user_id=request_user_id, error_reason="delete_failed",
                         detail={"container_id": container_id})
            return jsonify({"success": 0, "message": "Failed to delete container", "error_reason": "delete_failed"}), 500
    except container_service.NodeServiceError as e:
        # prefer remote's reason when available
        _log_failure(operation=OperationType.DELETE_CONTAINER, target_type="container", target_id=container_id,
                     operator_user_id=request_user_id, error_reason=getattr(e, 'reason', None),
                     detail={"container_id": container_id})
        status = 404 if getattr(e, 'reason', None) == 'not_found' else 500
        return jsonify({"success": 0, "message": str(e), "error_reason": getattr(e, 'reason', None)}), status
    except Exception as e:
        reason = getattr(e, 'reason', None) or getattr(e, 'error_reason', None)
        status = REASON_STATUS_MAP.get(reason, 500)
        payload = {"success": 0, "message": f"Internal error: {str(e)}"}
        if reason:
            payload['error_reason'] = reason
        _log_failure(operation=OperationType.DELETE_CONTAINER, target_type="container", target_id=container_id,
                     operator_user_id=request_user_id, error_reason=reason or "internal_error",
                     detail={"container_id": container_id})
        return jsonify(payload), status
    return jsonify({"success": 1, "message": "Container deleted successfully"}), 200


@api_bp.post("/containers/set_long_term_container")
def set_long_term_container_api():
    token = request.cookies.get("auth_token", "")
    if not authentications_repo.is_token_valid(token):
        return jsonify({"success": 0, "message": "invalid or missing token", "error_reason": "invalid_token"}), 401

    data = request.get_json() or {}
    if "container_id" not in data or "is_long_term" not in data:
        return jsonify({"success": 0, "message": "missing container_id or is_long_term", "error_reason": "invalid_payload"}), 400
    try:
        container_id = int(data.get("container_id"))
    except Exception:
        return jsonify({"success": 0, "message": "invalid container_id", "error_reason": "invalid_payload"}), 400
    is_long_term = parse_bool(data.get("is_long_term"))
    if is_long_term is None:
        return jsonify({"success": 0, "message": "is_long_term must be boolean", "error_reason": "invalid_payload"}), 400

    request_user_id = authentications_repo.get_user_id_by_token(token)
    try:
        result = container_service.set_long_term_container(
            container_id=container_id,
            is_long_term=is_long_term,
            operator_user_id=request_user_id,
        )
    except container_service.NodeServiceError as e:
        reason = getattr(e, "reason", None)
        status = REASON_STATUS_MAP.get(reason, 500)
        _log_failure(operation=OperationType.SET_LONG_TERM, target_type="container", target_id=container_id,
                     operator_user_id=request_user_id, error_reason=reason,
                     detail={"container_id": container_id, "is_long_term": is_long_term})
        return jsonify({"success": 0, "message": str(e), "error_reason": reason}), status
    except Exception as e:
        reason = getattr(e, "reason", None) or getattr(e, "error_reason", None)
        status = REASON_STATUS_MAP.get(reason, 500)
        payload = {"success": 0, "message": f"Internal error: {str(e)}"}
        if reason:
            payload["error_reason"] = reason
        _log_failure(operation=OperationType.SET_LONG_TERM, target_type="container", target_id=container_id,
                     operator_user_id=request_user_id, error_reason=reason or "internal_error",
                     detail={"container_id": container_id, "is_long_term": is_long_term})
        return jsonify(payload), status

    return jsonify({"success": 1, **result}), 200


@api_bp.post("/containers/start_container")
def start_container_api():
    '''
    请求格式：
    {"container_id" }
    '''
    token = request.cookies.get("auth_token", "")
    if (not authentications_repo.is_token_valid(token)):
        return jsonify({"success": 0, "message": "invalid or missing token", "error_reason": "invalid_token"}), 401
    data = request.get_json() or {}
    container_id = data.get("container_id", 0)
    request_user_id = authentications_repo.get_user_id_by_token(token)
    try:
        if not container_service.start_container(container_id=container_id, operator_user_id=request_user_id):
            _log_failure(operation=OperationType.START_CONTAINER, target_type="container", target_id=container_id,
                         operator_user_id=request_user_id, error_reason="start_failed",
                         detail={"container_id": container_id})
            return jsonify({"success": 0, "message": "Failed to start container", "error_reason": "start_failed"}), 500
    except container_service.NodeServiceError as e:
        # propagate known node errors
        _log_failure(operation=OperationType.START_CONTAINER, target_type="container", target_id=container_id,
                     operator_user_id=request_user_id, error_reason=getattr(e, 'reason', None),
                     detail={"container_id": container_id})
        return jsonify({"success": 0, "message": str(e), "error_reason": getattr(e, 'reason', None)}), 500
    except Exception as e:
        reason = getattr(e, 'reason', None) or getattr(e, 'error_reason', None)
        status = REASON_STATUS_MAP.get(reason, 500)
        payload = {"success": 0, "message": f"Internal error: {str(e)}"}
        if reason:
            payload['error_reason'] = reason
        _log_failure(operation=OperationType.START_CONTAINER, target_type="container", target_id=container_id,
                     operator_user_id=request_user_id, error_reason=reason or "internal_error",
                     detail={"container_id": container_id})
        return jsonify(payload), status
    return jsonify({"success": 1, "message": "Container start request sent"}), 200


@api_bp.post("/containers/stop_container")
def stop_container_api():
    '''
    请求格式：
    { "container_id" }
    '''
    token = request.cookies.get("auth_token", "")
    if (not authentications_repo.is_token_valid(token)):
        return jsonify({"success": 0, "message": "invalid or missing token", "error_reason": "invalid_token"}), 401
    data = request.get_json() or {}
    container_id = data.get("container_id", 0)
    request_user_id = authentications_repo.get_user_id_by_token(token)
    try:
        if not container_service.stop_container(container_id=container_id, operator_user_id=request_user_id):
            _log_failure(operation=OperationType.STOP_CONTAINER, target_type="container", target_id=container_id,
                         operator_user_id=request_user_id, error_reason="stop_failed",
                         detail={"container_id": container_id})
            return jsonify({"success": 0, "message": "Failed to stop container", "error_reason": "stop_failed"}), 500
    except container_service.NodeServiceError as e:
        _log_failure(operation=OperationType.STOP_CONTAINER, target_type="container", target_id=container_id,
                     operator_user_id=request_user_id, error_reason=getattr(e, 'reason', None),
                     detail={"container_id": container_id})
        return jsonify({"success": 0, "message": str(e), "error_reason": getattr(e, 'reason', None)}), 500
    except Exception as e:
        reason = getattr(e, 'reason', None) or getattr(e, 'error_reason', None)
        status = REASON_STATUS_MAP.get(reason, 500)
        payload = {"success": 0, "message": f"Internal error: {str(e)}"}
        if reason:
            payload['error_reason'] = reason
        _log_failure(operation=OperationType.STOP_CONTAINER, target_type="container", target_id=container_id,
                     operator_user_id=request_user_id, error_reason=reason or "internal_error",
                     detail={"container_id": container_id})
        return jsonify(payload), status
    return jsonify({"success": 1, "message": "Container stop request sent"}), 200


@api_bp.post("/containers/restart_container")
def restart_container_api():
    '''
    请求格式：
    { "container_id" }
    '''
    token = request.cookies.get("auth_token", "")
    if (not authentications_repo.is_token_valid(token)):
        return jsonify({"success": 0, "message": "invalid or missing token", "error_reason": "invalid_token"}), 401
    data = request.get_json() or {}
    container_id = data.get("container_id", 0)
    request_user_id = authentications_repo.get_user_id_by_token(token)
    try:
        if not container_service.restart_container(container_id=container_id, operator_user_id=request_user_id):
            _log_failure(operation=OperationType.RESTART_CONTAINER, target_type="container", target_id=container_id,
                         operator_user_id=request_user_id, error_reason="restart_failed",
                         detail={"container_id": container_id})
            return jsonify({"success": 0, "message": "Failed to restart container", "error_reason": "restart_failed"}), 500
    except container_service.NodeServiceError as e:
        _log_failure(operation=OperationType.RESTART_CONTAINER, target_type="container", target_id=container_id,
                     operator_user_id=request_user_id, error_reason=getattr(e, 'reason', None),
                     detail={"container_id": container_id})
        return jsonify({"success": 0, "message": str(e), "error_reason": getattr(e, 'reason', None)}), 500
    except Exception as e:
        reason = getattr(e, 'reason', None) or getattr(e, 'error_reason', None)
        status = REASON_STATUS_MAP.get(reason, 500)
        payload = {"success": 0, "message": f"Internal error: {str(e)}"}
        if reason:
            payload['error_reason'] = reason
        _log_failure(operation=OperationType.RESTART_CONTAINER, target_type="container", target_id=container_id,
                     operator_user_id=request_user_id, error_reason=reason or "internal_error",
                     detail={"container_id": container_id})
        return jsonify(payload), status
    return jsonify({"success": 1, "message": "Container restart request sent"}), 200

@api_bp.post("/containers/add_collaborator")
def add_collaborator_api():
    '''
    通信数据格式：
    发送格式：
    {
        "user_id",
        "container_id",
        "role"
    }
    返回格式：
    {
        "success": [0|1],
        "message": "xxxx",
        ["error_reason": "xxxx"]
    }
    '''
    token = request.cookies.get("auth_token", "")
    if (not authentications_repo.is_token_valid(token)):
        return jsonify({"success":0,"message":"invalid or missing token", "error_reason": "invalid_token"}),401
    data=request.get_json() or {}
    user_id=data.get("user_id","")
    container_id=data.get("container_id",0)
    operator_user_id = authentications_repo.get_user_id_by_token(token)
    role=data.get("role","COLLABORATOR")

        
    try:
        if not container_service.add_collaborator(container_id=container_id,
                     user_id=user_id,
                     role=ROLE(role),
                     operator_user_id=operator_user_id):
            return jsonify({"success":0,"message":"Failed to add collaborator", "error_reason": "add_collaborator_failed"}),500
    except container_service.NodeServiceError as e:    
        if getattr(e, 'reason', None) == 'container_offline':
            return jsonify({"success":0,"message": str(e), "error_reason": getattr(e, 'reason', None)}), 400
        return jsonify({"success":0,"message": str(e), "error_reason": getattr(e, 'reason', None)}), 500
    except Exception as e:
        return jsonify({"success": 0, "message": f"Internal error: {str(e)}"}), 500
    return jsonify({"success":1,"message":"Collaborator added successfully"}),201

@api_bp.post("/containers/remove_collaborator")
def remove_collaborator_api():
    '''
    通信数据格式：
    发送格式：
    {
        "container_id",
        "user_id"
    }
    返回格式：
    {
        "success": [0|1],
        "message": "xxxx",
        ["error_reason": "xxxx"]
    }
    '''
    token = request.cookies.get("auth_token", "")
    if (not authentications_repo.is_token_valid(token)):
        return jsonify({"success":0,"message":"invalid or missing token", "error_reason": "invalid_token"}),401
    data=request.get_json() or {}
    container_id=data.get("container_id",0)
    user_id=data.get("user_id","")
    request_user_id = authentications_repo.get_user_id_by_token(token)

    try:
        if not container_service.remove_collaborator(container_id=container_id,
                                                 user_id=user_id,
                                                 operator_user_id=request_user_id):
            return jsonify({"success":0,"message":"Failed to remove collaborator", "error_reason": "remove_collaborator_failed"}),500
    except container_service.NodeServiceError as e:
        if getattr(e, 'reason', None) == 'container_offline':
            return jsonify({"success":0,"message": str(e), "error_reason": getattr(e, 'reason', None)}), 400
        return jsonify({"success":0,"message": str(e), "error_reason": getattr(e, 'reason', None)}), 500
    except Exception as e:
        return jsonify({"success": 0, "message": f"Internal error: {str(e)}"}), 500
    return jsonify({"success":1,"message":"Collaborator removed successfully"}),200

@api_bp.post("/containers/update_role")
def update_role_api():
    '''
    通信数据格式：
    发送格式：
    {
        "container_id",
        "user_id",
        "updated_role"
    }
    返回格式：
    {
        "success": [0|1],
        "message": "xxxx",
        ["error_reason": "xxxx"]
    }
    '''
    token = request.cookies.get("auth_token", "")
    if (not authentications_repo.is_token_valid(token)):
        return jsonify({"success":0,"message":"invalid or missing token", "error_reason": "invalid_token"}),401
    data=request.get_json() or {}
    container_id=data.get("container_id",0)
    user_id=data.get("user_id","")
    updated_role=data.get("updated_role","COLLABORATOR")
    request_user_id = authentications_repo.get_user_id_by_token(token)
    try:
        if not container_service.update_role(container_id=container_id,
                user_id=user_id,
                updated_role=ROLE(updated_role),
                operator_user_id=request_user_id):
            return jsonify({"success":0,"message":"Failed to update role", "error_reason": "update_role_failed"}),500
    except container_service.NodeServiceError as e:
        if getattr(e, 'reason', None) == 'container_offline':
            return jsonify({"success":0,"message": str(e), "error_reason": getattr(e, 'reason', None)}), 400
        return jsonify({"success":0,"message": str(e), "error_reason": getattr(e, 'reason', None)}), 500
    except Exception as e:
        return jsonify({"success": 0, "message": f"Internal error: {str(e)}"}), 500
    return jsonify({"success":1,"message":"Role updated successfully"}),200

@api_bp.post("/containers/unpause_container")
def unpause_container_api():
    token = request.cookies.get("auth_token", "")
    if (not authentications_repo.is_token_valid(token)):
        return jsonify({"success": 0, "message": "invalid or missing token", "error_reason": "invalid_token"}), 401
    data = request.get_json() or {}
    container_id = data.get("container_id", 0)
    operator_user_id = authentications_repo.get_user_id_by_token(token)
    try:
        if container_service.unpause_container(container_id=container_id, operator_user_id=operator_user_id):
            return jsonify({"success": 1, "message": "Container unpaused"}), 200
        else:
            return jsonify({"success": 0, "message": "Failed to unpause container", "error_reason": "unpause_failed"}), 500
    except container_service.NodeServiceError as e:
        status = REASON_STATUS_MAP.get(getattr(e, 'reason', None), 500)
        return jsonify({"success": 0, "message": str(e), "error_reason": getattr(e, 'reason', None)}), status
    except Exception as e:
        return jsonify({"success": 0, "message": f"Internal error: {str(e)}"}), 500


@api_bp.post("/containers/get_container_detail_information")
def get_container_detail_information_api():
    '''
    通信数据格式：
    发送格式：
    {
        "container_id"
    }
    返回格式：
    {
        "success": [0|1],
        "message": "xxxx",
        ["error_reason": "xxxx"],
        "container_info": {
            "container_id",
            "container_name",
            "container_image",
            "machine_id",
            "machine_ip",
            "container_status",
            "memory_gb",
            "shared_gb",
            "gpu_number",
            "cpu_number",
            "port",
            "owners":['user_id'],
            "accounts":[(binding['user_id'],binding['username'],ROLE(binding['role']))],
        }
    }
    '''
    if (not authentications_repo.is_token_valid(request.cookies.get("auth_token", ""))):
        return jsonify({"success":0,"message":"invalid or missing token", "error_reason": "invalid_token"}),401
    data=request.get_json() or {}
    container_id=data.get("container_id",0)
    try:
        container_info=container_service.get_container_detail_information(container_id=container_id)
    except ValueError as e:
        return jsonify({"success":0,"message":"Container not found", "error_reason": "container_not_found"}),404
    return jsonify({"success":1,"container_info":container_info}),200


@api_bp.post("/containers/container_status")
def container_status_api():
    '''
    通信数据格式：
    发送格式：
    { 
        "machine_id": <id>, 
        "container_name": "name" 
    }
    返回格式：
    { 
        "container_status": "CREATING"|"ONLINE"|... 
    }
    '''
    if (not authentications_repo.is_token_valid(request.cookies.get("auth_token", ""))):
        return jsonify({"success":0, "message":"invalid or missing token", "error_reason": "invalid_token"}), 401
    data = request.get_json() or {}
    container_name = data.get('container_name', '')
    machine_id = data.get('machine_id', None)

    if not container_name or machine_id is None or machine_id == '':
        return jsonify({"container_status": None}), 200

    try:
        try:
            machine_id = int(machine_id)
        except Exception:
            return jsonify({"container_status": None}), 200

        cid = containers_repo.get_id_by_name_machine(container_name=container_name, machine_id=machine_id)
        if not cid:
            return jsonify({"container_status": None}), 200
        container = containers_repo.get_by_id(cid)
        if not container:
            return jsonify({"container_status": None}), 200
        return jsonify({"container_status": container.container_status.value}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.post("/containers/refresh_last_ssh_login_time")
def refresh_last_ssh_login_time_api():
    '''
    前端触发刷新容器上次 SSH 登录时间。
    请求格式：
    {
        "container_id": <int>
    }
    返回格式：
    {
        "success": 0|1,
        "container_id": <int>,
        "container_name": "<name>",
        "last_ssh_login_time": "<time or null>"
    }
    '''
    token = request.cookies.get("auth_token", "")
    if not authentications_repo.is_token_valid(token):
        return jsonify({"success": 0, "message": "invalid or missing token", "error_reason": "invalid_token"}), 401

    data = request.get_json() or {}
    container_id = data.get("container_id", 0)
    try:
        container_id = int(container_id)
    except Exception:
        return jsonify({"success": 0, "message": "invalid container_id", "error_reason": "invalid_payload"}), 400

    container = containers_repo.get_by_id(container_id)
    if not container:
        return jsonify({"success": 0, "message": "Container not found", "error_reason": "container_not_found"}), 404

    try:
        cid = container.id  # 提前取值，防止 commit 后 session 过期导致后台线程崩溃
        last_time = container_service.get_container_last_ssh_login_time(cid)
        cleanup_days = int(current_app.config.get("CONTAINER_CLEANUP_AFTER_DAYS", 7) or 7)
        cleanup_info = container_service.build_cleanup_info(last_time, cleanup_days)
        # 顺便刷新磁盘用量（异步，不阻塞 SSH 刷新返回）
        import threading
        threading.Thread(target=lambda: _refresh_disk_async(cid), daemon=True).start()
    except container_service.NodeServiceError as e:
        reason = getattr(e, "reason", None)
        status = REASON_STATUS_MAP.get(reason, 500)
        return jsonify({"success": 0, "message": str(e), "error_reason": reason}), status
    except Exception as e:
        reason = getattr(e, "reason", None) or getattr(e, "error_reason", None)
        status = REASON_STATUS_MAP.get(reason, 500)
        payload = {"success": 0, "message": f"Internal error: {str(e)}"}
        if reason:
            payload["error_reason"] = reason
        return jsonify(payload), status

    return jsonify({
        "success": 1,
        "container_id": container.id,
        "container_name": container.name,
        "last_ssh_login_time": last_time,
        "cleanup_after_days": cleanup_info.get("cleanup_after_days"),
        "cleanup_at": cleanup_info.get("cleanup_at"),
        "seconds_until_cleanup": cleanup_info.get("seconds_until_cleanup"),
        "cleanup_status": cleanup_info.get("cleanup_status"),
    }), 200


@api_bp.post("/containers/list_all_container_bref_information")
def list_all_containers_bref_information_api():
    '''
    通信数据格式：
    发送格式：
    {
        "machine_id",
        "user_id",
        "page_number",
        "page_size"
    }
    返回格式：
    {
        "success": [0|1],
        "message": "xxxx",
        ["error_reason": "xxxx"],
        "containers_info": [{
            "container_id",
            "container_name",
            "machine_id",
            "machine_ip",
            "port",
            "container_status"
        }],
    }
    '''
    token = request.cookies.get("auth_token", "")
    if (not authentications_repo.is_token_valid(token)):
        return jsonify({"success":0,"message":"invalid or missing token", "error_reason": "invalid_token"}),401
    data=request.get_json() or {}
    machine_id=data.get("machine_id","")
    user_id=data.get("user_id","")
    request_user_id = authentications_repo.get_user_id_by_token(token)
    page_number=data.get("page_number",0)
    page_size=data.get("page_size",10)
    # 在此处统一为 None，并数字化 ID
    if machine_id == "" or machine_id is None:
        machine_id = None
    else:
        try:
            machine_id = int(machine_id)
        except Exception:
            machine_id = None
    if user_id == "" or user_id is None:
        user_id = None
    else:
        try:
            user_id = int(user_id)
        except Exception:
            user_id = None
    try: # 这里其实理论不会报错 但是保留
        result = container_service.list_all_container_bref_information(
            machine_id=machine_id,
            request_user_id=request_user_id,
            page_number=page_number,
            page_size=page_size,
            user_id=user_id)
        # expect a dict: { containers: [...], total_page: n }
        containers_info = result.get('containers', [])
        total_page = result.get('total_page', 1)
        long_term_container_remaining = result.get('long_term_container_remaining')
        long_term_container_limit = result.get('long_term_container_limit')
    except Exception as e:
        reason = getattr(e, 'reason', None) or getattr(e, 'error_reason', None) or 'list_failed'
        status = REASON_STATUS_MAP.get(reason, 500)
        payload = {"success":0,"message":"Failed to list containers: " + str(e), "error_reason": reason}
        return jsonify(payload), status

    # convert pydantic models to plain dicts so jsonify can serialize
    out = []
    for c in containers_info:
        try:
            out.append(c.dict())
        except Exception:
            out.append(c)

    payload = {"success":1,"containers_info":out, "total_page": total_page}
    if user_id is not None:
        payload["long_term_container_remaining"] = long_term_container_remaining
        payload["long_term_container_limit"] = long_term_container_limit
    return jsonify(payload),200


def _refresh_disk_async(container_id: int):
    """异步拉取单个容器的磁盘用量并落库（不阻塞前端请求）。"""
    try:
        from flask import current_app
        app = current_app._get_current_object()
        with app.app_context():
            du = container_service.get_container_disk_usage(container_id, timeout=20.0)
            if isinstance(du, dict) and du.get("container"):
                from ..repositories import containers_repo as repo, machine_repo as mrepo
                from datetime import datetime
                c = repo.get_by_id(container_id)
                if not c:
                    return
                cd = du["container"]
                overlay = int(cd.get("overlay_rw_bytes") or 0)
                bind = int(cd.get("bind_mount_bytes") or 0)
                total = int(cd.get("total_bytes") or 0)
                limit = 0
                try:
                    m = mrepo.get_by_id(c.machine_id)
                    dg = getattr(m, 'disk_size_gb', 0) or 0
                    limit = int(dg * 1024**3)
                except Exception:
                    pass
                repo.update_container(c.id, commit=True,
                    disk_overlay_rw_bytes=overlay, disk_bind_mount_bytes=bind,
                    disk_total_bytes=total, disk_limit_bytes=limit,
                    disk_checked_at=datetime.utcnow())
    except Exception as e:
        print(f"[ssh-refresh] async disk refresh failed for container {container_id}: {e}")
