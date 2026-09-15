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


def _arm_parent_death_signal() -> None:
    """孤儿防护（数据通路对账契约 C9 补强）：父进程消失时随其退出。

    主进程可能以任何方式消失——SIGKILL、OOM、终端关闭——run.py 的 finally 收尾
    根本没有机会执行，子进程会以孤儿身份残留，还带着启动时的旧代码继续拨号落库
    （schema 变更后这类残留会持续报 Unknown column）。prctl(PR_SET_PDEATHSIG)
    让内核在父进程死亡那一刻投递 SIGTERM，不依赖任何收尾代码。

    只在受 run.py 看护启动时启用（环境标记）；手工启动不受影响，免得 shell
    一退出就误杀调试中的进程。
    """
    if os.getenv("FUXI_CTRL_SUPERVISED") != "1":
        return
    try:
        import ctypes
        import signal as _signal

        PR_SET_PDEATHSIG = 1  # linux/prctl.h
        libc = ctypes.CDLL("libc.so.6")
        if libc.prctl(PR_SET_PDEATHSIG, _signal.SIGTERM, 0, 0, 0) != 0:
            return
    except Exception:
        return
    # prctl 注册与父进程死亡之间存在竞态：父进程可能恰好在这两步之间退出。
    # 补一次显式核对（PPID 已被 init 收养 = 已孤儿，直接退出）。
    if os.getppid() == 1:
        os._exit(0)


if __name__ == "__main__":
    _arm_parent_death_signal()
    _configure_runtime()
    try:
        asyncio.run(_run_links())
    except KeyboardInterrupt:
        pass
