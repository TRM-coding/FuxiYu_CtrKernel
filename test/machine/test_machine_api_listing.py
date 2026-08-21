from types import SimpleNamespace

from ...api import machine_api, deps


def test_list_machine_bref_resolves_token_from_header(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: True)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: 7)
    def _list(page_number, page_size, user_id=None):
        captured["user_id"] = user_id
        return [], 0

    monkeypatch.setattr(machine_api.machine_service, "List_all_machine_bref_information", _list)

    resp = client.post("/api/machines/list_all_machine_bref_information", json={})

    assert resp.status_code == 200
    assert captured["user_id"] == 7


def test_list_machine_bref_resolves_token_from_cookie(client, monkeypatch):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: True)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: 7)
    monkeypatch.setattr(machine_api.machine_service, "List_all_machine_bref_information", lambda page_number, page_size, user_id=None: ([], 0))

    resp = client.post("/api/machines/list_all_machine_bref_information", json={})

    assert resp.status_code == 200


def test_list_machine_bref_requires_token(client, monkeypatch):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: False)

    resp = client.post("/api/machines/list_all_machine_bref_information", json={})

    assert resp.status_code == 401


def test_list_machine_bref_success_passes_user_id_to_service(client, monkeypatch):
    captured = {}
    machine = SimpleNamespace(id=1, machine_name="m", machine_ip="127.0.0.1", machine_type="GPU", machine_status="online")
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: True)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: 42)

    def _list(page_number, page_size, user_id=None):
        captured.update(page_number=page_number, page_size=page_size, user_id=user_id)
        return [machine], 1

    monkeypatch.setattr(machine_api.machine_service, "List_all_machine_bref_information", _list)

    resp = client.post(
        "/api/machines/list_all_machine_bref_information",
        json={"page_number": 2, "page_size": 5}
    )

    assert resp.status_code == 200
    assert captured == {"page_number": 2, "page_size": 5, "user_id": 42}
    assert resp.json()["machines"][0]["machine_name"] == "m"
