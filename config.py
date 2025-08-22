"""应用配置模块

提供不同环境的配置类，支持通过环境变量覆盖默认值。
"""

import os


class BaseConfig:
	SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
	SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///app.db")
	SQLALCHEMY_TRACK_MODIFICATIONS = False
	JSON_SORT_KEYS = False
	# 缓存: 默认使用简单内存缓存，可根据需要改成Redis等
	CACHE_TYPE = os.getenv("CACHE_TYPE", "SimpleCache")
	CACHE_DEFAULT_TIMEOUT = 300


class DevelopmentConfig(BaseConfig):
	DEBUG = True


class ProductionConfig(BaseConfig):
	DEBUG = False


class TestingConfig(BaseConfig):
	TESTING = True
	SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


config_map = {
	"development": DevelopmentConfig,
	"production": ProductionConfig,
	"testing": TestingConfig,
}


def get_config(name: str | None):
	if not name:
		return DevelopmentConfig
	return config_map.get(name, DevelopmentConfig)

