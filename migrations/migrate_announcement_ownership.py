"""One-off MySQL/MariaDB migration for Q68 announcement ownership.

This is deliberately NOT imported by the application and NOT part of normal
startup.  It only talks to a MySQL/MariaDB database supplied explicitly with
``--url``; every other dialect is rejected before any DDL is issued.

Usage:
    python migrations/migrate_announcement_ownership.py --url "mysql+pymysql://..."
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

SUPPORTED_DIALECTS = frozenset({"mysql", "mariadb"})
DRAFT_FK_NAME = "fk_announcement_drafts_created_by"
OWNER_COLUMN = "created_by"
USER_TABLE = "users"
USER_ID_COLUMN = "id"


class MigrationError(RuntimeError):
    """The target schema cannot be migrated safely."""


class UnsupportedDialectError(MigrationError):
    """The migration is only defined for MySQL/MariaDB."""


@dataclass(frozen=True)
class ForeignKeyDrop:
    table: str
    name: str


@dataclass(frozen=True)
class MigrationPlan:
    dialect: str
    drop_foreign_keys: tuple[ForeignKeyDrop, ...] = ()
    drop_columns: tuple[str, ...] = ()
    add_draft_cascade: bool = False
    no_op: bool = False


def ensure_supported_dialect(dialect_name: str) -> str:
    normalized = str(dialect_name or "").lower()
    if normalized not in SUPPORTED_DIALECTS:
        raise UnsupportedDialectError(
            "announcement ownership migration supports only MySQL/MariaDB; "
            f"got {dialect_name!r}"
        )
    return normalized


def _created_by_fks(inspector: Any, table: str) -> list[dict[str, Any]]:
    matches = [
        fk
        for fk in inspector.get_foreign_keys(table)
        if OWNER_COLUMN in (fk.get("constrained_columns") or [])
    ]
    for fk in matches:
        constrained = list(fk.get("constrained_columns") or [])
        referred_table = fk.get("referred_table")
        referred_columns = list(fk.get("referred_columns") or [])
        if (
            constrained != [OWNER_COLUMN]
            or referred_table != USER_TABLE
            or referred_columns != [USER_ID_COLUMN]
        ):
            name = fk.get("name") or "<unnamed>"
            raise MigrationError(
                f"{table}.{OWNER_COLUMN} unexpected foreign key {name!r}: "
                f"{constrained} -> {referred_table}.{referred_columns}; "
                f"expected [{OWNER_COLUMN}] -> {USER_TABLE}.[{USER_ID_COLUMN}]"
            )
    if len(matches) > 1:
        names = ", ".join(str(fk.get("name") or "<unnamed>") for fk in matches)
        raise MigrationError(
            f"{table}.{OWNER_COLUMN} has multiple foreign keys: {names}"
        )
    return matches


def _fk_name(table: str, fk: dict[str, Any]) -> str:
    name = fk.get("name")
    if not name:
        raise MigrationError(f"{table}.{OWNER_COLUMN} foreign key has no name")
    return str(name)


def _is_cascade(fk: dict[str, Any]) -> bool:
    rule = (fk.get("options") or {}).get("ondelete")
    return str(rule or "").upper() == "CASCADE"


def build_plan(inspector: Any, dialect_name: str) -> MigrationPlan:
    """Inspect real metadata and return the minimum MySQL/MariaDB DDL plan."""

    dialect = ensure_supported_dialect(dialect_name)
    tables = set(inspector.get_table_names())
    required = {
        "users",
        "announcements",
        "announcement_templates",
        "announcement_drafts",
    }
    missing = sorted(required - tables)
    if missing:
        raise MigrationError(f"required table(s) missing: {', '.join(missing)}")

    columns = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in required
    }
    drops: list[ForeignKeyDrop] = []
    drop_columns: list[str] = []

    for table in ("announcements", "announcement_templates"):
        if OWNER_COLUMN not in columns[table]:
            continue
        for fk in _created_by_fks(inspector, table):
            drops.append(ForeignKeyDrop(table=table, name=_fk_name(table, fk)))
        drop_columns.append(table)

    if OWNER_COLUMN not in columns["announcement_drafts"]:
        raise MigrationError("announcement_drafts.created_by is missing")
    draft_fks = _created_by_fks(inspector, "announcement_drafts")
    add_draft_cascade = not (len(draft_fks) == 1 and _is_cascade(draft_fks[0]))
    if add_draft_cascade:
        for fk in draft_fks:
            drops.append(
                ForeignKeyDrop(table="announcement_drafts", name=_fk_name("announcement_drafts", fk))
            )

    no_op = not drops and not drop_columns and not add_draft_cascade
    return MigrationPlan(
        dialect=dialect,
        drop_foreign_keys=tuple(drops),
        drop_columns=tuple(drop_columns),
        add_draft_cascade=add_draft_cascade,
        no_op=no_op,
    )


def render_plan(plan: MigrationPlan, preparer: Any) -> list[str]:
    q = preparer.quote
    statements: list[str] = []
    for fk in plan.drop_foreign_keys:
        statements.append(f"ALTER TABLE {q(fk.table)} DROP FOREIGN KEY {q(fk.name)}")
    for table in plan.drop_columns:
        statements.append(f"ALTER TABLE {q(table)} DROP COLUMN {q(OWNER_COLUMN)}")
    if plan.add_draft_cascade:
        statements.append(
            f"ALTER TABLE {q('announcement_drafts')} "
            f"ADD CONSTRAINT {q(DRAFT_FK_NAME)} "
            f"FOREIGN KEY ({q(OWNER_COLUMN)}) "
            f"REFERENCES {q(USER_TABLE)} ({q(USER_ID_COLUMN)}) "
            "ON DELETE CASCADE"
        )
    return statements


def migrate(url: Any) -> dict[str, Any]:
    """Run the migration against an explicit database URL.

    The dialect is checked before the first connection/DDL.  The function is
    idempotent: an already-migrated schema returns a no-op report.
    """

    engine: Engine = create_engine(url, future=True)
    try:
        dialect = engine.dialect.name
        ensure_supported_dialect(dialect)
        plan = build_plan(inspect(engine), dialect)
        statements = render_plan(plan, engine.dialect.identifier_preparer)
        if statements:
            with engine.begin() as connection:
                for statement in statements:
                    connection.exec_driver_sql(statement)
        return {
            "dialect": plan.dialect,
            "no_op": plan.no_op,
            "executed": len(statements),
            "drop_foreign_keys": [f"{fk.table}.{fk.name}" for fk in plan.drop_foreign_keys],
            "drop_columns": list(plan.drop_columns),
            "add_draft_cascade": plan.add_draft_cascade,
        }
    finally:
        engine.dispose()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate Q68 announcement ownership on MySQL/MariaDB (explicit one-off)."
    )
    parser.add_argument("--url", required=True, help="SQLAlchemy MySQL/MariaDB database URL")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = migrate(args.url)
    except Exception as exc:
        print(f"migration failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
