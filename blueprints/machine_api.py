from flask import jsonify, request
from . import api_bp
from ..services import machine_tasks as machine_service
from ..repositories import user_repo, authentications_repo
from ..schemas.user_schema import user_schema, users_schema
from ..constant import PERMISSION
from sqlalchemy.exc import IntegrityError


@api_bp.post("/machines/add_machine")
def add_machine_api():
    '''
    通信数据格式：
	发送格式：
	{
		"token",
        "machine_name",
        "machine_ip",
        "machine_type",
        "machine_description",
        "cpu_core_number",
        "gpu_number",
        "gpu_type",
        "memory_size",
        "disk_size"
    }
    返回格式：
	{
		"success": [0|1],
		"message": "xxxx",
        ["error_reason": "xxxx"]
	}
    '''
    if (not authentications_repo.is_token_valid(request.headers.get("token", ""))):
        return jsonify({"success": 0, "message": "invalid or missing token", "error_reason": "invalid_token"}), 401
    if (not user_repo.check_permission(request.headers.get("token", ""), required_permission=PERMISSION.OPERATOR)):
        return jsonify({"success": 0, "message": "insufficient permissions", "error_reason": "insufficient_permission"}), 403
    data = request.get_json() or {}
    machine_name = data.get("machine_name", "")
    machine_ip = data.get("machine_ip", "")
    machine_type = data.get("machine_type", "")
    machine_description = data.get("machine_description", "")
    cpu_core_number = data.get("cpu_core_number", 0)
    gpu_number = data.get("gpu_number", 0)
    gpu_type = data.get("gpu_type", "")
    memory_size = data.get("memory_size", 0)
    disk_size = data.get("disk_size", 0)
    try: # 仅仅是防御性质的措施
        success = machine_service.Add_machine(machine_name=machine_name,
                                            machine_ip=machine_ip,
                                            machine_type=machine_type,
                                            machine_description=machine_description,
                                            cpu_core_number=cpu_core_number,
                                            gpu_number=gpu_number,
                                            gpu_type=gpu_type,
                                            memory_size=memory_size,
                                            disk_size=disk_size)
    except IntegrityError as ie:
        # likely duplicate unique constraint (e.g. machine_name)
        return jsonify({"success": 0, "message": f"Duplicate entry: {str(ie.orig) if hasattr(ie, 'orig') else str(ie)}", "error_reason": "duplicate_entry"}), 409
    except Exception as e:
        return jsonify({"success": 0, "message": f"Internal error: {str(e)}", "error_reason": "internal_error"}), 500

    if success:
        return jsonify({"success": 1, "message": "Container created successfully"}), 201
    else:
        return jsonify({"success": 0, "message": "Failed to create container", "error_reason": "create_failed"}), 500
    
@api_bp.post("/machines/remove_machine")
def remove_machine_api():
    '''
    发送格式：
    {
        "token",
        "machine_ids",
    }
    返回格式：
    {
        "success": [0|1],
        "message": "xxxx",
        ["error_reason": "xxxx"]
    }
    '''
    if (not authentications_repo.is_token_valid(request.headers.get("token", ""))):
        return jsonify({"success": 0, "message": "invalid or missing token", "error_reason": "invalid_token"}), 401
    if (not user_repo.check_permission(request.headers.get("token", ""), required_permission=PERMISSION.OPERATOR)):
        return jsonify({"success": 0, "message": "insufficient permissions", "error_reason": "insufficient_permission"}), 403
    data = request.get_json() or {}
    data = request.get_json() or {}
    machine_ids = data.get("machine_ids", [])
    success = machine_service.Remove_machine(machine_id=machine_ids)
    if success:
        return jsonify({"success": 1, "message": "Machine(s) removed successfully"}), 200
    else:
        return jsonify({"success": 0, "message": "Failed to remove machine(s)", "error_reason": "remove_failed"}), 500
    
