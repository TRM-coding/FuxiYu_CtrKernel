# yourapp/__init__.py
from flask import Flask
from flask_cors import CORS
from .extensions import db, migrate, login_manager
from .config import get_config, CORSHeaderConfig
from .blueprints import register_blueprints

def create_app(config: str | None = None):
    app = Flask(__name__)
    app.config.from_object(get_config(config))
    # Configure CORS for API routes. FRONTEND_ORIGINS can be a comma-separated
    # list of allowed origins (e.g. "http://localhost:5173,http://127.0.0.1:5173").
    # When credentials are used, do NOT set origins to '*' — specify exact origins.
    # Use origins defined in config.CORSHeaderConfig
    frontend_origins = CORSHeaderConfig.ALLOW_ORIGINS
    origins = [o.strip() for o in frontend_origins.split(',') if o.strip()]
    CORS(app, supports_credentials=True, resources={r"/api/*": {"origins": origins}})

    db.init_app(app)
    migrate.init_app(app, db)
    # cache.init_app(app)
    login_manager.init_app(app)

    register_blueprints(app)
    return app
