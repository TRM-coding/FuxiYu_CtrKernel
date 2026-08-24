"""应用配置模块

提供不同环境的配置类，支持通过环境变量覆盖默认值。
网络配置采用三仓库统一键名：只填裸 IP 与端口，其余自动组装。
"""

import os


def _env_int(name: str, default: int) -> int:
    """读取整数型环境变量，空值/非法值回退默认。"""
    raw = os.getenv(name, "")
    if raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class SqlConfig:
    SQLNAME = "fuxi"
    SQLURL = "127.0.0.1"
    SQLPORT = "3306"
    SQLUSER = "fuxi_app"


class KeyConfig:
    PUBLIC_KEY_PATH = "public_A.pem"
    PRIVATE_KEY_PATH = "private_A.pem"
    PUBLIC_KEY_NODE = "public_node.pem"


class CommsConfig:
    # Node 端口（统一键名 NODE_PORT）；Ctrl 组装各宿主机 URL 时拼接
    NODE_PORT = _env_int("NODE_PORT", 5789)
    NODE_URL_MIDDLE = f":{NODE_PORT}/api"
    # WSS 接收 read 超时（半开连接防护；数据通路对账契约 C4）。健康态 Node 每 5s 一帧，
    # 30s 超时只打半开连接（Node 断电无 FIN/RST），超时走探活判离线。
    WSS_READ_TIMEOUT = _env_int("CTRL_WSS_READ_TIMEOUT", 30)


class NetConfig:
    """三仓库统一网络键名。分发时只改这几个值。"""
    CTRL_IP = os.getenv("CTRL_IP", "127.0.0.1")
    CTRL_PORT = _env_int("CTRL_PORT", 5000)
    WEB_IP = os.getenv("WEB_IP", "127.0.0.1")
    WEB_PORT = _env_int("WEB_PORT", 5173)


