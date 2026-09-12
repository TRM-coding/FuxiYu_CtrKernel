from sqlalchemy.dialects import sqlite
from sqlalchemy.schema import CreateTable

from ...extensions import _enable_sqlite_strict_autoincrement
from ...models.containers import Container
from ...models.machine import Machine
from ...models.user import User


def test_single_integer_primary_keys_use_sqlite_autoincrement():
    _enable_sqlite_strict_autoincrement()

    for model in (Container, Machine, User):
        ddl = str(CreateTable(model.__table__).compile(dialect=sqlite.dialect()))
        assert "PRIMARY KEY AUTOINCREMENT" in ddl
