from flask import Blueprint, jsonify, request
from ..services import service1
from ..repositories import user_repo
from ..schemas.user_schema import user_schema, users_schema


api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.get("/users")
def list_users():
	users = user_repo.list_users()
	return jsonify(users_schema.dump(users))


@api_bp.post("/users")
def create_user():
	data = request.get_json() or {}
	username = data.get("username")
	email = data.get("email")
	password = data.get("password", "123456")
	if not username or not email:
		return {"message": "username and email required"}, 400
	user = service1.register_user(username, email, password)
	return user_schema.dump(user), 201


def register_blueprints(app):
	app.register_blueprint(api_bp)

