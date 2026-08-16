"""测试 container_disk_check_task — 磁盘容量检测、冻结升级、宽限期。

核心验证点：
- 持久容器（LongTermContainer）接受容量响应（pause / 邮件）
- 非持久容器只做检测（写 DB + 日志），永不响应
- 冻结状态记录（first_frozen_at）与升级（7 天后 remove）
- 宽限期（解冻后 3 天内不 pause）
- 容量回落 < 95% 重置冻结状态
"""

from datetime import datetime, timedelta

from ...extensions import db
from ...models.containers import Container
from ...models.container_disk_freeze_state import ContainerDiskFreezeState
from ...repositories import (
    container_disk_freeze_state_repo,
    long_term_container_repo,
)
from ...schemas import container_disk_check_task
from ..factories import create_container_graph


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _usage_exceeding_soft_limit():
    """构造超过 soft limit（80%）但未超 hard limit（100%）的磁盘用量。

    测试机器的 disk_size_gb 默认 1024 GB → limit = 1024 * 1024^3 bytes。
    900 GB 对应 900/1024 ≈ 87.9%，触发 soft limit。
    """
    gb = 1024 ** 3
    return {
        "container": {
            "overlay_rw_bytes": int(600 * gb),
            "bind_mount_bytes": int(300 * gb),
            "total_bytes": int(900 * gb),
        }
    }


def _usage_exceeding_hard_limit():
    """构造超过 hard limit（100%）的磁盘用量。

    1100 GB > 1024 GB，触发 hard limit。
    """
    gb = 1024 ** 3
    return {
        "container": {
            "overlay_rw_bytes": int(800 * gb),
            "bind_mount_bytes": int(300 * gb),
            "total_bytes": int(1100 * gb),
        }
    }


def _usage_below_soft_limit():
    """构造低于 soft limit 的正常磁盘用量。"""
    gb = 1024 ** 3
    return {
        "container": {
            "overlay_rw_bytes": int(300 * gb),
            "bind_mount_bytes": int(200 * gb),
            "total_bytes": int(500 * gb),
        }
    }


# ---------------------------------------------------------------------------
# _evaluate_limits — 持久容器响应测试
# ---------------------------------------------------------------------------

class TestEvaluateLimitsLongTerm:
    """持久容器（LongTermContainer）：应接受容量响应。"""

    def test_soft_limit_triggers_handler(self, app, db_session, monkeypatch):
        """持久容器超过 soft limit → 触发 _handle_soft_limit。"""
        _root, machine, container = create_container_graph()
        long_term_container_repo.add(container.id)

        soft_calls = []
        hard_calls = []
        monkeypatch.setattr(
            container_disk_check_task, "_handle_soft_limit",
            lambda c, u, a: soft_calls.append((c.id, u["container"]["total_bytes"]))
        )
        monkeypatch.setattr(
            container_disk_check_task, "_handle_hard_limit",
            lambda c, u, a: hard_calls.append(c.id)
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", True)

        usage = _usage_exceeding_soft_limit()
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)

        assert len(soft_calls) == 1
        assert soft_calls[0][0] == container.id
        assert len(hard_calls) == 0

    def test_hard_limit_triggers_handler(self, app, db_session, monkeypatch):
        """持久容器超过 hard limit → 触发 _handle_hard_limit。"""
        _root, machine, container = create_container_graph()
        long_term_container_repo.add(container.id)

        soft_calls = []
        hard_calls = []
        monkeypatch.setattr(
            container_disk_check_task, "_handle_soft_limit",
            lambda c, u, a: soft_calls.append(c.id)
        )
        monkeypatch.setattr(
            container_disk_check_task, "_handle_hard_limit",
            lambda c, u, a: hard_calls.append((c.id, u["container"]["total_bytes"]))
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", True)

        usage = _usage_exceeding_hard_limit()
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)

        assert len(hard_calls) == 1
        assert hard_calls[0][0] == container.id
        assert len(soft_calls) == 0


# ---------------------------------------------------------------------------
# _evaluate_limits — 非持久容器只检测不响应
# ---------------------------------------------------------------------------

class TestEvaluateLimitsNonLongTerm:
    """非持久容器：只做检测（写 DB + 日志），不执行响应动作。"""

    def test_soft_limit_skips_response(self, app, db_session, monkeypatch):
        """非持久容器超过 soft limit → 不触发 _handle_soft_limit。"""
        _root, machine, container = create_container_graph()
        # 不调用 long_term_container_repo.add() —— 非持久容器

        soft_calls = []
        hard_calls = []
        monkeypatch.setattr(
            container_disk_check_task, "_handle_soft_limit",
            lambda c, u, a: soft_calls.append(c.id)
        )
        monkeypatch.setattr(
            container_disk_check_task, "_handle_hard_limit",
            lambda c, u, a: hard_calls.append(c.id)
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", True)

        usage = _usage_exceeding_soft_limit()
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)

        assert len(soft_calls) == 0, "非持久容器不应触发 soft limit 响应"
        assert len(hard_calls) == 0, "非持久容器不应触发 hard limit 响应"

    def test_hard_limit_skips_response(self, app, db_session, monkeypatch):
        """非持久容器超过 hard limit → 不触发 _handle_hard_limit。"""
        _root, machine, container = create_container_graph()

        soft_calls = []
        hard_calls = []
        monkeypatch.setattr(
            container_disk_check_task, "_handle_soft_limit",
            lambda c, u, a: soft_calls.append(c.id)
        )
        monkeypatch.setattr(
            container_disk_check_task, "_handle_hard_limit",
            lambda c, u, a: hard_calls.append(c.id)
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", True)

        usage = _usage_exceeding_hard_limit()
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)

        assert len(soft_calls) == 0
        assert len(hard_calls) == 0, "非持久容器不应触发 hard limit 响应"


