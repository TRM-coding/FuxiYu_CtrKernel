"""测试 container_disk_check_task — 磁盘容量检测与持久/非持久容器区分逻辑。

核心验证点：
- 持久容器（LongTermContainer）接受容量响应（pause / 邮件）
- 非持久容器只做检测（写 DB + 日志），永不响应
"""

from ...extensions import db
from ...models.containers import Container
from ...repositories import long_term_container_repo
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
