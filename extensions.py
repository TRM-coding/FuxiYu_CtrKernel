# extensions.py
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_caching import Cache
from flask_login import LoginManager

db = SQLAlchemy()
migrate = Migrate()
cache = Cache()
login_manager = LoginManager()
