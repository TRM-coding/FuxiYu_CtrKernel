"""Generate real WSS payloads from the current Node production code.

Run as a subprocess by test_cross_repo_protocol_replay.py.  No Docker daemon,
database, .env or network access is used: the Node caches are seeded with
production dataclasses/facts and the WSS frame builders are called directly.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

NODE_PARENT = Path(__file__).resolve().parents[3]
if str(NODE_PARENT) not in sys.path:
    sys.path.insert(0, str(NODE_PARENT))

from FuxiYu_NodeKernel import extensions  # noqa: E402
from FuxiYu_NodeKernel.docker_operates.disk_usage_cache import (  # noqa: E402
    DiskUsageCache,
    _norm_path,
    _utc_now,
    _utc_z,
)
from FuxiYu_NodeKernel.docker_operates.docker_fact import DockerFact  # noqa: E402
from FuxiYu_NodeKernel.docker_operates.status_cache import ContainerStatusCache  # noqa: E402
from FuxiYu_NodeKernel.network import wss  # noqa: E402


class _CacheStub:
    def __init__(self, value):
        self._value = value

    def snapshot(self):
        return dict(self._value)


class _WS:
    def __init__(self):
        self.frames = []

    async def send_text(self, text):
        self.frames.append(json.loads(text))

    async def receive(self):
        return {"type": "websocket.disconnect"}


def _online(cache: ContainerStatusCache, name: str) -> None:
    ticket = cache.issue_observation(name, "probe")
    fact = DockerFact(
        docker_id=f"id-{name}",
        status="running",
        running=True,
        paused=False,
        restarting=False,
        dead=False,
        started_at="2026-10-18T00:00:00Z",
        pid=123,
    )
    if not cache.publish_observed(name, ticket, fact, mark_ready=True):  # pragma: no cover
        raise RuntimeError(f"could not seed online state for {name}")


def _status_payloads():
    creating = ContainerStatusCache()
    creating.accept_action("node_creating", "create", "creating", create=True)
    extensions.status_cache = creating
    creating_frame = wss.build_status_snapshot()

    online = ContainerStatusCache()
    _online(online, "node_online")
    extensions.status_cache = online
    online_frame = wss.build_status_snapshot()

    collect = ContainerStatusCache()
    collect._collect_error = "collect_failed"  # production reconcile sets this marker
    extensions.status_cache = collect
    collect_frame = wss.build_status_snapshot()

    return {
        "creating": creating_frame,
        "online": online_frame,
        "collect_error": collect_frame,
    }


def _disk_payload(name: str, *, status: str, path: str | None, scenario: str, measured_at=None,
                  bind_ok: bool = True, cached_path: str | None = None):
    now = _utc_now()
    cache = DiskUsageCache()
    if cached_path is None:
        cached_path = path
    verification = {
        "status": status,
        "bind_mount_path": path,
        "source_path": path,
        "docker_id": f"id-{name}",
        "pid": 123,
    }
    if path is not None:
        normalized = _norm_path(path)
        entry = cache._bind_entry_locked(normalized)
        entry["running"] = False
        if bind_ok:
            entry["bytes"] = 600
            entry["status"] = "ok"
            entry["measured_at"] = _utc_z(measured_at) if measured_at else _utc_z(now)
        else:
            # Node publishes no successful measurement/time in this branch.
            entry["bytes"] = None
            entry["status"] = "error"
            entry["measured_at"] = None
            entry["reason"] = "du_failed"
    overlay = {"overlay_rw_bytes": 400, "overlay_rw_source": "attrs"}
    usage = cache._compose_usage(name, None, verification, overlay, now)
    if cached_path is not None and cached_path != path:
        usage["bind_mount_path"] = cached_path
        usage["mount_path_status"] = "resolved"
    cache._container_cache[name] = {"usage": usage, "updated_at": now}
    cache._path_state[name] = {
        "bind_mount_path": path,
        "mount_path_status": status,
        "path_version": 1,
    }
    extensions.disk_usage_cache = cache
    return wss.build_disk_usage_snapshot()


def _disk_payloads():
    now = _utc_now()
    path_a = "/home/u/containers/a"
    path_b = "/home/u/containers/b"
    payloads = {
        "resolved_b": _disk_payload(
            "disk_node", status="resolved", path=path_b, scenario="resolved_b", measured_at=now,
        ),
        "unresolved_a": _disk_payload(
            "disk_node", status="unresolved", path=path_a, scenario="unresolved_a", measured_at=now,
        ),
        "not_running_a": _disk_payload(
            "disk_node", status="not_running", path=path_a, scenario="not_running_a", measured_at=now,
        ),
        "no_bind": _disk_payload(
            "disk_node", status="no_bind", path=None, scenario="no_bind", measured_at=now,
        ),
        "old_sample_a": _disk_payload(
            "disk_node", status="resolved", path=path_a, scenario="old_sample_a",
            measured_at=now - timedelta(seconds=60),
        ),
        "missing_measured_at_b": _disk_payload(
            "disk_node", status="resolved", path=path_b, scenario="missing_measured_at_b",
            bind_ok=False,
        ),
        "path_changed_old_sample": _disk_payload(
            "disk_node", status="resolved", path=path_b, scenario="path_changed_old_sample",
            measured_at=now, cached_path=path_a,
        ),
    }
    return payloads


def _delete_and_snapshot_frames():
    cache = ContainerStatusCache()
    _online(cache, "keep_online")
    cache._deleted = [{"name": "gone_node", "generation": cache._meta_for("gone_node")["generation"]}]
    cache._confirm_absent = lambda name, client: True
    extensions.status_cache = cache
    extensions.docker_client = object()
    extensions.disk_usage_cache = DiskUsageCache()
    extensions.last_ssh_cache = _CacheStub({})
    extensions.sys_cache = _CacheStub({})

    ws = _WS()
    asyncio.run(wss._push_snapshot_frames(ws, wss.NodeIdentity(uid="probe-uid")))
    if len(ws.frames) < 2:  # pragma: no cover
        raise RuntimeError(f"expected delete + snapshot frames, got {ws.frames!r}")
    return {"frames": ws.frames}


def main() -> None:
    result = {
        "node_head": os.getenv("NODE_HEAD", ""),
        "status": _status_payloads(),
        "disk": _disk_payloads(),
        "wss": _delete_and_snapshot_frames(),
    }
    # A subprocess captures stdout; keep it machine-readable even if Node logs.
    print(json.dumps(result, ensure_ascii=True, default=str))


if __name__ == "__main__":
    main()
