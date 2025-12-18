from flask import Blueprint, jsonify, request
from ..services import user_tasks as user_service
from ..repositories import user_repo
from ..schemas.user_schema import user_schema, users_schema


api_bp = Blueprint("api", __name__, url_prefix="/api")


def register_blueprints(app):
	app.register_blueprint(api_bp)

