"""Ctrl ↔ Node 传输层抽象。

设计目标：WSS 迁移时的"可换壳"。
- 消息层协议（HTTPS + TLS 承载身份，check_keys 信封已退役）——测试断言不变
- 今天 `HttpNodeLinkTransport` 走 HTTPS POST；WSS 落地后新增
  `WssNodeLinkTransport` 实现同一接口，链路测试文件不用改

接口约定：
    transport.post(endpoint: str, payload: dict, timeout: float) -> dict
    endpoint 形如 "/api/create_container"（不带域名前缀，域是传输层自己的事）
"""
import json

from FuxiYu_CtrKernel.services import container_tasks


class HttpNodeLinkTransport:
    """基于当前 HTTPS + 明文 JSON 的实现（TLS 承载身份）。"""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def post(self, endpoint: str, payload: dict, timeout: float = 5.0) -> dict:
        return container_tasks.send(f"{self.base_url}{endpoint}", payload, timeout=timeout)


# WSS 迁移占位：届时实现
# class WssNodeLinkTransport:
#     def __init__(self, wss_url: str): ...
#     def post(self, endpoint: str, payload: dict, timeout: float = 5.0) -> dict:
#         # 同一消息层协议，换成 WS 帧收发
#         ...
