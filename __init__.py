# yourapp/__init__.py
from pathlib import Path
from dotenv import load_dotenv

_DOTENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_DOTENV_PATH, override=True)

import os
from flask import Flask
from flask_cors import CORS
from .extensions import db
from .config import get_config, build_allowed_origins
from .blueprints import register_blueprints
from .schemas.container_ssh_refresh_task import start_container_ssh_refresh_scheduler
from .schemas.container_cleanup_task import start_container_cleanup_scheduler
from .schemas.container_mount_cleanup_task import start_mount_cleanup_scheduler
from .utils.logging_config import configure_daily_logging


def create_app(config: str | None = None, overrides: dict | None = None):
    if not overrides:
        load_dotenv(_DOTENV_PATH, override=True)
    app = Flask(__name__)
    app.config.from_object(get_config(config))
    if overrides:
        app.config.update(overrides)
    configure_daily_logging(app)
    # Configure CORS for API routes. 统一由 build_allowed_origins() 生成：
    # 只枚举 https 变体 + WEB_IP/127.0.0.1/localhost 三种写法，尾斜杠归一化。
    # When credentials are used, do NOT set origins to * — specify exact origins.
    origins = build_allowed_origins()
    CORS(app, supports_credentials=True, resources={r"/api/*": {"origins": origins}})

    db.init_app(app)
    with app.app_context():
        from . import models
        db.create_all()


    register_blueprints(app)

    # 启动“每5分钟刷新容器上次 SSH 登录时间”的后台任务。
    # Flask debug 模式下父进程和子进程都会执行 create_app，这里仅在 reloader 子进程启动任务，避免重复线程。
    if (
        not app.config.get("TESTING")
        and not app.config.get("DISABLE_BACKGROUND_TASKS")
        and ((not app.debug) or os.environ.get("WERKZEUG_RUN_MAIN") == "true")
    ):
        start_container_ssh_refresh_scheduler(app, interval_seconds=300)
        # 启动容器定时清理任务（每20分钟扫描一次到期容器并释放）
        start_container_cleanup_scheduler(app, interval_seconds=1200)
        # 启动已删除容器 mount 清理任务（每天一次）
        start_mount_cleanup_scheduler(app)

    return app
