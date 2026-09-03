import asyncio
import sys
from datetime import datetime
from pathlib import Path

import pytest

from ...constant import ContainerStatus, MachineStatus, MachineTypes
from ...models.containers import Container
from ...models.machine import Machine
from ...repositories import containers_repo, machine_repo
from ...extensions import session_scope
from ...services import machine_tasks
from ...services.container_module import node_comms
from ..factories import bind_user_container, create_container, create_machine, create_user

# 枚举对齐测试（契约 C8）需要跨仓库导入 NodeKernel（同 test_machine_enrollment_wss 模式）
NODE_ROOT = Path(__file__).resolve().parents[3] / "FuxiYu_NodeKernel"
if str(NODE_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(NODE_ROOT.parent))


class _ClosingWebSocket:
    def __init__(self, uid: str):
        self.scope = {"query_string": f"uid={uid}".encode("utf-8")}
        self.accepted = False
        self.close_calls = []

    async def accept(self):
        self.accepted = True

    async def receive_text(self):
        raise RuntimeError("wss closed")

    async def close(self, code=None):
        self.close_calls.append(code)


class _FramesThenRaiseWebSocket(_ClosingWebSocket):
    """先吐帧（可能坏帧），耗尽后抛异常断开。"""

    def __init__(self, uid: str, frames: list[str]):
        super().__init__(uid)
        self.frames = list(frames)

    async def receive_text(self):
        if self.frames:
            return self.frames.pop(0)
        raise RuntimeError("wss closed")


def test_update_machine_missing_machine_returns_false(db_session):
    assert machine_tasks.Update_machine(999999, machine_name="missing") is False


def test_update_machine_regular_update_calls_repo(db_session):
    machine = create_machine(machine_name="update_machine")

    assert machine_tasks.Update_machine(machine.id, machine_name="updated_machine") is True

    db_session.expire_all()
    assert db_session.get(Machine, machine.id).machine_name == "updated_machine"


@pytest.mark.parametrize("value", ["bad", 9, -1])
def test_update_machine_rejects_invalid_shared_size(db_session, value):
    machine = create_machine(max_memory_gb=8)

    with pytest.raises(ValueError) as excinfo:
        machine_tasks.Update_machine(machine.id, max_shared_gb=value)

    assert getattr(excinfo.value, "error_reason") == "update_failed"


def test_update_machine_rejects_max_shared_greater_than_target_memory(db_session):
    machine = create_machine(max_memory_gb=8)

    with pytest.raises(ValueError, match="cannot be greater"):
        machine_tasks.Update_machine(machine.id, max_shared_gb=6, max_memory_gb=4)


def test_update_machine_sets_maintenance_switch(db_session):
    # 维护态为纯开关，不写入 machine_status。
    machine = create_machine(machine_status=MachineStatus.ONLINE, machine_description="old")

    assert machine_tasks.Update_machine(machine.id, is_maintenance=True, machine_description="new") is True

    db_session.expire_all()
    refreshed = db_session.get(Machine, machine.id)
    assert refreshed.machine_status == MachineStatus.ONLINE
    assert refreshed.is_maintenance is True
    assert refreshed.machine_description == "new"


def test_update_machine_rejects_maintenance_as_machine_status(db_session):
    machine = create_machine(machine_status=MachineStatus.ONLINE)

    with pytest.raises(ValueError, match="is_maintenance"):
        machine_tasks.Update_machine(machine.id, machine_status="maintenance")


def test_set_maintenance_updates_switch_without_status_change(db_session):
    machine = create_machine(machine_status=MachineStatus.ONLINE, is_maintenance=False)

    assert machine_tasks.Set_maintenance(machine.id, True) is True

    db_session.expire_all()
    refreshed = db_session.get(Machine, machine.id)
    assert refreshed.machine_status == MachineStatus.ONLINE
    assert refreshed.is_maintenance is True


def test_set_maintenance_missing_machine_returns_false(db_session):
    assert machine_tasks.Set_maintenance(999999, True) is False


def test_is_machine_online_remote_true_when_node_online(monkeypatch, db_session):
    machine = create_machine(machine_ip="10.0.0.8")
    monkeypatch.setattr(node_comms, "send", lambda url, payload, timeout=2.0: {"success": 1, "machine_status": "online"})

    assert machine_tasks.is_machine_online_remote(machine.id) is True


def test_is_machine_online_remote_false_when_machine_missing(db_session):
    assert machine_tasks.is_machine_online_remote(999999) is False


def test_is_machine_online_remote_false_when_node_offline(monkeypatch, db_session):
    machine = create_machine()
    monkeypatch.setattr(node_comms, "send", lambda url, payload, timeout=2.0: {"success": 1, "machine_status": "offline"})

    assert machine_tasks.is_machine_online_remote(machine.id) is False