# ---------------------------------------------------------------------------
# _evaluate_limits — 磁盘用量持久化（两类容器均持久化）
# ---------------------------------------------------------------------------

class TestEvaluateLimitsPersistence:
    """不论是否持久容器，磁盘用量都应写入 DB。"""

    def test_long_term_container_persists_disk_usage(self, app, db_session, monkeypatch):
        """持久容器：磁盘快照写入 DB。"""
        _root, machine, container = create_container_graph()
        long_term_container_repo.add(container.id)

        monkeypatch.setattr(
            container_disk_check_task, "_handle_soft_limit",
            lambda c, u, a: None
        )
        monkeypatch.setattr(
            container_disk_check_task, "_handle_hard_limit",
            lambda c, u, a: None
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", True)

        usage = _usage_exceeding_soft_limit()
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)
            # 在 context 内验证持久化（退出 context 时 Flask-SQLAlchemy
            # 会触发 teardown_appcontext → db.session.remove()，导致后续读到空值）
            c = db.session.get(Container, container.id)
            assert c.disk_total_bytes == usage["container"]["total_bytes"]
            assert c.disk_limit_bytes == int(1024 * 1024 ** 3)
            assert c.disk_overlay_rw_bytes == usage["container"]["overlay_rw_bytes"]
            assert c.disk_bind_mount_bytes == usage["container"]["bind_mount_bytes"]
            assert c.disk_checked_at is not None

    def test_non_long_term_container_persists_disk_usage(self, app, db_session, monkeypatch):
        """非持久容器：磁盘快照同样写入 DB。"""
        _root, machine, container = create_container_graph()

        monkeypatch.setattr(
            container_disk_check_task, "_handle_soft_limit",
            lambda c, u, a: None
        )
        monkeypatch.setattr(
            container_disk_check_task, "_handle_hard_limit",
            lambda c, u, a: None
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", True)

        usage = _usage_exceeding_hard_limit()
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)
            c = db.session.get(Container, container.id)
            assert c.disk_total_bytes == usage["container"]["total_bytes"]
            assert c.disk_limit_bytes == int(1024 * 1024 ** 3)
            assert c.disk_checked_at is not None


# ---------------------------------------------------------------------------
# _evaluate_limits — response 全局关闭时
# ---------------------------------------------------------------------------

class TestEvaluateLimitsResponseDisabled:
    """全局 RESPONSE_ENABLED=false 时，持久容器也不响应。"""

    def test_long_term_skips_when_response_disabled(self, app, db_session, monkeypatch):
        """response 关闭 → 持久容器也不触发 handler。"""
        _root, machine, container = create_container_graph()
        long_term_container_repo.add(container.id)

        soft_calls = []
        hard_calls = []
        monkeypatch.setattr(
            container_disk_check_task, "_handle_soft_limit",
            lambda c, u, a: soft_calls.append(c.id)
        )
        monkeypatch.setattr(
            container_disk_check_task, "_handle_hard_limit",
            lambda c, u, a: hard_calls.append(c.id)
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", False)

        usage = _usage_exceeding_hard_limit()
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)

        assert len(soft_calls) == 0
        assert len(hard_calls) == 0

    def test_non_long_term_skips_when_response_disabled(self, app, db_session, monkeypatch):
        """response 关闭 + 非持久 → 双重保险，不触发 handler。"""
        _root, machine, container = create_container_graph()

        soft_calls = []
        hard_calls = []
        monkeypatch.setattr(
            container_disk_check_task, "_handle_soft_limit",
            lambda c, u, a: soft_calls.append(c.id)
        )
        monkeypatch.setattr(
            container_disk_check_task, "_handle_hard_limit",
            lambda c, u, a: hard_calls.append(c.id)
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", False)

        usage = _usage_exceeding_hard_limit()
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)

        assert len(soft_calls) == 0
        assert len(hard_calls) == 0


# ---------------------------------------------------------------------------
# _evaluate_limits — 磁盘检测总开关关闭时
# ---------------------------------------------------------------------------

class TestEvaluateLimitsCheckDisabled:
    """CONTAINER_DISK_CHECK_ENABLED=false 时，直接跳过所有逻辑。"""

    def test_skips_everything_when_check_disabled(self, app, db_session, monkeypatch):
        """检测关闭 → 不持久化、不响应。"""
        _root, machine, container = create_container_graph()
        long_term_container_repo.add(container.id)

        soft_calls = []
        hard_calls = []
        monkeypatch.setattr(
            container_disk_check_task, "_handle_soft_limit",
            lambda c, u, a: soft_calls.append(c.id)
        )
        monkeypatch.setattr(
            container_disk_check_task, "_handle_hard_limit",
            lambda c, u, a: hard_calls.append(c.id)
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", False)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", True)

        usage = _usage_exceeding_hard_limit()
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)

        assert len(soft_calls) == 0
        assert len(hard_calls) == 0

        c = db.session.get(Container, container.id)
        assert c.disk_checked_at is None, "检测关闭时不应写入磁盘快照"


# ---------------------------------------------------------------------------
# _evaluate_limits — 边界条件
# ---------------------------------------------------------------------------

