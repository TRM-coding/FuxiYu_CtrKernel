"""冻结天数的查询展示与调度升级判定必须是同一口径。

本文件锁定三件事：
1. 公共纯函数 `effective_days_frozen` 的算术（整日向下取整、负值夹 0、NULL 当 0）；
2. 查询出口（详情 / 列表）与调度 `_days_frozen` 对同一条记录给出同一个数；
3. 真正参与调度的因素（已结算顺延、维护/离线窗口门禁）在两侧一致，不做"只改字段名"的改造。
"""

from datetime import datetime, timedelta

from ...constant import MachineStatus
from ...repositories import (
    container_disk_freeze_state_repo,
    long_term_container_repo,
)
from ...schedulers import container_disk_check_task
from ...services import container_tasks
from ...services.container_module import queries
from ...services.container_module.utils import effective_days_frozen
from ..factories import create_container_graph


def _usage_exceeding_hard_limit():
    """超过 hard limit 的磁盘用量（测试机器默认 1024GB 上限）。"""
    gb = 1024 ** 3
    return {
        "container": {
            "overlay_rw_bytes": int(800 * gb),
            "bind_mount_bytes": int(300 * gb),
            "total_bytes": int(1100 * gb),
        }
    }


def _freeze(db_session, container, *, days_ago=0, seconds_ago=0, deferral=0):
    """造一条冻结记录并指定锚点/顺延，返回刷新后的行。"""
    state = container_disk_freeze_state_repo.upsert_first_frozen(container.id, session=db_session)
    state.first_frozen_at = datetime.utcnow() - timedelta(days=days_ago, seconds=seconds_ago)
    state.deferral_seconds = deferral
    db_session.commit()
    db_session.expire_all()
    return container_disk_freeze_state_repo.get(container.id, session=db_session)


def _enable_disk_response(monkeypatch):
    monkeypatch.setattr(container_disk_check_task.settings_tasks, "get_container_disk_check_enabled", lambda: True)
    monkeypatch.setattr(container_disk_check_task.settings_tasks, "get_container_disk_response_enabled", lambda: True)
    monkeypatch.setattr(container_disk_check_task.settings_tasks, "get_container_disk_soft_limit_percent", lambda: 80)
    monkeypatch.setattr(container_disk_check_task.settings_tasks, "get_container_disk_hard_limit_percent", lambda: 100)
    monkeypatch.setattr(container_disk_check_task.settings_tasks, "get_container_disk_freeze_reset_percent", lambda: 95)
    monkeypatch.setattr(container_disk_check_task.settings_tasks, "get_container_disk_freeze_escalation_days", lambda: 7)
    monkeypatch.setattr(container_disk_check_task.settings_tasks, "get_container_disk_freeze_grace_days", lambda: 3)
    monkeypatch.setattr(container_disk_check_task, "_DISK_CHECK_CACHE", {})


class TestEffectiveDaysFrozenPure:
    """公共纯计算的算术（显式传 now，不依赖墙钟）。"""

    def test_deferral_is_subtracted_in_whole_days(self):
        now = datetime(2026, 10, 1, 12, 0, 0)
        assert effective_days_frozen(now - timedelta(days=20), 10 * 86400, now=now) == 10

    def test_partial_day_is_floored(self):
        now = datetime(2026, 10, 1, 12, 0, 0)
        assert effective_days_frozen(now - timedelta(days=5, hours=23), 0, now=now) == 5
        # 半日顺延：5.5 天 − 1 天 = 4.5 天 → 4
        assert effective_days_frozen(now - timedelta(days=5, hours=12), 86400, now=now) == 4

    def test_over_credited_deferral_clamps_to_zero(self):
        now = datetime(2026, 10, 1, 12, 0, 0)
        assert effective_days_frozen(now - timedelta(days=1), 30 * 86400, now=now) == 0

    def test_null_deferral_reads_as_zero_and_missing_anchor_as_zero(self):
        now = datetime(2026, 10, 1, 12, 0, 0)
        assert effective_days_frozen(now - timedelta(days=5), None, now=now) == 5
        assert effective_days_frozen(None, 10 * 86400, now=now) == 0


