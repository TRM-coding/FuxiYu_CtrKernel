from contextlib import asynccontextmanager
from pathlib import Path
import warnings

from dotenv import load_dotenv

_DOTENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_DOTENV_PATH, override=True)

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from flask import Flask
from flask_cors import CORS

warnings.filterwarnings("ignore", message="starlette.middleware.wsgi is deprecated.*")
from starlette.middleware.wsgi import WSGIMiddleware

from .api import register_api, register_legacy_api
from .config import build_allowed_origins, get_config
from .extensions import db
from .schedulers.container_cleanup_task import start_container_cleanup_scheduler
from .schedulers.container_mount_cleanup_task import start_mount_cleanup_scheduler
from .utils.logging_config import configure_daily_logging


def _create_flask_runtime_app(
    config: str | None = None,
    overrides: dict | None = None,
    *,
    register_legacy_routes: bool = True,
) -> Flask:
    """创建迁移期 Flask runtime。

    FastAPI 端点通过它提供 Flask-SQLAlchemy app context；尚未迁移的 API
    也继续由它通过 WSGI middleware 承接。
    """

    if not overrides:
        load_dotenv(_DOTENV_PATH, override=True)

    flask_app = Flask(__name__)
    flask_app.config.from_object(get_config(config))
    if overrides:
        flask_app.config.update(overrides)

    configure_daily_logging(flask_app)
    origins = build_allowed_origins()
    CORS(flask_app, supports_credentials=True, resources={r"/api/*": {"origins": origins}})

    db.init_app(flask_app)
    with flask_app.app_context():
        from . import models

        db.create_all()

        # RBAC 预设组/权限点 seed（幂等）；TESTING 下也执行，保证新库可用
        try:
            from .services.rbac_service import seed_rbac_defaults
            seed_rbac_defaults()
        except Exception as e:  # 建表/seed 异常不应阻断启动（老库无新表时兜底）
            import logging
            logging.getLogger(__name__).warning("rbac seed skipped: %s", e)

    if register_legacy_routes:
        register_legacy_api(flask_app)

    return flask_app


def _should_start_background_tasks(flask_app: Flask) -> bool:
    """判断是否启动 Ctrl 后台任务。"""

    return not flask_app.config.get("TESTING") and not flask_app.config.get("DISABLE_BACKGROUND_TASKS")


def _start_background_tasks(flask_app: Flask) -> None:
    """启动 Ctrl 后台任务。

    任务内部仍按 Flask app context 编写；FastAPI lifespan 只负责启动位置迁移。
    """

    start_container_cleanup_scheduler(flask_app, interval_seconds=1200)
    start_mount_cleanup_scheduler(flask_app)


def create_app(config: str | None = None, overrides: dict | None = None) -> FastAPI:
    """创建 Ctrl FastAPI 应用。

    当前是增量迁移形态：FastAPI 承接已迁移 API，未迁移 API 通过 legacy
    Flask WSGI app 兜底；service/repository 暂不改。
    """

    flask_app = _create_flask_runtime_app(config, overrides, register_legacy_routes=True)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if _should_start_background_tasks(flask_app):
            _start_background_tasks(flask_app)
        yield

    app = FastAPI(title="FuxiYu CtrlKernel API", lifespan=lifespan)
    app.state.flask_app = flask_app
    app.state.db = db

    app.add_middleware(
        CORSMiddleware,
        allow_origins=build_allowed_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        reason = "invalid_payload"
        fields = {
            str(part)
            for error in errors
            for part in error.get("loc", ())
            if part not in ("body", "query", "path")
        }
        if any(error.get("type") == "json_invalid" for error in errors):
            reason = "invalid_json"
        elif request.url.path.endswith("/users/get_user_detail_information") and "user_id" in fields:
            reason = "missing_user_id"
        elif request.url.path.endswith("/request_register_code") and "email" in fields:
            reason = "missing_email"
        elif request.url.path.endswith("/machines/add_machine_permission") and {"machine_id", "user_id"} & fields:
            reason = "missing_fields"
        return JSONResponse(
            status_code=400,
            content={
                "success": 0,
                "message": "invalid request payload",
                "error_reason": reason,
                "detail": errors,
            },
        )

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(_: Request, exc: HTTPException):
        if isinstance(exc.detail, dict) and "success" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail, headers=exc.headers)
        return JSONResponse(
            status_code=exc.status_code,
            content={"success": 0, "message": str(exc.detail), "error_reason": None},
            headers=exc.headers,
        )

    register_api(app)

    # 未迁移 API 兜底。必须最后挂载，让 FastAPI 已迁移路由优先匹配。
    app.mount("/", WSGIMiddleware(flask_app))
    return app
