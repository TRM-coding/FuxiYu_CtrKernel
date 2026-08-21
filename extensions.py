"""应用扩展与数据库会话入口。

数据库访问固定为显式 session 范式：
API dependency / scheduler / WSS 进入 service/tasks，由 service/tasks 使用
session_scope 打开工作单元，并把 session 显式传给 repo。repo 只负责
query/write/flush，不负责 commit/rollback。
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
    """SQLAlchemy 声明式模型命名空间。

    这里只提供模型声明所需的类型和元数据操作，不暴露隐式事务入口。
    """

    Model = Base

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

    create_app 读取配置后调用；测试覆盖 DATABASE_URL 时也使用同一入口。
    """

    global engine
    SessionRegistry.remove()
    engine.dispose()
    engine = _make_engine(database_url)
    SessionLocal.configure(bind=engine)


@contextmanager
def session_scope(*, commit: bool = True) -> Iterator[Session]:
    """统一的数据库工作单元。

    成功后按需提交，异常时回滚。需要组合事务时，在同一个 scope 内把
    session 显式传给多个 repo。
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
