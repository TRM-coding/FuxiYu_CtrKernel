"""机器端点解析（Ctrl → Node 的出站目标）。

三条出站路径——HTTPS 动作请求、WSS 链路拨号、TOFU 取对端证书——都从这里取值，
口径唯一。此前三处各写各的：前两条会自行拆 machine_ip 里的 `host:port`，第三条
直接把全局端口拼在地址之后，写入侧的 pin 键还与读取侧不一致。本模块是那些写法的
唯一落点。

端口来源是机器记录上的 port 列；留空回落全局 `CommsConfig.NODE_PORT`。
全局默认**调用时读取**，不在导入期冻结——否则改了配置对已加载的进程无效，
而且会与另一份派生常量形成两个可漂移的真值来源。
"""

from __future__ import annotations

from ....config import CommsConfig

# Node 操作通道的路径前缀（HTTPS 动作与 enrollment 共用同一个监听）。
NODE_API_PATH = "/api"


def default_node_port() -> int:
    """全局默认 Node 端口。每次调用现读，不缓存、不在导入期冻结。"""

    return int(CommsConfig.NODE_PORT)


def resolve_port(port: int | None) -> int:
    """端口取值的唯一落点：机器列优先，留空回落全局默认。"""

    return int(port) if port else default_node_port()


def bare_host(value: str | None) -> str:
    """取裸主机（不含端口）。

    pin 文件键与 URL 的主机段都用它。对含 `:` 的历史值取冒号前一段——`machine_ip`
    现已不允许携带端口（入口校验拒绝），这里的容错只是不让旧值把整条路径带崩。
    """

    return str(value or "").partition(":")[0]


def resolve_endpoint(machine_ip: str | None, port: int | None) -> tuple[str, int]:
    """(地址列, 端口列) → (裸 host, port)。端口留空回落全局默认。"""

    return bare_host(machine_ip), resolve_port(port)


def machine_endpoint(machine) -> tuple[str, int]:
    """机器记录 → (裸 host, port)。"""

    return resolve_endpoint(
        getattr(machine, "machine_ip", None),
        getattr(machine, "port", None),
    )


def node_api_base(host: str, port: int) -> str:
    """HTTPS 操作通道的 URL 基址。"""

    return f"https://{host}:{port}{NODE_API_PATH}"
