from ...blueprints import container_api
from ...models.containers import Container
from ...services import container_tasks
from ..factories import create_container


def _auth(monkeypatch, *, valid=True, user_id=1):
    monkeypatch.setattr(container_api.authentications_repo, "is_token_valid", lambda token: valid)
    monkeypatch.setattr(container_api.authentications_repo, "get_user_id_by_token", lambda token: user_id)


def test_get_container_detail_api_not_found(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(
        container_api.container_service,
        "get_container_detail_information",
        lambda **kwargs: (_ for _ in ()).throw(ValueError("missing")),
    )

    resp = client.post("/api/containers/get_container_detail_information", json={"container_id": 1} )

    assert resp.status_code == 404


def test_get_container_detail_api_success(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(
        container_api.container_service,
        "get_container_detail_information",
        lambda **kwargs: {"container_id": 1, "container_name": "c"},
    )

    resp = client.post("/api/containers/get_container_detail_information", json={"container_id": 1} )

    assert resp.status_code == 200
    assert resp.get_json()["container_info"]["container_name"] == "c"


def test_container_status_api_missing_fields_returns_none(client, monkeypatch):
    _auth(monkeypatch)

    resp = client.post("/api/containers/container_status", json={} )

    assert resp.status_code == 200
    assert resp.get_json()["container_status"] is None


def test_container_status_api_success(client, monkeypatch, db_session):
    _auth(monkeypatch)
    container = create_container()

    resp = client.post(
        "/api/containers/container_status",
        json={"machine_id": container.machine_id, "container_name": container.name},
        ,
    )

    assert resp.status_code == 200
    assert resp.get_json()["container_status"] == container.container_status.value


def test_refresh_last_ssh_login_time_api_node_endpoint_missing_returns_502(client, monkeypatch, db_session):
    _auth(monkeypatch)
    container = create_container()

    def _raise(container_id):
        raise container_tasks.NodeServiceError("endpoint missing", reason="node_endpoint_not_found")

    monkeypatch.setattr(container_api.container_service, "get_container_last_ssh_login_time", _raise)

    resp = client.post(
        "/api/containers/refresh_last_ssh_login_time",
        json={"container_id": container.id},
        ,
    )

    assert resp.status_code == 502


def test_refresh_last_ssh_login_time_api_success(client, monkeypatch, db_session):
    _auth(monkeypatch)
    container = create_container()
    monkeypatch.setattr(container_api.container_service, "get_container_last_ssh_login_time", lambda container_id: "2026-05-25T10:00:00")

    resp = client.post(
        "/api/containers/refresh_last_ssh_login_time",
        json={"container_id": container.id},
        ,
    )

    assert resp.status_code == 200
    assert resp.get_json()["last_ssh_login_time"] == "2026-05-25T10:00:00"


def test_list_container_bref_api_includes_long_term_limit_when_user_filter_present(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(
        container_api.container_service,
        "list_all_container_bref_information",
        lambda **kwargs: {
            "containers": [],
            "total_page": 1,
            "long_term_container_remaining": 0,
            "long_term_container_limit": 1,
        },
    )

    resp = client.post(
        "/api/containers/list_all_container_bref_information",
        json={"user_id": 1, "page_number": 0, "page_size": 10},
        ,
    )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["long_term_container_remaining"] == 0
    assert payload["long_term_container_limit"] == 1
