from types import SimpleNamespace

import pytest

from ...api import user_api, deps

pytestmark = pytest.mark.usefixtures("ensure_auth_users")


def _valid_token(monkeypatch, user_id=1):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: True)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: user_id)


def test_get_user_detail_requires_token(client, monkeypatch):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: False)

    resp = client.get("/api/users/get_user_detail_information?user_id=1")

    assert resp.status_code == 401


def test_get_user_detail_requires_user_id(client, monkeypatch):
    _valid_token(monkeypatch)

    resp = client.get("/api/users/get_user_detail_information" )

    assert resp.status_code == 400
    assert resp.json()["error_reason"] == "invalid_resource_id"


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
    assert resp.json()["user_info"]["username"] == "u"


def test_list_users_requires_token(client, monkeypatch):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: False)

    resp = client.get("/api/users/list_all_user_bref_information")

    assert resp.status_code == 401


def test_list_users_success(client, monkeypatch):
    _valid_token(monkeypatch)
    user = SimpleNamespace(dict=lambda: {"user_id": 1, "username": "u"})
    captured = {}

    def _list(page_number, page_size, user_search=None, viewer_user_id=None):
        captured.update(page_number=page_number, page_size=page_size, user_search=user_search, viewer_user_id=viewer_user_id)
        return [user]

    monkeypatch.setattr(user_api.user_tasks, "List_all_user_bref_information", _list)

    resp = client.get("/api/users/list_all_user_bref_information?user_search=alice" )

    assert resp.status_code == 200
    assert captured["user_search"] == "alice"
    assert resp.json()["users"] == [{"user_id": 1, "username": "u"}]


def test_list_users_task_failure(client, monkeypatch):
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_entity", lambda uid, code: True)

    _valid_token(monkeypatch)
    monkeypatch.setattr(user_api.user_tasks, "List_all_user_bref_information", lambda page_number, page_size, user_search=None: (_ for _ in ()).throw(RuntimeError("boom")))

    resp = client.get("/api/users/list_all_user_bref_information" )

    assert resp.status_code == 500
    assert resp.json()["error_reason"] == "list_failed"


def test_change_password_success(client, monkeypatch):
    _valid_token(monkeypatch)
    monkeypatch.setattr(user_api.user_repo, "get_by_id", lambda user_id, **_: SimpleNamespace(id=user_id))
    monkeypatch.setattr(user_api.user_tasks, "Change_password", lambda user, old, new: True)

    resp = client.post("/api/users/change_password", json={"user_id": 1, "old_password": "old", "new_password": "new"} )

    assert resp.status_code == 200


def test_change_password_wrong_old_password(client, monkeypatch):
    _valid_token(monkeypatch)
    monkeypatch.setattr(user_api.user_repo, "get_by_id", lambda user_id, **_: SimpleNamespace(id=user_id))
    monkeypatch.setattr(user_api.user_tasks, "Change_password", lambda user, old, new: False)

    resp = client.post("/api/users/change_password", json={"user_id": 1, "old_password": "bad", "new_password": "new"} )

    assert resp.status_code == 400
    assert resp.json()["error_reason"] == "old_password_incorrect"


def test_change_password_others_requires_self(client, monkeypatch):
    """改密只能改自己：目标 user_id 与会话用户不一致 → 403，Change_password 不应被调用。"""
    _valid_token(monkeypatch, user_id=2)  # 当前用户 2，目标用户 1
    called = []
    monkeypatch.setattr(user_api.user_tasks, "Change_password", lambda user, old, new: called.append(user.id) or True)

    resp = client.post("/api/users/change_password", json={"user_id": 1, "old_password": "old", "new_password": "new"} )

    assert resp.status_code == 403
    assert resp.json()["error_reason"] == "insufficient_permission"
    assert called == []


def test_delete_user_success(client, monkeypatch):
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_entity", lambda uid, code: True)

    _valid_token(monkeypatch)
    monkeypatch.setattr(user_api.user_tasks, "Delete_user", lambda user_id: True)

    resp = client.post("/api/users/delete_user", json={"user_id": 1} )

    assert resp.status_code == 200


