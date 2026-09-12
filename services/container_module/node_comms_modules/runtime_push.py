from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

import requests

from ....config import AppConfig, NetConfig

logger = logging.getLogger(__name__)

def _ctrl_api_internal_origin() -> str:
    scheme = "https" if getattr(AppConfig, "SSL_ENABLED", False) else "http"
    return f"{scheme}://127.0.0.1:{NetConfig.CTRL_PORT}"


def _ctrl_api_internal_verify():
    if not getattr(AppConfig, "SSL_ENABLED", False):
        return False
    try:
        from ....utils.cert_utils import ctrl_certificate_paths

        ca_cert = ctrl_certificate_paths().ca_cert
        if ca_cert.exists():
            return str(ca_cert)
    except Exception as e:
        logger.warning("runtime buffer push: Ctrl CA resolve failed: %s", e)
    logger.warning("runtime buffer push: Ctrl CA missing; TLS verify disabled for loopback runtime push")
    return False


def _internal_token_path() -> Path:
    """内部运行时推送共享 token 文件（API 主进程与 WSS 子进程同机共享，缺失即生成）。"""

    return Path(os.getenv("CTRL_INTERNAL_TOKEN_FILE", "certs/internal_token"))


def _read_internal_token() -> str | None:
    """读内部推送共享 token；文件缺失时原子生成（与证书同模式，零人工配置）。

    create_app 启动时预热（API 先于 WSS 子进程），保证两进程读到同一 token。
    """
    path = _internal_token_path()
    try:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(secrets.token_urlsafe(32), encoding="utf-8")
            os.replace(tmp, path)  # 原子替换，防半写/并发竞态
        token = path.read_text(encoding="utf-8").strip()
        return token or None
    except Exception as e:
        logger.warning("internal token read failed: %s", e)
        return None


def _post_runtime_buffer(endpoint: str, payload: dict) -> bool:
    """WSS 子进程通过本机回环 HTTP 把运行态帧投递给 API 主进程（带共享 token）。"""

    url = f"{_ctrl_api_internal_origin()}/api/internal/runtime/{endpoint}"
    try:
        token = _read_internal_token()
        headers = {"X-Internal-Token": token} if token else {}
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=float(os.getenv("CTRL_RUNTIME_BUFFER_PUSH_TIMEOUT", "0.5")),
            verify=_ctrl_api_internal_verify(),
        )
        response.raise_for_status()
        return True
    except Exception as e:
        logger.warning("runtime buffer push failed: endpoint=%s err=%s", endpoint, e)
        return False
