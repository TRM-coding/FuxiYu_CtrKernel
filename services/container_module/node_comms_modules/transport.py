from __future__ import annotations

import logging
import os
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


def _post_node_json(url: str, payload: dict, timeout: float, cert, verify):
    # verify 是 pin 文件路径时（已接入的机器）走自定义适配器；False 时（尚未 pin 的
    # TOFU 过渡态）保持原生行为。
    if isinstance(verify, str):
        session = requests.Session()
        session.mount("https://", _PinnedNodeAdapter(verify))
        try:
            return session.post(url, json=payload, timeout=timeout, cert=cert)
        finally:
            session.close()
    return requests.post(url, json=payload, timeout=timeout, cert=cert, verify=verify)


def _decode_node_response(response) -> dict:
    # Keep Node's structured error reason even on 4xx/5xx responses.
    try:
        result = response.json()
        if isinstance(result, dict):
            result.setdefault("status_code", response.status_code)
        return result
    except ValueError:
        return {"status_code": response.status_code, "text": response.text}
