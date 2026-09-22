import os
import signal
import subprocess
import sys
import threading
from importlib import import_module

import uvicorn

pkg_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(pkg_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from FuxiYu_CtrKernel.config import AppConfig
from FuxiYu_CtrKernel.utils.logging_config import pump_child_output

package_name = os.path.basename(pkg_dir)
create_app = import_module(package_name).create_app

app = create_app()


def _truthy_env(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes", "on"}


def _start_wss_receiver() -> subprocess.Popen | None:
    """启动 Node 链路旁挂。

    链路是 Node 状态主通道（Ctrl 主动拨 Node）；`python run.py` 必须同时拉起
    它，否则拿不到任何快照，机器状态无法落库。
    """

    if not _truthy_env("CTRL_WSS_ENABLED", "1"):
        return None

    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = parent_dir if not pythonpath else f"{parent_dir}{os.pathsep}{pythonpath}"
    # 看护标记：run_node_links 只在受本进程看护时启用「随父进程死亡」防护
    # （见 run_node_links._arm_parent_death_signal），手工启动不受影响。
    env["FUXI_CTRL_SUPERVISED"] = "1"

    process = subprocess.Popen(
        [sys.executable, "-m", "FuxiYu_CtrKernel.run_node_links"],
        cwd=pkg_dir,
        env=env,
        # 子进程不再自己开文件日志：它发 `级别 + 消息`，输出逐行搬进本进程的 logger、由本进程
        # 唯一的 handler 补上时间戳与模块名落地（见 pump_child_output）。stderr 并进同一条
        # 管道，行序不乱。
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    # 守护线程：必须一直读到 EOF——管道写满会把子进程卡在写日志上
    threading.Thread(
        target=pump_child_output,
        kwargs={"process": process},
        name="wss-log-pump",
        daemon=True,
    ).start()
    return process


def _stop_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.terminate()
        else:
            process.send_signal(signal.SIGTERM)
        process.wait(timeout=5)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


if __name__ == "__main__":
    ssl_enabled = getattr(AppConfig, "SSL_ENABLED", False)

    ssl_kwargs = {}
    if ssl_enabled:
        from FuxiYu_CtrKernel.utils.cert_utils import ensure_ctrl_certificates

        certs = ensure_ctrl_certificates()
        ssl_kwargs = {"ssl_certfile": str(certs.cert_file), "ssl_keyfile": str(certs.key_file)}

    # Node 链路子进程 + 看护（数据通路对账契约 C9）：主进程对链路存活负责，
    # 意外退出即重启；主进程退出时停掉子进程。
    from FuxiYu_CtrKernel.schedulers.wss_supervisor import watch_wss_process

    wss_process_ref = [None]
    wss_stop_event = threading.Event()
    if _truthy_env("CTRL_WSS_ENABLED", "1"):
        wss_process_ref[0] = _start_wss_receiver()
        threading.Thread(
            target=watch_wss_process,
            args=(wss_process_ref, wss_stop_event, _start_wss_receiver),
            daemon=True,
        ).start()
    try:
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=int(os.getenv("CTRL_PORT", "5000")),
            reload=False,
            **ssl_kwargs,
        )
    finally:
        wss_stop_event.set()
        _stop_process(wss_process_ref[0])