def test_is_machine_online_remote_false_when_send_raises(monkeypatch, db_session):
    machine = create_machine()
    monkeypatch.setattr(node_comms, "send", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network")))

    assert machine_tasks.is_machine_online_remote(machine.id) is False


def test_handle_node_ws_marks_machine_online_on_accept(monkeypatch, db_session):
    uid = "wss-online-uid"
    machine = create_machine(machine_status=MachineStatus.OFFLINE)
    with session_scope() as session:
        machine_repo.update_machine(machine.id, node_uid=uid, session=session)
    monkeypatch.setattr(node_comms, "probe_machine_connectivity", lambda machine_id: True)

    ws = _ClosingWebSocket(uid)
    asyncio.run(node_comms.handle_node_ws(ws))

    db_session.expire_all()
    assert ws.accepted is True
    assert db_session.get(Machine, machine.id).machine_status == MachineStatus.ONLINE


def test_handle_node_ws_marks_machine_offline_when_disconnect_probe_fails(monkeypatch, db_session):
    uid = "wss-offline-uid"
    machine = create_machine(machine_status=MachineStatus.ONLINE)
    with session_scope() as session:
        machine_repo.update_machine(machine.id, node_uid=uid, session=session)
    monkeypatch.setattr(node_comms, "probe_machine_connectivity", lambda machine_id: False)

    ws = _ClosingWebSocket(uid)
    asyncio.run(node_comms.handle_node_ws(ws))

    db_session.expire_all()
    assert ws.accepted is True
    assert ws.close_calls
    assert db_session.get(Machine, machine.id).machine_status == MachineStatus.OFFLINE


def test_handle_node_ws_keeps_machine_online_when_disconnect_probe_succeeds(monkeypatch, db_session):
    uid = "wss-probe-ok-uid"
    machine = create_machine(machine_status=MachineStatus.ONLINE)
    with session_scope() as session:
        machine_repo.update_machine(machine.id, node_uid=uid, session=session)
    monkeypatch.setattr(node_comms, "probe_machine_connectivity", lambda machine_id: True)

    ws = _ClosingWebSocket(uid)
    asyncio.run(node_comms.handle_node_ws(ws))

    db_session.expire_all()
    assert ws.accepted is True
    assert db_session.get(Machine, machine.id).machine_status == MachineStatus.ONLINE


def test_apply_container_status_snapshot_removes_db_container_missing_on_node(db_session):
    machine = create_machine()
    container = create_container(machine=machine, name="missing_on_node", status=ContainerStatus.CREATING)
    container_id = container.id

    # 非空快照中缺该容器 → 视为 Node 侧消失，复用删除清理
    result = node_comms.apply_container_status_snapshot({"other_container": {"status": "online"}}, machine.id)

    db_session.expire_all()
    assert result["vanished"] == 1
    assert db_session.get(Container, container_id) is None


def test_apply_container_status_snapshot_ignores_empty_snapshot(db_session):
    # 数据通路对账契约 C1：空 dict 不触发 vanished（Node 契约不发出空 dict；防御性跳过）
    machine = create_machine()
    container = create_container(machine=machine, name="keep_on_empty", status=ContainerStatus.ONLINE)
    container_id = container.id

    result = node_comms.apply_container_status_snapshot({}, machine.id)

    db_session.expire_all()
    assert result["vanished"] == 0
    assert result["failed"] == 0
    assert db_session.get(Container, container_id) is not None


def test_apply_container_status_snapshot_collect_error_sets_machine_flag_not_container_status(db_session):
    # 数据通路对账契约 C1（机器轴）：collect_error 形状 → 置位机器 collect_error_at，
    # 不动容器 DB 状态（保持最后已知值，非容器诊断）
    machine = create_machine()
    c1 = create_container(machine=machine, name="err_c1", status=ContainerStatus.ONLINE)
    c2 = create_container(machine=machine, name="err_c2", status=ContainerStatus.CREATING)

    result = node_comms.apply_container_status_snapshot({"collect_error": "collect_failed"}, machine.id)

    db_session.expire_all()
    assert result["failed"] == 0
    assert db_session.get(Machine, machine.id).collect_error_at is not None
    assert db_session.get(Container, c1.id).container_status == ContainerStatus.ONLINE
    assert db_session.get(Container, c2.id).container_status == ContainerStatus.CREATING


def test_apply_container_status_snapshot_normal_snapshot_clears_collect_error(db_session):
    # 数据通路对账契约 C1（恢复）：正常快照清除机器 collect_error_at，状态照常覆盖
    machine = create_machine()
    container = create_container(machine=machine, name="recover_c", status=ContainerStatus.ONLINE)
    with session_scope() as session:
        machine_repo.update_machine(machine.id, collect_error_at=datetime(2026, 8, 24), session=session)

    result = node_comms.apply_container_status_snapshot({"recover_c": {"status": "offline"}}, machine.id)

    db_session.expire_all()
    assert result["updated"] == 1
    machine_row = db_session.get(Machine, machine.id)
    assert machine_row.collect_error_at is None
    assert db_session.get(Container, container.id).container_status == ContainerStatus.OFFLINE


def test_apply_container_status_snapshot_unknown_sets_marker_keeps_last_status(db_session):
    # 容器轴 unknown（2026-09-03，仿机器 collect_error）：unknown 帧只落标记列，
    # 不覆盖 container_status（最后已知为真），展示派生 status_unknown
    machine = create_machine()
    container = create_container(machine=machine, name="unknown_c", status=ContainerStatus.ONLINE)
    container_id = container.id

    result = node_comms.apply_container_status_snapshot(
        {"unknown_c": {"status": "unknown", "status_source": "cold_start_verify", "unknown_since": "2026-09-03T01:20:00"}},
        machine.id,
    )

    db_session.expire_all()
    row = db_session.get(Container, container_id)
    assert result["updated"] == 1
    assert row.container_status == ContainerStatus.ONLINE  # 不被覆盖
    assert row.status_source == "cold_start_verify"
    assert row.status_unknown_since is not None

    # 同一标记重复推送（心跳）→ 不重复写
    result2 = node_comms.apply_container_status_snapshot(
        {"unknown_c": {"status": "unknown", "status_source": "cold_start_verify", "unknown_since": "2026-09-03T01:20:00"}},
        machine.id,
    )
    assert result2["updated"] == 0


def test_apply_container_status_snapshot_concrete_status_clears_unknown_marker(db_session):
    # 容器轴 unknown 恢复：具体状态帧（probe 通过 online）→ 清除标记并覆盖状态
    machine = create_machine()
    container = create_container(machine=machine, name="unknown_recover", status=ContainerStatus.ONLINE)
    container_id = container.id
    with session_scope() as session:
        containers_repo.update_container(
            container_id,
            status_unknown_since=datetime(2026, 9, 3, 1, 20),
            status_source="cold_start_verify",
            session=session,
        )

    result = node_comms.apply_container_status_snapshot(
        {"unknown_recover": {"status": "online"}}, machine.id,
    )

    db_session.expire_all()
    row = db_session.get(Container, container_id)
    assert result["updated"] == 1
    assert row.status_unknown_since is None
    assert row.status_source is None
    assert row.container_status == ContainerStatus.ONLINE


def test_apply_container_status_snapshot_collect_error_without_machine_id_skipped(db_session):
    machine = create_machine()
    container = create_container(machine=machine, name="err_no_mid", status=ContainerStatus.ONLINE)

    result = node_comms.apply_container_status_snapshot({"collect_error": "collect_failed"}, None)

    db_session.expire_all()
    assert result["failed"] == 0
    assert db_session.get(Machine, machine.id).collect_error_at is None
    assert db_session.get(Container, container.id).container_status == ContainerStatus.ONLINE


def test_apply_snapshot_batch_drops_frame_on_unresolved_uid(db_session):
    # 数据通路对账契约 C5：node_uid 归位失败 → 整帧丢弃（不降级 name 查找）
    machine = create_machine()
    container = create_container(machine=machine, name="no_uid_c", status=ContainerStatus.ONLINE)
    container_id = container.id

    result = node_comms.apply_snapshot_batch({
        "type": "snapshot_batch",
        "node_uid": "does-not-exist",
        "payload": [{"type": "snapshot", "topic": "container_status",
                     "payload": {"no_uid_c": {"status": "offline"}}}],
    })

    db_session.expire_all()
    assert result == {}
    assert db_session.get(Container, container_id).container_status == ContainerStatus.ONLINE


def test_apply_snapshot_batch_dispatches_with_resolved_uid(db_session):
    machine = create_machine()
    with session_scope() as session:
        machine_repo.update_machine(machine.id, node_uid="uid-ok", session=session)
    container = create_container(machine=machine, name="uid_ok_c", status=ContainerStatus.ONLINE)

    result = node_comms.apply_snapshot_batch({
        "type": "snapshot_batch",
        "node_uid": "uid-ok",
        "payload": [{"type": "snapshot", "topic": "container_status",
                     "payload": {"uid_ok_c": {"status": "offline"}}}],
    })

    db_session.expire_all()
    assert result["container_status"]["updated"] == 1
    assert db_session.get(Container, container.id).container_status == ContainerStatus.OFFLINE


def test_probe_machines_online_once_marks_unreachable_offline(monkeypatch, db_session):
    # 数据通路对账契约 C3：Ctrl 启动探活，不达的 ONLINE 机器置 OFFLINE
    machine = create_machine(machine_status=MachineStatus.ONLINE)
    monkeypatch.setattr(node_comms, "probe_machine_connectivity", lambda machine_id: False)

    result = node_comms.probe_machines_online_once()

    db_session.expire_all()
    assert result["probed"] == 1
    assert result["turned_offline"] == [machine.id]
    assert db_session.get(Machine, machine.id).machine_status == MachineStatus.OFFLINE


def test_probe_machines_online_once_keeps_reachable_online(monkeypatch, db_session):
    machine = create_machine(machine_status=MachineStatus.ONLINE)
    monkeypatch.setattr(node_comms, "probe_machine_connectivity", lambda machine_id: True)

    result = node_comms.probe_machines_online_once()

    db_session.expire_all()
    assert result["probed"] == 1
    assert result["turned_offline"] == []
    assert db_session.get(Machine, machine.id).machine_status == MachineStatus.ONLINE


def test_handle_node_ws_malformed_frame_does_not_kill_connection(monkeypatch, db_session):
    # 契约 C7：坏帧（非 JSON/非 dict/数组）→ 帧级容错 continue，不杀连接；
    # 连接只由最后一次 receive 的断开异常正常收尾
    uid = "wss-badframe-uid"
    machine = create_machine(machine_status=MachineStatus.ONLINE)
    with session_scope() as session:
        machine_repo.update_machine(machine.id, node_uid=uid, session=session)
    probe_calls = []
    monkeypatch.setattr(node_comms, "probe_machine_connectivity",
                        lambda machine_id: probe_calls.append(machine_id) or False)

    ws = _FramesThenRaiseWebSocket(uid, ["{not json", '"hello"', "[]"])
    asyncio.run(node_comms.handle_node_ws(ws))

    db_session.expire_all()
    assert probe_calls == [machine.id]  # 只断一次（收尾路径），坏帧不触发
    assert db_session.get(Machine, machine.id).machine_status == MachineStatus.OFFLINE


def test_handle_node_ws_read_timeout_triggers_probe_and_offline(monkeypatch, db_session):
    # 契约 C4：半开连接（receive 挂起）→ wait_for 超时 → 探活 → 不达置 OFFLINE
    uid = "wss-timeout-uid"
    machine = create_machine(machine_status=MachineStatus.ONLINE)
    with session_scope() as session:
        machine_repo.update_machine(machine.id, node_uid=uid, session=session)
    probe_calls = []
    monkeypatch.setattr(node_comms, "probe_machine_connectivity",
                        lambda machine_id: probe_calls.append(machine_id) or False)
    monkeypatch.setattr(node_comms.CommsConfig, "WSS_READ_TIMEOUT", 0.01)

    class _HangingWebSocket(_ClosingWebSocket):
        async def receive_text(self):
            await asyncio.sleep(3600)

    ws = _HangingWebSocket(uid)
    asyncio.run(node_comms.handle_node_ws(ws))

    db_session.expire_all()
    assert probe_calls == [machine.id]
    assert db_session.get(Machine, machine.id).machine_status == MachineStatus.OFFLINE


def test_enqueue_frame_drops_oldest_when_full():
    # 契约 C7：队列满时丢最旧（快照幂等覆盖，丢旧不丢新），receive 永不阻塞
    q = asyncio.Queue(maxsize=2)
    node_comms._enqueue_frame(q, {"seq": 1})
    node_comms._enqueue_frame(q, {"seq": 2})
    node_comms._enqueue_frame(q, {"seq": 3})

    assert q.qsize() == 2
    assert q.get_nowait() == {"seq": 2}
    assert q.get_nowait() == {"seq": 3}


def test_consume_frames_applies_snapshot_and_delete(monkeypatch):
    # 契约 C7：单消费者串行处理（快照落库线程化，事件循环只 receive）
    applied = []
    monkeypatch.setattr(node_comms, "apply_snapshot_batch", lambda batch: applied.append(batch))
    monkeypatch.setattr(node_comms, "_handle_container_deleted", lambda name, machine_id=None: applied.append(("del", name)))
    q = asyncio.Queue()
    q.put_nowait({"type": "snapshot_batch", "payload": [1]})
    q.put_nowait({"type": "delete", "container_name": "ghost_c"})

    async def _run():
        task = asyncio.create_task(node_comms._consume_frames(q, "uid", machine_id=7))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run())
    assert applied == [{"type": "snapshot_batch", "payload": [1]}, ("del", "ghost_c")]


