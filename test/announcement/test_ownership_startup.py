"""Startup-path boundary: _ensure_announcement_schema never drops ownership columns."""

from sqlalchemy import inspect, text

from ... import _ensure_announcement_schema


def test_ensure_announcement_schema_does_not_drop_creator_columns(db_session, monkeypatch):
    # Lightweight schema mutation: this is not a legacy SQLite migration fixture.
    db_session.execute(text("ALTER TABLE announcements ADD COLUMN created_by INTEGER"))
    db_session.execute(
        text("ALTER TABLE announcement_templates ADD COLUMN created_by INTEGER")
    )
    db_session.commit()

    from ...migrations import migrate_announcement_ownership

    calls = []

    def _must_not_run(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("startup path must not call the explicit migration")

    monkeypatch.setattr(migrate_announcement_ownership, "migrate", _must_not_run)

    _ensure_announcement_schema()

    inspector = inspect(db_session.get_bind())
    announcement_columns = {
        column["name"] for column in inspector.get_columns("announcements")
    }
    template_columns = {
        column["name"] for column in inspector.get_columns("announcement_templates")
    }
    assert "created_by" in announcement_columns
    assert "created_by" in template_columns
    assert calls == []
