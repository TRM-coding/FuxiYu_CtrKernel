"""Pure/entry tests for the MySQL announcement-ownership migration planner.

These tests never connect to MySQL and never run the real migration.  They
only verify metadata selection, DDL rendering, and the non-MySQL entry guard.
The real acceptance is root's external MySQL harness.
"""

import sqlite3

import pytest

from ...migrations.migrate_announcement_ownership import (
    ForeignKeyDrop,
    MigrationError,
    UnsupportedDialectError,
    build_plan,
    ensure_supported_dialect,
    migrate,
    render_plan,
)


class _FakeInspector:
    def __init__(self, *, columns, foreign_keys):
        self._columns = columns
        self._foreign_keys = foreign_keys

    def get_table_names(self):
        return ["users", "announcements", "announcement_templates", "announcement_drafts"]

    def get_columns(self, table):
        return [{"name": name} for name in self._columns[table]]

    def get_foreign_keys(self, table):
        return list(self._foreign_keys.get(table, ()))


class _FakePreparer:
    @staticmethod
    def quote(name):
        return f"`{name}`"


def _fk(
    name,
    column="created_by",
    *,
    referred="users",
    ondelete=None,
    constrained_columns=None,
    referred_columns=None,
):
    return {
        "name": name,
        "constrained_columns": list(constrained_columns or [column]),
        "referred_table": referred,
        "referred_columns": list(referred_columns or ["id"]),
        "options": {"ondelete": ondelete} if ondelete else {},
    }


def _inspector(*, draft_cascade=False):
    columns = {
        "users": {"id"},
        "announcements": {"id", "title", "content", "created_by", "template_id"},
        "announcement_templates": {"id", "name", "created_by"},
        "announcement_drafts": {"id", "title", "created_by"},
    }
    fks = {
        "announcements": [
            _fk("announcements_ibfk_1"),
            _fk("announcements_ibfk_2", column="template_id", referred="announcement_templates"),
        ],
        "announcement_templates": [
            _fk("q68_announcement_templates_explicit_author"),
        ],
        "announcement_drafts": [
            _fk(
                "q68_announcement_drafts_explicit_author",
                ondelete="CASCADE" if draft_cascade else None,
            )
        ],
    }
    return _FakeInspector(columns=columns, foreign_keys=fks)


def _inspector_with_fks(table, foreign_keys):
    base = _inspector()
    return _FakeInspector(
        columns=base._columns,
        foreign_keys={**base._foreign_keys, table: foreign_keys},
    )


def test_planner_selects_auto_and_explicit_fk_names():
    plan = build_plan(_inspector(), "mysql")

    assert plan.drop_foreign_keys == (
        ForeignKeyDrop("announcements", "announcements_ibfk_1"),
        ForeignKeyDrop(
            "announcement_templates", "q68_announcement_templates_explicit_author"
        ),
        ForeignKeyDrop(
            "announcement_drafts", "q68_announcement_drafts_explicit_author"
        ),
    )
    assert plan.drop_columns == ("announcements", "announcement_templates")
    assert plan.add_draft_cascade is True


def test_planner_compiles_mysql_ddl_and_rejects_other_dialects():
    plan = build_plan(_inspector(), "mariadb")
    statements = render_plan(plan, _FakePreparer())
    rendered = "\n".join(statements)

    assert "DROP FOREIGN KEY `q68_announcement_templates_explicit_author`" in rendered
    assert "DROP FOREIGN KEY `q68_announcement_drafts_explicit_author`" in rendered
    assert "ALTER TABLE `announcements` DROP COLUMN `created_by`" in rendered
    assert "ALTER TABLE `announcement_templates` DROP COLUMN `created_by`" in rendered
    assert "ON DELETE CASCADE" in rendered
    assert "fk_announcement_drafts_created_by" in rendered
    assert "template_id" not in rendered
    assert ensure_supported_dialect("mariadb") == "mariadb"
    with pytest.raises(UnsupportedDialectError):
        ensure_supported_dialect("postgresql")
    with pytest.raises(MigrationError):
        build_plan(_inspector(), "sqlite")

    bad_cases = (
        (
            "composite",
            "announcements",
            [_fk("bad_composite", constrained_columns=["created_by", "other"])],
        ),
        (
            "wrong target table",
            "announcement_templates",
            [_fk("bad_table", referred="other_table")],
        ),
        (
            "wrong referred column",
            "announcements",
            [_fk("bad_column", referred_columns=["other_id"])],
        ),
        (
            "multiple",
            "announcement_drafts",
            [_fk("dup_one"), _fk("dup_two")],
        ),
        (
            "wrong target with cascade",
            "announcement_drafts",
            [_fk("bad_target_cascade", referred="other_table", ondelete="CASCADE")],
        ),
    )
    for label, table, foreign_keys in bad_cases:
        with pytest.raises(MigrationError, match="unexpected foreign key|multiple foreign keys"):
            build_plan(_inspector_with_fks(table, foreign_keys), "mysql")


def test_migrate_entry_rejects_sqlite_before_ddl(tmp_path):
    db_path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE announcements (id INTEGER PRIMARY KEY, title TEXT, created_by INTEGER)")
        conn.execute("INSERT INTO announcements (title, created_by) VALUES ('keep', 7)")
        conn.commit()
        before = conn.execute("PRAGMA table_info(announcements)").fetchall()

    with pytest.raises(UnsupportedDialectError):
        migrate(f"sqlite:///{db_path}")

    with sqlite3.connect(db_path) as conn:
        after = conn.execute("PRAGMA table_info(announcements)").fetchall()
        row = conn.execute("SELECT title, created_by FROM announcements").fetchone()
    assert after == before
    assert row == ("keep", 7)
