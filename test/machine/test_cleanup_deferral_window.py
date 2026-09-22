"""机器不可用窗口 → ssh 到期清理顺延（deferral）机制测试。

语义：
- 不可用窗口 = machine_status != ONLINE 或 is_maintenance；进入置 unavailable_since，
  恢复（ONLINE 且非维护）时把整段故障时长批量累加到该机器全部 ssh deferral_seconds
- deferral 只加不清（量 = 真实不可用时长）；真登录（last_ssh_login_time 值变化）清零；
  同值心跳帧不清
- 到期判定：有效最后登录 = last_ssh + deferral（build_cleanup_info 掺入）
"""

import datetime as _real_dt
from datetime import datetime, timedelta

import pytest

from ...constant import MachineStatus
from ...extensions import session_scope
from ...models.container_ssh_login import ContainerSSHLogin
from ...models.machine import Machine
from ...repositories import (
    container_disk_freeze_state_repo,
    container_ssh_login_repo,
    deleted_container_restore_snapshot_repo,
    machine_repo,
)
from ...schedulers import container_cleanup_task, container_disk_check_task
from ...services import container_tasks
from ...services import machine_tasks as machine_tasks_mod
from ...services.container_module import node_comms
from ...services.container_module.node_comms_modules import snapshots
from ...services.container_module.utils import build_cleanup_info
from ..factories import create_container_graph

_CLOCK_STATE: dict = {"clock": None}


@pytest.fixture(autouse=True)
def _mute_machine_audit(monkeypatch):
    # These tests isolate deferral behavior, not operation-log persistence.
    for name in ("log_result", "log_success", "log_failure"):
        monkeypatch.setattr(machine_tasks_mod, name, lambda *args, **kwargs: None)


class _ClockedDatetime(_real_dt.datetime):
    """datetime 子类：utcnow 由活动时钟供给（patch machine_tasks.datetime 模块引用）。"""

    @classmethod
    def utcnow(cls):
        c = _CLOCK_STATE["clock"]
        return c.now if c is not None else super().utcnow()


class _Clock:
    def __init__(self):
        self.now = _real_dt.datetime.utcnow()

    def advance(self, *, days=0, hours=0, minutes=0, seconds=0):
        self.now += timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)


def _install_clock(monkeypatch):
    clock = _Clock()
    monkeypatch.setitem(_CLOCK_STATE, "clock", clock)
    monkeypatch.setattr(machine_tasks_mod, "datetime", _ClockedDatetime)
    return clock


def _make_ssh_record(db_session, container, last_ssh_time: str, deferral: int | None = 0):
    rec = ContainerSSHLogin(
        machine_id=container.machine_id,
        container_id=container.id,
        last_ssh_login_time=last_ssh_time,
        deferral_seconds=deferral,
    )
    db_session.add(rec)
    db_session.commit()
    return rec


