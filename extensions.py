# extensions.py
"""应用扩展与数据库会话入口。

新范式只保留显式 session：调用方用 session_scope 打开工作单元，并把 session
传给 repo。repo 不再隐式读取全局 session，避免 Flask app context 式依赖复活。
"""
from collections.abc import Iterator
from contextlib import contextmanager
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, scoped_session, sessionmaker
from sqlalchemy.pool import StaticPool


def _default_database_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite:///app.db")


def _make_engine(database_url: str):
    kwargs = {"future": True}
    if database_url in {"sqlite:///:memory:", "sqlite://"}:
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = StaticPool
    return create_engine(database_url, **kwargs)


engine = _make_engine(_default_database_url())
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)
SessionRegistry = scoped_session(SessionLocal)
Base = declarative_base()


class _DbNamespace:
    """SQLAlchemy 构造命名空间。

    临时保留给尚未迁完的 model 使用；它不提供隐式 current_session。
    """

    Model = Base
    session = SessionRegistry

    def __getattr__(self, name: str):
        import sqlalchemy as sa
        from sqlalchemy import orm

        if hasattr(sa, name):
            return getattr(sa, name)
        if hasattr(orm, name):
            return getattr(orm, name)
        raise AttributeError(name)

    def create_all(self) -> None:
        Base.metadata.create_all(bind=engine)

    def drop_all(self) -> None:
        Base.metadata.drop_all(bind=engine)


db = _DbNamespace()


def configure_database(database_url: str) -> None:
    """配置数据库连接。

    create_app 在读取配置后调用一次；测试覆盖 DATABASE_URL 时也走同一入口。
    """
    global engine
    SessionRegistry.remove()
    engine.dispose()
    engine = _make_engine(database_url)
    SessionLocal.configure(bind=engine)


@contextmanager
def session_scope(*, commit: bool = True) -> Iterator[Session]:
    """统一的 repo 写入作用域。

    成功后按需提交，异常时回滚。需要组合事务时，在同一个 scope 内把 session
    显式传给多个 repo。
    """
    managed = SessionLocal()
    try:
        yield managed
        if commit:
            managed.commit()
    except Exception:
        managed.rollback()
        raise
    finally:
        managed.close()
