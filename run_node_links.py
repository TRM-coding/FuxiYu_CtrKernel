"""Ctrl Node 链路管理进程。

Ctrl 主动拨各 Node 的 `/ws/ctrl` 端点取快照。本进程是常驻旁挂：把 N 条出站
长连接挡在 API 主进程之外，主进程只负责它的存活（见 schedulers/wss_supervisor）。
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_DOTENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_DOTENV_PATH, override=True)


def _configure_runtime() -> None:
    """配置链路进程运行上下文。

    旁挂进程必须显式加载同一套 DB 配置，避免和 API 主进程读到不同的相对路径数据库。

    ★ **刻意不配文件日志**（2026-09 修）：本进程由 run.py 用 `subprocess.Popen` 拉起，输出
    走管道**原样**搬进主进程的 logger（run.py 里的 `pump_child_output`），由主进程那唯一一份
    handler 落地。此前这里也调用 `configure_daily_logging`，于是**两个进程各持一个
    `TimedRotatingFileHandler` 写同一个 `ctrl.log`**：谁先轮转就把这个公共文件改名，另一个
    进程的 fd 跟着 inode 走、从此写进改名后的老文件。实测后果是"`ctrl.log` 里看不到访问
    日志了"，且文件名与内容错位一天（`...09-18` 装 09-19 的行），两个 handler 还会互相
    覆盖、互相清理。**一个日志文件只能有一个轮转者。**

    下面的 stderr 配置只服务于"手工起这个进程调试"的场景；受看护时它同样被搬进主日志。
    """

    from FuxiYu_CtrKernel.config import AppConfig
    from FuxiYu_CtrKernel.extensions import configure_database

    configure_database(AppConfig.SQLALCHEMY_DATABASE_URI)
    # 只落 stderr：本进程不开文件。受看护时由主进程接管（逐行搬进 ctrl.log），
    # 手工启动时直接落在终端。
    #
    # 格式按运行方式分两档（2026-09 决策）：受看护时**不带时间戳与模块名**（那是主进程的
    # handler 统一补的，自己再带一套就成了两层头），只保留级别——行里没有级别的话，
    # 合并之后 `grep ERROR` 就找不到链路自己的报错了。手工启动时才带全，免得在终端里
    # 看不出是谁在什么时候说的。
    supervised = os.getenv("FUXI_CTRL_SUPERVISED") == "1"
    logging.basicConfig(
        level=os.getenv("CTRL_LOG_LEVEL", "INFO").upper(),
        format="%(levelname)s %(message)s" if supervised
        else "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stderr,
    )
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