class TestUnavailableWindow:
    """窗口进/出与 deferral 批量加法。"""

    def test_offline_window_adds_deferral_on_recovery(self, app, db_session, monkeypatch):
        _root, machine, container = create_container_graph()
        _make_ssh_record(db_session, container, last_ssh_time="2026-01-01T00:00:00")
        # 机器默认 ONLINE。
        clock = _install_clock(monkeypatch)

        machine_tasks_mod.Update_machine(machine.id, machine_status=MachineStatus.OFFLINE)
        db_session.expire_all()
        m = db_session.get(type(machine), machine.id)
        assert m.unavailable_since is not None

        # 宕机 3 小时后恢复
        clock.advance(hours=3)
        machine_tasks_mod.Update_machine(machine.id, machine_status=MachineStatus.ONLINE)
        db_session.expire_all()
        m = db_session.get(type(machine), machine.id)
        assert m.unavailable_since is None
        rec = container_ssh_login_repo.get_by_machine_container(
            machine.id, container.id, session=db_session
        )
        assert rec.deferral_seconds is not None
        assert abs(rec.deferral_seconds - 3 * 3600) <= 5  # delta ≈ 3h

    def test_deferral_applies_to_all_records_of_machine(self, app, db_session, monkeypatch):
        _root, machine, container_a = create_container_graph()
        _root2, _m2, container_b = create_container_graph(machine=machine)
        _make_ssh_record(db_session, container_a, "2026-01-01T00:00:00")
        _make_ssh_record(db_session, container_b, "2026-01-02T00:00:00")
        clock = _install_clock(monkeypatch)

        machine_tasks_mod.Update_machine(machine.id, machine_status=MachineStatus.OFFLINE)
        clock.advance(minutes=30)
        machine_tasks_mod.Update_machine(machine.id, machine_status=MachineStatus.ONLINE)

        for c in (container_a, container_b):
            rec = container_ssh_login_repo.get_by_machine_container(
                machine.id, c.id, session=db_session
            )
            assert abs((rec.deferral_seconds or 0) - 1800) <= 5

    def test_maintenance_window_opens_and_closes(self, app, db_session, monkeypatch):
        _root, machine, container = create_container_graph()
        _make_ssh_record(db_session, container, "2026-01-01T00:00:00")
        clock = _install_clock(monkeypatch)

        # 维护是独立开关，machine_status 保持 ONLINE
        assert machine_tasks_mod.Set_maintenance(machine.id, True) is True
        db_session.expire_all()
        m = db_session.get(type(machine), machine.id)
        assert m.is_maintenance is True
        assert m.unavailable_since is not None

        clock.advance(hours=2)
        assert machine_tasks_mod.Set_maintenance(machine.id, False) is True
        db_session.expire_all()
        m = db_session.get(type(machine), machine.id)
        assert m.unavailable_since is None
        rec = container_ssh_login_repo.get_by_machine_container(
            machine.id, container.id, session=db_session
        )
        assert abs((rec.deferral_seconds or 0) - 2 * 3600) <= 5

    def test_interleaved_offline_maintenance_counts_full_window_once(self, app, db_session, monkeypatch):
        """离线中开维护、先关维护仍离线、最后恢复 → 累计整段时长，不重复计。"""
        _root, machine, container = create_container_graph()
        _make_ssh_record(db_session, container, "2026-01-01T00:00:00")
        clock = _install_clock(monkeypatch)

        machine_tasks_mod.Update_machine(machine.id, machine_status=MachineStatus.OFFLINE)  # t0
        clock.advance(hours=1)
        machine_tasks_mod.Set_maintenance(machine.id, True)  # 离线中开维护：since 保持 t0
        db_session.expire_all()
        m = db_session.get(type(machine), machine.id)
        since_after_maintenance = m.unavailable_since

        clock.advance(hours=1)
        machine_tasks_mod.Set_maintenance(machine.id, False)  # 关维护但仍离线：窗口继续
        db_session.expire_all()
        m = db_session.get(type(machine), machine.id)
        assert m.unavailable_since == since_after_maintenance

        clock.advance(hours=1)
        machine_tasks_mod.Update_machine(machine.id, machine_status=MachineStatus.ONLINE)  # t0+3h
        db_session.expire_all()
        rec = container_ssh_login_repo.get_by_machine_container(
            machine.id, container.id, session=db_session
        )
        assert abs((rec.deferral_seconds or 0) - 3 * 3600) <= 5
        assert db_session.get(type(machine), machine.id).unavailable_since is None

    def test_non_state_updates_do_not_open_window(self, app, db_session, monkeypatch):
        """非状态类字段更新（如扩容）不触发窗口：已在线的机器不会被误标进窗。"""
        _root, machine, container = create_container_graph()
        _install_clock(monkeypatch)

        machine_tasks_mod.Update_machine(machine.id, max_disk_size_gb=2048)
        db_session.expire_all()
        m = db_session.get(type(machine), machine.id)
        assert m.unavailable_since is None
        assert m.max_disk_size_gb == 2048


