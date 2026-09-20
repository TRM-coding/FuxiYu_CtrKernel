import logging
import os
import re
import sys
from logging.handlers import TimedRotatingFileHandler


_CONFIGURED = False


class _StreamToLogger:
    def __init__(self, logger: logging.Logger, level: int):
        self.logger = logger
        self.level = level
        self._buffer = ""

    def write(self, message: str) -> int:
        self._buffer += message
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line:
                self.logger.log(self.level, line)
        return len(message)

    def flush(self) -> None:
        if self._buffer:
            self.logger.log(self.level, self._buffer)
            self._buffer = ""

    def isatty(self) -> bool:
        return False


class _HeartbeatAccessFilter(logging.Filter):
    """过滤 Node 心跳的 uvicorn access 行（每 5s ×2 端点刷屏，值接近零）。"""

    _HEARTBEAT_RE = re.compile(r'"(?:GET|POST|PUT|DELETE|PATCH) /api/internal/runtime/')

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            return not self._HEARTBEAT_RE.search(record.getMessage())
        except Exception:
            return True


class _UvicornStreamToLogger(_StreamToLogger):
    """Map uvicorn stderr lines back to their textual log level."""

    _LEVEL_RE = re.compile(r"^\s*(?P<level>TRACE|DEBUG|INFO|WARNING|ERROR|CRITICAL):\s+(?P<message>.*)$")
    _LEVELS = {
        "TRACE": logging.DEBUG,
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }

    def _emit_line(self, line: str) -> None:
        match = self._LEVEL_RE.match(line)
        if match:
            self.logger.log(self._LEVELS[match.group("level")], match.group("message"))
            return
        self.logger.log(self.level, line)

    def write(self, message: str) -> int:
        self._buffer += message
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line:
                self._emit_line(line)
        return len(message)

    def flush(self) -> None:
        if self._buffer:
            self._emit_line(self._buffer)
            self._buffer = ""


def pump_child_output(process, *, logger_name: str = "FuxiYu_CtrKernel.run.wss") -> None:
    """把子进程的输出**逐行原样**搬进本进程的 logger，直到它退出（读到 EOF）。

    ★ 用途：run.py 拉起的链路旁挂进程**不再自己配文件日志**——它的 stdout/stderr 由
    `subprocess.PIPE` 接到这里，走本进程那**唯一**的 handler 落地。此前两个进程各持一个
    `TimedRotatingFileHandler` 写同一个 `ctrl.log`：谁先轮转就把这个公共文件改名，另一个
    进程的 fd 跟着 inode 走、从此写进改名后的老文件（2026-09 实测：`ctrl.log` 里再也看不到
    访问日志，且文件名与内容错位一天，两个 handler 还会互相覆盖、互相清理）。
    **一个日志文件只能有一个轮转者。**

    ★ 逐行原样转交：不改写、不筛选、**不解析级别**。行里带不带时间戳/模块名，由
    **子进程自己的 formatter** 决定——受看护时它发 `级别 + 消息`（见
    `run_node_links._configure_runtime`），时间戳与模块名由主进程的 handler 统一补。
    这样"日志该长什么样"只有一个决定点；在这里翻译格式就会变成两个决定点，
    子进程格式一变这里就静默降级。

    ★ 注意级别在这里是**文本**、不是记录级别：搬运统一按 INFO 记。所以行里的
    `ERROR` 能被 `grep` 到，但主进程那侧按级别做的过滤（`CTRL_LOG_LEVEL`）认不出它。

    ★ 必须有人一直读：管道写满之后子进程会**阻塞在写日志上**，表现为"链路莫名其妙不动了"。
    所以它要跑在独立的守护线程里，随子进程退出（EOF）自然结束。
    """
    stream = getattr(process, "stdout", None)
    if stream is None:
        return
    logger = logging.getLogger(logger_name)
    try:
        for line in stream:
            if isinstance(line, (bytes, bytearray)):
                line = line.decode("utf-8", errors="replace")
            line = line.rstrip("\r\n")
            if line:
                logger.info("%s", line)
    except Exception:
        # 读取失败（子进程被杀、管道异常）只该让搬运停下，不该影响主进程
        pass
    finally:
        try:
            stream.close()
        except Exception:
            pass


def configure_daily_logging(app) -> None:
    global _CONFIGURED

    app_logger = getattr(app, "logger", logging.getLogger("FuxiYu_CtrKernel"))
    app_logger.handlers = []
    app_logger.propagate = True

    if _CONFIGURED:
        try:
            app._daily_logging_configured = True
        except Exception:
            pass
        return

    base_dir = os.path.dirname(os.path.abspath(os.path.join(__file__, "..")))
    log_dir = os.getenv("CTRL_LOG_DIR", os.path.join(base_dir, "logs"))
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, os.getenv("CTRL_LOG_FILE", "ctrl.log"))
    backup_count = int(os.getenv("CTRL_LOG_BACKUP_COUNT", "30"))
    level_name = os.getenv("CTRL_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=backup_count,
        encoding="utf-8",
        utc=False,
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    file_handler.suffix = "%Y-%m-%d"

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(file_handler)

    logging.getLogger("werkzeug").setLevel(level)

    sys.stdout = _StreamToLogger(logging.getLogger("stdout"), logging.INFO)
    sys.stderr = _UvicornStreamToLogger(logging.getLogger("stderr"), logging.ERROR)
    logging.getLogger("stdout").addFilter(_HeartbeatAccessFilter())

    _CONFIGURED = True
    try:
        app._daily_logging_configured = True
    except Exception:
        pass