def test_apply_container_status_snapshot_transition_states_kept_last_known(db_session):
    # 契约 C8：pausing/unpausing 显式跳过，DB 保持最后已知值（终态由下一帧收敛）
    machine = create_machine()
    c1 = create_container(machine=machine, name="pausing_c", status=ContainerStatus.ONLINE)
    c2 = create_container(machine=machine, name="unpausing_c", status=ContainerStatus.PAUSED)

    result = node_comms.apply_container_status_snapshot(
        {"pausing_c": {"status": "pausing"}, "unpausing_c": {"status": "unpausing"}},
        machine.id,
    )

    db_session.expire_all()
    assert result["skipped"] == 2
    assert db_session.get(Container, c1.id).container_status == ContainerStatus.ONLINE
    assert db_session.get(Container, c2.id).container_status == ContainerStatus.PAUSED


def test_node_emittable_statuses_covered_by_ctrl_mapping():
    """契约 C8：Node 可发状态枚举 ⊆ Ctrl 映射表 ∪ 显式跳过集（防静默漏配）。

    Node 侧全集 = docker 终态映射值 ∪ 事件映射值 ∪ begin_action 转换态 ∪ failed/unknown。
    任一新增状态未覆盖 → 测试失败，迫使 Ctrl 侧显式处置。
    """
    pytest.importorskip("FuxiYu_NodeKernel", reason="NodeKernel 仓库不在本机")
    from FuxiYu_NodeKernel.constant import ContainerStatus as NodeContainerStatus
    from FuxiYu_NodeKernel.docker_operates import status_cache as node_status_cache

    emittable = set(node_status_cache._DOCKER_STATUS_TO_APP.values())
    emittable |= set(node_status_cache._EVENT_STATUS_MAP.values())
    emittable |= {
        NodeContainerStatus.CREATING.value,   # begin_action create（api.py）
        NodeContainerStatus.BUILDING.value,   # begin_build（api.py）
        NodeContainerStatus.STOPPING.value,   # begin_action stop
        "pausing",                            # begin_action pause（api.py 字面量）
        "unpausing",                          # begin_action unpause（api.py 字面量）
        NodeContainerStatus.FAILED.value,     # finish_action failed / pending TTL 超时
        NodeContainerStatus.UNKNOWN.value,    # c.status 兜底（契约 C2 后理论不可达）
    }
    covered = set(node_comms._NODE_STATUS_TO_CTRL) | set(node_comms._NODE_STATUS_SKIP)
    uncovered = emittable - covered
    assert not uncovered, f"Node 可发状态未覆盖: {uncovered}"


