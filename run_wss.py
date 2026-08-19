"""Ctrl WSS 接收服务（旁挂 uvicorn 实例）。

Node → Ctrl `/ws/node` 接收端点，独立端口运行，TLS **客户端证书校验（REQUIRED）**：
- 主 API uvicorn（CTRL_PORT，默认 5000）不能开 REQUIRED——浏览器前端不带客户端证书；
- 本实例只服务 /ws/node，Node 必须持有已 pin 的自签证书私钥才能握手（传输层凭据）。
- 应用层再校验 ?uid= 归位 machine 记录（双凭据）。

落库需 Flask app context：旁挂实例桥接进 Ctrl 的 Flask runtime（repositories 零改动）。
"""
import os
import ssl

from fastapi import FastAPI

WSS_PORT = int(os.getenv("CTRL_WSS_PORT", "5001"))


def _flask_runtime(overrides: dict | None = None):
    """延迟获取 Ctrl Flask runtime（避免模块级循环 import）。

    *overrides* 透传给 runtime（测试注入 SQLite 等）；生产旁挂不传 → 真实配置。
    """
    from FuxiYu_CtrKernel import _create_flask_runtime_app
    return _create_flask_runtime_app(None, overrides, register_legacy_routes=False)


def _build_ssl_context():
    """WSS ssl context：Ctrl 证书 + REQUIRED + ca_certs=pin chain（Node 自签即信任锚）。"""
    from FuxiYu_CtrKernel.utils.cert_utils import ctrl_certificate_paths, ensure_ctrl_certificates
    from FuxiYu_CtrKernel.services.container_module.node_comms import rebuild_pinned_chain

    ensure_ctrl_certificates()
    paths = ctrl_certificate_paths()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(paths.cert_file), str(paths.key_file))
    chain = rebuild_pinned_chain()
    if chain is None:
        import logging
        logging.getLogger(__name__).warning(
            "no pinned Node certs yet — REQUIRED disabled; Node must enroll before secure WSS")
    else:
        ctx.load_verify_locations(str(chain))
        ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def create_wss_app(overrides: dict | None = None) -> FastAPI:
    """创建 WSS 接收应用（挂 /ws/node → node_comms.handle_node_ws）。

    *overrides* 透传给 Flask runtime（测试注入 SQLite 等）。
    """
    app = FastAPI(title="FuxiYu CtrlKernel WSS Receiver")
    flask_app = _flask_runtime(overrides)

    from FuxiYu_CtrKernel.services.container_module.node_comms import handle_node_ws

    @app.websocket("/ws/node")
    async def ws_node(websocket):
        # apply_* 落库用 db.session —— 长连接持有 Flask app context 桥接
        with flask_app.app_context():
            await handle_node_ws(websocket)

    return app


if __name__ == "__main__":
    import uvicorn

    app = create_wss_app()
    ctx = _build_ssl_context()
    uvicorn.run(app, host="0.0.0.0", port=WSS_PORT, ssl=ctx)
