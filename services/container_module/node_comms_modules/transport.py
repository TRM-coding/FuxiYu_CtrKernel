from __future__ import annotations

import hashlib
import logging
import os
import socket
import ssl
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter


logger = logging.getLogger(__name__)
PINNED_CERTS_DIR = os.getenv(
    "CTRL_PINNED_CERTS_DIR",
    str(Path(__file__).resolve().parents[3] / "pinned_certs"),
)

def _pin_file(machine_ip: str) -> Path:
    return Path(PINNED_CERTS_DIR) / f"{machine_ip}.pem"


# 节点是局域网端点：环境里的 http_proxy/https_proxy 不该介入 Ctrl → Node 的出站。
# 代理一旦生效，requests 会改走 ProxyManager，`_PinnedNodeAdapter` 钉在 poolmanager 上的
# ssl_context/assert_hostname 全被绕过、cert_verify 又把 ca_certs 退回 certifi —— pin 就此
# 失效，而报错仍是 `self-signed certificate`（证书与 pin 其实一字不差，诊断会说"指纹一致"）。
# 必须把 scheme 键显式置 None：**只传空字典挡不住环境代理**（requests 用 setdefault 合并）。
_DIRECT_PROXIES = {"http": None, "https": None}

def _resolve_tls(url: str, cert=None, verify=None):
    """解析 send 的 TLS 参数。

    - cert 默认 Ctrl 客户端证书（cert_utils 已生成时）
    - verify 默认对端 pin 文件（按 URL 的 host 定位）；未接入（未 pin）时降级
      verify=False（TOFU 过渡，警告）
    """
    host = url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    if cert is None:
        from ....utils.cert_utils import ctrl_certificate_paths
        paths = ctrl_certificate_paths()
        if paths.cert_file.exists() and paths.key_file.exists():
            cert = (str(paths.cert_file), str(paths.key_file))
    if verify is None:
        pin = _pin_file(host)
        if pin.exists():
            verify = str(pin)
        else:
            logger.warning("send to %s: no pinned cert (machine not enrolled yet); TLS verify disabled", host)
            verify = False
    return cert, verify


############################################################
# TLS 失败诊断（动作通道的"读得懂"报错）
############################################################

def _split_netloc(url: str) -> tuple[str, int]:
    """URL → (host, port)。仅用于诊断连接，不参与正常请求组装。"""

    netloc = url.split("://", 1)[-1].split("/", 1)[0]
    host, _, port_str = netloc.partition(":")
    try:
        port = int(port_str)
    except ValueError:
        port = 443
    return host, port


def _peer_cert_fingerprint(url: str, timeout: float = 5.0) -> str | None:
    """**不信任何证书**地握一次手，取对端当前出示证书的 SHA-256 指纹（诊断用）。

    只在链校验失败后被调用：此时正常路径已经走不通，需要一个不设前提的取样，
    才能回答"它现在拿的是哪张证书"。
    """

    host, port = _split_netloc(url)
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        # 必须带上本端客户端证书：Node 侧配了 CTRL_CA 就要求 mTLS，裸握手会被直接拒，
        # 那样取样永远失败、诊断只会说"取不到指纹"——把真正的原因盖住。
        from ....utils.cert_utils import ctrl_certificate_paths
        paths = ctrl_certificate_paths()
        if paths.cert_file.exists() and paths.key_file.exists():
            ctx.load_cert_chain(certfile=str(paths.cert_file), keyfile=str(paths.key_file))
        with ctx.wrap_socket(
            socket.create_connection((host, port), timeout=timeout), server_hostname=host,
        ) as sock:
            der = sock.getpeercert(binary_form=True)
    except Exception as exc:  # pragma: no cover - 诊断失败不该盖住原错误
        logger.debug("diagnose peer cert failed for %s: %s", url, exc)
        return None
    return hashlib.sha256(der).hexdigest() if der else None


def _pin_cert_fingerprint(verify) -> str | None:
    """pin 文件里那张证书的 SHA-256 指纹。"""

    if not isinstance(verify, str):
        return None
    try:
        der = ssl.PEM_cert_to_DER_cert(Path(verify).read_text())
    except Exception as exc:  # pragma: no cover
        logger.debug("diagnose pin cert failed for %s: %s", verify, exc)
        return None
    return hashlib.sha256(der).hexdigest()


