from types import SimpleNamespace

import pytest

from ...api import user_api, deps


def _valid_token(monkeypatch):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token: True)


def test_get_user_detail_requires_token(client, monkeypatch):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token: False)

    resp = client.get("/api/users/get_user_detail_information?user_id=1")

    assert resp.status_code == 401


def test_get_user_detail_requires_user_id(client, monkeypatch):
    _valid_token(monkeypatch)

    resp = client.get("/api/users/get_user_detail_information" )

    assert resp.status_code == 400
    assert resp.get_json()["error_reason"] == "missing_user_id"


def test_get_user_detail_not_found(client, monkeypatch):
    _valid_token(monkeypatch)
    monkeypatch.setattr(user_api.user_tasks, "Get_user_detail_information", lambda user_id: None)

    resp = client.get("/api/users/get_user_detail_information?user_id=1" )

    assert resp.status_code == 404


def test_get_user_detail_success(client, monkeypatch):
    _valid_token(monkeypatch)
    info = SimpleNamespace(dict=lambda: {"user_id": 1, "username": "u"})
    monkeypatch.setattr(user_api.user_tasks, "Get_user_detail_information", lambda user_id: info)

    resp = client.get("/api/users/get_user_detail_information?user_id=1" )

    assert resp.status_code == 200
    assert resp.get_json()["user_info"]["username"] == "u"


def test_list_users_requires_token(client, monkeypatch):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token: False)

    resp = client.get("/api/users/list_all_user_bref_information")

    assert resp.status_code == 401


def test_list_users_success(client, monkeypatch):
    _valid_token(monkeypatch)
    user = SimpleNamespace(dict=lambda: {"user_id": 1, "username": "u"})
    monkeypatch.setattr(user_api.user_tasks, "List_all_user_bref_information", lambda page_number, page_size: [user])

    resp = client.get("/api/users/list_all_user_bref_information" )

    assert resp.status_code == 200
    assert resp.get_json()["users"] == [{"user_id": 1, "username": "u"}]


def test_list_users_task_failure(client, monkeypatch):
    _valid_token(monkeypatch)
    monkeypatch.setattr(user_api.user_tasks, "List_all_user_bref_information", lambda page_number, page_size: (_ for _ in ()).throw(RuntimeError("boom")))

    resp = client.get("/api/users/list_all_user_bref_information" )

    assert resp.status_code == 500
    assert resp.get_json()["error_reason"] == "list_failed"


def test_change_password_success(client, monkeypatch):
    _valid_token(monkeypatch)
    monkeypatch.setattr(deps.user_repo, "get_by_id", lambda user_id: SimpleNamespace(id=user_id))
    monkeypatch.setattr(user_api.user_tasks, "Change_password", lambda user, old, new: True)

    resp = client.post("/api/users/change_password", json={"user_id": 1, "old_password": "old", "new_password": "new"} )

    assert resp.status_code == 200


def test_change_password_wrong_old_password(client, monkeypatch):
    _valid_token(monkeypatch)
    monkeypatch.setattr(deps.user_repo, "get_by_id", lambda user_id: SimpleNamespace(id=user_id))
    monkeypatch.setattr(user_api.user_tasks, "Change_password", lambda user, old, new: False)

    resp = client.post("/api/users/change_password", json={"user_id": 1, "old_password": "bad", "new_password": "new"} )

    assert resp.status_code == 400
    assert resp.get_json()["error_reason"] == "old_password_incorrect"


def test_delete_user_success(client, monkeypatch):
    _valid_token(monkeypatch)
    monkeypatch.setattr(user_api.user_tasks, "Delete_user", lambda user_id: True)

    resp = client.post("/api/users/delete_user", json={"user_id": 1} )

    assert resp.status_code == 200


def test_delete_user_wild_containers(client, monkeypatch):
    _valid_token(monkeypatch)

    def _raise(user_id):
        exc = Exception("wild")
        exc.wild_containers = [144]
        raise exc

    monkeypatch.setattr(user_api.user_tasks, "Delete_user", _raise)

    resp = client.post("/api/users/delete_user", json={"user_id": 1} )

    assert resp.status_code == 400
    assert resp.get_json()["wild_containers"] == [144]


def test_update_user_success(client, monkeypatch):
    _valid_token(monkeypatch)
    monkeypatch.setattr(user_api.user_tasks, "Update_user", lambda user_id, **fields: SimpleNamespace(username="updated"))

    resp = client.post("/api/users/update_user", json={"user_id": 1, "fields": {"username": "updated"}} )

    assert resp.status_code == 200
    assert resp.get_json()["user"] == "updated"


@pytest.mark.parametrize("reason", ["invalid_username", "no_none_ascii"])
def test_update_user_validation_errors(client, monkeypatch, reason):
    _valid_token(monkeypatch)
    monkeypatch.setattr(user_api.user_tasks, "Update_user", lambda user_id, **fields: (_ for _ in ()).throw(ValueError(reason)))

    resp = client.post("/api/users/update_user", json={"user_id": 1, "fields": {"username": "bad"}} )

    assert resp.status_code == 400
    assert resp.get_json()["error_reason"] == reason
