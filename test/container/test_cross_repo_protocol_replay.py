"""跨仓协议回放：Node 当前生产帧 → Ctrl 当前接收 → 隔离 SQLite。

Node 侧在子进程中运行 test/container/_node_protocol_probe.py，禁止写 Node 的
pyc；只读取 Node/Web 当前代码。所有持久化都落在 Ctrl 测试 SQLite，不连接
Docker、Node 服务、生产库，也不读取 .env。

这里验证的是本地协议契约，不是生产部署，也不宣称跨进程动作原子性。
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from ...constant import ContainerStatus, OperationType
from ...models.containers import Container
from ...models.deleted_container_restore_snapshot import DeletedContainerRestoreSnapshot
from ...models.operation_log import OperationLog
from ...repositories import containers_repo, long_term_container_repo
from ...services import container_tasks
from ...services.container_module import node_comms
from ..factories import create_container, create_container_graph

REPO_ROOT = Path(__file__).resolve().parents[2]
NODE_ROOT = REPO_ROOT.parent / "FuxiYu_NodeKernel"
WEB_ROOT = REPO_ROOT.parent / "FuxiYu_Web"
PROBE = Path(__file__).with_name("_node_protocol_probe.py")
NODE_UID = "probe-uid"


@pytest.fixture(scope="session")
def node_payloads():
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
        pytest.fail(f"Node payload probe failed: {proc.stderr}\n{proc.stdout}")
    return json.loads(proc.stdout)


def _row(db_session, container_id: int):
    db_session.expire_all()
    return containers_repo.get_by_id(container_id, session=db_session, include_invalid=True)


def _apply_status_frame(db_session, machine, frame) -> dict:
    machine.node_uid = NODE_UID
    db_session.commit()
    return node_comms.apply_snapshot_batch({
        "type": "snapshot_batch",
        "node_uid": NODE_UID,
        "payload": [frame],
    })


def _apply_disk_frame(machine, frame) -> dict:
    return node_comms.apply_disk_usage_snapshot(frame["payload"], machine.id)


def _disk_usage(frame) -> dict:
    return next(iter(frame["payload"]["containers"].values()))


def _parse_node_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def _setup_disk(db_session, *, path: str = "/home/u/containers/a"):
    _root, machine, container = create_container_graph()
    container.name = "disk_node"
    container.bind_mount_path = path
    container.disk_overlay_rw_bytes = 11
    container.disk_bind_mount_bytes = 22
    container.disk_total_bytes = 33
    container.disk_checked_at = datetime.utcnow() - timedelta(minutes=5)
    db_session.commit()
    return machine, container


def _delete_logs(db_session, container_id: int):
    return db_session.scalars(
        select(OperationLog).where(
            OperationLog.operation == OperationType.DELETE_CONTAINER,
            OperationLog.target_id == container_id,
        )
    ).all()


def _snapshots(db_session, container_id: int):
    return db_session.scalars(
        select(DeletedContainerRestoreSnapshot).where(
            DeletedContainerRestoreSnapshot.original_container_id == container_id,
        )
    ).all()


# ---------------------------------------------------------------------------
# 状态快照 / delete 帧 / collect_error 交错
# ---------------------------------------------------------------------------

def test_node_creating_payload_keeps_ctrl_creating_record(app, db_session, node_payloads):
    _root, machine, container = create_container_graph()
    container.name = "node_creating"
    container.container_status = ContainerStatus.CREATING
    db_session.commit()

    result = _apply_status_frame(db_session, machine, node_payloads["status"]["creating"])

    row = _row(db_session, container.id)
    assert result["container_status"]["updated"] == 1
    assert row is not None and row.is_valid is True
    assert row.container_status == ContainerStatus.CREATING
    assert row.status_source is None
    assert row.deleted_trigger is None


def test_node_snapshot_missing_marks_pending_not_deleted(app, db_session, node_payloads):
    root, machine, container = create_container_graph()
    container.name = "ctrl_only_creating"
    container.container_status = ContainerStatus.CREATING
    long_term_container_repo.add(container.id, created_by_user_id=root.id, session=db_session)
    db_session.commit()

    result = _apply_status_frame(db_session, machine, node_payloads["status"]["online"])

    row = _row(db_session, container.id)
    assert result["container_status"]["vanished"] == 1
    assert row.is_valid is True
    assert row.id == container.id
    assert row.status_source == "snapshot_missing"
    assert row.status_unknown_since is not None
    assert long_term_container_repo.is_long_term(container.id, session=db_session) is True
    assert _delete_logs(db_session, container.id) == []
    assert _snapshots(db_session, container.id) == []


def test_node_collect_error_payload_does_not_mark_or_delete(app, db_session, node_payloads):
    _root, machine, container = create_container_graph()
    container.name = "ctrl_collect_error"
    db_session.commit()

    result = _apply_status_frame(db_session, machine, node_payloads["status"]["collect_error"])

    row = _row(db_session, container.id)
    assert result["container_status"]["vanished"] == 0
    assert row.is_valid is True
    assert row.status_source is None
    assert db_session.get(type(machine), machine.id).collect_error_at is not None
    assert _delete_logs(db_session, container.id) == []


def test_node_delete_then_snapshot_frames_do_not_soft_delete(
    app, db_session, node_payloads,
):
    """Node 真实 WSS 一帧 delete + 后续 snapshot_batch，经 Ctrl 串行消费者处理。"""
    _root, machine, container = create_container_graph()
    container.name = "gone_node"
    db_session.commit()
    frames = node_payloads["wss"]["frames"]
    assert frames[0] == {"type": "delete", "container_name": "gone_node"}
    assert frames[1]["type"] == "snapshot_batch"
    machine.node_uid = NODE_UID
    db_session.commit()

    async def _run():
        queue = asyncio.Queue()
        for frame in frames:
            queue.put_nowait(frame)
        task = asyncio.create_task(node_comms._consume_frames(queue, NODE_UID, machine.id))
        try:
            await asyncio.wait_for(queue.join(), timeout=10)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    asyncio.run(_run())

    row = _row(db_session, container.id)
    assert row.is_valid is True
    assert row.status_source in {"delete_frame", "snapshot_missing"}
    assert row.status_unknown_since is not None
    assert _delete_logs(db_session, container.id) == []
    assert _snapshots(db_session, container.id) == []


# ---------------------------------------------------------------------------
# 磁盘 Node 生产 payload
# ---------------------------------------------------------------------------

def test_node_resolved_payload_updates_path_and_measurement(app, db_session, node_payloads):
    machine, container = _setup_disk(db_session)
    payload = _disk_usage(node_payloads["disk"]["resolved_b"])

    result = _apply_disk_frame(machine, node_payloads["disk"]["resolved_b"])

    row = _row(db_session, container.id)
    assert result == {"updated": 1, "skipped": 0}
    assert row.bind_mount_path == payload["bind_mount_path"] == "/home/u/containers/b"
    assert row.disk_total_bytes == payload["total_bytes"] == 1000
    assert row.disk_overlay_rw_bytes == payload["overlay_rw_bytes"] == 400
    assert row.disk_bind_mount_bytes == payload["bind_mount_bytes"] == 600
    assert row.disk_checked_at == _parse_node_time(payload["measured_at"])


@pytest.mark.parametrize("key", ["unresolved_a", "not_running_a"])
def test_node_unresolved_and_not_running_keep_path_and_accept_measurement(
    app, db_session, node_payloads, key,
):
    machine, container = _setup_disk(db_session)
    payload = _disk_usage(node_payloads["disk"][key])

    result = _apply_disk_frame(machine, node_payloads["disk"][key])

    row = _row(db_session, container.id)
    assert result == {"updated": 1, "skipped": 0}
    assert payload["mount_path_status"] == ("unresolved" if key == "unresolved_a" else "not_running")
    assert row.bind_mount_path == "/home/u/containers/a"
    assert row.disk_total_bytes == 1000
    assert row.disk_checked_at == _parse_node_time(payload["measured_at"])


def test_node_no_bind_payload_clears_path_and_uses_overlay_only(app, db_session, node_payloads):
    machine, container = _setup_disk(db_session)
    payload = _disk_usage(node_payloads["disk"]["no_bind"])

    result = _apply_disk_frame(machine, node_payloads["disk"]["no_bind"])

    row = _row(db_session, container.id)
    assert result == {"updated": 1, "skipped": 0}
    assert payload["mount_path_status"] == "no_bind"
    assert row.bind_mount_path is None
    assert row.disk_bind_mount_bytes is None
    assert row.disk_total_bytes == 400
    assert row.disk_checked_at == _parse_node_time(payload["measured_at"])


def test_node_path_change_does_not_attach_old_a_bytes_to_b(app, db_session, node_payloads):
    machine, container = _setup_disk(db_session)

    first = _apply_disk_frame(machine, node_payloads["disk"]["path_changed_old_sample"])
    row = _row(db_session, container.id)
    assert first == {"updated": 1, "skipped": 0}
    assert row.bind_mount_path == "/home/u/containers/b"
    assert row.disk_total_bytes is None
    assert row.disk_bind_mount_bytes is None
    assert row.disk_checked_at is None

    second = _apply_disk_frame(machine, node_payloads["disk"]["resolved_b"])
    payload = _disk_usage(node_payloads["disk"]["resolved_b"])
    row = _row(db_session, container.id)
    assert second == {"updated": 1, "skipped": 0}
    assert row.bind_mount_path == "/home/u/containers/b"
    assert row.disk_total_bytes == 1000
    assert row.disk_checked_at == _parse_node_time(payload["measured_at"])


def test_node_old_sample_is_rejected_against_ctrl_checkpoint(app, db_session, node_payloads):
    machine, container = _setup_disk(db_session)
    checkpoint = datetime.utcnow()
    container.disk_checked_at = checkpoint
    db_session.commit()
    payload = _disk_usage(node_payloads["disk"]["old_sample_a"])
    assert _parse_node_time(payload["measured_at"]) < checkpoint

    result = _apply_disk_frame(machine, node_payloads["disk"]["old_sample_a"])

    row = _row(db_session, container.id)
    assert result == {"updated": 0, "skipped": 1}
    assert row.bind_mount_path == "/home/u/containers/a"
    assert row.disk_total_bytes == 33
    assert row.disk_checked_at == checkpoint


def test_node_missing_measured_at_applies_path_without_fake_measurement(
    app, db_session, node_payloads,
):
    machine, container = _setup_disk(db_session)
    payload = _disk_usage(node_payloads["disk"]["missing_measured_at_b"])
    assert payload["measured_at"] is None
    assert payload["total_bytes"] is None

    result = _apply_disk_frame(machine, node_payloads["disk"]["missing_measured_at_b"])

    row = _row(db_session, container.id)
    assert result == {"updated": 1, "skipped": 0}
    assert row.bind_mount_path == "/home/u/containers/b"
    assert row.disk_total_bytes is None
    assert row.disk_bind_mount_bytes is None
    assert row.disk_checked_at is None


def test_node_payloads_carry_no_control_side_dir_identity(node_payloads):
    forbidden = {"st_dev", "st_ino", "pid", "source_path", "docker_id", "disk_identity"}

    def _keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from _keys(item)
        elif isinstance(value, list):
            for item in value:
                yield from _keys(item)

    observed = set(_keys(node_payloads["status"])) | set(_keys(node_payloads["disk"]))
    observed |= set(_keys(node_payloads["wss"]))
    assert observed.isdisjoint(forbidden)
    assert {c.name for c in Container.__table__.columns}.isdisjoint(forbidden)
    source = Path(__file__).parents[2] / "services/container_module/node_comms_modules/snapshots.py"
    text = source.read_text(encoding="utf-8")
    assert "st_dev" not in text
    assert "st_ino" not in text


# ---------------------------------------------------------------------------
# Web 当前共享 containerActions 消费字段
# ---------------------------------------------------------------------------

def _brief(db_session, machine, container, root):
    result = container_tasks.list_all_container_bref_information(
        machine_id=machine.id,
        request_user_id=root.id,
        page_number=0,
        page_size=20,
        viewer_user_id=None,
    )
    for item in result["containers"]:
        item = item.model_dump() if hasattr(item, "model_dump") else item
        if item.get("container_name") == container.name:
            return item
    raise AssertionError(f"container {container.name} not found in brief output")


def _web_context():
    return {
        "permissions": ["container:operation", "container:manage", "bypass_resource"],
        "containerRole": "ROOT",
        "readOnly": False,
    }


def _run_web_actions(inputs):
    if not WEB_ROOT.is_dir() or shutil.which("node") is None:
        pytest.skip("FuxiYu_Web/node runtime is not available")
    action_module = (WEB_ROOT / "src/utils/containerActions.js").resolve().as_uri()
    script = """