def build_allowed_origins() -> list[str]:
    """统一生成 CORS 允许列表。

    - 只枚举 https 变体（Web 强制 https，http 由部署层 301 重定向）
    - 同时放行 WEB_IP、127.0.0.1、localhost 三种写法（分发机 IP 与本地开发并存）
    - 尾斜杠归一化：Origin 有时带尾斜杠，生成时统一去掉，避免精确匹配漏判
    """
    ips = sorted({NetConfig.WEB_IP, "127.0.0.1", "localhost"})
    origins = [f"https://{ip}:{NetConfig.WEB_PORT}" for ip in ips]
    return [o.rstrip("/") for o in origins]


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
    # 锁死 MySQL session 时区为 UTC，不受系统时区切换影响（SQLite 跳过以兼容测试）
    _connect_args = {}
    if SQLALCHEMY_DATABASE_URI and "mysql" in SQLALCHEMY_DATABASE_URI:
        _connect_args["init_command"] = "SET time_zone = '+00:00'"
    SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": _connect_args}
    SECRET_KEY = os.getenv("SECRET_KEY", "dev")
    # SSL / HTTPS (development toggle)
    # Set ENABLE_SSL=false to disable HTTPS in development. 默认开了启，除非明确设置为 false（字符串）。--- IGNORE ---
    SSL_ENABLED = os.getenv("ENABLE_SSL", "true").lower() == "true"
    # Ctrl HTTPS 默认读取本仓库 certs/ 下的 ctrl.pem / ctrl-key.pem。
    SSL_CERT_PATH = os.getenv("SSL_CERT_PATH", "certs/ctrl.pem")
    SSL_KEY_PATH = os.getenv("SSL_KEY_PATH", "certs/ctrl-key.pem")
    # 容器自动清理阈值（天）。这里只用于计算和展示，不在此处执行实际清理动作。
    CONTAINER_CLEANUP_AFTER_DAYS = int(os.getenv("CONTAINER_CLEANUP_AFTER_DAYS", "7"))
    # 每个用户最多可设置的长期容器数量。
    LONG_TERM_CONTAINER_LIMIT = int(os.getenv("LONG_TERM_CONTAINER_LIMIT", "1"))
    # 容器清理前邮件提醒节点，单位小时，逗号分隔。
    CONTAINER_CLEANUP_REMINDER_HOURS = os.getenv("CONTAINER_CLEANUP_REMINDER_HOURS", "72,24,12")
    # NodeKernel 并发请求线程池大小上限。
    NODE_REQUEST_POOL_SIZE = int(os.getenv("NODE_REQUEST_POOL_SIZE", "8"))
    # 并发化开关，通过环境变量可独立开关。
    NODE_PARALLEL_ENABLED_MACHINES = os.getenv("NODE_PARALLEL_ENABLED_MACHINES", "true").lower() == "true"
    NODE_PARALLEL_ENABLED_CONTAINERS = os.getenv("NODE_PARALLEL_ENABLED_CONTAINERS", "true").lower() == "true"
    NODE_PARALLEL_ENABLED_SSH_REFRESH = os.getenv("NODE_PARALLEL_ENABLED_SSH_REFRESH", "true").lower() == "true"
    # 容器磁盘检测配置（Phase 1: 只读，默认关闭）
    CONTAINER_DISK_CHECK_ENABLED = os.getenv("CONTAINER_DISK_CHECK_ENABLED", "false").lower() == "true"
    CONTAINER_DISK_CHECK_INTERVAL_SECONDS = int(os.getenv("CONTAINER_DISK_CHECK_INTERVAL_SECONDS", "900"))
    CONTAINER_DISK_SOFT_LIMIT_PERCENT = int(os.getenv("CONTAINER_DISK_SOFT_LIMIT_PERCENT", "80"))
    CONTAINER_DISK_HARD_LIMIT_PERCENT = int(os.getenv("CONTAINER_DISK_HARD_LIMIT_PERCENT", "100"))
    CONTAINER_DISK_RESPONSE_ENABLED = os.getenv("CONTAINER_DISK_RESPONSE_ENABLED", "false").lower() == "true"
    # 磁盘超限冻结升级配置（Phase 5-6）
    CONTAINER_DISK_FREEZE_ESCALATION_DAYS = int(
        os.getenv("CONTAINER_DISK_FREEZE_ESCALATION_DAYS", "7")
    )
    CONTAINER_DISK_FREEZE_GRACE_DAYS = int(
        os.getenv("CONTAINER_DISK_FREEZE_GRACE_DAYS", "3")
    )
    CONTAINER_DISK_FREEZE_RESET_PERCENT = int(
        os.getenv("CONTAINER_DISK_FREEZE_RESET_PERCENT", "95")
    )
    # 已删除容器 mount 清理配置（Phase 8）
    CONTAINER_MOUNT_CLEANUP_ENABLED = os.getenv(
        "CONTAINER_MOUNT_CLEANUP_ENABLED", "false"
    ).lower() == "true"
    CONTAINER_MOUNT_CLEANUP_INTERVAL_SECONDS = int(
        os.getenv("CONTAINER_MOUNT_CLEANUP_INTERVAL_SECONDS", "86400")
    )
    CONTAINER_MOUNT_CLEANUP_AFTER_DAYS = int(
        os.getenv("CONTAINER_MOUNT_CLEANUP_AFTER_DAYS", "14")
    )
    # 公告系统配置
    ANNOUNCEMENT_MAX_RECIPIENTS = int(os.getenv("ANNOUNCEMENT_MAX_RECIPIENTS", "200"))
    ANNOUNCEMENT_SEND_COOLDOWN_SECONDS = int(os.getenv("ANNOUNCEMENT_SEND_COOLDOWN_SECONDS", "60"))
    ANNOUNCEMENT_BATCH_SEND_MAX = int(os.getenv("ANNOUNCEMENT_BATCH_SEND_MAX", "20"))


def get_config(env: str | None = None):
    """
    返回应用运行配置类。
    目前仅提供单一配置，如需可根据 env 扩展。
    """
    return AppConfig
