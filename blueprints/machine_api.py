from flask import jsonify, request
from . import api_bp
from ..services import user_tasks as user_service
from ..repositories import user_repo
from ..schemas.user_schema import user_schema, users_schema


@api_bp.get("/containers/create_container")
def create_container_api():
    data = request.get_json() or {}
    user_name = data.get("user_name")
    machine_ip = data.get("machine_ip")
    container_info = data.get("container_info")
    