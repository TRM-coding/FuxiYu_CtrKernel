import pytest

from .. import create_app
from .conftest import TEST_CONFIG_OVERRIDES


@pytest.mark.unit
def test_app_factory_testing_does_not_start_background_tasks(monkeypatch):
    calls = []

    def _record_cleanup(*args, **kwargs):
        calls.append("cleanup")

    monkeypatch.setattr("FuxiYu_CtrKernel.schedulers.container_cleanup_task.start_container_cleanup_scheduler", _record_cleanup)

    fastapi_app = create_app(overrides=TEST_CONFIG_OVERRIDES)

    assert fastapi_app.state.config.TESTING is True
    assert fastapi_app.state.config.DISABLE_BACKGROUND_TASKS is True
    assert calls == []


@pytest.mark.db
def test_app_fixture_uses_test_database(app):
    assert app.state.config.SQLALCHEMY_DATABASE_URI.startswith("sqlite://")


@pytest.mark.api
def test_client_fixture_can_access_registered_api(client):
    response = client.get("/api/users/list_all_user_bref_information")

    assert response.status_code == 401
    data = response.json()
    assert data["error_reason"] == "invalid_token"
