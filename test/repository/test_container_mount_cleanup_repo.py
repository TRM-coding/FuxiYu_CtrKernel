"""container_mount_cleanup_repo 单元测试。"""

from datetime import datetime, timedelta

from ...models.container_mount_cleanup import ContainerMountCleanup
from ...repositories import container_mount_cleanup_repo


class TestMountCleanupRepo:
    def test_insert_creates_record(self, app, db_session):
        row = container_mount_cleanup_repo.insert(
            container_id=1,
            container_name="test_ctr",
            machine_id=2,
            mount_path="/home/test/containers/test_ctr/",
            escalation=False,
            session=db_session,
        )
        assert row.id is not None
        assert row.container_name == "test_ctr"
        assert row.escalation is False
        assert row.cleaned_at is None

    def test_insert_with_escalation_and_cleaned(self, app, db_session):
        now = datetime.utcnow()
        row = container_mount_cleanup_repo.insert(
            container_id=10,
            container_name="esc_ctr",
            machine_id=3,
            mount_path="/home/esc/containers/esc_ctr/",
            escalation=True,
            cleaned_at=now,
            session=db_session,
        )
        assert row.escalation is True
        assert row.cleaned_at == now

    def test_list_pending_returns_only_old_uncleaned(self, app, db_session):
        old = datetime.utcnow() - timedelta(days=20)
        recent = datetime.utcnow() - timedelta(days=3)
        cutoff = datetime.utcnow() - timedelta(days=14)

        # old, not cleaned, not escalation → should be returned
        r1 = container_mount_cleanup_repo.insert(
            container_id=1, container_name="old",
            machine_id=1, mount_path="/home/x/containers/old/",
            escalation=False, removed_at=old,
            session=db_session,
        )
        # old but already cleaned → should NOT be returned
        container_mount_cleanup_repo.insert(
            container_id=2, container_name="cleaned",
            machine_id=1, mount_path="/home/x/containers/cleaned/",
            escalation=False, removed_at=old, cleaned_at=datetime.utcnow(),
            session=db_session,
        )
        # old but escalation → should NOT be returned
        container_mount_cleanup_repo.insert(
            container_id=3, container_name="esc",
            machine_id=1, mount_path="/home/x/containers/esc/",
            escalation=True, removed_at=old, cleaned_at=datetime.utcnow(),
            session=db_session,
        )
        # recent → should NOT be returned
        container_mount_cleanup_repo.insert(
            container_id=4, container_name="recent",
            machine_id=1, mount_path="/home/x/containers/recent/",
            escalation=False, removed_at=recent,
            session=db_session,
        )

        pending = container_mount_cleanup_repo.list_pending(cutoff, session=db_session)
        assert len(pending) == 1
        assert pending[0].id == r1.id

    def test_list_pending_respects_limit(self, app, db_session):
        old = datetime.utcnow() - timedelta(days=20)
        cutoff = datetime.utcnow() - timedelta(days=14)
        for i in range(5):
            container_mount_cleanup_repo.insert(
                container_id=100 + i, container_name=f"c{i}",
                machine_id=1, mount_path=f"/home/x/containers/c{i}/",
                escalation=False, removed_at=old,
                session=db_session,
            )

        pending = container_mount_cleanup_repo.list_pending(cutoff, limit=3, session=db_session)
        assert len(pending) == 3

    def test_mark_cleaned_sets_timestamp(self, app, db_session):
        row = container_mount_cleanup_repo.insert(
            container_id=1, container_name="x",
            machine_id=1, mount_path="/home/x/containers/x/",
            escalation=False,
            session=db_session,
        )
        assert row.cleaned_at is None

        result = container_mount_cleanup_repo.mark_cleaned(row.id, session=db_session)
        assert result is True

        # re-fetch
        refreshed = db_session.get(ContainerMountCleanup, row.id)
        assert refreshed.cleaned_at is not None

    def test_mark_cleaned_returns_false_when_not_found(self, app, db_session):
        assert container_mount_cleanup_repo.mark_cleaned(99999, session=db_session) is False
