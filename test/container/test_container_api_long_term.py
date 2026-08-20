from ...api import container_api, deps
from ...services import container_tasks


def _auth(monkeypatch, *, valid=True, user_id=1):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token: valid)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token: user_id)


def test_set_long_term_api_validates_required_fields(client, monkeypatch):
    _auth(monkeypatch)

    resp = client.post("/api/containers/set_long_term_container", json={"container_id": 1} )

    assert resp.status_code == 400


def test_set_long_term_api_maps_limit_to_409(client, monkeypatch):
    _auth(monkeypatch)

    def _raise(**kwargs):
        raise container_tasks.NodeServiceError("limit", reason="long_term_limit_reached")

    monkeypatch.setattr(container_api.container_service, "set_long_term_container", _raise)

    resp = client.post(
        "/api/containers/set_long_term_container",
        json={"container_id": 1, "is_long_term": True},
    )

    assert resp.status_code == 409
    assert resp.get_json()["error_reason"] == "long_term_limit_reached"


def test_set_long_term_api_success(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(
        container_api.container_service,
        "set_long_term_container",
        lambda **kwargs: {"container_id": 1, "is_long_term": True},
    )

    resp = client.post(
        "/api/containers/set_long_term_container",
        json={"container_id": 1, "is_long_term": True},
    )

    assert resp.status_code == 200
    assert resp.get_json()["is_long_term"] is True