class TestEvaluateLimitsEdgeCases:
    """边界条件测试。"""

    def test_ok_usage_triggers_neither_handler(self, app, db_session, monkeypatch):
        """正常用量不触发任何 handler。"""
        _root, machine, container = create_container_graph()
        long_term_container_repo.add(container.id)

        soft_calls = []
        hard_calls = []
        monkeypatch.setattr(
            container_disk_check_task, "_handle_soft_limit",
            lambda c, u, a: soft_calls.append(c.id)
        )
        monkeypatch.setattr(
            container_disk_check_task, "_handle_hard_limit",
            lambda c, u, a: hard_calls.append(c.id)
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", True)

        usage = _usage_below_soft_limit()
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)

        assert len(soft_calls) == 0
        assert len(hard_calls) == 0

    def test_machine_without_disk_size_gb_skips(self, app, db_session, monkeypatch):
        """机器未配置 disk_size_gb → 跳过评估，不触发 handler。"""
        from ..factories import create_machine, create_container as _create_container
        from ..factories import create_user, bind_user_container
        from ...repositories import machine_permission_repo
        from ...constant import ROLE

        user = create_user()
        machine = create_machine(disk_size_gb=0)  # disk_size_gb=0
        container = _create_container(machine=machine)
        machine_permission_repo.add_permission(machine.id, user.id)
        bind_user_container(user, container, role=ROLE.ROOT)
        long_term_container_repo.add(container.id)

        soft_calls = []
        hard_calls = []
        monkeypatch.setattr(
            container_disk_check_task, "_handle_soft_limit",
            lambda c, u, a: soft_calls.append(c.id)
        )
        monkeypatch.setattr(
            container_disk_check_task, "_handle_hard_limit",
            lambda c, u, a: hard_calls.append(c.id)
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", True)

        usage = _usage_exceeding_hard_limit()
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)

        assert len(soft_calls) == 0
        assert len(hard_calls) == 0


# ---------------------------------------------------------------------------
# scheduler
# ---------------------------------------------------------------------------

class TestDiskCheckScheduler:
    """start_container_disk_check_scheduler 调度器测试。"""

    def test_returns_none_when_disabled(self, app):
        """检测关闭时调度器返回 None。"""
        app.config["CONTAINER_DISK_CHECK_ENABLED"] = False
        result = container_disk_check_task.start_container_disk_check_scheduler(
            app, interval_seconds=999
        )
        assert result is None

    def test_returns_existing_thread_when_alive(self, app):
        """已有存活线程时返回现有线程。"""
        app.config["CONTAINER_DISK_CHECK_ENABLED"] = True

        class _Thread:
            def is_alive(self):
                return True

        existing = _Thread()
        app.extensions["container_disk_check_scheduler"] = {"thread": existing}

        result = container_disk_check_task.start_container_disk_check_scheduler(
            app, interval_seconds=999
        )
        assert result is existing


# ============================================================================
# Phase 5-6: 冻结升级 & 宽限期
# ============================================================================

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _usage_below_reset():
    """构造低于 95% 重置阈值的磁盘用量。"""
    gb = 1024 ** 3
    return {
        "container": {
            "overlay_rw_bytes": int(400 * gb),
            "bind_mount_bytes": int(400 * gb),
            "total_bytes": int(800 * gb),  # 800/1024 ≈ 78.1% < 95%
        }
    }


# ---------------------------------------------------------------------------
# Repository 层
# ---------------------------------------------------------------------------

class TestFreezeStateRepo:
    """container_disk_freeze_state_repo 单元测试。"""

    def test_get_returns_none_when_no_record(self, app, db_session):
        assert container_disk_freeze_state_repo.get(999) is None

    def test_get_returns_record_when_exists(self, app, db_session):
        _root, _machine, container = create_container_graph()
        container_disk_freeze_state_repo.upsert_first_frozen(container.id)
        row = container_disk_freeze_state_repo.get(container.id)
        assert row is not None
        assert row.container_id == container.id
        assert row.first_frozen_at is not None

    def test_upsert_creates_new_record(self, app, db_session):
        _root, _machine, container = create_container_graph()
        row = container_disk_freeze_state_repo.upsert_first_frozen(container.id)
        assert row is not None
        assert row.first_frozen_at is not None
        # verify persisted
        row2 = container_disk_freeze_state_repo.get(container.id)
        assert row2 is not None

    def test_upsert_preserves_first_frozen_at(self, app, db_session):
        _root, _machine, container = create_container_graph()
        row1 = container_disk_freeze_state_repo.upsert_first_frozen(container.id)
        original = row1.first_frozen_at
        # second call
        row2 = container_disk_freeze_state_repo.upsert_first_frozen(container.id)
        assert row2.first_frozen_at == original

    def test_reset_deletes_record(self, app, db_session):
        _root, _machine, container = create_container_graph()
        container_disk_freeze_state_repo.upsert_first_frozen(container.id)
        assert container_disk_freeze_state_repo.get(container.id) is not None
        container_disk_freeze_state_repo.reset(container.id)
        assert container_disk_freeze_state_repo.get(container.id) is None

    def test_reset_returns_false_when_no_record(self, app, db_session):
        assert container_disk_freeze_state_repo.reset(999) is False

    def test_reset_returns_true_when_record_deleted(self, app, db_session):
        _root, _machine, container = create_container_graph()
        container_disk_freeze_state_repo.upsert_first_frozen(container.id)
        assert container_disk_freeze_state_repo.reset(container.id) is True

    def test_set_grace_sets_grace_until(self, app, db_session):
        _root, _machine, container = create_container_graph()
        container_disk_freeze_state_repo.upsert_first_frozen(container.id)
        assert container_disk_freeze_state_repo.set_grace(container.id, 3) is True
        row = container_disk_freeze_state_repo.get(container.id)
        assert row.grace_until is not None
        # should be ~3 days from now
        delta = row.grace_until - datetime.utcnow()
        assert timedelta(days=2, hours=23) < delta < timedelta(days=3, hours=1)

    def test_set_grace_returns_false_when_no_record(self, app, db_session):
        assert container_disk_freeze_state_repo.set_grace(999, 3) is False

    def test_set_grace_overwrites_existing_grace(self, app, db_session):
        _root, _machine, container = create_container_graph()
        container_disk_freeze_state_repo.upsert_first_frozen(container.id)
        container_disk_freeze_state_repo.set_grace(container.id, 3)
        first = container_disk_freeze_state_repo.get(container.id).grace_until
        container_disk_freeze_state_repo.set_grace(container.id, 5)
        second = container_disk_freeze_state_repo.get(container.id).grace_until
        assert second > first

    def test_clear_grace_sets_null(self, app, db_session):
        _root, _machine, container = create_container_graph()
        container_disk_freeze_state_repo.upsert_first_frozen(container.id)
        container_disk_freeze_state_repo.set_grace(container.id, 3)
        assert container_disk_freeze_state_repo.clear_grace(container.id) is True
        row = container_disk_freeze_state_repo.get(container.id)
        assert row.grace_until is None

    def test_clear_grace_returns_false_when_no_grace(self, app, db_session):
        _root, _machine, container = create_container_graph()
        container_disk_freeze_state_repo.upsert_first_frozen(container.id)
        # no grace set yet
        assert container_disk_freeze_state_repo.clear_grace(container.id) is False


