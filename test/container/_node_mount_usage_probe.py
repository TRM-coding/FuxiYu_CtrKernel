"""Generate real Node ``/api/check_mount_usage`` JSON for cross-repo replay.

Run as a subprocess by ``test_mount_usage_cross_repo.py``.  The probe:

- imports only the Node API router and a real ``DiskUsageCache``;
- uses a bare FastAPI app + TestClient (no Node lifespan, no WSS, no Docker);
- points ``NODE_CONTAINERS_BASE`` at one temporary directory;
- puts a gated ``du`` shim first on PATH, so the first real ``du`` blocks until
  release (producing an actual pending response), then executes the real du;
- seeds only the zero-byte and stable-error cache samples, both returned through
  the real Node endpoint rather than hand-written JSON.

No .env, database, Docker daemon, SSH or network access is used.  Bytecode writes
are disabled by the parent and by ``sys.dont_write_bytecode``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True

# Never let the probe consume deployment secrets from the parent environment.
for _secret_key in (
    "DATABASE_URL",
    "SECRET_KEY",
    "PUBLIC_KEY_PATH",
    "PRIVATE_KEY_PATH",
    "NODE_UID",
    "NODE_CTRL_CA_FILE",
    "NODE_TLS_CERT_FILE",
    "NODE_TLS_KEY_FILE",
    "NODE_IDENTITY_FILE",
):
    os.environ.pop(_secret_key, None)

NODE_PARENT = Path(__file__).resolve().parents[3]
if str(NODE_PARENT) not in sys.path:
    sys.path.insert(0, str(NODE_PARENT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from FuxiYu_NodeKernel import extensions  # noqa: E402
from FuxiYu_NodeKernel.docker_operates.disk_usage_cache import (  # noqa: E402
    DiskUsageCache,
    _norm_path,
    _utc_z,
)
from FuxiYu_NodeKernel.network.api import router as api_router  # noqa: E402

ENDPOINT = "/api/check_mount_usage"


def _wait_for(path: Path, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.01)
    return False


def _request(client: TestClient, paths: list[str]) -> dict:
    response = client.post(
        ENDPOINT,
        json={"config": {"mount_paths": paths}},
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Node endpoint returned HTTP {response.status_code}: {response.text}"
        )
    body = response.json()
    if body.get("success") != 1:
        raise RuntimeError(f"Node endpoint did not return success=1: {body!r}")
    mounts = body.get("mounts")
    if not isinstance(mounts, list) or len(mounts) != len(paths):
        raise RuntimeError(f"Node endpoint returned wrong mounts shape: {body!r}")
    if [item.get("path") for item in mounts] != paths:
        raise RuntimeError(f"Node endpoint lost request order: {body!r}")
    return body


def _by_path(body: dict) -> dict[str, dict]:
    return {item["path"]: item for item in body["mounts"]}


def _seed_success(cache: DiskUsageCache, path: Path, *, bytes_value: int) -> None:
    key = _norm_path(os.path.realpath(str(path)))
    with cache._lock:
        entry = cache._bind_entry_locked(key)
        entry.update(
            {
                "bytes": bytes_value,
                "status": "ok",
                "reason": None,
                "measured_at": _utc_z(),
                "running": False,
                "request_id": 0,
                "failed_at": None,
            }
        )


def _seed_error(cache: DiskUsageCache, path: Path, *, reason: str) -> None:
    key = _norm_path(os.path.realpath(str(path)))
    with cache._lock:
        entry = cache._bind_entry_locked(key)
        entry.update(
            {
                "bytes": None,
                "status": "error",
                "reason": reason,
                "measured_at": None,
                "running": False,
                "request_id": 0,
                "failed_at": _utc_z(),
            }
        )


def _assert_mount(item: dict, *, path: str, pending: bool, error, bytes_ok) -> None:
    if item.get("path") != path:
        raise RuntimeError(f"path mismatch: {item!r}")
    if item.get("pending") is not pending:
        raise RuntimeError(f"pending mismatch: {item!r}")
    if item.get("error") != error:
        raise RuntimeError(f"error mismatch: {item!r}")
    if not bytes_ok(item.get("bytes")):
        raise RuntimeError(f"bytes mismatch: {item!r}")
    if pending:
        if item.get("bytes") is not None or item.get("measured_at") is not None:
            raise RuntimeError(f"pending item carried bytes/time: {item!r}")
    if error is not None:
        if item.get("bytes") is not None or item.get("measured_at") is not None:
            raise RuntimeError(f"error item carried bytes/time: {item!r}")


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="fuxi-node-mount-usage-"))
    client = None
    release = tmp / "du-release"
    try:
        base = tmp / "home"
        containers = base / "alice" / "containers"
        containers.mkdir(parents=True)
        slow = containers / "slow"
        zero = containers / "zero"
        invalid = containers / "not-a-directory"
        missing = containers / "never-existed"
        failed = containers / "failed"
        for path in (slow, zero, failed):
            path.mkdir()
        (slow / "payload.bin").write_bytes(b"x" * 2048)
        invalid.write_text("not a directory", encoding="utf-8")

        real_du = shutil.which("du")
        if not real_du:
            raise RuntimeError("du is required for the real Node mount-usage probe")
        wrapper_dir = tmp / "bin"
        wrapper_dir.mkdir()
        calls_file = tmp / "du-calls"
        started_file = tmp / "du-started"
        wrapper = wrapper_dir / "du"
        wrapper.write_text(
            "#!/bin/sh\n"
            'last=""\n'
            'for arg in "$@"; do last="$arg"; done\n'
            'printf \'%s\\n\' "$last" >> "$GATE_CALLS"\n'
            ': > "$GATE_STARTED"\n'
            "i=0\n"
            'while [ ! -f "$GATE_RELEASE" ] && [ "$i" -lt 1500 ]; do\n'
            "  sleep 0.02\n"
            "  i=$((i+1))\n"
            "done\n"
            'exec "$REAL_DU" "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o755)

        os.environ.update(
            {
                "NODE_CONTAINERS_BASE": os.path.realpath(str(base)),
                "NODE_LOG_DIR": str(tmp / "logs"),
                "PATH": str(wrapper_dir) + os.pathsep + os.environ.get("PATH", ""),
                "REAL_DU": real_du,
                "GATE_CALLS": str(calls_file),
                "GATE_STARTED": str(started_file),
                "GATE_RELEASE": str(release),
            }
        )

        cache = DiskUsageCache()
        _seed_success(cache, zero, bytes_value=0)
        _seed_error(cache, failed, reason="du_failed")
        extensions.disk_usage_cache = cache

        app = FastAPI()
        app.include_router(api_router)
        # Deliberately no ``with TestClient(...)``: no lifespan, no WSS, no cache.start().
        client = TestClient(app)
        paths = [
            str(slow),
            str(zero),
            str(invalid),
            str(missing),
            str(failed),
        ]

        pending = _request(client, paths)
        p = _by_path(pending)
        _assert_mount(p[str(slow)], path=str(slow), pending=True, error=None, bytes_ok=lambda v: v is None)
        _assert_mount(p[str(zero)], path=str(zero), pending=False, error=None, bytes_ok=lambda v: v == 0)
        _assert_mount(
            p[str(invalid)], path=str(invalid), pending=False, error="invalid_path",
            bytes_ok=lambda v: v is None,
        )
        _assert_mount(
            p[str(missing)], path=str(missing), pending=False, error="not_found",
            bytes_ok=lambda v: v is None,
        )
        _assert_mount(
            p[str(failed)], path=str(failed), pending=False, error="du_failed",
            bytes_ok=lambda v: v is None,
        )

        if not _wait_for(started_file, 10.0):
            raise RuntimeError("real du did not start behind the gate")
        if calls_file.exists():
            started_calls = calls_file.read_text(encoding="utf-8").splitlines()
            if started_calls != [_norm_path(os.path.realpath(str(slow)))]:
                raise RuntimeError(f"unexpected du calls before release: {started_calls!r}")
        release.write_text("release", encoding="utf-8")

        success = None
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            candidate = _request(client, paths)
            if _by_path(candidate)[str(slow)]["pending"] is False:
                success = candidate
                break
            time.sleep(0.01)
        if success is None:
            raise RuntimeError("gated du did not settle after release")

        s = _by_path(success)
        slow_item = s[str(slow)]
        slow_bytes = slow_item["bytes"]
        if not isinstance(slow_bytes, int) or slow_bytes < 2048:
            raise RuntimeError(f"real du did not return expected logical bytes: {slow_item!r}")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", slow_item["measured_at"] or ""):
            raise RuntimeError(f"real du did not return UTC measured_at: {slow_item!r}")
        _assert_mount(
            slow_item, path=str(slow), pending=False, error=None,
            bytes_ok=lambda v: isinstance(v, int) and v >= 2048,
        )
        _assert_mount(
            s[str(zero)], path=str(zero), pending=False, error=None,
            bytes_ok=lambda v: v == 0,
        )
        _assert_mount(
            s[str(invalid)], path=str(invalid), pending=False, error="invalid_path",
            bytes_ok=lambda v: v is None,
        )
        _assert_mount(
            s[str(missing)], path=str(missing), pending=False, error="not_found",
            bytes_ok=lambda v: v is None,
        )
        _assert_mount(
            s[str(failed)], path=str(failed), pending=False, error="du_failed",
            bytes_ok=lambda v: v is None,
        )

        cache_hit = _request(client, paths)
        h = _by_path(cache_hit)
        if h[str(slow)]["bytes"] != slow_bytes:
            raise RuntimeError(f"TTL cache hit changed bytes: {h[str(slow)]!r}")
        if h[str(slow)]["measured_at"] != slow_item["measured_at"]:
            raise RuntimeError(f"TTL cache hit refreshed measured_at: {h[str(slow)]!r}")

        shutil.rmtree(slow)
        gone = _request(client, paths)
        g = _by_path(gone)
        _assert_mount(
            g[str(slow)], path=str(slow), pending=False, error="not_found",
            bytes_ok=lambda v: v is None,
        )
        _assert_mount(
            g[str(zero)], path=str(zero), pending=False, error=None,
            bytes_ok=lambda v: v == 0,
        )
        _assert_mount(
            g[str(failed)], path=str(failed), pending=False, error="du_failed",
            bytes_ok=lambda v: v is None,
        )

        du_calls = calls_file.read_text(encoding="utf-8").splitlines() if calls_file.exists() else []
        expected_call = _norm_path(os.path.realpath(str(slow)))
        if du_calls != [expected_call]:
            raise RuntimeError(
                f"expected one real du for {expected_call!r}, got {du_calls!r}"
            )

        result = {
            "endpoint": ENDPOINT,
            "request_payload": {"config": {"mount_paths": paths}},
            "paths": {
                "slow": str(slow),
                "zero": str(zero),
                "invalid": str(invalid),
                "missing": str(missing),
                "failed": str(failed),
            },
            "pending": pending,
            "success": success,
            "cache_hit": cache_hit,
            "directory_gone": gone,
            "du_calls": du_calls,
        }
        print(json.dumps(result, ensure_ascii=True))
    finally:
        try:
            release.write_text("release", encoding="utf-8")
        except OSError:
            pass
        if client is not None:
            client.close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
