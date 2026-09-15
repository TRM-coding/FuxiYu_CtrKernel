"""Ctrl 内部运行态 buffer 写入端点。"""

import hmac
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..config import AppConfig
from ..services.container_module import node_comms

router = APIRouter(prefix="/internal/runtime", tags=["internal-runtime"], include_in_schema=False)

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


class RuntimeSnapshotRequest(BaseModel):
    machine_id: int = Field(..., ge=1)
    snapshot: dict[str, Any] = Field(default_factory=dict)


def _is_loopback(request: Request) -> bool:
    client = request.client
    if client is None:
        return False
    if client.host in _LOOPBACK_HOSTS:
        return True
    return bool(getattr(AppConfig, "TESTING", False) and client.host == "testclient")


def _valid_internal_token(request: Request) -> bool:
    """共享 token 校验（常量时间比较）；测试环境（testclient）豁免与 _is_loopback 一致。"""

    client = request.client
    if getattr(AppConfig, "TESTING", False) and client is not None and client.host == "testclient":
        return True
    provided = request.headers.get("X-Internal-Token", "") or ""
    expected = node_comms._read_internal_token() or ""
    return bool(expected) and hmac.compare_digest(provided, expected)


def _forbidden() -> HTTPException:
    return HTTPException(status_code=403, detail={"success": 0, "message": "forbidden", "error_reason": "forbidden"})


@router.post("/containers")
def write_container_runtime_snapshot(request: Request, payload: RuntimeSnapshotRequest):
    """WSS 子进程写入容器运行态 buffer；非业务 API（loopback + 共享 token 双重校验）。"""

    if not _is_loopback(request) or not _valid_internal_token(request):
        raise _forbidden()
    updated = node_comms.write_container_runtime_buffer(payload.machine_id, payload.snapshot)
    return {"success": 1, "updated": updated}


@router.post("/machines")
def write_machine_runtime_snapshot(request: Request, payload: RuntimeSnapshotRequest):
    """WSS 子进程写入机器运行态 buffer；非业务 API（loopback + 共享 token 双重校验）。"""

    if not _is_loopback(request) or not _valid_internal_token(request):
        raise _forbidden()
    updated = node_comms.write_machine_runtime_buffer(payload.machine_id, payload.snapshot)
    return {"success": 1, "updated": updated}