def test_apply_container_status_snapshot_ignores_unknown_node_container(db_session, monkeypatch):
    machine = create_machine()
    published = []
    monkeypatch.setattr(node_comms, "_publish_container_runtime_snapshot", lambda machine_id, snapshot: published.append((machine_id, snapshot)))

    result = node_comms.apply_container_status_snapshot(
        {"unknown_on_ctrl": {"status": "online", "runtime_metrics": {"cpu_usage_percent": 50}}},
        machine.id,
    )

    assert result["updated"] == 0
    assert result["skipped"] == 1
    assert result["vanished"] == 0
    assert node_comms.get_cached_container_runtime_metrics(machine.id, "unknown_on_ctrl") is None
    assert published == []


def test_apply_container_status_snapshot_caches_known_container_runtime_metrics(db_session, monkeypatch):
    machine = create_machine()
    create_container(machine=machine, name="metrics_on_ctrl", status=ContainerStatus.ONLINE)
    published = []
    monkeypatch.setattr(node_comms, "_publish_container_runtime_snapshot", lambda machine_id, snapshot: published.append((machine_id, snapshot)))

    result = node_comms.apply_container_status_snapshot(
        {
            "metrics_on_ctrl": {
                "status": "online",
                "runtime_metrics": {
                    "cpu_usage_percent": 12.5,
                    "memory_usage_percent": 40,
                    "gpu": {
                        "device_ids": ["0"],
                        "devices": [{"index": 0, "utilization_gpu_percent": 70}],
                    },
                },
            }
        },
        machine.id,
    )

    assert result["updated"] == 1
    assert published == [
        (
            machine.id,
            {
                "metrics_on_ctrl": {
                    "status": "online",
                    "runtime_metrics": {
                        "cpu_usage_percent": 12.5,
                        "memory_usage_percent": 40,
                        "gpu": {
                            "device_ids": ["0"],
                            "devices": [{"index": 0, "utilization_gpu_percent": 70}],
                        },
                    },
                },
            },
        )
    ]
    node_comms.write_container_runtime_buffer(machine.id, published[0][1])
    cached = node_comms.get_cached_container_runtime_metrics(machine.id, "metrics_on_ctrl")
    assert cached["cpu_usage_percent"] == 12.5
    assert cached["gpu"]["devices"][0]["utilization_gpu_percent"] == 70