# ---------------------------------------------------------------------------
# _evaluate_limits — 冻结记录与升级
# ---------------------------------------------------------------------------

class TestFreezeEscalation:
    """冻结记录、倒计时、升级删除。"""

    def test_first_frozen_recorded_on_hard_limit(self, app, db_session, monkeypatch):
        """长期容器首次超 hard limit → FreezeState 写入。"""
        _root, machine, container = create_container_graph()
        long_term_container_repo.add(container.id)

        monkeypatch.setattr(
            container_disk_check_task, "_handle_hard_limit",
            lambda c, u, a: None
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", True)

        usage = _usage_exceeding_hard_limit()
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)

        row = container_disk_freeze_state_repo.get(container.id)
        assert row is not None
        assert row.first_frozen_at is not None

    def test_first_frozen_not_updated_on_second_hit(self, app, db_session, monkeypatch):
        """第二次超限 → first_frozen_at 不变。"""
        _root, machine, container = create_container_graph()
        long_term_container_repo.add(container.id)

        monkeypatch.setattr(
            container_disk_check_task, "_handle_hard_limit",
            lambda c, u, a: None
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", True)

        usage = _usage_exceeding_hard_limit()
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)
        first = container_disk_freeze_state_repo.get(container.id).first_frozen_at

        # second hit
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)
        second = container_disk_freeze_state_repo.get(container.id).first_frozen_at
        assert first == second

    def test_escalation_after_7_days(self, app, db_session, monkeypatch):
        """冻结满 7 天 → _handle_freeze_escalation 被调用。"""
        _root, machine, container = create_container_graph()
        long_term_container_repo.add(container.id)

        escalated = []
        hard_calls = []
        monkeypatch.setattr(
            container_disk_check_task, "_handle_freeze_escalation",
            lambda c, u, a, d: escalated.append((c.id, d))
        )
        monkeypatch.setattr(
            container_disk_check_task, "_handle_hard_limit",
            lambda c, u, a: hard_calls.append(c.id)
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", True)

        # pre-create freeze state with first_frozen_at = 8 days ago
        container_disk_freeze_state_repo.upsert_first_frozen(container.id)
        row = container_disk_freeze_state_repo.get(container.id)
        row.first_frozen_at = datetime.utcnow() - timedelta(days=8)
        db.session.commit()

        usage = _usage_exceeding_hard_limit()
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)

        assert len(escalated) == 1
        assert escalated[0][0] == container.id
        assert escalated[0][1] >= 7
        assert len(hard_calls) == 0

    def test_escalation_not_triggered_before_7_days(self, app, db_session, monkeypatch):
        """冻结 3 天 → 只走 _handle_hard_limit，不升级。"""
        _root, machine, container = create_container_graph()
        long_term_container_repo.add(container.id)

        escalated = []
        hard_calls = []
        monkeypatch.setattr(
            container_disk_check_task, "_handle_freeze_escalation",
            lambda c, u, a, d: escalated.append(c.id)
        )
        monkeypatch.setattr(
            container_disk_check_task, "_handle_hard_limit",
            lambda c, u, a: hard_calls.append(c.id)
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", True)

        container_disk_freeze_state_repo.upsert_first_frozen(container.id)
        row = container_disk_freeze_state_repo.get(container.id)
        row.first_frozen_at = datetime.utcnow() - timedelta(days=3)
        db.session.commit()

        usage = _usage_exceeding_hard_limit()
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)

        assert len(escalated) == 0
        assert len(hard_calls) == 1

    def test_escalation_not_triggered_for_short_term(self, app, db_session, monkeypatch):
        """冻结满 7 天但已是短期容器 → 不升级。"""
        _root, machine, container = create_container_graph()
        # NOT long-term

        escalated = []
        hard_calls = []
        monkeypatch.setattr(
            container_disk_check_task, "_handle_freeze_escalation",
            lambda c, u, a, d: escalated.append(c.id)
        )
        monkeypatch.setattr(
            container_disk_check_task, "_handle_hard_limit",
            lambda c, u, a: hard_calls.append(c.id)
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", True)

        # create legacy freeze state
        container_disk_freeze_state_repo.upsert_first_frozen(container.id)
        row = container_disk_freeze_state_repo.get(container.id)
        row.first_frozen_at = datetime.utcnow() - timedelta(days=8)
        db.session.commit()

        usage = _usage_exceeding_hard_limit()
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)

        assert len(escalated) == 0, "短期容器不应升级"
        assert len(hard_calls) == 0, "短期容器不应 pause"


