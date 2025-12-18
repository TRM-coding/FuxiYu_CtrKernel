from flask import Blueprint

api_bp = Blueprint("api", __name__, url_prefix="/api")

# 导入各个 API 模块以注册路由
from . import user_api


def register_blueprints(app):
	app.register_blueprint(api_bp)