def test_apply_container_status_snapshot_suppresses_runtime_metrics_when_machine_not_online(db_session, monkeypatch):
    machine = create_machine(machine_status=MachineStatus.OFFLINE)
    create_container(machine=machine, name="offline_metrics_on_ctrl", status=ContainerStatus.ONLINE)
    published = []
    monkeypatch.setattr(node_comms, "_publish_container_runtime_snapshot", lambda machine_id, snapshot: published.append((machine_id, snapshot)))

    result = node_comms.apply_container_status_snapshot(
        {
            "offline_metrics_on_ctrl": {
                "status": "online",
                "runtime_metrics": {
                    "cpu_usage_percent": 88,
                    "gpu": {
                        "device_ids": ["0"],
                        "devices": [{"index": 0, "utilization_gpu_percent": 70}],
                    },
                },
            }
        },
        machine.id,
    )

    assert result["updated"] == 1
    assert published == [
        (
            machine.id,
            {
                "offline_metrics_on_ctrl": {
                    "status": "online",
                    "failed_reason": None,
                    "failed_detail": None,
                },
            },
        )
    ]
    node_comms.write_container_runtime_buffer(machine.id, published[0][1])
    assert node_comms.get_cached_container_runtime_metrics(machine.id, "offline_metrics_on_ctrl") is None


def test_write_container_runtime_buffer_clears_named_runtime_metrics(db_session):
    machine = create_machine()
    node_comms.write_container_runtime_buffer(
        machine.id,
        {"buffer_clear_c": {"status": "online", "runtime_metrics": {"cpu_usage_percent": 50}}},
    )
    assert node_comms.get_cached_container_runtime_metrics(machine.id, "buffer_clear_c") == {"cpu_usage_percent": 50}

    node_comms.write_container_runtime_buffer(
        machine.id,
        {"buffer_clear_c": {"status": "online", "failed_reason": None, "failed_detail": None}},
    )

    assert node_comms.get_cached_container_runtime_metrics(machine.id, "buffer_clear_c") is None


def test_internal_runtime_api_writes_container_and_machine_buffers(client, db_session):
    machine = create_machine()
    container_payload = {
        "machine_id": machine.id,
        "snapshot": {
            "api_buffer_c": {
                "status": "online",
                "runtime_metrics": {"cpu_usage_percent": 18.5},
            },
        },
    }
    machine_payload = {
        "machine_id": machine.id,
        "snapshot": {"cpu": {"usage_percent": 22.0}},
    }

    c_resp = client.post("/api/internal/runtime/containers", json=container_payload)
    m_resp = client.post("/api/internal/runtime/machines", json=machine_payload)

    assert c_resp.status_code == 200
    assert c_resp.json()["updated"] == 1
    assert m_resp.status_code == 200
    assert m_resp.json()["updated"] == 1
    assert node_comms.get_cached_container_runtime_metrics(machine.id, "api_buffer_c") == {"cpu_usage_percent": 18.5}
    assert node_comms.get_cached_machine_runtime_snapshot(machine.id) == {"cpu": {"usage_percent": 22.0}}


