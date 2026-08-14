"""Ctrl ↔ Node 传输层抽象。

设计目标：WSS 迁移时的"可换壳"。
- 消息层协议（加密 + 签名 + 请求/响应语义）不变，测试断言不变
- 今天 `HttpNodeLinkTransport` 走 HTTP POST；WSS 落地后新增
  `WssNodeLinkTransport` 实现同一接口，链路测试文件不用改

接口约定：
    transport.post(endpoint: str, payload: dict, timeout: float) -> dict
    endpoint 形如 "/api/create_container"（不带域名前缀，域是传输层自己的事）
"""
import json

from FuxiYu_CtrKernel.services import container_tasks
from FuxiYu_CtrKernel.utils.CheckKeys import encryption, signature


class HttpNodeLinkTransport:
    """基于当前 HTTP + RSA/AES 消息层协议的实现。"""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def post(self, endpoint: str, payload: dict, timeout: float = 5.0) -> dict:
        raw = json.dumps(payload)
        enc = encryption(raw)
        sig = signature(raw)
        # container_tasks.send 的内部 wire 格式就是 {"message": b64, "signature": b64}
        return container_tasks.send(enc, sig, f"{self.base_url}{endpoint}", timeout=timeout)


# WSS 迁移占位：届时实现
# class WssNodeLinkTransport:
#     def __init__(self, wss_url: str): ...
#     def post(self, endpoint: str, payload: dict, timeout: float = 5.0) -> dict:
#         # 同一消息层协议，换成 WS 帧收发
#         ...