class TestDeferralLifecycle:
    """upsert 值变化清零 / 同值心跳帧保留 / add_deferral 幂等语义。"""

    def _ssh_row(self, db_session, container, last="2026-01-01T00:00:00", deferral=3600):
        rec = ContainerSSHLogin(
            machine_id=container.machine_id,
            container_id=container.id,
            last_ssh_login_time=last,
            deferral_seconds=deferral,
        )
        db_session.add(rec)
        db_session.commit()
        return rec

    def test_value_change_clears_deferral(self, app, db_session, container=None):
        _root, machine, container = create_container_graph()
        self._ssh_row(db_session, container)

        # 顺延 1h 后，用户真登录（新时间帧）→ 清零
        container_ssh_login_repo.upsert_last_ssh_login_time(
            machine.id, container.id, "2026-02-01T08:00:00", session=db_session
        )
        db_session.commit()
        rec = container_ssh_login_repo.get_by_machine_container(
            machine.id, container.id, session=db_session
        )
        assert rec.deferral_seconds == 0

    def test_same_value_frame_keeps_deferral(self, app, db_session):
        _root, machine, container = create_container_graph()
        self._ssh_row(db_session, container)

        # Node 心跳同值帧（无新登录）→ 顺延保留
        container_ssh_login_repo.upsert_last_ssh_login_time(
            machine.id, container.id, "2026-01-01T00:00:00", session=db_session
        )
        db_session.commit()
        rec = container_ssh_login_repo.get_by_machine_container(
            machine.id, container.id, session=db_session
        )
        assert rec.deferral_seconds == 3600

    def test_add_deferral_accumulates(self, app, db_session):
        _root, machine, container = create_container_graph()
        self._ssh_row(db_session, container)
        container_ssh_login_repo.add_deferral_seconds(machine.id, 1800, session=db_session)
        container_ssh_login_repo.add_deferral_seconds(machine.id, 1800, session=db_session)
        db_session.commit()
        rec = container_ssh_login_repo.get_by_machine_container(
            machine.id, container.id, session=db_session
        )
        assert rec.deferral_seconds == 3600 + 3600


