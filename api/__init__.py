"""Ctrl FastAPI 路由聚合。"""
from fastapi import APIRouter

from . import announcement_api
from . import container_api
from . import image_api
from . import internal_runtime_api
from . import machine_api
from . import operation_log_api
from . import rbac_api
from . import settings_api
from . import user_api

router = APIRouter(prefix="/api")

router.include_router(announcement_api.router)
router.include_router(container_api.router)
router.include_router(image_api.router)
router.include_router(internal_runtime_api.router)
router.include_router(machine_api.router)
router.include_router(operation_log_api.router)
router.include_router(rbac_api.router)
router.include_router(settings_api.router)
router.include_router(user_api.router)


def register_api(app) -> None:
    """注册 Ctrl FastAPI 路由。"""
    app.include_router(router)