def test_delete_user_wild_containers(client, monkeypatch):
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_entity", lambda uid, code: True)

    _valid_token(monkeypatch)

    def _raise(user_id):
        exc = Exception("wild")
        exc.wild_containers = [144]
        raise exc

    monkeypatch.setattr(user_api.user_tasks, "Delete_user", _raise)

    resp = client.post("/api/users/delete_user", json={"user_id": 1} )

    assert resp.status_code == 400
    assert resp.json()["wild_containers"] == [144]


def test_update_user_success(client, monkeypatch):
    _valid_token(monkeypatch)
    monkeypatch.setattr(user_api.user_tasks, "Update_user", lambda user_id, **fields: SimpleNamespace(username="updated"))

    resp = client.post("/api/users/update_user", json={"user_id": 1, "fields": {"username": "updated"}} )

    assert resp.status_code == 200
    assert resp.json()["user"] == "updated"


def test_update_user_blank_graduation_year_does_not_block_other_updates(client, monkeypatch):
    _valid_token(monkeypatch)
    captured = {}

    def _update(user_id, **fields):
        captured.update(fields)
        return SimpleNamespace(username="updated")

    monkeypatch.setattr(user_api.user_tasks, "Update_user", _update)

    resp = client.post(
        "/api/users/update_user",
        json={"user_id": 1, "fields": {"username": "updated", "graduation_year": ""}},
    )

    assert resp.status_code == 200
    assert captured == {"username": "updated"}


@pytest.mark.parametrize("reason", ["invalid_username", "no_none_ascii"])
def test_update_user_validation_errors(client, monkeypatch, reason):
    _valid_token(monkeypatch)
    monkeypatch.setattr(user_api.user_tasks, "Update_user", lambda user_id, **fields: (_ for _ in ()).throw(ValueError(reason)))

    resp = client.post("/api/users/update_user", json={"user_id": 1, "fields": {"username": "bad"}} )

    assert resp.status_code == 400
    assert resp.json()["error_reason"] == reason


def test_update_user_others_requires_operator(client, monkeypatch):
    """分级调控:普通用户改他人 → 403。"""
    _valid_token(monkeypatch, user_id=2)  # 当前用户 2,目标用户 1
    called = []

    def _update(user_id, **fields):
        called.append(user_id)
        return SimpleNamespace(username="x")

    monkeypatch.setattr(user_api.user_tasks, "Update_user", _update)

    resp = client.post("/api/users/update_user", json={"user_id": 1, "fields": {"username": "x"}})

    assert resp.status_code == 403
    assert called == []  # Update_user 不应被调用


def test_update_user_others_as_operator_allowed(client, monkeypatch):
    """分级调控:operator 改他人 → 200。"""
    _valid_token(monkeypatch, user_id=2)
    from ...services import rbac_service
    monkeypatch.setattr(rbac_service, "_has_entity_direct", lambda uid, entity: True)
    monkeypatch.setattr(user_api.user_tasks, "Update_user", lambda user_id, **fields: SimpleNamespace(username="x"))

    resp = client.post("/api/users/update_user", json={"user_id": 1, "fields": {"username": "x"}})

    assert resp.status_code == 200
    assert resp.json()["user"] == "x"


def test_my_permissions_returns_user_group_entities(client, monkeypatch):
    """me/permissions:普通用户(默认 user 组)返回基础权限点,不含 manage。"""
    _valid_token(monkeypatch)
    resp = client.get("/api/users/me/permissions")
    assert resp.status_code == 200
    entities = resp.json()["entities"]
    assert "machine:view" in entities
    assert "container:operation" in entities
    assert "user:manage" not in entities
    assert "bypass_auth_entity" not in entities


def test_my_permissions_operator_returns_all(client, monkeypatch):
    """me/permissions:operator 组用户返回全部权限点(通配)。"""
    _valid_token(monkeypatch)
    from ...repositories import auth_repo
    from ...extensions import session_scope as _ss
    with _ss() as session:
        group = auth_repo.ensure_group("operator", "t", session=session)
        for code in ("bypass_auth_entity", "bypass_resource"):
            auth_repo.ensure_group_entity(group.id, code, session=session)
            auth_repo.ensure_user_group(1, group.id, session=session)
    resp = client.get("/api/users/me/permissions")
    assert resp.status_code == 200
    entities = resp.json()["entities"]
    assert "bypass_auth_entity" in entities
    assert "machine:manage" in entities
