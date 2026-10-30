"""跨仓契约回放：真实 Node 端点 → Ctrl API/SQLite → Web 纯函数。

Node 侧由子进程 ``_node_mount_usage_probe.py`` 启动 bare FastAPI router +
TestClient（不启动 lifespan），用真实 ``du``（门闩阻塞）和临时目录生成 pending /
success / cache-hit / directory-gone / invalid-path / stable-error JSON。

Ctrl 侧只 mock ``node_comms.send``，把上面的真实 Node body 交入现有 API 路由、
只读解析和隔离 SQLite；Web 侧用 Node 动态 import 真实 ``mountUsage.js``，消费
Ctrl 实际序列化响应。不连接 Docker、远端 Node、真实数据库，也不读取 .env。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import event, func, select

from ...api import deps
from ...models.container_mount_cleanup import ContainerMountCleanup
from ...models.deleted_container_restore_snapshot import DeletedContainerRestoreSnapshot
from ...repositories import (
    container_mount_cleanup_repo,
    deleted_container_restore_snapshot_repo,
)
from ...services.container_module import mount_usage, node_comms
from ..factories import create_machine

REPO_ROOT = Path(__file__).resolve().parents[2]
NODE_ROOT = REPO_ROOT.parent / "FuxiYu_NodeKernel"
WEB_ROOT = REPO_ROOT.parent / "FuxiYu_Web"
PROBE = Path(__file__).with_name("_node_mount_usage_probe.py")
MOUNT_USAGE_URL = "/api/containers/get_deleted_container_mount_usage"
MACHINE_IP = "127.0.50.10"
MACHINE_PORT = 23456
BATCH_KEYS = ("slow", "zero", "invalid", "missing", "failed")


@pytest.fixture(scope="session")
def node_mount_payloads():
    if not NODE_ROOT.is_dir():
        pytest.skip("FuxiYu_NodeKernel is not available")
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(NODE_ROOT.parent), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("DATABASE_URL", None)
    proc = subprocess.run(
        [sys.executable, str(PROBE)],
        cwd=str(NODE_ROOT.parent),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        pytest.fail(f"Node mount-usage probe failed: {proc.stderr}\n{proc.stdout}")
    return json.loads(proc.stdout)


def _auth(monkeypatch, *, manage=True):
    monkeypatch.setattr(
        deps.authentications_repo,
        "is_token_valid",
        lambda token, **kwargs: True,
    )
    monkeypatch.setattr(
        deps.authentications_repo,
        "get_user_id_by_token",
        lambda token, **kwargs: 1,
    )
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.rbac_service.user_has_entity",
        lambda uid, code: manage or code != "container:manage",
    )
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.rbac_service.user_has_resource",
        lambda *args, **kwargs: True,
    )


def _insert_deleted(db_session, *, machine, path):
    cleanup = container_mount_cleanup_repo.insert(
        container_id=999,
        container_name="cross_repo_deleted",
        machine_id=machine.id,
        mount_path=path,
        session=db_session,
    )
    row = deleted_container_restore_snapshot_repo.insert(
        {
            "container_id": 0,
            "container_name": "cross_repo_deleted",
            "machine_id": machine.id,
            "bind_mount_path": path,
        },
        session=db_session,
        mount_cleanup_id=cleanup.id,
        removed_at=datetime(2026, 10, 20, 8, 0, 0),
        mount_cleaned=False,
    )
    cleanup.deleted_id = row.id
    db_session.commit()
    return row, cleanup


def _prepare_rows(db_session, payloads):
    machine = create_machine(machine_ip=MACHINE_IP)
    machine.port = MACHINE_PORT
    db_session.commit()
    paths = [payloads["paths"][key] for key in BATCH_KEYS]
    rows = [
        _insert_deleted(db_session, machine=machine, path=path)[0]
        for path in paths
    ]
    return machine, paths, rows


def _mock_send(monkeypatch, responses):
    calls = []

    def _send(url, payload, timeout=5.0, **kwargs):
        calls.append({"url": url, "payload": payload, "timeout": timeout})
        if not responses:
            raise AssertionError("unexpected extra Node request")
        return responses.pop(0)

    monkeypatch.setattr(node_comms, "send", _send)
    return calls


@contextmanager
def _capture_sql(db_session):
    statements = []
    engine = db_session.get_bind()

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor_execute)


def _dml_statements(statements):
    return [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
    ]


def _by_path(body):
    return {item["path"]: item for item in body["mounts"]}


def _by_id(body):
    return {item["deleted_id"]: item for item in body["usages"]}


def _assert_five_fields(item):
    assert set(item) == {"deleted_id", "bytes", "measured_at", "pending", "error"}
    assert "path" not in item


def _assert_usage_shape(body, expected_ids):
    assert set(body) == {"success", "usages"}
    assert body["success"] == 1
    assert [item["deleted_id"] for item in body["usages"]] == expected_ids
    for item in body["usages"]:
        _assert_five_fields(item)


def _norm_path(value):
    return os.path.normcase(os.path.normpath(os.path.abspath(value)))


def _web_run(input_data):
    if not WEB_ROOT.is_dir():
        pytest.skip("FuxiYu_Web is not available")
    node = shutil.which("node")
    if not node:
        pytest.fail("node runtime is required for the Web mountUsage replay")
    version = subprocess.run(
        [node, "--version"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if version.returncode != 0:
        pytest.fail(f"node --version failed: {version.stderr}")
    major = int(version.stdout.strip().lstrip("v").split(".", 1)[0])
    if major < 18:
        pytest.fail(f"node >= 18 is required, got {version.stdout.strip()}")

    script = r"""