def test_apply_container_status_snapshot_accepts_restarting(db_session):
    machine = create_machine()
    container = create_container(machine=machine, name="restarting_on_node", status=ContainerStatus.ONLINE)

    result = node_comms.apply_container_status_snapshot(
        {"restarting_on_node": {"status": ContainerStatus.RESTARTING.value}},
        machine.id,
    )

    db_session.expire_all()
    assert result["updated"] == 1
    assert result["skipped"] == 0
    assert result["vanished"] == 0
    assert db_session.get(Container, container.id).container_status == ContainerStatus.RESTARTING


def test_apply_container_status_snapshot_persists_failed_diagnostics(db_session):
    machine = create_machine()
    container = create_container(machine=machine, name="build_failed_on_node", status=ContainerStatus.BUILDING)

    result = node_comms.apply_container_status_snapshot(
        {
            "build_failed_on_node": {
                "status": ContainerStatus.FAILED.value,
                "failed_reason": "build_failed",
                "failed_detail": "docker build failed",
            }
        },
        machine.id,
    )

    db_session.expire_all()
    refreshed = db_session.get(Container, container.id)
    assert result["updated"] == 1
    assert result["failed"] == 1
    assert result["vanished"] == 0
    assert refreshed.container_status == ContainerStatus.FAILED
    assert refreshed.failed_reason == "build_failed"
    assert refreshed.failed_detail == "docker build failed"


def test_apply_container_status_snapshot_clears_failed_diagnostics_on_recovery(db_session):
    machine = create_machine()
    container = create_container(machine=machine, name="recover_failed_diag", status=ContainerStatus.FAILED)
    with session_scope() as session:
        containers_repo.update_container(
            container.id,
            container_status=ContainerStatus.FAILED,
            failed_reason="build_failed",
            failed_detail="docker build failed",
            session=session,
        )

    result = node_comms.apply_container_status_snapshot(
        {"recover_failed_diag": {"status": ContainerStatus.ONLINE.value}},
        machine.id,
    )

    db_session.expire_all()
    refreshed = db_session.get(Container, container.id)
    assert result["updated"] == 1
    assert refreshed.container_status == ContainerStatus.ONLINE
    assert refreshed.failed_reason is None
    assert refreshed.failed_detail is None


def test_list_machine_bref_does_not_probe_or_mutate_offline_machine(monkeypatch, db_session):
    machine = create_machine(machine_status=MachineStatus.OFFLINE)
    monkeypatch.setattr(
        machine_tasks,
        "is_machine_online_remote",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not probe node")),
    )

    result, total_pages = machine_tasks.List_all_machine_bref_information(0, 10)

    assert total_pages == 1
    assert result[0].id == machine.id
    assert result[0].machine_status == MachineStatus.OFFLINE.value
    db_session.expire_all()
    assert db_session.get(Machine, machine.id).machine_status == MachineStatus.OFFLINE


def test_list_machine_bref_keeps_online_machine_and_containers_without_probe(monkeypatch, db_session):
    machine = create_machine(machine_status=MachineStatus.ONLINE)
    container = create_container(machine=machine, status=ContainerStatus.ONLINE)
    monkeypatch.setattr(
        machine_tasks,
        "is_machine_online_remote",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not probe node")),
    )

    result, _ = machine_tasks.List_all_machine_bref_information(0, 10)

    assert result[0].machine_status == MachineStatus.ONLINE.value
    db_session.expire_all()
    assert db_session.get(Machine, machine.id).machine_status == MachineStatus.ONLINE
    assert db_session.get(Container, container.id).container_status == ContainerStatus.ONLINE


def test_list_machine_bref_keeps_maintenance_flag_without_probe(monkeypatch, db_session):
    machine = create_machine(machine_status=MachineStatus.OFFLINE, is_maintenance=True)
    monkeypatch.setattr(
        machine_tasks,
        "is_machine_online_remote",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not probe node")),
    )

    result, _ = machine_tasks.List_all_machine_bref_information(0, 10)

    assert result[0].machine_status == MachineStatus.OFFLINE.value
    assert result[0].is_maintenance is True


def test_list_machine_bref_online_maintenance_flag_without_probe(monkeypatch, db_session):
    machine = create_machine(machine_status=MachineStatus.ONLINE, is_maintenance=True)
    monkeypatch.setattr(
        machine_tasks,
        "is_machine_online_remote",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not probe node")),
    )

    result, _ = machine_tasks.List_all_machine_bref_information(0, 10)

    assert result[0].machine_status == MachineStatus.ONLINE.value
    assert result[0].is_maintenance is True


def test_list_machine_bref_keeps_machine_status_when_collect_error_exists(db_session):
    online = create_machine(machine_name="ce_online", machine_status=MachineStatus.ONLINE)
    offline = create_machine(machine_name="ce_offline", machine_status=MachineStatus.OFFLINE)
    with session_scope() as session:
        machine_repo.update_machine(online.id, collect_error_at=datetime(2026, 8, 24), session=session)
        machine_repo.update_machine(offline.id, collect_error_at=datetime(2026, 8, 24), session=session)

    result, _ = machine_tasks.List_all_machine_bref_information(0, 10)

    by_name = {m.machine_name: m for m in result}
    assert by_name["ce_online"].machine_status == MachineStatus.ONLINE.value
    assert by_name["ce_offline"].machine_status == MachineStatus.OFFLINE.value

