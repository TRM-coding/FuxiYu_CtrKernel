from sqlalchemy.exc import IntegrityError
from flask import jsonify, request
from . import api_bp
from ..services import container_tasks as container_service
from ..utils.Container import Container_info
from ..constant import ROLE
from ..repositories import containers_repo, authentications_repo
from ..schemas.user_schema import user_schema, users_schema

@api_bp.post("/containers/create_container")
def create_container_api():
    '''
    通信数据格式：
    发送格式：
    {
        "token",
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
    if (not authentications_repo.is_token_valid(request.headers.get("token", ""))):
        return jsonify({"success": 0, "message": "invalid or missing token", "error_reason": "invalid_token"}), 401
    data = request.get_json() or {}
    owner_name = data.get("user_name", "")
    machine_id = data.get("machine_id", 0)

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
    if public_key is '':  # treat empty string as None
        public_key = None
    # 这里纯粹只是为了增加报错信息的友好性
    try:
        gpu_list = container_raw.get("GPU_LIST") or container_raw.get("gpu_list") or []
        cpu_number = int(container_raw.get("CPU_NUMBER") or container_raw.get("cpu_number") or 0)
        memory = int(container_raw.get("MEMORY") or container_raw.get("memory") or 0)
        name = container_raw.get("NAME") or container_raw.get("name") or ""
        image = container_raw.get("image") or container_raw.get("IMAGE") or ""

        # construct Container_info instance expected by service layer
        container_obj = Container_info(gpu_list=gpu_list, cpu_number=cpu_number, memory=memory, name=name, image=image)

    except Exception as e:
        return jsonify({"success": 0, "message": f"Invalid container payload: {str(e)}", "error_reason": "invalid_payload"}), 400
    # 这里：error_reason的补映射表。原则上服务层应该尽量提供明确的error_reason以便前端处理，但这里也做一个兜底，以防万一
    reason_map = {
        "container_exists": 409,
        "invalid_payload": 400,
        "invalid_signature": 401,
        "invalid_json": 400,
        "invalid_config": 400,
        "docker_init_failed": 502,
        "docker_check_failed": 502,
        "unexpected_response": 502,
    }

    try:
        if not container_service.Create_container(owner_name=owner_name,
                        machine_id=machine_id,
                        container=container_obj,
                        public_key=public_key):
            return jsonify({"success": 0, "message": "Failed to create container", "error_reason": "create_failed"}), 500
    except IntegrityError as e:
        return jsonify({"success": 0, "message": f"Duplicate entry: {str(e.orig) if hasattr(e, 'orig') else str(e)}", "error_reason": "duplicate_entry"}), 409
    except container_service.NodeServiceError as e:
        status = reason_map.get(getattr(e, 'reason', None), 500)
        return jsonify({"success": 0, "message": str(e), "error_reason": getattr(e, 'reason', None)}), status
    except Exception as e: 
        return jsonify({"success": 0, "message": f"Internal error: {str(e)}"}), 500
    return jsonify({"success": 1, "message": "Create container request sent"}), 200
    
    
@api_bp.post("/containers/delete_container")
def delete_container_api():
    '''
    通信数据格式：
    发送格式：
    {
        "token",
        "container_id"
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
    container_id = data.get("container_id", 0)
    try:
        if not container_service.remove_container(container_id=container_id):
            return jsonify({"success": 0, "message": "Failed to delete container", "error_reason": "delete_failed"}), 500
    except container_service.NodeServiceError as e:
        # prefer remote's reason when available
        status = 404 if getattr(e, 'reason', None) == 'not_found' else 500
        return jsonify({"success": 0, "message": str(e), "error_reason": getattr(e, 'reason', None)}), status
    except Exception as e:
        return jsonify({"success": 0, "message": f"Internal error: {str(e)}"}), 500
    return jsonify({"success": 1, "message": "Container deleted successfully"}), 200

@api_bp.post("/containers/add_collaborator")
def add_collaborator_api():
    '''
    通信数据格式：
    发送格式：
    {
        "token",
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
    if (not authentications_repo.is_token_valid(request.headers.get("token",""))):
        return jsonify({"success":0,"message":"invalid or missing token", "error_reason": "invalid_token"}),401
    data=request.get_json() or {}
    user_id=data.get("user_id","")
    container_id=data.get("container_id",0)
    role=data.get("role","COLLABORATOR")

        
    try:
        if not container_service.add_collaborator(container_id=container_id,
                     user_id=user_id,
                     role=ROLE(role)):
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
        "token",
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
    if (not authentications_repo.is_token_valid(request.headers.get("token",""))):
        return jsonify({"success":0,"message":"invalid or missing token", "error_reason": "invalid_token"}),401
    data=request.get_json() or {}
    container_id=data.get("container_id",0)
    user_id=data.get("user_id","")

    try:
        if not container_service.remove_collaborator(container_id=container_id,
                                                 user_id=user_id):
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
        "token",
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
    if (not authentications_repo.is_token_valid(request.headers.get("token",""))):
        return jsonify({"success":0,"message":"invalid or missing token", "error_reason": "invalid_token"}),401
    data=request.get_json() or {}
    container_id=data.get("container_id",0)
    user_id=data.get("user_id","")
    updated_role=data.get("updated_role","COLLABORATOR")
    try:
        if not container_service.update_role(container_id=container_id,
                user_id=user_id,
                updated_role=ROLE(updated_role)):
            return jsonify({"success":0,"message":"Failed to update role", "error_reason": "update_role_failed"}),500
    except container_service.NodeServiceError as e:
        if getattr(e, 'reason', None) == 'container_offline':
            return jsonify({"success":0,"message": str(e), "error_reason": getattr(e, 'reason', None)}), 400
        return jsonify({"success":0,"message": str(e), "error_reason": getattr(e, 'reason', None)}), 500
    except Exception as e:
        return jsonify({"success": 0, "message": f"Internal error: {str(e)}"}), 500
    return jsonify({"success":1,"message":"Role updated successfully"}),200

@api_bp.post("/containers/get_container_detail_information")
def get_container_detail_information_api():
    '''
    通信数据格式：
    发送格式：
    {
        "token",
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
            "container_status",
            "port",
            "owners":['user_id'],
            "accounts":[(binding['user_id'],binding['username'],ROLE(binding['role']))],
        }
    }
    '''
    if (not authentications_repo.is_token_valid(request.headers.get("token",""))):
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
        "token",
        "machine_id": <id>, 
        "container_name": "name" 
    }
    返回格式：
    { 
        "container_status": "CREATING"|"ONLINE"|... 
    }
    '''
    if (not authentications_repo.is_token_valid(request.headers.get("token",""))):
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

@api_bp.post("/containers/list_all_container_bref_information")
def list_all_containers_bref_information_api():
    '''
    通信数据格式：
    发送格式：
    {
        "token",
        "machine_id",
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
            "port",
            "container_status"
        }],
    }
    '''
    if (not authentications_repo.is_token_valid(request.headers.get("token",""))):
        return jsonify({"success":0,"message":"invalid or missing token", "error_reason": "invalid_token"}),401
    data=request.get_json() or {}
    machine_id=data.get("machine_id","")
    user_id=data.get("user_id","")
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
            user_id=user_id,
            page_number=page_number,
            page_size=page_size)
        # expect a dict: { containers: [...], total_page: n }
        containers_info = result.get('containers', [])
        total_page = result.get('total_page', 1)
    except Exception as e:
        return jsonify({"success":0,"message":"Failed to list containers", "error_reason": "list_failed"}),500

    # convert pydantic models to plain dicts so jsonify can serialize
    out = []
    for c in containers_info:
        try:
            out.append(c.dict())
        except Exception:
            out.append(c)

    return jsonify({"success":1,"containers_info":out, "total_page": total_page}),200