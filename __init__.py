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