def test_is_machine_collect_error_reads_machine_flag(db_session):
    machine = create_machine()
    assert machine_tasks.is_machine_collect_error(machine.id) is False
    with session_scope() as session:
        machine_repo.update_machine(machine.id, collect_error_at=datetime(2026, 8, 24), session=session)
    db_session.expire_all()
    assert machine_tasks.is_machine_collect_error(machine.id) is True


def test_list_machine_bref_filters_by_machine_search(monkeypatch, db_session):
    target = create_machine(machine_name="search_target", machine_ip="10.20.30.40")
    create_machine(machine_name="other_machine", machine_ip="10.20.30.41")
    monkeypatch.setattr(
        machine_tasks,
        "is_machine_online_remote",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not probe node")),
    )

    by_name, _ = machine_tasks.List_all_machine_bref_information(0, 10, machine_search="target")
    by_ip, _ = machine_tasks.List_all_machine_bref_information(0, 10, machine_search="10.20.30.40")
    by_id, _ = machine_tasks.List_all_machine_bref_information(0, 10, machine_search=str(target.id))

    assert [m.id for m in by_name] == [target.id]
    assert [m.id for m in by_ip] == [target.id]
    assert target.id in [m.id for m in by_id]


def test_list_machine_bref_operator_bypasses_machine_permission(monkeypatch, db_session):
    operator = create_user(operator=True)
    # 模拟建号流程的组绑定：operator 用户加入含 bypass_resource 的组
    from ...repositories import auth_repo
    with session_scope() as session:
        group = auth_repo.ensure_group("operator", "t", session=session)
        auth_repo.ensure_group_entity(group.id, "bypass_resource", session=session)
        auth_repo.ensure_user_group(operator.id, group.id, session=session)
    m1 = create_machine(machine_name="operator_machine_1")
    m2 = create_machine(machine_name="operator_machine_2")
    monkeypatch.setattr(
        machine_tasks,
        "is_machine_online_remote",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not probe node")),
    )

    result, _ = machine_tasks.List_all_machine_bref_information(0, 10, user_id=operator.id)

    assert {m.id for m in result} == {m1.id, m2.id}


def test_apply_sys_snapshot_drift_updates_db_and_trims_limits(db_session, monkeypatch):
    """实际硬件缩水 → 更新 DB 实际值 + trim CPU/内存上限（GPU 不 trim，走三集合）。"""
    machine = create_machine(
        machine_type=MachineTypes.GPU,
        cpu_core_number=8, memory_size_gb=16, gpu_number=2,
        max_cpu_core_number=8, max_memory_gb=16, max_gpu_number=2,
    )
    monkeypatch.setattr(node_comms, "_publish_machine_runtime_snapshot", lambda *a, **k: None)

    result = node_comms.apply_sys_snapshot({
        "cpu": {"cores": 8, "usage_percent": 10},
        "memory": {"total_gb": 7, "usage_percent": 50},
        "disk": {"bind_mount": {"total_gb": 200, "percent": 20}},
        "gpu": [],
    }, machine.id)

    assert result["drifted"] == 1
    db_session.expire_all()
    m = db_session.get(Machine, machine.id)
    assert m.memory_size_gb == 7      # 实际更新
    assert m.max_memory_gb == 7       # trim
    assert m.gpu_number == 0          # 实际更新
    assert m.gpu_list == []           # gpu_list 事实字段更新
    assert m.max_gpu_number == 2      # GPU 不 trim（决策：许可人工）
    assert m.cpu_core_number == 8     # 无变化不动
    assert m.max_cpu_core_number == 8
    assert m.disk_size_gb == 200      # disk_size_gb 显示字段更新（bind_mount 分区容量）

    # 第二次同帧：不再视为 drift（已收敛），不重复写
    result2 = node_comms.apply_sys_snapshot({
        "cpu": {"cores": 8},
        "memory": {"total_gb": 7},
        "disk": {"bind_mount": {"total_gb": 200}},
        "gpu": [],
    }, machine.id)
    assert result2["drifted"] == 0


def test_alloc_cascade_drift_then_container_trim(db_session, monkeypatch):
    """规格(3) 全链路（DB 实走）：机器真值 3/上限 5 → 漂移 trim 上限 3；
    容器申请 4 → alloc 沿新上限显示 3 + degraded。两层递进降级。"""
    machine = create_machine(
        machine_type=MachineTypes.GPU,
        cpu_core_number=5, memory_size_gb=5, gpu_number=1,
        max_cpu_core_number=5, max_memory_gb=5, max_gpu_number=1,
    )
    container = create_container(machine=machine, name="cascade_c", status=ContainerStatus.ONLINE)
    monkeypatch.setattr(node_comms, "_publish_machine_runtime_snapshot", lambda *a, **k: None)

    # 层 1：机器真值降级 5 → 3，drift 将 max_* trim 到 3
    result = node_comms.apply_sys_snapshot({
        "cpu": {"cores": 3, "usage_percent": 10},
        "memory": {"total_gb": 3, "usage_percent": 50},
        "disk": {"bind_mount": {"total_gb": 100, "percent": 20}},
        "gpu": [],
    }, machine.id)
    assert result["drifted"] == 1

    # 层 2：容器申请 4，沿已 trim 的新上限派生显示
    from ...services.container_module.utils import derive_allocated_limits
    container.cpu_number = 4
    container.memory_gb = 4
    with session_scope(commit=False) as session:
        m = machine_repo.get_by_id(machine.id, session=session)
    alloc = derive_allocated_limits(container, m)
    assert m.max_cpu_core_number == 3
    assert m.max_memory_gb == 3
    assert alloc["alloc_cpu_number"] == 3
    assert alloc["alloc_memory_gb"] == 3
    assert alloc["alloc_degraded"] is True


