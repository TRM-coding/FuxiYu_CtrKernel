import os
import signal
import subprocess
import sys
from importlib import import_module

import uvicorn

pkg_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(pkg_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from FuxiYu_CtrKernel.config import AppConfig

package_name = os.path.basename(pkg_dir)
create_app = import_module(package_name).create_app

app = create_app()


def _truthy_env(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes", "on"}


def _start_wss_receiver() -> subprocess.Popen | None:
    """启动 Ctrl WSS 接收旁挂。

    WSS 是 Node -> Ctrl 状态主链路；`python run.py` 必须同时拉起接收端，
    否则 Node 会持续连接 5001 失败，状态无法落库。
    """

    if not _truthy_env("CTRL_WSS_ENABLED", "1"):
        return None

    env = os.environ.copy()
    env.setdefault("CTRL_WSS_PORT", "5001")
    pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = parent_dir if not pythonpath else f"{parent_dir}{os.pathsep}{pythonpath}"

    return subprocess.Popen(
        [sys.executable, "-m", "FuxiYu_CtrKernel.run_wss"],
        cwd=pkg_dir,
        env=env,
    )


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

    wss_process = _start_wss_receiver()
    try:
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=int(os.getenv("CTRL_PORT", "5000")),
            reload=False,
            **ssl_kwargs,
        )
    finally:
        _stop_process(wss_process)