import { registerHooks } from 'node:module';
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith('.') && !/\\.[cm]?js$/.test(specifier)) {
      return nextResolve(specifier + '.js', context);
    }
    return nextResolve(specifier, context);
  },
});
const { resolveContainerActions } = await import(process.env.FUXI_CONTAINER_ACTIONS);
const inputs = JSON.parse(process.env.FUXI_INPUT);
process.stdout.write(JSON.stringify(inputs.map((input) => resolveContainerActions(input))));
"""
    env = os.environ.copy()
    env["FUXI_CONTAINER_ACTIONS"] = action_module
    env["FUXI_INPUT"] = json.dumps(inputs)
    proc = subprocess.run(
        [shutil.which("node"), "--input-type=module", "-e", script],
        cwd=str(WEB_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        pytest.fail(f"Web containerActions probe failed: {proc.stderr}\n{proc.stdout}")
    return json.loads(proc.stdout)


def test_web_container_actions_consume_existing_ctrl_fields(app, db_session):
    # 1) 配额满的 brief；2) 硬超限的详情嵌套磁盘；3) 普通 online；4) 待核实 unknown。
    quota_root, quota_machine, quota_target = create_container_graph()
    _r2, _m2, other = create_container_graph(root_user=quota_root, machine=quota_machine)
    long_term_container_repo.add(other.id, created_by_user_id=quota_root.id, session=db_session)
    db_session.commit()
    quota_brief = _brief(db_session, quota_machine, quota_target, quota_root)

    disk_root, disk_machine, disk_target = create_container_graph()
    disk_machine.max_disk_size_gb = 512
    disk_target.disk_total_bytes = 600 * 1024**3
    disk_target.disk_checked_at = datetime.utcnow()
    db_session.commit()
    disk_detail = container_tasks.get_container_detail_information(disk_target.id)

    _online_root, online_machine, online_target = create_container_graph()
    online_brief = _brief(db_session, online_machine, online_target, _online_root)

    unknown_root, unknown_machine, unknown_target = create_container_graph()
    node_comms._handle_container_vanish(unknown_target.name, unknown_machine.id)
    db_session.commit()
    unknown_brief = _brief(db_session, unknown_machine, unknown_target, unknown_root)

    inputs = [
        {
            "container": {
                "effective_status": quota_brief["effective_status"],
                "is_long_term": quota_brief["is_long_term"],
                "long_term_container_can_enable": quota_brief["long_term_container_can_enable"],
                "disk_usage_percent": quota_brief["disk_usage_percent"],
            },
            "context": _web_context(),
        },
        {
            "container": {
                "effective_status": disk_detail["effective_status"],
                "is_long_term": disk_detail["is_long_term"],
                "long_term_container_can_enable": disk_detail["long_term_container_can_enable"],
                "disk_usage": disk_detail["disk_usage"],
            },
            "context": _web_context(),
        },
        {
            "container": {
                "effective_status": online_brief["effective_status"],
                "is_long_term": online_brief["is_long_term"],
                "long_term_container_can_enable": online_brief["long_term_container_can_enable"],
                "disk_usage_percent": online_brief["disk_usage_percent"],
            },
            "context": _web_context(),
        },
        {
            "container": {
                "effective_status": unknown_brief["effective_status"],
                "is_long_term": unknown_brief["is_long_term"],
                "long_term_container_can_enable": unknown_brief["long_term_container_can_enable"],
                "disk_usage_percent": unknown_brief["disk_usage_percent"],
            },
            "context": _web_context(),
        },
    ]

    results = _run_web_actions(inputs)

    assert results[0]["actions"]["long_term_enable"]["enabled"] is False
    assert results[0]["actions"]["long_term_enable"]["reason"] == "long_term_limit_reached"
    assert results[1]["actions"]["long_term_enable"]["enabled"] is False
    assert results[1]["actions"]["long_term_enable"]["reason"] == "disk_usage_over_limit"
    assert results[2]["actions"]["delete"]["enabled"] is True
    assert results[3]["actions"]["delete"]["enabled"] is False
    assert results[3]["actions"]["delete"]["reason"] == "container_status_unknown"

    source = (WEB_ROOT / "src/utils/containerActions.js").read_text(encoding="utf-8")
    assert "fetch(" not in source
    assert "axios" not in source
    assert "/api/" not in source
