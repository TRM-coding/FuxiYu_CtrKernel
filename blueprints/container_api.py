from flask import jsonify, request
from . import api_bp
from ..services import container_tasks as container_service
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
    }
    '''
    if (not authentications_repo.is_token_valid(request.headers.get("token", ""))):
           return jsonify({"success": 0, "message": "invalid or missing token"}), 401
    data = request.get_json() or {}
    user_name = data.get("user_name", "")
    machine_id = data.get("machine_id", 0)
    container = {
        "GPU_LIST": data.get("GPU_LIST", []),
        "CPU_NUMBER": data.get("CPU_NUMBER", 0),
        "MEMORY": data.get("MEMORY", 0),
        "NAME": data.get("NAME", ""),
        "image": data.get("image", ""),
    }
    public_key = data.get("public_key", "")

    
    if not container_service.Create_container(user_name=user_name,
                     machine_id=machine_id,
                     container=container,
                     public_key=public_key):
        return jsonify({"success": 0, "message": "Failed to create container"}), 500
    return jsonify({"success": 1, "message": "Container created successfully"}), 201
    
    
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
    }
    '''
    if (not authentications_repo.is_token_valid(request.headers.get("token", ""))):
           return jsonify({"success": 0, "message": "invalid or missing token"}), 401
    data = request.get_json() or {}
    container_id = data.get("container_id", 0)
    if not container_service.remove_container(container_id=container_id):
        return jsonify({"success": 0, "message": "Failed to delete container"}), 500
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
    }
    '''
    if (not authentications_repo.is_token_valid(request.headers.get("token",""))):
           return jsonify({"success":0,"message":"invalid or missing token"}),401
    data=request.get_json() or {}
    user_id=data.get("user_id","")
    container_id=data.get("container_id",0)
    role=data.get("role","COLLABORATOR")

        
    if not container_service.add_collaborator(container_id=container_id,
                     user_id=user_id,
                     role=ROLE(role)):
        return jsonify({"success":0,"message":"Failed to add collaborator"}),500
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
    }
    '''
    if (not authentications_repo.is_token_valid(request.headers.get("token",""))):
           return jsonify({"success":0,"message":"invalid or missing token"}),401
    data=request.get_json() or {}
    container_id=data.get("container_id",0)
    user_id=data.get("user_id","")

    if not container_service.remove_collaborator(container_id=container_id,
                                                 user_id=user_id):
        return jsonify({"success":0,"message":"Failed to remove collaborator"}),500
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
    }
    '''
    if (not authentications_repo.is_token_valid(request.headers.get("token",""))):
           return jsonify({"success":0,"message":"invalid or missing token"}),401
    data=request.get_json() or {}
    container_id=data.get("container_id",0)
    user_id=data.get("user_id","")
    updated_role=data.get("updated_role","COLLABORATOR")
    if not container_service.update_role(container_id=container_id,
                user_id=user_id,
                updated_role=ROLE(updated_role)):
        return jsonify({"success":0,"message":"Failed to update role"}),500
    return jsonify({"success":1,"message":"Role updated successfully"}),200

@api_bp.get("/containers/get_container_detail_information")
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
        "container_info": {...},
    }
    '''
    if (not authentications_repo.is_token_valid(request.headers.get("token",""))):
           return jsonify({"success":0,"message":"invalid or missing token"}),401
    data=request.get_json() or {}
    container_id=data.get("container_id",0)
    try:
        container_info=container_service.get_container_detail_information(container_id=container_id)
    except Exception as e:
        return jsonify({"success":0,"message":"Failed to get container detail information"}),500
    return jsonify({"success":1,"container_info":container_info}),200

@api_bp.get("/containers/list_all_container_bref_information")
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
        "containers_info": [...],
    }
    '''
    if (not authentications_repo.is_token_valid(request.headers.get("token",""))):
           return jsonify({"success":0,"message":"invalid or missing token"}),401
    data=request.get_json() or {}
    machine_id=data.get("machine_id","")
    page_number=data.get("page_number",1)
    page_size=data.get("page_size",10)
    try: # 这里其实理论不会报错 但是保留
        containers_info=container_service.list_all_container_bref_information(
            machine_id=machine_id,
            page_number=page_number,
            page_size=page_size)
    except Exception as e:
        return jsonify({"success":0,"message":"Failed to list containers"}),500
    return jsonify({"success":1,"containers_info":containers_info}),200