const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const input = JSON.parse(Buffer.concat(chunks).toString('utf8'));
const mod = await import(input.moduleUrl);
const normalized = input.normalizeItems.map(item => mod.normalizeMountUsageItem(item));
const resolved = input.batches.map(batch => mod.resolveMountUsageBatch(batch.usages, batch.requestedIds));
process.stdout.write(JSON.stringify({
  normalized,
  resolved,
  zeroLabel: mod.formatLogicalBytes(0),
  nullLabel: mod.formatLogicalBytes(null),
}));
"""
    input_data = dict(input_data)
    input_data["moduleUrl"] = (WEB_ROOT / "src/utils/mountUsage.js").resolve().as_uri()
    proc = subprocess.run(
        [node, "--input-type=module", "-e", script],
        input=json.dumps(input_data),
        cwd=str(WEB_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        pytest.fail(f"Web mountUsage replay failed: {proc.stderr}\n{proc.stdout}")
    return json.loads(proc.stdout)


# ---------------------------------------------------------------------------
# 1) Node 当前真实端点输出
# ---------------------------------------------------------------------------

def test_node_probe_emits_real_endpoint_json_for_all_states(node_mount_payloads):
    payloads = node_mount_payloads
    assert payloads["endpoint"] == "/api/check_mount_usage"
    assert payloads["request_payload"]["config"]["mount_paths"] == [
        payloads["paths"][key] for key in BATCH_KEYS
    ]
    for body_name in ("pending", "success", "cache_hit", "directory_gone"):
        body = payloads[body_name]
        assert body["success"] == 1
        assert len(body["mounts"]) == len(BATCH_KEYS)
        for item in body["mounts"]:
            assert set(item) == {"path", "bytes", "measured_at", "pending", "error"}

    pending = _by_path(payloads["pending"])
    success = _by_path(payloads["success"])
    cache_hit = _by_path(payloads["cache_hit"])
    gone = _by_path(payloads["directory_gone"])
    slow = payloads["paths"]["slow"]
    zero = payloads["paths"]["zero"]
    invalid = payloads["paths"]["invalid"]
    missing = payloads["paths"]["missing"]
    failed = payloads["paths"]["failed"]

    assert pending[slow]["pending"] is True
    assert pending[slow]["bytes"] is None
    assert pending[slow]["measured_at"] is None
    assert success[slow]["bytes"] >= 2048
    assert success[slow]["measured_at"].endswith("Z")
    assert cache_hit[slow]["bytes"] == success[slow]["bytes"]
    assert cache_hit[slow]["measured_at"] == success[slow]["measured_at"]
    assert gone[slow]["error"] == "not_found"

    assert success[zero]["bytes"] == 0
    assert success[zero]["pending"] is False
    assert success[zero]["error"] is None
    assert success[invalid]["error"] == "invalid_path"
    assert success[missing]["error"] == "not_found"
    assert success[failed]["error"] == "du_failed"

    assert payloads["du_calls"] == [_norm_path(slow)]


# ---------------------------------------------------------------------------
# 2) 真实 Node body → Ctrl API / 只读解析 / SQLite
# ---------------------------------------------------------------------------

def test_real_node_batch_through_ctrl_api_is_machine_targeted_and_readonly(
    client, monkeypatch, db_session, node_mount_payloads,
):
    _auth(monkeypatch)
    machine, _paths, rows = _prepare_rows(db_session, node_mount_payloads)
    ids = [row.id for row in rows]
    responses = [
        node_mount_payloads["pending"],
        node_mount_payloads["success"],
        node_mount_payloads["cache_hit"],
        node_mount_payloads["directory_gone"],
    ]
    calls = _mock_send(monkeypatch, responses)

    before_snapshot_count = db_session.scalar(
        select(func.count()).select_from(DeletedContainerRestoreSnapshot)
    )
    before_cleanup_count = db_session.scalar(
        select(func.count()).select_from(ContainerMountCleanup)
    )

    with _capture_sql(db_session) as statements:
        first = client.post(MOUNT_USAGE_URL, json={"deleted_ids": ids})
        second = client.post(MOUNT_USAGE_URL, json={"deleted_ids": ids})
        third = client.post(MOUNT_USAGE_URL, json={"deleted_ids": ids})
        fourth = client.post(MOUNT_USAGE_URL, json={"deleted_ids": ids})

    bodies = [first.json(), second.json(), third.json(), fourth.json()]
    assert [resp.status_code for resp in (first, second, third, fourth)] == [200, 200, 200, 200]
    for body in bodies:
        _assert_usage_shape(body, ids)

    assert len(calls) == 4
    expected_url = f"https://{MACHINE_IP}:{MACHINE_PORT}/api/check_mount_usage"
    expected_payload = node_mount_payloads["request_payload"]
    for call in calls:
        assert call["url"] == expected_url
        assert call["payload"] == expected_payload
        assert call["timeout"] == mount_usage.NODE_QUERY_TIMEOUT_SECONDS

    slow, zero, invalid, missing, failed = (
        _by_id(bodies[0])[row.id] for row in rows
    )
    assert slow["pending"] is True
    assert slow["bytes"] is None and slow["measured_at"] is None
    assert zero["bytes"] == 0 and zero["pending"] is False and zero["error"] is None
    assert invalid["error"] == "invalid_path"
    assert missing["error"] == "not_found"
    assert failed["error"] == "du_failed"

    success_body = _by_id(bodies[1])
    node_success = _by_path(node_mount_payloads["success"])[
        node_mount_payloads["paths"]["slow"]
    ]
    assert success_body[rows[0].id]["bytes"] == node_success["bytes"]
    assert success_body[rows[0].id]["measured_at"] == node_success["measured_at"]
    assert success_body[rows[1].id]["bytes"] == 0
    assert success_body[rows[2].id]["error"] == "invalid_path"
    assert success_body[rows[3].id]["error"] == "not_found"
    assert success_body[rows[4].id]["error"] == "du_failed"

    cache_body = _by_id(bodies[2])
    assert cache_body[rows[0].id]["bytes"] == success_body[rows[0].id]["bytes"]
    assert cache_body[rows[0].id]["measured_at"] == success_body[rows[0].id]["measured_at"]

    gone_body = _by_id(bodies[3])
    assert gone_body[rows[0].id]["error"] == "not_found"
    assert gone_body[rows[0].id]["bytes"] is None
    assert gone_body[rows[1].id]["bytes"] == 0
    assert gone_body[rows[4].id]["error"] == "du_failed"

    assert _dml_statements(statements) == []
    db_session.expire_all()
    assert db_session.scalar(
        select(func.count()).select_from(DeletedContainerRestoreSnapshot)
    ) == before_snapshot_count
    assert db_session.scalar(
        select(func.count()).select_from(ContainerMountCleanup)
    ) == before_cleanup_count
    for index, row in enumerate(rows):
        refreshed = db_session.get(DeletedContainerRestoreSnapshot, row.id)
        assert refreshed is not None
        assert refreshed.mount_cleaned is False
        assert refreshed.snapshot["bind_mount_path"] == node_mount_payloads["paths"][
            BATCH_KEYS[index]
        ]
    for cleanup in db_session.scalars(select(ContainerMountCleanup)).all():
        assert cleanup.cleaned_at is None
    assert machine.port == MACHINE_PORT


# ---------------------------------------------------------------------------
# 3) 真实 Ctrl 序列化响应 → Web 纯函数
# ---------------------------------------------------------------------------

def test_web_mount_usage_consumes_real_ctrl_serialized_response(
    client, monkeypatch, db_session, node_mount_payloads,
):
    if not WEB_ROOT.is_dir():
        pytest.skip("FuxiYu_Web is not available")
    _auth(monkeypatch)
    _machine, _paths, rows = _prepare_rows(db_session, node_mount_payloads)
    ids = [row.id for row in rows]
    responses = [
        node_mount_payloads["pending"],
        node_mount_payloads["success"],
        node_mount_payloads["cache_hit"],
        node_mount_payloads["directory_gone"],
    ]
    _mock_send(monkeypatch, responses)
    bodies = [
        client.post(MOUNT_USAGE_URL, json={"deleted_ids": ids}).json()
        for _ in range(4)
    ]
    pending_body, success_body, cache_body, gone_body = bodies
    for body in bodies:
        _assert_usage_shape(body, ids)

    pending = _by_id(pending_body)
    success = _by_id(success_body)
    cache = _by_id(cache_body)
    gone = _by_id(gone_body)
    slow_id, zero_id, invalid_id, missing_id, failed_id = ids

    result = _web_run(
        {
            "normalizeItems": [
                success[slow_id],
                pending[slow_id],
                success[zero_id],
                success[invalid_id],
                success[missing_id],
                success[failed_id],
                # Deliberate pure-function negative: a future/unknown error code
                # must not be interpreted as success or 0.
                {
                    "deleted_id": 999998,
                    "bytes": None,
                    "measured_at": None,
                    "pending": False,
                    "error": "future_reason",
                },
            ],
            "batches": [
                {"usages": pending_body["usages"], "requestedIds": ids + [999999]},
                {"usages": success_body["usages"], "requestedIds": ids},
                {"usages": cache_body["usages"], "requestedIds": ids},
                {"usages": gone_body["usages"], "requestedIds": ids},
                {
                    "usages": [
                        {
                            "deleted_id": 999998,
                            "bytes": None,
                            "measured_at": None,
                            "pending": False,
                            "error": "future_reason",
                        }
                    ],
                    "requestedIds": [999998],
                },
            ],
        }
    )

    normalized = result["normalized"]
    assert normalized[0] == {
        "status": "success",
        "bytes": success[slow_id]["bytes"],
        "measuredAt": success[slow_id]["measured_at"],
    }
    assert normalized[1] == {"status": "pending"}
    assert normalized[2] == {
        "status": "success",
        "bytes": 0,
        "measuredAt": success[zero_id]["measured_at"],
    }
    assert normalized[3] == {"status": "error", "reason": "invalid_path"}
    assert normalized[4] == {"status": "error", "reason": "not_found"}
    # Known contract errors retain their reason; unknown codes are tested separately.
    assert normalized[5] == {
        "status": "error",
        "reason": "du_failed",
    }
    assert normalized[6] is None, "unknown error code must not become success/0"

    (
        resolved_pending,
        resolved_success,
        resolved_cache,
        resolved_gone,
        resolved_unknown,
    ) = result["resolved"]
    assert resolved_pending[str(slow_id)] == {"status": "pending"}
    assert resolved_pending[str(zero_id)] == {
        "status": "success",
        "bytes": 0,
        "measuredAt": success[zero_id]["measured_at"],
    }
    assert resolved_pending[str(invalid_id)] == {
        "status": "error",
        "reason": "invalid_path",
        "message": "统计不可用（路径无效）",
    }
    assert resolved_pending[str(missing_id)] == {
        "status": "error",
        "reason": "not_found",
        "message": "统计不可用（目录不存在）",
    }
    assert resolved_pending[str(failed_id)]["status"] == "error"
    assert "bytes" not in resolved_pending[str(failed_id)]
    assert "measured_at" not in resolved_pending[str(failed_id)]
    assert resolved_pending[str(failed_id)]["message"]
    assert resolved_pending[str(failed_id)]["reason"] == "du_failed"
    assert resolved_pending["999999"] == {
        "status": "unavailable",
        "message": "统计不可用",
    }
    assert resolved_unknown["999998"] == {
        "status": "unavailable",
        "message": "统计不可用",
    }

    assert resolved_success[str(slow_id)]["status"] == "success"
    assert resolved_success[str(slow_id)]["bytes"] == success[slow_id]["bytes"]
    assert resolved_success[str(zero_id)]["bytes"] == 0
    assert resolved_cache[str(slow_id)] == resolved_success[str(slow_id)]
    assert resolved_gone[str(slow_id)] == {
        "status": "error",
        "reason": "not_found",
        "message": "统计不可用（目录不存在）",
    }
    assert resolved_gone[str(zero_id)]["bytes"] == 0
    assert resolved_gone[str(failed_id)]["status"] == "error"
    assert resolved_gone[str(failed_id)]["reason"] == "du_failed"
    assert "bytes" not in resolved_gone[str(failed_id)]
    assert result["zeroLabel"] == "0 B"
    assert result["nullLabel"] is None