# ---------------------------------------------------------------------------
# _evaluate_limits — 宽限期
# ---------------------------------------------------------------------------

class TestGracePeriod:
    """宽限期：解冻后 3 天内跳过 pause，到期恢复。"""

    def test_grace_period_skips_pause(self, app, db_session, monkeypatch):
        """宽限期内超 hard limit → 不触发任何 handler。"""
        _root, machine, container = create_container_graph()
        long_term_container_repo.add(container.id)

        escalated = []
        hard_calls = []
        monkeypatch.setattr(
            container_disk_check_task, "_handle_freeze_escalation",
            lambda c, u, a, d: escalated.append(c.id)
        )
        monkeypatch.setattr(
            container_disk_check_task, "_handle_hard_limit",
            lambda c, u, a: hard_calls.append(c.id)
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", True)

        # create freeze state with active grace
        container_disk_freeze_state_repo.upsert_first_frozen(container.id)
        container_disk_freeze_state_repo.set_grace(container.id, 3)

        usage = _usage_exceeding_hard_limit()
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)

        assert len(escalated) == 0, "宽限期内不应升级"
        assert len(hard_calls) == 0, "宽限期内不应 pause"

    def test_grace_period_skips_escalation_even_if_7_days(self, app, db_session, monkeypatch):
        """宽限期内 + 冻结满 7 天 → 仍跳过升级（宽限优先）。"""
        _root, machine, container = create_container_graph()
        long_term_container_repo.add(container.id)

        escalated = []
        hard_calls = []
        monkeypatch.setattr(
            container_disk_check_task, "_handle_freeze_escalation",
            lambda c, u, a, d: escalated.append(c.id)
        )
        monkeypatch.setattr(
            container_disk_check_task, "_handle_hard_limit",
            lambda c, u, a: hard_calls.append(c.id)
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", True)

        container_disk_freeze_state_repo.upsert_first_frozen(container.id)
        row = container_disk_freeze_state_repo.get(container.id)
        row.first_frozen_at = datetime.utcnow() - timedelta(days=8)
        container_disk_freeze_state_repo.set_grace(container.id, 3)
        db.session.commit()

        usage = _usage_exceeding_hard_limit()
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)

        assert len(escalated) == 0, "宽限期内不应升级（即使已满 7 天）"
        assert len(hard_calls) == 0

    def test_grace_expired_resumes_freeze(self, app, db_session, monkeypatch):
        """宽限期到期 + 仍超限 → 恢复 _handle_hard_limit，清除 grace_until。"""
        _root, machine, container = create_container_graph()
        long_term_container_repo.add(container.id)

        escalated = []
        hard_calls = []
        monkeypatch.setattr(
            container_disk_check_task, "_handle_freeze_escalation",
            lambda c, u, a, d: escalated.append(c.id)
        )
        monkeypatch.setattr(
            container_disk_check_task, "_handle_hard_limit",
            lambda c, u, a: hard_calls.append(c.id)
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", True)

        container_disk_freeze_state_repo.upsert_first_frozen(container.id)
        # set grace that expired 1 day ago
        row = container_disk_freeze_state_repo.get(container.id)
        row.grace_until = datetime.utcnow() - timedelta(days=1)
        db.session.commit()

        usage = _usage_exceeding_hard_limit()
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)

        assert len(hard_calls) == 1, "宽限期到期应恢复 pause"
        assert len(escalated) == 0
        # grace_until should be cleared
        row2 = container_disk_freeze_state_repo.get(container.id)
        assert row2.grace_until is None

    def test_grace_expired_triggers_escalation_if_7_days(self, app, db_session, monkeypatch):
        """宽限期到期 + 冻结满 7 天 → 直接升级删除。"""
        _root, machine, container = create_container_graph()
        long_term_container_repo.add(container.id)

        escalated = []
        hard_calls = []
        monkeypatch.setattr(
            container_disk_check_task, "_handle_freeze_escalation",
            lambda c, u, a, d: escalated.append((c.id, d))
        )
        monkeypatch.setattr(
            container_disk_check_task, "_handle_hard_limit",
            lambda c, u, a: hard_calls.append(c.id)
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", True)

        container_disk_freeze_state_repo.upsert_first_frozen(container.id)
        row = container_disk_freeze_state_repo.get(container.id)
        row.first_frozen_at = datetime.utcnow() - timedelta(days=8)
        row.grace_until = datetime.utcnow() - timedelta(days=1)  # expired
        db.session.commit()

        usage = _usage_exceeding_hard_limit()
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)

        assert len(escalated) == 1, "宽限到期 + 已满 7 天 → 应升级"
        assert escalated[0][0] == container.id
        assert len(hard_calls) == 0

    def test_multiple_unpause_extends_grace(self, app, db_session, monkeypatch):
        """宽限期内再次设宽限 → grace_until 延长。"""
        _root, machine, container = create_container_graph()
        container_disk_freeze_state_repo.upsert_first_frozen(container.id)
        container_disk_freeze_state_repo.set_grace(container.id, 3)
        first = container_disk_freeze_state_repo.get(container.id).grace_until
        container_disk_freeze_state_repo.set_grace(container.id, 5)
        second = container_disk_freeze_state_repo.get(container.id).grace_until
        assert second > first


