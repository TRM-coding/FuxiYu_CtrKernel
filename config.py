"""应用配置模块

提供不同环境的配置类，支持通过环境变量覆盖默认值。
"""

import os


class SqlConfig:
    SQLNAME = "fuxi"
    SQLURL = "127.0.0.1"
    SQLPORT = "3306"
    SQLUSER = "root"


class KeyConfig:
    PUBLIC_KEY_PATH = "public_A.pem"
    PRIVATE_KEY_PATH = "private_A.pem"
    PUBLIC_KEY_NODE = "public_node.pem"


class CommsConfig:
    NODE_URL_MIDDLE = ":5789/api"


class CORSHeaderConfig:
    # Allow both localhost and 127.0.0.1 origins used in development
    # 这里列出允许的前端地址，前端开发时可能会用 localhost 或230
    ALLOW_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,http://192.168.5.141:5173,http://192.168.5.141:4173,http://192.168.5.230:5173,https://localhost:5173,https://127.0.0.1:5173,https://192.168.5.141:5173,https://192.168.5.141:4173,https://192.168.5.230:5173"


class AppConfig(SqlConfig, KeyConfig):
    # 允许通过环境变量覆盖
    SQLNAME = os.getenv("SQLNAME", SqlConfig.SQLNAME)
    SQLURL = os.getenv("SQLURL", SqlConfig.SQLURL)
    SQLPORT = os.getenv("SQLPORT", SqlConfig.SQLPORT)
    SQLUSER = os.getenv("SQLUSER", SqlConfig.SQLUSER)
    SQLPASSWORD = os.getenv("SQLPASSWORD", "")
    DATABASE_URL = os.getenv("DATABASE_URL")
    PUBLIC_KEY_PATH = os.getenv("PUBLIC_KEY_PATH", KeyConfig.PUBLIC_KEY_PATH)
    PRIVATE_KEY_PATH = os.getenv("PRIVATE_KEY_PATH", KeyConfig.PRIVATE_KEY_PATH)

    # 默认使用 MySQL；若指定 DATABASE_URL，则优先使用它，便于本地部署或测试切换到 SQLite。
    if DATABASE_URL:
        SQLALCHEMY_DATABASE_URI = DATABASE_URL
    else:
        auth = f":{SQLPASSWORD}" if SQLPASSWORD else ""
        SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{SQLUSER}{auth}@{SQLURL}:{SQLPORT}/{SQLNAME}?charset=utf8mb4"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv("SECRET_KEY", "dev")
    # SSL / HTTPS (development toggle)
    # Set ENABLE_SSL=false to disable HTTPS in development. 默认开了启，除非明确设置为 false（字符串）。--- IGNORE ---
    SSL_ENABLED = os.getenv("ENABLE_SSL", "true").lower() == "true"
    # P这些都是相对于web根目录存的/certs/localhost.pem。与现有架构有出入 可调整
    SSL_CERT_PATH = os.getenv("SSL_CERT_PATH", "certs/localhost.pem")
    SSL_KEY_PATH = os.getenv("SSL_KEY_PATH", "certs/localhost-key.pem")
    # 容器自动清理阈值（天）。这里只用于计算和展示，不在此处执行实际清理动作。
    CONTAINER_CLEANUP_AFTER_DAYS = int(os.getenv("CONTAINER_CLEANUP_AFTER_DAYS", "7"))


def get_config(env: str | None = None):
    """
    返回用于 Flask app.config.from_object 的配置类。
    目前仅提供单一配置，如需可根据 env 扩展。
    """
    return AppConfig
