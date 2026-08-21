"""Ctrl WSS 接收服务。"""

import logging
import os
import ssl
import threading
import time

from fastapi import FastAPI, WebSocket

WSS_PORT = int(os.getenv("CTRL_WSS_PORT", "5001"))


def _build_ssl_context():
    """构建 WSS TLS context，并加载已 pin 的 Node 证书链。"""

    from FuxiYu_CtrKernel.utils.cert_utils import ctrl_certificate_paths, ensure_ctrl_certificates
    from FuxiYu_CtrKernel.services.container_module.node_comms import rebuild_pinned_chain

    ensure_ctrl_certificates()
    paths = ctrl_certificate_paths()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(paths.cert_file), str(paths.key_file))
    chain = rebuild_pinned_chain()
    if chain is None:
        logging.getLogger(__name__).warning(
            "no pinned Node certs yet; client cert verification is disabled until enrollment"
        )
    else:
        ctx.load_verify_locations(str(chain))
        if hasattr(ssl, "VERIFY_X509_PARTIAL_CHAIN"):
            ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
        ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def _marker_mtime(marker) -> float:
    """读取 WSS reload marker 的更新时间；不存在则返回 0。"""

    try:
        return marker.stat().st_mtime
    except OSError:
        return 0.0


def create_wss_app(overrides: dict | None = None) -> FastAPI:
    """创建 WSS 接收应用；overrides 保留给测试入口。"""

    app = FastAPI(title="FuxiYu CtrlKernel WSS Receiver")

    from FuxiYu_CtrKernel.services.container_module.node_comms import handle_node_ws

    @app.websocket("/ws/node")
    async def ws_node(websocket: WebSocket):
        await handle_node_ws(websocket)

    return app


if __name__ == "__main__":
    import uvicorn

    logger = logging.getLogger(__name__)

    while True:
        from FuxiYu_CtrKernel.services.container_module.node_comms import wss_reload_marker

        marker = wss_reload_marker()
        marker_mtime = _marker_mtime(marker)
        app = create_wss_app()
        ctx = _build_ssl_context()
        reload_requested = {"value": False}

        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=WSS_PORT,
            ssl_context_factory=lambda _config, _default: ctx,
        )
        server = uvicorn.Server(config)

        def _watch_reload_marker() -> None:
            """监听 register_machine 写入的 marker，触发 WSS 自动重启。"""

            while not server.should_exit:
                time.sleep(float(os.getenv("CTRL_WSS_RELOAD_POLL_SECONDS", "2")))
                current_mtime = _marker_mtime(marker)
                if current_mtime > marker_mtime:
                    logger.warning("WSS reload marker changed; restarting WSS receiver to reload pinned certs")
                    reload_requested["value"] = True
                    server.should_exit = True
                    return

        threading.Thread(target=_watch_reload_marker, daemon=True).start()
        server.run()
        if not reload_requested["value"]:
            break
        time.sleep(0.5)