# ---------------------------------------------------------------------------
# _evaluate_limits — 重置
# ---------------------------------------------------------------------------

class TestFreezeReset:
    """容量回落 < 95% → 清除冻结状态。"""

    def test_freeze_state_reset_on_usage_below_reset(self, app, db_session, monkeypatch):
        """长期容器 + 有冻结记录 + 容量回落 < 95% → 记录删除。"""
        _root, machine, container = create_container_graph()
        long_term_container_repo.add(container.id)

        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", True)

        # first, create a freeze state
        container_disk_freeze_state_repo.upsert_first_frozen(container.id)
        assert container_disk_freeze_state_repo.get(container.id) is not None

        soft_calls = []
        hard_calls = []
        monkeypatch.setattr(
            container_disk_check_task, "_handle_soft_limit",
            lambda c, u, a: soft_calls.append(c.id)
        )
        monkeypatch.setattr(
            container_disk_check_task, "_handle_hard_limit",
            lambda c, u, a: hard_calls.append(c.id)
        )

        # now simulate usage dropping below reset
        usage = _usage_below_reset()
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)

        assert container_disk_freeze_state_repo.get(container.id) is None
        assert len(soft_calls) == 0, "重置后不应触发 soft limit"
        assert len(hard_calls) == 0, "重置后不应触发 hard limit"

    def test_freeze_state_reset_works_for_short_term(self, app, db_session, monkeypatch):
        """短期容器（曾是长期）+ 容量回落 → 状态清除。"""
        _root, machine, container = create_container_graph()
        # NOT long-term, but has legacy freeze state
        container_disk_freeze_state_repo.upsert_first_frozen(container.id)
        assert container_disk_freeze_state_repo.get(container.id) is not None

        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", True)

        usage = _usage_below_reset()
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)

        assert container_disk_freeze_state_repo.get(container.id) is None, (
            "短期容器容量回落也应清除冻结状态"
        )

    def test_freeze_state_not_reset_on_usage_above_reset(self, app, db_session, monkeypatch):
        """容量 96%（不满足 < 95%）→ 状态保留。"""
        _root, machine, container = create_container_graph()
        long_term_container_repo.add(container.id)
        container_disk_freeze_state_repo.upsert_first_frozen(container.id)

        monkeypatch.setattr(
            container_disk_check_task, "_handle_soft_limit",
            lambda c, u, a: None
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", True)

        # 96% — above 95% reset threshold, triggers soft limit
        gb = 1024 ** 3
        usage = {
            "container": {
                "overlay_rw_bytes": int(500 * gb),
                "bind_mount_bytes": int(483 * gb),
                "total_bytes": int(983 * gb),  # 983/1024 ≈ 96.0%
            }
        }
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)

        assert container_disk_freeze_state_repo.get(container.id) is not None, (
            "容量 96% 不满足 < 95% 重置条件，状态应保留"
        )

    def test_freeze_state_survives_long_to_short_transition(self, app, db_session):
        """切换为短期 → 冻结记录仍在。"""
        _root, machine, container = create_container_graph()
        # was long-term, got frozen
        long_term_container_repo.add(container.id)
        container_disk_freeze_state_repo.upsert_first_frozen(container.id)

        # switch to short-term (remove from long_term)
        long_term_container_repo.remove(container.id)

        # freeze state should still exist
        assert container_disk_freeze_state_repo.get(container.id) is not None, (
            "切换为短期容器不应清除冻结状态"
        )

    def test_freeze_state_cascade_on_container_delete(self, app, db_session):
        """容器删 → FreezeState 可通过 repo.reset 清除（级联由 DB FK 保证）。"""
        _root, machine, container = create_container_graph()
        container_disk_freeze_state_repo.upsert_first_frozen(container.id)
        fid = container.id
        assert container_disk_freeze_state_repo.get(fid) is not None

        # 清理时先删 freeze state，再删容器（生产环境由 FK CASCADE 自动处理）
        container_disk_freeze_state_repo.reset(fid)
        db.session.delete(container)
        db.session.commit()

        assert container_disk_freeze_state_repo.get(fid) is None

    def test_grace_cleared_on_usage_below_reset(self, app, db_session, monkeypatch):
        """宽限期内容量回落 < 95% → 整条记录删除（含 grace_until）。"""
        _root, machine, container = create_container_graph()
        long_term_container_repo.add(container.id)
        container_disk_freeze_state_repo.upsert_first_frozen(container.id)
        container_disk_freeze_state_repo.set_grace(container.id, 3)
        assert container_disk_freeze_state_repo.get(container.id).grace_until is not None

        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", True)

        usage = _usage_below_reset()
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)

        assert container_disk_freeze_state_repo.get(container.id) is None, (
            "重置应删除整条记录（含宽限期）"
        )


# ---------------------------------------------------------------------------
# _handle_freeze_escalation — 升级删除
# ---------------------------------------------------------------------------

