"""Ctrl Node 链路管理进程。

Ctrl 主动拨各 Node 的 `/ws/ctrl` 端点取快照。本进程是常驻旁挂：把 N 条出站
长连接挡在 API 主进程之外，主进程只负责它的存活（见 schedulers/wss_supervisor）。
"""

import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

_DOTENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_DOTENV_PATH, override=True)


def _configure_runtime() -> None:
    """配置链路进程运行上下文。

    旁挂进程必须显式加载同一套 DB 与日志配置，避免和 API 主进程读到不同的
    相对路径数据库，也避免链路错误只落在终端。
    """

    from FuxiYu_CtrKernel.config import AppConfig
    from FuxiYu_CtrKernel.extensions import configure_database
    from FuxiYu_CtrKernel.utils.logging_config import configure_daily_logging

    configure_database(AppConfig.SQLALCHEMY_DATABASE_URI)
    configure_daily_logging(AppConfig)
    logging.getLogger(__name__).info(
        "Ctrl node link runtime configured: cwd=%s database=%s",
        os.getcwd(),
        AppConfig.SQLALCHEMY_DATABASE_URI,
    )


async def _run_links() -> None:
    from FuxiYu_CtrKernel.services.container_module.node_comms import run_links_forever

    await run_links_forever()


if __name__ == "__main__":
    _configure_runtime()
    try:
        asyncio.run(_run_links())
    except KeyboardInterrupt:
        pass
