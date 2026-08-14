import os
import tempfile
from pathlib import Path

import pytest

from .. import create_app
from ..extensions import db


TEST_CONFIG_OVERRIDES = {
    "TESTING": True,
    "DISABLE_BACKGROUND_TASKS": True,
    "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    "SQLALCHEMY_TRACK_MODIFICATIONS": False,
    "SQLALCHEMY_ENGINE_OPTIONS": {},  # 清除 MySQL 专属的 init_command
    "WTF_CSRF_ENABLED": False,
}

TEST_AUTH_TOKEN = "test-token"
TEST_OPERATOR_TOKEN = "test-operator-token"


def _assert_sqlite_database_uri(app):
    uri = str(app.config.get("SQLALCHEMY_DATABASE_URI", ""))
    if not uri.startswith("sqlite://"):
        raise RuntimeError(f"Refusing to run tests against non-SQLite database URI: {uri}")

@pytest.fixture(scope="session", autouse=True)
def _ensure_db():
    db.create_all()

@pytest.fixture(scope="session", autouse=True)
def _safe_test_environment():
    with tempfile.TemporaryDirectory(prefix="fuxiyu-ctrl-test-") as tmpdir:
        old_env = {}
        updates = {
            "DATABASE_URL": TEST_CONFIG_OVERRIDES["SQLALCHEMY_DATABASE_URI"],
            "CTRL_LOG_DIR": str(Path(tmpdir) / "logs"),
            "DISABLE_BACKGROUND_TASKS": "1",
        }
        for key, value in updates.items():
            old_env[key] = os.environ.get(key)
            os.environ[key] = value
        yield
        for key, old_value in old_env.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


@pytest.fixture(scope="session")
def app():
    app = create_app(overrides=TEST_CONFIG_OVERRIDES)
    _assert_sqlite_database_uri(app)
    with app.app_context():
        from .. import models  # noqa: F401

        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def db_session(app):
    _assert_sqlite_database_uri(app)
    with app.app_context():
        try:
            yield db.session
        finally:
            db.session.remove()
            db.drop_all()
            db.create_all()


@pytest.fixture(autouse=True)
def mock_external_services(monkeypatch, request):
    if request.node.get_closest_marker("integration"):
        yield
        return

    def _blocked_post(*args, **kwargs):
        raise AssertionError("Real HTTP requests are blocked in the safe pytest suite")

    def _mail_send(*args, **kwargs):
        to = kwargs.get("to")
        if to is None and args:
            to = args[0]
        recipients = [to] if isinstance(to, str) else list(to or [])
        return {"ok": True, "to": recipients, "mode": "pytest-mock"}

    def _mail_send_batch(messages, **kwargs):
        results = []
        for m in messages:
            to = m.get("to", "")
            recips = [to] if isinstance(to, str) else list(to)
            results.append({"ok": True, "to": recips, "mode": "pytest-mock"})
        return results

    def _fake_thread(*args, **kwargs):
        class _Thread:
            def is_alive(self):
                return True

        return _Thread()

    monkeypatch.setattr("requests.post", _blocked_post)
    monkeypatch.setattr("smtplib.SMTP", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Real SMTP is blocked in the safe pytest suite")))
    monkeypatch.setattr("smtplib.SMTP_SSL", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Real SMTP_SSL is blocked in the safe pytest suite")))
    monkeypatch.setattr("FuxiYu_CtrKernel.utils.mail.send", _mail_send)
    monkeypatch.setattr("FuxiYu_CtrKernel.utils.mail.send_batch", _mail_send_batch)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.user_tasks.send_mail", _mail_send)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.announcement_tasks.send_mail", _mail_send)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.announcement_tasks.send_batch", _mail_send_batch)
    monkeypatch.setattr("FuxiYu_CtrKernel.schemas.container_cleanup_task.send_mail", _mail_send)
    monkeypatch.setattr("FuxiYu_CtrKernel.utils.heartbeat.start_machine_maintenance_transition_heartbeat", _fake_thread)
    monkeypatch.setattr("FuxiYu_CtrKernel.utils.heartbeat.container_starting_status_heartbeat", _fake_thread)
    monkeypatch.setattr("FuxiYu_CtrKernel.utils.heartbeat.container_stopping_status_heartbeat", _fake_thread)
    monkeypatch.setattr("FuxiYu_CtrKernel.utils.heartbeat.container_restart_status_heartbeat", _fake_thread)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.machine_tasks.start_machine_maintenance_transition_heartbeat", _fake_thread)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.container_tasks.container_starting_status_heartbeat", _fake_thread)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.container_tasks.container_stopping_status_heartbeat", _fake_thread)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.container_tasks.container_restart_status_heartbeat", _fake_thread)
    yield