class TestHandleFreezeEscalation:
    """升级删除函数：remove_container + 邮件 + 操作日志。"""

    def test_escalation_calls_remove_container(self, app, db_session, monkeypatch):
        """升级时 remove_container 被调用。"""
        _root, machine, container = create_container_graph()
        long_term_container_repo.add(container.id)

        removed = []
        monkeypatch.setattr(
            container_disk_check_task.container_tasks, "remove_container",
            lambda cid: removed.append(cid) or True
        )
        monkeypatch.setattr(
            container_disk_check_task.container_tasks,
            "get_container_root_owner_emails",
            lambda cid: []
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)

        usage = _usage_exceeding_hard_limit()
        with app.app_context():
            container_disk_check_task._handle_freeze_escalation(
                container, usage, app, days_frozen=8
            )

        assert container.id in removed

    def test_escalation_sends_email(self, app, db_session, monkeypatch):
        """升级时发送通知邮件。"""
        _root, machine, container = create_container_graph()
        long_term_container_repo.add(container.id)

        sent = []
        monkeypatch.setattr(
            container_disk_check_task.container_tasks, "remove_container",
            lambda cid: True
        )
        monkeypatch.setattr(
            container_disk_check_task.container_tasks,
            "get_container_root_owner_emails",
            lambda cid: ["owner@test.com"]
        )

        def _fake_send_mail(*, to, subject, content):
            sent.append({"to": to, "subject": subject, "content": content})
            return {"ok": True}

        monkeypatch.setattr(
            "FuxiYu_CtrKernel.utils.mail.send", _fake_send_mail
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)

        usage = _usage_exceeding_hard_limit()
        with app.app_context():
            container_disk_check_task._handle_freeze_escalation(
                container, usage, app, days_frozen=8
            )

        assert len(sent) == 1
        assert sent[0]["to"] == "owner@test.com"
        assert "已被清除" in sent[0]["subject"]
        assert "8 天" in sent[0]["content"]

    def test_escalation_writes_operation_log(self, app, db_session, monkeypatch):
        """升级时写入操作日志。"""
        _root, machine, container = create_container_graph()
        long_term_container_repo.add(container.id)

        logs = []
        monkeypatch.setattr(
            container_disk_check_task.container_tasks, "remove_container",
            lambda cid: True
        )
        monkeypatch.setattr(
            container_disk_check_task.container_tasks,
            "get_container_root_owner_emails",
            lambda cid: []
        )
        from ...services import operation_log_tasks
        monkeypatch.setattr(
            operation_log_tasks,
            "write_operation_log",
            lambda **kwargs: logs.append(kwargs)
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)

        usage = _usage_exceeding_hard_limit()
        with app.app_context():
            container_disk_check_task._handle_freeze_escalation(
                container, usage, app, days_frozen=8
            )

        assert len(logs) == 1
        assert logs[0]["operation"] == "remove_container"
        assert logs[0]["detail"]["reason"] == "disk_freeze_escalation"
        assert logs[0]["detail"]["days_frozen"] == 8

    def test_escalation_email_cooled_down_24h(self, app, db_session, monkeypatch):
        """同一容器 24h 内不重复发升级邮件（验证 cooldown 状态）。"""
        _root, machine, container = create_container_graph()
        long_term_container_repo.add(container.id)

        removed_count = []
        monkeypatch.setattr(
            container_disk_check_task.container_tasks, "remove_container",
            lambda cid: removed_count.append(cid) or True
        )
        monkeypatch.setattr(
            container_disk_check_task.container_tasks,
            "get_container_root_owner_emails",
            lambda cid: ["owner@test.com"]
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)

        # 使用 conftest 已有的 mail.send mock（无需额外 mock）
        usage = _usage_exceeding_hard_limit()
        with app.app_context():
            # 首次调用：设下 cooldown
            container_disk_check_task._handle_freeze_escalation(
                container, usage, app, days_frozen=8
            )
            cooldown_after_first = getattr(app, '_disk_check_cache', {})
            escalation_key = f"_escalation_last_sent_{container.id}"
            assert escalation_key in cooldown_after_first, (
                "首次调用应写入 cooldown key"
            )

            # 第二次调用：仍在 cooldown 内
            container_disk_check_task._handle_freeze_escalation(
                container, usage, app, days_frozen=8
            )

        # remove 两次都执行（无 cooldown 限制）
        assert len(removed_count) == 2


# ---------------------------------------------------------------------------
# _evaluate_limits — RESPONSE_ENABLED=false 时可观测
# ---------------------------------------------------------------------------

class TestFreezeObservability:
    """RESPONSE_ENABLED=false 时冻结状态追踪仍可观测。"""

    def test_reset_still_works_when_response_disabled(self, app, db_session, monkeypatch):
        """response 关闭时容量回落仍清除冻结记录。"""
        _root, machine, container = create_container_graph()
        long_term_container_repo.add(container.id)
        container_disk_freeze_state_repo.upsert_first_frozen(container.id)
        assert container_disk_freeze_state_repo.get(container.id) is not None

        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", False)

        usage = _usage_below_reset()
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)

        assert container_disk_freeze_state_repo.get(container.id) is None, (
            "response 关闭时仍应执行重置"
        )

    def test_short_term_with_legacy_freeze_state_logs(self, app, db_session, monkeypatch):
        """短期容器 + 遗留冻结记录 → _log_freeze_state_if_exists 不抛异常。"""
        _root, machine, container = create_container_graph()
        # NOT long-term, but has freeze state (was long-term before)
        container_disk_freeze_state_repo.upsert_first_frozen(container.id)
        row = container_disk_freeze_state_repo.get(container.id)
        row.first_frozen_at = datetime.utcnow() - timedelta(days=5)
        db.session.commit()

        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)
        monkeypatch.setitem(app.config, "CONTAINER_DISK_RESPONSE_ENABLED", True)

        usage = _usage_exceeding_hard_limit()
        with app.app_context():
            # should not raise
            container_disk_check_task._evaluate_limits(container, usage)

        # freeze state should still exist (short-term doesn't clear it)
        assert container_disk_freeze_state_repo.get(container.id) is not None


