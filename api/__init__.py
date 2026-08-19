from fastapi import APIRouter
from flask import Blueprint

router = APIRouter(prefix="/api")
api_bp = Blueprint("api", __name__, url_prefix="/api")

# 已迁移到 FastAPI 的路由
from . import machine_api

router.include_router(machine_api.router)

# 尚未迁移的 Flask API 模块，继续挂在 legacy Blueprint 上。
from . import user_api
from . import container_api
from . import announcement_api
from . import operation_log_api


def register_api(app):
	"""注册 Ctrl FastAPI 路由。"""

	app.include_router(router)


def register_legacy_api(app):
	"""注册尚未迁移的 Flask Blueprint 路由。"""

	app.register_blueprint(api_bp)


# 兼容旧调用名，后续整体切完 FastAPI 时再清。
register_blueprints = register_legacy_api
