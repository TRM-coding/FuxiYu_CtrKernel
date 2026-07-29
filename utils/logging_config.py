import logging
import os
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


def configure_daily_logging(app) -> None:
    global _CONFIGURED

    app.logger.handlers = []
    app.logger.propagate = True

    if _CONFIGURED:
        app._daily_logging_configured = True
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
    sys.stderr = _StreamToLogger(logging.getLogger("stderr"), logging.ERROR)

    _CONFIGURED = True
    app._daily_logging_configured = True