class TestQueryAndSchedulerShareOneFormula:
    """同一条冻结记录：查询出口与调度判定给出同一个数。"""

    def test_twenty_days_frozen_with_ten_days_deferral_reads_ten_in_both(self, app, db_session):
        _root, _machine, container = create_container_graph()
        state = _freeze(db_session, container, days_ago=20, deferral=10 * 86400)

        query = queries._get_container_freeze_state(container.id)

        assert query["days_frozen"] == 10
        assert container_disk_check_task._days_frozen(state) == 10

    def test_detail_and_list_display_use_the_effective_value(self, app, db_session):
        root, _machine, container = create_container_graph()
        _freeze(db_session, container, days_ago=20, deferral=10 * 86400)

        detail = container_tasks.get_container_detail_information(container.id)
        assert detail["freeze_state"]["days_frozen"] == 10

        page = container_tasks.list_all_container_bref_information(
            machine_id=None, request_user_id=root.id, page_number=0, page_size=10,
            viewer_user_id=root.id,
        )
        item = next(c for c in page["containers"] if c.container_id == container.id)
        assert item.freeze_days_frozen == 10

    def test_unfrozen_container_has_no_freeze_state_and_no_days(self, app, db_session):
        root, _machine, container = create_container_graph()

        assert queries._get_container_freeze_state(container.id) is None

        detail = container_tasks.get_container_detail_information(container.id)
        assert detail["freeze_state"] is None

        page = container_tasks.list_all_container_bref_information(
            machine_id=None, request_user_id=root.id, page_number=0, page_size=10,
            viewer_user_id=root.id,
        )
        item = next(c for c in page["containers"] if c.container_id == container.id)
        assert item.freeze_days_frozen is None

    def test_partial_and_negative_agree_between_query_and_scheduler(self, app, db_session):
        _root, _machine, container = create_container_graph()
        partial = _freeze(db_session, container, days_ago=5, seconds_ago=12 * 3600, deferral=86400)
        assert queries._get_container_freeze_state(container.id)["days_frozen"] == 4
        assert container_disk_check_task._days_frozen(partial) == 4

        over = _freeze(db_session, container, days_ago=1, deferral=30 * 86400)
        assert queries._get_container_freeze_state(container.id)["days_frozen"] == 0
        assert container_disk_check_task._days_frozen(over) == 0

    def test_null_deferral_agrees_between_query_and_scheduler(self, app, db_session):
        _root, _machine, container = create_container_graph()
        state = _freeze(db_session, container, days_ago=5, deferral=None)

        assert queries._get_container_freeze_state(container.id)["days_frozen"] == 5
        assert container_disk_check_task._days_frozen(state) == 5


class TestMaintenanceWindowIsConsistent:
    """维护/离线窗口是**真正参与调度**的因素，两侧必须一致。"""

    def test_open_window_defers_action_and_both_sides_read_the_same_value(
        self, app, db_session, monkeypatch,
    ):
        """窗口开着：调度整体不评估、动作不发生；两侧仍按同一口径读（只扣已结算顺延）。

        顺延只在窗口关闭时一次性结算，所以窗口期读数暂时偏大是既有边界——此时调度
        压根不消费它（`machine_in_scope` 为假），不存在"用偏大的数去升级"。
        """
        _root, machine, container = create_container_graph()
        long_term_container_repo.add(container.id, session=db_session)
        db_session.commit()
        _freeze(db_session, container, days_ago=20, deferral=0)
        machine.machine_status = MachineStatus.OFFLINE
        machine.unavailable_since = datetime.utcnow() - timedelta(days=3)
        db_session.commit()
        _enable_disk_response(monkeypatch)
        calls = []
        monkeypatch.setattr(container_disk_check_task, "_handle_hard_limit", lambda c, u, a: calls.append("pause"))
        monkeypatch.setattr(container_disk_check_task, "_handle_freeze_escalation", lambda *a, **k: calls.append("escalate"))

        container_disk_check_task._evaluate_limits(container, _usage_exceeding_hard_limit())

        assert calls == []
        db_session.expire_all()
        state = container_disk_freeze_state_repo.get(container.id, session=db_session)
        # 窗口未关闭，顺延尚未结算——两侧读的是同一个（未顺延的）数，且谁都没动作
        assert queries._get_container_freeze_state(container.id)["days_frozen"] == 20
        assert container_disk_check_task._days_frozen(state) == 20

    def test_only_settled_window_credit_changes_both_sides(self, app, db_session, monkeypatch):
        """窗口关闭把整段时长结算进 deferral 后，两侧一起变小，并据此升级。"""
        _root, machine, container = create_container_graph()
        long_term_container_repo.add(container.id, session=db_session)
        db_session.commit()
        _freeze(db_session, container, days_ago=20, deferral=0)
        machine.machine_status = MachineStatus.OFFLINE
        machine.unavailable_since = datetime.utcnow() - timedelta(days=3)
        db_session.commit()

        # 窗口关闭：refresh_unavailable_window 的动作就是清标志 + 给该机器全部冻结态累加顺延
        machine.machine_status = MachineStatus.ONLINE
        machine.unavailable_since = None
        container_disk_freeze_state_repo.add_deferral_seconds(machine.id, 3 * 86400, session=db_session)
        db_session.commit()
        db_session.expire_all()
        state = container_disk_freeze_state_repo.get(container.id, session=db_session)

        assert queries._get_container_freeze_state(container.id)["days_frozen"] == 17
        assert container_disk_check_task._days_frozen(state) == 17

        # 现在机器可评估：17 ≥ 7 → 走升级分支（证明展示的数就是动作依据的数）
        _enable_disk_response(monkeypatch)
        escalated = []
        monkeypatch.setattr(
            container_disk_check_task, "_handle_freeze_escalation",
            lambda c, u, a, days_frozen=0: escalated.append(days_frozen),
        )
        container_disk_check_task._evaluate_limits(container, _usage_exceeding_hard_limit())
        assert escalated == [17]
