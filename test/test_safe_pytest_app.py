import pytest

from .. import create_app
from .conftest import TEST_CONFIG_OVERRIDES


@pytest.mark.unit
def test_app_factory_testing_does_not_start_background_tasks(monkeypatch):
    calls = []

    def _record_ssh(*args, **kwargs):
        calls.append("ssh")

    def _record_cleanup(*args, **kwargs):
        calls.append("cleanup")

    monkeypatch.setattr("FuxiYu_CtrKernel.start_container_ssh_refresh_scheduler", _record_ssh)
    monkeypatch.setattr("FuxiYu_CtrKernel.start_container_cleanup_scheduler", _record_cleanup)

    app = create_app(overrides=TEST_CONFIG_OVERRIDES)

    assert app.config["TESTING"] is True
    assert app.config["DISABLE_BACKGROUND_TASKS"] is True
    assert calls == []


@pytest.mark.db
def test_app_fixture_uses_test_database(app):
    assert app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite://")


@pytest.mark.api
def test_client_fixture_can_access_registered_blueprints(client):
    response = client.get("/api/users/list_all_user_bref_information")

    assert response.status_code == 401
    data = response.get_json()
    assert data["error_reason"] == "invalid_token"
