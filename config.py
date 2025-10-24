"""应用配置模块

提供不同环境的配置类，支持通过环境变量覆盖默认值。
"""

import os


class SqlConfig:
    SQLNAME='fuxi'
    SQLURL='127.0.0.1'
    SQLPORT='3306'
    SQLUSER='root'

class KeyConfig:
    PUBLIC_KEY_PATH='public_A.pem'
    PRIVATE_KEY_PATH='private_A.pem'

# 新增：统一的 AppConfig 和 get_config
class AppConfig(SqlConfig, KeyConfig):
    # 允许通过环境变量覆盖
    SQLNAME = os.getenv("SQLNAME", SqlConfig.SQLNAME)
    SQLURL = os.getenv("SQLURL", SqlConfig.SQLURL)
    SQLPORT = os.getenv("SQLPORT", SqlConfig.SQLPORT)
    SQLUSER = os.getenv("SQLUSER", SqlConfig.SQLUSER)
    PUBLIC_KEY_PATH = os.getenv("PUBLIC_KEY_PATH", KeyConfig.PUBLIC_KEY_PATH)
    PRIVATE_KEY_PATH = os.getenv("PRIVATE_KEY_PATH", KeyConfig.PRIVATE_KEY_PATH)

    # 使用本地 MySQL（root 无密码）
    SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{SQLUSER}@{SQLURL}:{SQLPORT}/{SQLNAME}?charset=utf8mb4"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv("SECRET_KEY", "dev")

def get_config(env: str | None = None):
    """
    返回用于 Flask app.config.from_object 的配置类。
    目前仅提供单一配置，如需可根据 env 扩展。
    """
    return AppConfig