class TestCleanupInfoDeferral:
    """判定掺入：build_cleanup_info 的 cleanup_at / 状态随 deferral 顺延。"""

    def test_deferral_shifts_cleanup_and_rescues_due(self, app, db_session):
        # 10 天前登录，7 天到期 → 本应 due
        last = (datetime.utcnow() - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S")
        due = build_cleanup_info(last, 7, deferral_seconds=0)
        assert due["cleanup_status"] == "due"

        # 顺延 10 天（机器宕过 10 天）→ 有效最后登录 ≈ now → countdown，且到期时刻 +10d
        deferred = build_cleanup_info(last, 7, deferral_seconds=10 * 86400)
        assert deferred["cleanup_status"] == "countdown"
        assert deferred["seconds_until_cleanup"] > 7 * 86400 - 10
        assert deferred["seconds_until_cleanup"] < 7 * 86400 + 10

    def test_open_window_freezes_the_countdown(self):
        """窗口**开着**时倒计时应当停住。

        顺延只在窗口关闭时一次性结算，所以窗口期若只看 deferral_seconds，倒计时会照走、
        甚至走到 due——而它其实会在窗口关闭时被整体拨回。把窗口已持续的时长折进来，
        「不可用期间时钟不走」才在读的这一刻也成立，而不只是终态成立。
        """
        last = (datetime.utcnow() - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S")

        assert build_cleanup_info(last, 7)["cleanup_status"] == "due"

        opened = datetime.utcnow() - timedelta(days=10)
        frozen = build_cleanup_info(last, 7, unavailable_since=opened)

        assert frozen["cleanup_status"] == "countdown"
        assert 7 * 86400 - 60 < frozen["seconds_until_cleanup"] < 7 * 86400 + 60

    def test_open_window_adds_on_top_of_settled_deferral(self):
        """两个来源叠加：已结算的 deferral_seconds + 正在进行的窗口，不是二选一。"""
        last = (datetime.utcnow() - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S")
        opened = datetime.utcnow() - timedelta(days=5)

        settled_only = build_cleanup_info(last, 7, deferral_seconds=5 * 86400)
        with_window = build_cleanup_info(
            last, 7, deferral_seconds=5 * 86400, unavailable_since=opened,
        )

        assert with_window["seconds_until_cleanup"] - settled_only["seconds_until_cleanup"] == pytest.approx(
            5 * 86400, abs=60,
        )

    def test_no_open_window_is_byte_for_byte_the_old_behaviour(self):
        """窗口为 None（从未不可用，或已结算完）→ 与旧口径完全一致。"""
        last = (datetime.utcnow() - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S")

        assert build_cleanup_info(last, 7) == build_cleanup_info(last, 7, unavailable_since=None)

    def test_window_start_in_the_future_is_clamped(self):
        """时钟回拨让起点落到未来 → 夹到 0，不倒扣用户时间。"""
        last = (datetime.utcnow() - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S")
        future = datetime.utcnow() + timedelta(days=1)

        assert build_cleanup_info(last, 7, unavailable_since=future) == build_cleanup_info(last, 7)

    def test_detail_read_path_picks_up_the_open_window(self, app, db_session):
        """读侧共用口径：详情/接口走的 get_container_cleanup_state 也认窗口。"""
        _root, machine, container = create_container_graph()
        last = (datetime.utcnow() - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S")
        _make_ssh_record(db_session, container, last_ssh_time=last)
        # 窗口字段不在 update_machine 的白名单里（它不是操作员可编辑字段，由
        # refresh_unavailable_window 直接写 ORM 对象），测试同样直接赋值。
        with session_scope() as session:
            row = machine_repo.get_by_id(machine.id, session=session)
            row.unavailable_since = datetime.utcnow() - timedelta(days=10)

        state = container_tasks.get_container_cleanup_state(container)

        assert state["cleanup_status"] == "countdown"
        assert 7 * 86400 - 60 < state["seconds_until_cleanup"] < 7 * 86400 + 60

    def test_cleanup_scan_skips_deferred_due_container(self, app, db_session, monkeypatch):
        """调度扫描：ssh 到期但 deferral 覆盖（机器不可用补偿）→ 不触发移除。"""
        _root, machine, container = create_container_graph()
        removed = []
        monkeypatch.setattr(container_cleanup_task.container_tasks, "remove_container",
                            lambda *a, **k: removed.append(k.get("container_id") or (a[0] if a else None)))
        monkeypatch.setattr(container_cleanup_task.settings_tasks,
                            "get_container_cleanup_after_days", lambda: 7)
        monkeypatch.setattr(
            "FuxiYu_CtrKernel.utils.mail._send_smtp", lambda **kw: {"ok": False})

        last = (datetime.utcnow() - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S")
        _make_ssh_record(db_session, container, last_ssh_time=last, deferral=10 * 86400)

        container_cleanup_task.cleanup_expired_containers_once(7)
        assert removed == []  # deferral 使 due → countdown

        # 同一容器 deferral 归零（用户没登录也没补偿）→ due → 移除
        rec = container_ssh_login_repo.get_by_machine_container(
            machine.id, container.id, session=db_session)
        rec.deferral_seconds = 0
        db_session.commit()
        container_cleanup_task.cleanup_expired_containers_once(7)
        assert removed == [container.id]


class TestLastSeenHeartbeat:
    """采集心跳：Ctrl 最后一次成功取得该机器数据的时刻。"""

    @pytest.fixture(autouse=True)
    def _reset_throttle(self, monkeypatch):
        # 节流表是模块级状态，跨用例会串味
        monkeypatch.setattr(snapshots, "_last_seen_written", {})

    def test_snapshot_batch_updates_last_seen(self, app, db_session):
        _root, machine, container = create_container_graph()
        with session_scope() as session:
            machine_repo.update_machine(machine.id, node_uid="uid-touch", session=session)

        node_comms.apply_snapshot_batch({
            "type": "snapshot_batch",
            "node_uid": "uid-touch",
            "payload": [{"type": "snapshot", "topic": "container_status",
                         "payload": {container.name: {"status": "online"}}}],
        })

        db_session.expire_all()
        assert db_session.get(Machine, machine.id).last_seen_at is not None

    def test_collect_error_batch_still_counts_as_heard(self, app, db_session):
        """采集异常（对端可达但 docker 卡死）也算听到——语义是链路层的事实。"""
        _root, machine, _container = create_container_graph()
        with session_scope() as session:
            machine_repo.update_machine(machine.id, node_uid="uid-hung", session=session)

        node_comms.apply_snapshot_batch({
            "type": "snapshot_batch",
            "node_uid": "uid-hung",
            "payload": [{"type": "snapshot", "topic": "container_status",
                         "payload": {"collect_error": "docker hung"}}],
        })

        db_session.expire_all()
        assert db_session.get(Machine, machine.id).last_seen_at is not None

    def test_unresolvable_uid_does_not_touch(self, app, db_session):
        """取不到数据就不该记「听到过」——否则会给一台没在场的机器开窗口。"""
        _root, machine, _container = create_container_graph()

        node_comms.apply_snapshot_batch({
            "type": "snapshot_batch",
            "node_uid": "uid-unknown",
            "payload": [{"type": "snapshot", "topic": "container_status", "payload": {}}],
        })

        db_session.expire_all()
        assert db_session.get(Machine, machine.id).last_seen_at is None

    def test_throttle_writes_once_within_window(self, app, db_session, monkeypatch):
        _root, machine, _container = create_container_graph()
        writes = []
        real = machine_repo.touch_last_seen

        def _counting(machine_id, when, *, session):
            writes.append(when)
            return real(machine_id, when, session=session)

        monkeypatch.setattr(snapshots.machine_repo, "touch_last_seen", _counting)

        snapshots._touch_machine_last_seen(machine.id)
        snapshots._touch_machine_last_seen(machine.id)
        snapshots._touch_machine_last_seen(machine.id)

        assert len(writes) == 1

    def test_touch_missing_machine_is_false(self, app, db_session):
        with session_scope() as session:
            assert machine_repo.touch_last_seen(999999, _real_dt.datetime.utcnow(), session=session) is False


class TestSeedUnavailableWindows:
    """启动扫描：用采集心跳兜住窗口起点（Ctrl 停机期间的观测盲区）。"""

    def _machine(self, db_session, **fields):
        """直接落库：update_machine 有白名单，不接受窗口类字段（与业务一致）。"""
        _root, machine, _container = create_container_graph()
        self._machine_fields(db_session, machine.id, **fields)
        return machine

    def _machine_fields(self, db_session, machine_id, **fields):
        with session_scope() as session:
            row = machine_repo.get_by_id(machine_id, session=session)
            for key, value in fields.items():
                setattr(row, key, value)
            session.flush()

    def test_seeds_window_from_last_seen(self, app, db_session):
        seen = _real_dt.datetime(2026, 9, 1, 12, 0, 0)
        machine = self._machine(db_session, last_seen_at=seen)

        result = machine_tasks_mod.seed_unavailable_windows_from_last_seen()

        db_session.expire_all()
        assert result["seeded"] == [machine.id]
        assert db_session.get(Machine, machine.id).unavailable_since == seen

    def test_skips_machine_without_last_seen(self, app, db_session):
        """刚建档的机器两列皆空，不能凭空调制窗口。"""
        machine = self._machine(db_session)

        result = machine_tasks_mod.seed_unavailable_windows_from_last_seen()

        db_session.expire_all()
        assert result["seeded"] == []
        assert db_session.get(Machine, machine.id).unavailable_since is None

    def test_does_not_touch_open_window(self, app, db_session):
        """已有窗口的机器起点更早，改写只会让顺延变少。"""
        opened = _real_dt.datetime(2026, 9, 1, 0, 0, 0)
        seen = _real_dt.datetime(2026, 9, 2, 0, 0, 0)
        machine = self._machine(db_session, unavailable_since=opened, last_seen_at=seen)

        result = machine_tasks_mod.seed_unavailable_windows_from_last_seen()

        db_session.expire_all()
        assert result["seeded"] == []
        assert db_session.get(Machine, machine.id).unavailable_since == opened

    def test_is_idempotent(self, app, db_session):
        seen = _real_dt.datetime(2026, 9, 1, 12, 0, 0)
        machine = self._machine(db_session, last_seen_at=seen)

        machine_tasks_mod.seed_unavailable_windows_from_last_seen()
        second = machine_tasks_mod.seed_unavailable_windows_from_last_seen()

        db_session.expire_all()
        assert second["seeded"] == []
        assert db_session.get(Machine, machine.id).unavailable_since == seen

    def test_seeded_window_defers_from_last_seen_not_from_reobserve(self, app, db_session, monkeypatch):
        """端到端：顺延从 last_seen_at 起算，而不是从「Ctrl 恢复观测」那一刻。

        这就是本能力要修的那条路径——Ctrl 停机期间进窗，若不兜底，起点会被记成
        重启时刻，delta 少算（清理提前触发，不可逆）。
        """
        _root, machine, container = create_container_graph()
        _make_ssh_record(db_session, container, last_ssh_time="2026-01-01T00:00:00")
        clock = _install_clock(monkeypatch)
        # Ctrl 停机前的最后一次接触，紧接着就停机
        seen = clock.now

        # 停机三天：期间机器进入不可用（无人观测），窗口起点本会丢失
        self._machine_fields(db_session, machine.id, last_seen_at=seen)
        clock.advance(days=3)

        # Ctrl 重启：先播种（未被观测的进窗被兜住），链路随后连上并置 ONLINE
        machine_tasks_mod.seed_unavailable_windows_from_last_seen()
        machine_tasks_mod.Update_machine(machine.id, machine_status=MachineStatus.ONLINE)

        db_session.expire_all()
        rec = container_ssh_login_repo.get_by_machine_container(machine.id, container.id, session=db_session)
        assert abs((rec.deferral_seconds or 0) - 3 * 24 * 3600) <= 5

    def _machine_fields(self, db_session, machine_id, **fields):
        with session_scope() as session:
            row = machine_repo.get_by_id(machine_id, session=session)
            for key, value in fields.items():
                setattr(row, key, value)
            session.flush()


class _FreezeState:
    """_days_frozen 的入参替身：只需要两个字段，不必建整行。"""

    def __init__(self, *, first_frozen_at, deferral_seconds):
        self.first_frozen_at = first_frozen_at
        self.deferral_seconds = deferral_seconds


class TestDeferralAppliesToOtherDeadlines:
    """顺延是「业务正常时间」这把尺子，三条期限共用——不只 ssh 到期清理。

    差异只在实时性：ssh 倒计时要在窗口期就读（故读侧还要折算正在进行的窗口），
    冻结升级与挂载保留期只在窗口关闭后被动作消费，靠窗口关闭时的累加器即可。
    """

    def test_window_close_credits_freeze_state(self, app, db_session, monkeypatch):
        _root, machine, container = create_container_graph()
        clock = _install_clock(monkeypatch)
        with session_scope() as session:
            container_disk_freeze_state_repo.upsert_first_frozen(container.id, session=session)

        machine_tasks_mod.Update_machine(machine.id, machine_status=MachineStatus.OFFLINE)
        clock.advance(days=10)
        machine_tasks_mod.Update_machine(machine.id, machine_status=MachineStatus.ONLINE)

        db_session.expire_all()
        state = container_disk_freeze_state_repo.get(container.id, session=db_session)
        assert abs((state.deferral_seconds or 0) - 10 * 86400) <= 60

    def test_window_close_credits_pending_deleted_snapshot(self, app, db_session, monkeypatch):
        _root, machine, container = create_container_graph()
        clock = _install_clock(monkeypatch)
        row = deleted_container_restore_snapshot_repo.insert(
            {"container_id": container.id, "container_name": container.name, "machine_id": machine.id},
            session=db_session,
        )
        db_session.commit()

        machine_tasks_mod.Update_machine(machine.id, machine_status=MachineStatus.OFFLINE)
        clock.advance(days=10)
        machine_tasks_mod.Update_machine(machine.id, machine_status=MachineStatus.ONLINE)

        db_session.expire_all()
        refreshed = deleted_container_restore_snapshot_repo.get_by_id(row.id, session=db_session)
        assert abs((refreshed.deferral_seconds or 0) - 10 * 86400) <= 60

    def test_already_cleaned_snapshot_is_not_credited(self, app, db_session, monkeypatch):
        """已清理的记录不再被读，不再累加（避免无意义写入）。"""
        _root, machine, container = create_container_graph()
        clock = _install_clock(monkeypatch)
        row = deleted_container_restore_snapshot_repo.insert(
            {"container_id": container.id, "container_name": container.name, "machine_id": machine.id},
            session=db_session,
        )
        deleted_container_restore_snapshot_repo.mark_mount_cleaned(row.id, session=db_session)
        db_session.commit()

        machine_tasks_mod.Update_machine(machine.id, machine_status=MachineStatus.OFFLINE)
        clock.advance(days=10)
        machine_tasks_mod.Update_machine(machine.id, machine_status=MachineStatus.ONLINE)

        db_session.expire_all()
        refreshed = deleted_container_restore_snapshot_repo.get_by_id(row.id, session=db_session)
        assert (refreshed.deferral_seconds or 0) == 0

    def test_frozen_days_exclude_unavailable_time(self):
        """有效冻结天数 = 自然日 − 顺延（纯算术，不需要假时钟）。"""
        now = datetime.utcnow()
        assert container_disk_check_task._days_frozen(
            _FreezeState(first_frozen_at=now - timedelta(days=12), deferral_seconds=10 * 86400),
        ) == 2

    def test_frozen_days_never_negative_when_over_credited(self):
        """顺延超过自然日（理论上不该发生）时夹到 0，不倒扣。"""
        now = datetime.utcnow()
        assert container_disk_check_task._days_frozen(
            _FreezeState(first_frozen_at=now - timedelta(days=1), deferral_seconds=30 * 86400),
        ) == 0

    def test_frozen_days_missing_deferral_reads_as_zero(self):
        """存量行 deferral 为 NULL → 按 0 处理，行为与此前一致。"""
        now = datetime.utcnow()
        assert container_disk_check_task._days_frozen(
            _FreezeState(first_frozen_at=now - timedelta(days=5), deferral_seconds=None),
        ) == 5

    def test_grace_deadline_is_shifted_by_deferral(self):
        """**宽限到期时刻也要顺延**——它是第四条共用这把尺子的期限。

        宽限存的是**绝对时刻**，不加顺延的话宕机期间照走；恢复后第一次磁盘检测就看到它
        已过期，直接进动作分支，而用户在被宽恕的那段时间里根本登不上去处理磁盘。
        """
        from ...services.container_module.utils import effective_grace_until

        frozen_at = datetime.utcnow() - timedelta(days=5)
        state = _FreezeState(first_frozen_at=frozen_at, deferral_seconds=5 * 86400)
        state.grace_until = frozen_at + timedelta(days=3)      # 宽限 3 天

        effective = effective_grace_until(state)
        assert effective == state.grace_until + timedelta(days=5)
        # 场景：宕机 5 天，宽限 3 天 → 恢复那一刻**仍在宽限内**（旧的墙钟比法会判已过期）
        assert datetime.utcnow() < effective

    def test_grace_deadline_without_deferral_is_unchanged(self):
        from ...services.container_module.utils import effective_grace_until

        now = datetime.utcnow()
        for deferral in (0, None):
            state = _FreezeState(first_frozen_at=now, deferral_seconds=deferral)
            state.grace_until = now + timedelta(days=3)
            assert effective_grace_until(state) == state.grace_until

    def test_grace_deadline_absent_reads_as_none(self):
        from ...services.container_module.utils import effective_grace_until

        now = datetime.utcnow()
        state = _FreezeState(first_frozen_at=now, deferral_seconds=86400)
        state.grace_until = None
        assert effective_grace_until(state) is None

    def test_mount_cleanup_skips_deferred_snapshot(self, app, db_session):
        """保留期按业务正常时间计：自然日 20 天、其中顺延 15 天 → 未到期。"""
        _root, machine, container = create_container_graph()
        old = datetime.utcnow() - timedelta(days=20)
        row = deleted_container_restore_snapshot_repo.insert(
            {"container_id": container.id, "container_name": container.name, "machine_id": machine.id},
            removed_at=old, session=db_session,
        )
        row.deferral_seconds = 15 * 86400
        db_session.commit()

        cutoff = datetime.utcnow() - timedelta(days=14)
        pending = deleted_container_restore_snapshot_repo.list_pending_mount_cleanup(
            cutoff, session=db_session,
        )

        assert row.id not in {r.id for r in pending}

    def test_mount_cleanup_picks_undeferred_snapshot(self, app, db_session):
        """对照：同样的年龄但没有顺延 → 照常到期（证明上面的过滤不是恒假）。"""
        _root, machine, container = create_container_graph()
        old = datetime.utcnow() - timedelta(days=20)
        row = deleted_container_restore_snapshot_repo.insert(
            {"container_id": container.id, "container_name": container.name, "machine_id": machine.id},
            removed_at=old, session=db_session,
        )
        db_session.commit()

        cutoff = datetime.utcnow() - timedelta(days=14)
        pending = deleted_container_restore_snapshot_repo.list_pending_mount_cleanup(
            cutoff, session=db_session,
        )

        assert row.id in {r.id for r in pending}

    def test_deferred_row_does_not_starve_younger_ones(self, app, db_session):
        """顺延大的行 removed_at 最老、排最前。

        若在 SQL 之后用 Python 筛，它会占满 limit 窗口，让真正到期的年轻行永远进不来
        —— 所以过滤必须落在 SQL 里（本用例用 limit=1 把它钉住）。
        """
        _root, machine, container = create_container_graph()
        now = datetime.utcnow()
        deferred = deleted_container_restore_snapshot_repo.insert(
            {"container_id": container.id, "container_name": "deferred", "machine_id": machine.id},
            removed_at=now - timedelta(days=30), session=db_session,
        )
        deferred.deferral_seconds = 30 * 86400
        eligible = deleted_container_restore_snapshot_repo.insert(
            {"container_id": container.id, "container_name": "eligible", "machine_id": machine.id},
            removed_at=now - timedelta(days=15), session=db_session,
        )
        db_session.commit()

        cutoff = now - timedelta(days=14)
        pending = deleted_container_restore_snapshot_repo.list_pending_mount_cleanup(
            cutoff, limit=1, session=db_session,
        )

        assert [r.id for r in pending] == [eligible.id]