def describe_cert_mismatch(url: str, verify) -> str:
    """链校验失败后，把两组指纹并排给出——这决定了下一步该做什么。

    **对端指纹 ≠ pin 指纹**：Node 换过证书（自签名证书被重新生成）。Ctrl 手里的信任锚
    已作废 → 需要**重新建立信任**（修复连接），而不是重试。

    **两者相同**：证书没变，失败另有原因（例如 pin 文件本身损坏）→ 不该去按修复连接。

    没有这组信息时，操作员只能看到一句 `self-signed certificate`，无从判断是"该重新
    装订"还是"别的东西坏了"——这正是本函数存在的理由。
    """

    live = _peer_cert_fingerprint(url)
    pinned = _pin_cert_fingerprint(verify)
    if live is None:
        return "（诊断：取不到对端证书指纹，对端可能不可达或未启用 TLS）"
    if pinned is None:
        return f"（诊断：对端指纹={live[:16]}…，但取不到 pin 指纹）"
    if live == pinned:
        return (
            f"（诊断：对端与 pin 指纹一致 {live[:16]}… —— 证书没变，"
            "失败另有原因，不要按「修复连接」）"
        )
    return (
        f"（诊断：对端证书已变 —— 对端={live[:16]}… pin={pinned[:16]}…；"
        "Node 重新生成过自签名证书，Ctrl 的信任锚已作废 → 请点「修复连接」重新建立信任）"
    )


class _PinnedNodeAdapter(HTTPAdapter):
    """以 pin 为信任锚校验对端证书，但**不做主机名校验**。

    口径与链路侧 `link.build_link_ssl_context` 一致：pin 是那台 Node 的自签证书本身，
    链校验通过即证明对端持有那把私钥——身份由**密钥**确定，与"用哪个名字拨过去"无关。
    公共 CA 模型下 hostname 校验是承重的（一个 CA 给很多名字签证书）；这里信任锚只有
    一张证书，它既不增加信息，又会在端点变化时误杀——而端点可变正是本系统的常态
    （IP 与端口都可改，见 per-machine-node-port）。

    urllib3 v2 另有一道独立于 ssl 模块的 hostname 匹配，故 `assert_hostname` 也要关：
    只设 `context.check_hostname = False` 仍会被它拦下。
    """

    def __init__(self, pin_path: str, **kwargs):
        self._pin_path = pin_path
        super().__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context(cafile=self._pin_path)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_REQUIRED
        kwargs["ssl_context"] = context
        kwargs["assert_hostname"] = False
        return super().init_poolmanager(*args, **kwargs)

    def cert_verify(self, conn, url, verify, cert):
        """本适配器自己就是 TLS 策略，不让 requests 再往连接上写信任锚。

        requests 的默认实现在 verify 为真时把 ca_certs 设成 certifi 公共 CA 包，urllib3 随后
        （ssl_wrap_socket）把它 load 进本适配器已装好 pin 的 context——信任锚于是变成
        「pin ∪ 122 张公共 CA」。而本适配器**关掉了 hostname 校验**，公共 CA 那条路没有任何
        名字约束：任何一张公共 CA 签发的证书都能冒充该 Node，pin 就不再是唯一信任锚了。
        客户端证书不在此处补：`_urllib3_request_context` 已把它作为请求级 pool_kwargs 的
        cert_file/key_file 交给连接池，建连接时自然带上（见本模块的防代理用例）。
        """


def _post_node_json(url: str, payload: dict, timeout: float, cert, verify):
    # verify 是 pin 文件路径时（已接入的机器）走自定义适配器；False 时（尚未 pin 的
    # TOFU 过渡态）保持原生行为。
    if isinstance(verify, str):
        session = requests.Session()
        session.mount("https://", _PinnedNodeAdapter(verify))
        try:
            return session.post(url, json=payload, timeout=timeout, cert=cert, proxies=_DIRECT_PROXIES)
        finally:
            session.close()
    return requests.post(url, json=payload, timeout=timeout, cert=cert, verify=verify,
                         proxies=_DIRECT_PROXIES)


def _decode_node_response(response) -> dict:
    # Keep Node's structured error reason even on 4xx/5xx responses.
    try:
        result = response.json()
        if isinstance(result, dict):
            result.setdefault("status_code", response.status_code)
        return result
    except ValueError:
        return {"status_code": response.status_code, "text": response.text}
