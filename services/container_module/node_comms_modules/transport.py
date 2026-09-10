from __future__ import annotations

import logging
import os
from pathlib import Path

import requests


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


def _post_node_json(url: str, payload: dict, timeout: float, cert, verify):
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