@api_bp.post("/machines/update_machine")
def update_machine_api():
    '''
    allowed = {"machine_name", "machine_ip", "machine_type", "machine_status", "cpu_core_number",
               "memory_size", "gpu_number", "gpu_type", "disk_size", "machine_description"}

    通信数据格式：
	发送格式：
	{
		"token",
        "machine_id",
        "machine_name",
        "machine_ip",
        "machine_type",
        "machine_status",
        "cpu_core_number",
        "gpu_number",
        "gpu_type",
        "memory_size",
        "disk_size",
        "machine_description"
    }
    返回格式：
	{
		"success": [0|1],
		"message": "xxxx",
        ["error_reason": "xxxx"]
	}
    '''
    if (not authentications_repo.is_token_valid(request.headers.get("token", ""))):
        return jsonify({"success": 0, "message": "invalid or missing token", "error_reason": "invalid_token"}), 401
    if (not user_repo.check_permission(request.headers.get("token", ""), required_permission=PERMISSION.OPERATOR)):
        return jsonify({"success": 0, "message": "insufficient permissions", "error_reason": "insufficient_permission"}), 403
    data = request.get_json() or {}
    data = request.get_json() or {}
    machine_id = data.get("machine_id", 0)
    fields = data.get("fields", {})
    success = machine_service.Update_machine(machine_id=machine_id, **fields)
    if success:
        return jsonify({"success": 1, "message": "Machine updated successfully"}), 200
    else:
        return jsonify({"success": 0, "message": "Failed to update machine", "error_reason": "update_failed"}), 500
            

@api_bp.post("/machines/get_detail_information")
def get_detail_information_api():
    '''
    通信数据格式：
	发送格式：
	{
		"token",
        "machine_id",
    }
    返回格式：
	{
		"success": [0|1],
		"message": "xxxx",
        ["error_reason": "xxxx"]
	}
    '''
    if (not authentications_repo.is_token_valid(request.headers.get("token", ""))):
        return jsonify({"success": 0, "message": "invalid or missing token", "error_reason": "invalid_token"}), 401
    data = request.get_json() or {}
    machine_id = data.get("machine_id", 0)
    machine_info = machine_service.Get_detail_information(machine_id=machine_id)
    if machine_info:
        return jsonify({
            "machine_name": machine_info.machine_name,
            "machine_ip": machine_info.machine_ip,
            "machine_type": machine_info.machine_type,
            "machine_description": machine_info.machine_description,
            "cpu_core_number": machine_info.cpu_core_number,
            "gpu_number": machine_info.gpu_number,
            "gpu_type": machine_info.gpu_type,
            "memory_size_gb": machine_info.memory_size_gb,
            "disk_size_gb": machine_info.disk_size_gb,
            "containers": machine_info.containers
        }), 200
    else:
        return jsonify({"success": 0, "message": "Machine not found", "error_reason": "machine_not_found"}), 404
    
@api_bp.post("/machines/list_all_machine_bref_information")
def list_all_machine_bref_information_api():
    '''
    通信数据格式：
    发送格式：
    {
        "token",
        "page_number",
        "page_size"
    }
    返回格式：
    {
        "success": [0|1],
        "message": "xxxx",
        ["error_reason": "xxxx"]
    }
    '''
    if (not authentications_repo.is_token_valid(request.headers.get("token", ""))):
        return jsonify({"success": 0, "message": "invalid or missing token", "error_reason": "invalid_token"}), 401
    data = request.get_json(silent=True) or {}
    page_number = int(data.get("page_number", 0))
    page_size = int(data.get("page_size", 10))
    machines_info, total_pages = machine_service.List_all_machine_bref_information(page_number=page_number, page_size=page_size)
    machines_list = []
    for machine in machines_info:
        machines_list.append({
            "machine_id": getattr(machine, 'id', None),
            "machine_name": machine.machine_name,
            "machine_ip": machine.machine_ip,
            "machine_type": machine.machine_type,
            "machine_status": machine.machine_status
        })
    return jsonify({"machines": machines_list, "total_pages": total_pages}), 200