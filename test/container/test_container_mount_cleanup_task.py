"""container_mount_cleanup_task 单元测试。"""

from datetime import datetime, timedelta

from ...repositories import container_mount_cleanup_repo
from ...schedulers import container_mount_cleanup_task


class TestMountCleanupTask:
    """run_mount_cleanup_once 定期清理逻辑。"""

    def test_no_pending_rows_does_nothing(self, app, db_session, monkeypatch):
        """无待清理记录 → 不做任何请求。"""
        db_session.commit()

        sent = []
        monkeypatch.setattr(
            container_mount_cleanup_task, "send",
            lambda *a, **kw: sent.append(a) or {"success": 1}
        )
        monkeypatch.setattr(container_mount_cleanup_task.settings_tasks, "get_container_mount_cleanup_enabled", lambda: True)
        monkeypatch.setattr(container_mount_cleanup_task.settings_tasks, "get_container_mount_cleanup_after_days", lambda: 14)

        container_mount_cleanup_task.run_mount_cleanup_once()

        assert len(sent) == 0

    def test_cleans_old_pending_mount(self, app, db_session, monkeypatch):
        """有超过 14 天的待清理记录 → 发送 clean_mount 请求并标记 cleaned。"""
        old = datetime.utcnow() - timedelta(days=20)
        row = container_mount_cleanup_repo.insert(
            container_id=1,
            container_name="old_ctr",
            machine_id=2,
            mount_path="/home/test/containers/old_ctr/",
            escalation=False,
            removed_at=old,
            session=db_session,
        )

        db_session.commit()

        sent_payloads = []
        monkeypatch.setattr(
            container_mount_cleanup_task, "send",
            lambda url, payload, timeout: sent_payloads.append(url) or {"success": 1}
        )
        # mock machine_repo to return a valid IP
        db_session.commit()

        monkeypatch.setattr(
            container_mount_cleanup_task.machine_repo,
            "get_machine_ip_by_id",
            lambda mid, **kwargs: "10.0.0.2"
        )
        monkeypatch.setattr(container_mount_cleanup_task.settings_tasks, "get_container_mount_cleanup_enabled", lambda: True)
        monkeypatch.setattr(container_mount_cleanup_task.settings_tasks, "get_container_mount_cleanup_after_days", lambda: 14)

        container_mount_cleanup_task.run_mount_cleanup_once()

        assert len(sent_payloads) == 1
        assert "/clean_mount" in sent_payloads[0]

        db_session.expire_all()
        # verify row is marked cleaned
        from ...models.container_mount_cleanup import ContainerMountCleanup
        refreshed = db_session.get(ContainerMountCleanup, row.id)
        assert refreshed.cleaned_at is not None

    def test_skips_recent_removals(self, app, db_session, monkeypatch):
        """删除不到 14 天 → 不触发清理。"""
        recent = datetime.utcnow() - timedelta(days=3)
        container_mount_cleanup_repo.insert(
            container_id=1,
            container_name="recent_ctr",
            machine_id=2,
            mount_path="/home/test/containers/recent/",
            escalation=False,
            removed_at=recent,
            session=db_session,
        )

        sent = []
        monkeypatch.setattr(
            container_mount_cleanup_task, "send",
            lambda *a, **kw: sent.append(a) or {"success": 1}
        )
        monkeypatch.setattr(container_mount_cleanup_task.settings_tasks, "get_container_mount_cleanup_enabled", lambda: True)
        monkeypatch.setattr(container_mount_cleanup_task.settings_tasks, "get_container_mount_cleanup_after_days", lambda: 14)

        container_mount_cleanup_task.run_mount_cleanup_once()

        assert len(sent) == 0

    def test_continues_on_single_failure(self, app, db_session, monkeypatch):
        """某条记录清理失败 → 不标记 cleaned → 继续处理下一条。"""
        from ...models.container_mount_cleanup import ContainerMountCleanup

        old = datetime.utcnow() - timedelta(days=20)
        r1 = container_mount_cleanup_repo.insert(
            container_id=1, container_name="c1",
            machine_id=1, mount_path="/home/x/containers/c1/",
            escalation=False, removed_at=old,
            session=db_session,
        )
        r2 = container_mount_cleanup_repo.insert(
            container_id=2, container_name="c2",
            machine_id=2, mount_path="/home/x/containers/c2/",
            escalation=False, removed_at=old,
            session=db_session,
        )

        db_session.commit()

        call_count = [0]

        def _fail_first(url, payload, timeout):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("node unreachable")
            return {"success": 1}

        monkeypatch.setattr(
            container_mount_cleanup_task, "send", _fail_first
        )
        monkeypatch.setattr(
            container_mount_cleanup_task.machine_repo,
            "get_machine_ip_by_id",
            lambda mid, **kwargs: "10.0.0.1"
        )
        monkeypatch.setattr(container_mount_cleanup_task.settings_tasks, "get_container_mount_cleanup_enabled", lambda: True)
        monkeypatch.setattr(container_mount_cleanup_task.settings_tasks, "get_container_mount_cleanup_after_days", lambda: 14)

        container_mount_cleanup_task.run_mount_cleanup_once()

        db_session.expire_all()
        # r1 still not cleaned
        r1_refreshed = db_session.get(ContainerMountCleanup, r1.id)
        assert r1_refreshed.cleaned_at is None
        # r2 cleaned
        r2_refreshed = db_session.get(ContainerMountCleanup, r2.id)
        assert r2_refreshed.cleaned_at is not None

    def test_skips_when_machine_not_found(self, app, db_session, monkeypatch):
        """机器不存在 → 跳过该条记录，不崩溃。"""
        old = datetime.utcnow() - timedelta(days=20)
        container_mount_cleanup_repo.insert(
            container_id=1, container_name="orphan",
            machine_id=99999, mount_path="/home/x/containers/orphan/",
            escalation=False, removed_at=old,
            session=db_session,
        )

        monkeypatch.setattr(
            container_mount_cleanup_task.machine_repo,
            "get_machine_ip_by_id",
            lambda mid, **kwargs: None  # machine not found
        )
        monkeypatch.setattr(container_mount_cleanup_task.settings_tasks, "get_container_mount_cleanup_enabled", lambda: True)
        monkeypatch.setattr(container_mount_cleanup_task.settings_tasks, "get_container_mount_cleanup_after_days", lambda: 14)

        # should not raise
        container_mount_cleanup_task.run_mount_cleanup_once()
