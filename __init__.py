from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

_DOTENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_DOTENV_PATH, override=True)

from .api import register_api
from .config import AppConfig, build_allowed_origins
from . import extensions
from .extensions import configure_database, db
from .utils.logging_config import configure_daily_logging


def _apply_overrides(overrides: dict | None) -> None:
    """Apply test or local configuration overrides."""

    if not overrides:
        return
    for key, value in overrides.items():
        setattr(AppConfig, key, value)


def _init_database() -> None:
    """Import models, create tables, and seed minimal RBAC defaults."""

    from . import models  # noqa: F401

    db.create_all()
    _ensure_image_template_schema()
    _ensure_container_failure_schema()
    try:
        from .services.rbac_service import seed_rbac_defaults

        seed_rbac_defaults()
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("rbac seed skipped: %s", e)
    try:
        from .services.image_tasks import seed_image_defaults

        seed_image_defaults()
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("image seed skipped: %s", e)
    try:
        from .services.settings_tasks import seed_system_settings_defaults

        seed_system_settings_defaults()
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("system settings seed skipped: %s", e)


def _ensure_image_template_schema() -> None:
    """补齐开发期旧 images 表缺失的镜像模板列。

    create_all 只创建新表，不会修改旧表；镜像模板在开发期经历过字段拆分，
    旧 SQLite 库会缺 base_image/dockerfile_body 等列，导致列表接口 500。
    """

    import logging

    from sqlalchemy import inspect, text

    current_engine = extensions.engine
    inspector = inspect(current_engine)
    if not inspector.has_table("images"):
        return

    existing = {column["name"] for column in inspector.get_columns("images")}
    required_sqlite = {
        "base_image": "ALTER TABLE images ADD COLUMN base_image VARCHAR(255) NOT NULL DEFAULT 'ubuntu:22.04'",
        "dockerfile_body": "ALTER TABLE images ADD COLUMN dockerfile_body TEXT NOT NULL DEFAULT ''",
        "status": "ALTER TABLE images ADD COLUMN status VARCHAR(8) NOT NULL DEFAULT 'draft'",
        "created_by_user_id": "ALTER TABLE images ADD COLUMN created_by_user_id INTEGER NULL",
        "created_at": "ALTER TABLE images ADD COLUMN created_at DATETIME NULL",
        "updated_at": "ALTER TABLE images ADD COLUMN updated_at DATETIME NULL",
    }
    required_mysql = {
        "base_image": "ALTER TABLE images ADD COLUMN base_image VARCHAR(255) NOT NULL DEFAULT 'ubuntu:22.04'",
        "dockerfile_body": "ALTER TABLE images ADD COLUMN dockerfile_body TEXT NOT NULL",
        "status": "ALTER TABLE images ADD COLUMN status ENUM('draft', 'ready', 'disabled') NOT NULL DEFAULT 'draft'",
        "created_by_user_id": "ALTER TABLE images ADD COLUMN created_by_user_id INT NULL",
        "created_at": "ALTER TABLE images ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "ALTER TABLE images ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    }
    required = required_sqlite if current_engine.dialect.name == "sqlite" else required_mysql

    missing = [name for name in required if name not in existing]
    if not missing:
        return

    with current_engine.begin() as conn:
        for name in missing:
            conn.execute(text(required[name]))
    logging.getLogger(__name__).warning("image schema upgraded: added columns %s", ", ".join(missing))


def _ensure_container_failure_schema() -> None:
    """补齐开发期旧 containers 表缺失的失败诊断列。"""

    import logging

    from sqlalchemy import inspect, text

    current_engine = extensions.engine
    inspector = inspect(current_engine)
    if not inspector.has_table("containers"):
        return

    existing = {column["name"] for column in inspector.get_columns("containers")}
    required = {
        "failed_reason": "ALTER TABLE containers ADD COLUMN failed_reason VARCHAR(255) NULL",
        "failed_detail": "ALTER TABLE containers ADD COLUMN failed_detail TEXT NULL",
    }
    missing = [name for name in required if name not in existing]
    if not missing:
        return

    with current_engine.begin() as conn:
        for name in missing:
            conn.execute(text(required[name]))
    logging.getLogger(__name__).warning("container schema upgraded: added columns %s", ", ".join(missing))


def _should_start_background_tasks() -> bool:
    """Return whether Ctrl background tasks should start."""

    return not getattr(AppConfig, "TESTING", False) and not getattr(AppConfig, "DISABLE_BACKGROUND_TASKS", False)


def _start_background_tasks() -> None:
    """Start Ctrl background tasks after their DB access is migrated."""

    return None


def create_app(config: str | None = None, overrides: dict | None = None) -> FastAPI:
    """Create the Ctrl FastAPI application."""

    _apply_overrides(overrides)
    configure_database(AppConfig.SQLALCHEMY_DATABASE_URI)
    configure_daily_logging(AppConfig)
    _init_database()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if _should_start_background_tasks():
            _start_background_tasks()
        yield

    app = FastAPI(title="FuxiYu CtrlKernel API", lifespan=lifespan)
    app.state.config = AppConfig
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
    return app