# ============================================================================
# Phase 8: mount 路径持久化 & 升级立刻清理
# ============================================================================

class TestBindMountPathPersistence:
    """bind_mount_path 在磁盘检测时持久化到 Container。"""

    def test_bind_mount_path_persisted_during_disk_check(self, app, db_session, monkeypatch):
        """磁盘检测时 NodeKernel 返回 bind_mount_path → Container 表记录更新。"""
        _root, machine, container = create_container_graph()
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)

        mount_path = "/home/alice/containers/test_mount/"
        usage = _usage_below_soft_limit()
        usage["container"]["bind_mount_path"] = mount_path

        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)
            c = db.session.get(Container, container.id)
            assert c.bind_mount_path == mount_path

    def test_bind_mount_path_none_persisted(self, app, db_session, monkeypatch):
        """NodeKernel 不返回 bind_mount_path → 不报错，正常跳过。"""
        _root, machine, container = create_container_graph()
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)

        usage = _usage_below_soft_limit()
        # no bind_mount_path in usage
        with app.app_context():
            container_disk_check_task._evaluate_limits(container, usage)

        c = db.session.get(Container, container.id)
        # should not crash, value is None (update_container skips None)


class TestEscalationMountCleanup:
    """升级删除时立刻清理 mount。"""

    def test_clean_mount_immediately_inserts_record(self, app, db_session, monkeypatch):
        """升级删除 → MountCleanup 记录写入，escalation=True, cleaned_at 立刻非空。"""
        from ...models.container_mount_cleanup import ContainerMountCleanup

        _root, machine, container = create_container_graph()
        container.bind_mount_path = "/home/test/containers/test_esc/"
        db.session.commit()

        monkeypatch.setattr(
            container_disk_check_task.container_tasks, "remove_container",
            lambda cid: True
        )
        monkeypatch.setattr(
            container_disk_check_task.container_tasks,
            "get_container_root_owner_emails",
            lambda cid: []
        )
        # mock send to avoid real HTTP
        monkeypatch.setattr(
            container_disk_check_task.container_tasks, "send",
            lambda enc, sig, url, timeout: {"success": 1}
        )
        monkeypatch.setattr(
            container_disk_check_task.container_tasks, "signature",
            lambda p: b"sig"
        )
        monkeypatch.setattr(
            container_disk_check_task.container_tasks, "encryption",
            lambda p: b"enc"
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)

        usage = _usage_exceeding_hard_limit()
        with app.app_context():
            container_disk_check_task._handle_freeze_escalation(
                container, usage, app, days_frozen=8
            )

        row = db.session.query(ContainerMountCleanup).filter_by(
            container_id=container.id,
            escalation=True,
        ).first()
        assert row is not None
        assert row.mount_path == "/home/test/containers/test_esc/"
        assert row.cleaned_at is not None

    def test_clean_mount_immediately_sends_to_node(self, app, db_session, monkeypatch):
        """升级删除 → NodeKernel /api/clean_mount 被调用。"""
        _root, machine, container = create_container_graph()
        container.bind_mount_path = "/home/test/containers/test_esc2/"
        db.session.commit()

        monkeypatch.setattr(
            container_disk_check_task.container_tasks, "remove_container",
            lambda cid: True
        )
        monkeypatch.setattr(
            container_disk_check_task.container_tasks,
            "get_container_root_owner_emails",
            lambda cid: []
        )

        sent_calls = []
        monkeypatch.setattr(
            container_disk_check_task.container_tasks, "send",
            lambda enc, sig, url, timeout: sent_calls.append(url) or {"success": 1}
        )
        monkeypatch.setattr(
            container_disk_check_task.container_tasks, "signature",
            lambda p: b"sig"
        )
        monkeypatch.setattr(
            container_disk_check_task.container_tasks, "encryption",
            lambda p: b"enc"
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)

        usage = _usage_exceeding_hard_limit()
        with app.app_context():
            container_disk_check_task._handle_freeze_escalation(
                container, usage, app, days_frozen=8
            )

        assert len(sent_calls) == 1
        assert "/clean_mount" in sent_calls[0]

    def test_clean_mount_immediately_skips_without_path(self, app, db_session, monkeypatch):
        """容器无 bind_mount_path → 升级删除不崩溃，跳过清理。"""
        _root, machine, container = create_container_graph()
        # bind_mount_path is None

        monkeypatch.setattr(
            container_disk_check_task.container_tasks, "remove_container",
            lambda cid: True
        )
        monkeypatch.setattr(
            container_disk_check_task.container_tasks,
            "get_container_root_owner_emails",
            lambda cid: []
        )
        monkeypatch.setitem(app.config, "CONTAINER_DISK_CHECK_ENABLED", True)

        usage = _usage_exceeding_hard_limit()
        with app.app_context():
            # should not raise
            container_disk_check_task._handle_freeze_escalation(
                container, usage, app, days_frozen=8
            )