def test_apply_sys_snapshot_gpu_enum_updates_gpu_list_not_allow(db_session, monkeypatch):
    """GPU 枚举变化 → 更新 gpu_list/gpu_number（事实），allow_list/max_gpu_number 不动。"""
    machine = create_machine(
        machine_type=MachineTypes.GPU,
        cpu_core_number=8, memory_size_gb=16, gpu_number=2,
        max_cpu_core_number=8, max_memory_gb=16, max_gpu_number=2,
        gpu_allow_list=[0, 1],
    )
    monkeypatch.setattr(node_comms, "_publish_machine_runtime_snapshot", lambda *a, **k: None)

    result = node_comms.apply_sys_snapshot({
        "cpu": {"cores": 8},
        "memory": {"total_gb": 16},
        "disk": {"bind_mount": {"total_gb": 1024}},
        "gpu": [{"index": 0, "name": "RTX 4060"}],
    }, machine.id)

    assert result["drifted"] == 1
    db_session.expire_all()
    m = db_session.get(Machine, machine.id)
    assert m.gpu_number == 1          # 实际数量更新
    assert m.gpu_list == [0]          # 事实枚举更新
    assert m.gpu_allow_list == [0, 1]  # 许可不动（人工维护）
    assert m.max_gpu_number == 2      # 不 trim


def test_apply_container_status_snapshot_backfills_port_mappings(db_session):
    """docker 自动分配端口：快照条目带 port/port_mappings → 落库（None 不覆盖现值）。"""
    machine = create_machine()
    container = create_container(machine=machine)

    result = node_comms.apply_container_status_snapshot({
        container.name: {
            "status": "online",
            "port": 32791,
            "port_mappings": [
                {"container_port": 22, "host_port": 32791, "protocol": "tcp"},
                {"container_port": 8888, "host_port": 32792, "protocol": "tcp"},
            ],
        },
    }, machine.id)

    assert result["updated"] == 1
    db_session.expire_all()
    c = db_session.get(Container, container.id)
    assert c.port == 32791
    assert c.port_mappings[1]["container_port"] == 8888

    # 后续帧无端口信息（None）→ 不覆盖 DB 现值
    node_comms.apply_container_status_snapshot({container.name: {"status": "online"}}, machine.id)
    db_session.expire_all()
    c = db_session.get(Container, container.id)
    assert c.port == 32791
    assert c.port_mappings is not None


def test_handle_container_deleted_scoped_to_sending_machine(db_session):
    """delete 帧删除限定在发送机器内：跨机器同名容器不被误删（2026-09 修复）。

    容器名只在单机内唯一——机器 A 的容器 X 消失，机器 B 的 delete 帧
    不得抹掉机器 A 的记录。
    """
    from ...models.containers import Container

    machine_a = create_machine(machine_name="node-a")
    machine_b = create_machine(machine_name="node-b")
    ca = create_container(machine=machine_a, name="shared_name")
    cb = create_container(machine=machine_b, name="shared_name")
    db_session.commit()

    def _exists(cid):
        with session_scope(commit=False) as session:
            return session.get(Container, cid) is not None

    # 机器 B 报 shared_name 消失 → 只应删机器 B 的容器
    node_comms._handle_container_deleted("shared_name", machine_b.id)

    assert _exists(ca.id), "机器 A 的容器不应被机器 B 的 delete 帧删除"
    assert not _exists(cb.id), "机器 B 自己的容器应被删除"

    # 无 machine_id → 拒绝删除（不降级全局查找）
    node_comms._handle_container_deleted("shared_name")
    assert _exists(ca.id)

    # 机器 A 自己的 vanished 路径正常删除
    node_comms._handle_container_deleted("shared_name", machine_a.id)
    assert not _exists(ca.id)


def test_internal_runtime_api_requires_shared_token(client, monkeypatch):
    """内部 buffer 端点双重校验：loopback + 共享 token（2026-09 修复）。

    testclient 豁免仅限 TESTING；模拟本地来源后无/错 token → 403，正确 token → 200。
    """
    from ...api import internal_runtime_api

    machine = create_machine()
    payload = {"machine_id": machine.id, "snapshot": {"token_c": {"runtime_metrics": {"cpu_usage_percent": 1.0}}}}

    # 模拟"本地进程"来源 + 关闭 TESTING 豁免（验证 token 本身，而非 testclient 白名单）
    monkeypatch.setattr(internal_runtime_api, "_is_loopback", lambda request: True)
    monkeypatch.setattr(internal_runtime_api.AppConfig, "TESTING", False)

    # 无 token → 403
    resp = client.post("/api/internal/runtime/containers", json=payload)
    assert resp.status_code == 403

    # 错误 token → 403
    resp = client.post("/api/internal/runtime/containers", json=payload, headers={"X-Internal-Token": "wrong-token"})
    assert resp.status_code == 403

    # 正确 token → 200
    token = node_comms._read_internal_token()
    assert token
    resp = client.post("/api/internal/runtime/containers", json=payload, headers={"X-Internal-Token": token})
    assert resp.status_code == 200
    assert resp.json()["updated"] == 1
