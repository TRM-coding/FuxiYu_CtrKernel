from flask import jsonify, request
from . import api_bp
from ..services import user_tasks as user_service
from ..repositories import user_repo
from ..schemas.user_schema import user_schema, users_schema


@api_bp.get("/users/list_users")
def list_users():
	pass


@api_bp.post("/users/register")
def create_user():
	pass

@api_bp.post("/users/login")
def login_user():
	pass
	
@api_bp.post("/users/change_password")
def change_password_user():
	pass

@api_bp.post("/users/delete_user")
def delete_user_api():
	pass