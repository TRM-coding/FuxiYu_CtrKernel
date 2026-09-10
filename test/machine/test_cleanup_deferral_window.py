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
from ...models.container_ssh_login import ContainerSSHLogin
from ...repositories import container_ssh_login_repo
from ...schedulers import container_cleanup_task
from ...services import machine_tasks as machine_tasks_mod
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
