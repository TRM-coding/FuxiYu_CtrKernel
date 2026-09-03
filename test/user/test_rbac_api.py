import pytest

from ...api import deps
from ...repositories import auth_repo
from ...extensions import session_scope
from ...services.rbac_service import list_user_entities, user_has_entity

pytestmark = pytest.mark.usefixtures("ensure_auth_users")


def _valid_token(monkeypatch, user_id=1):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: True)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: user_id)


def _grant_rbac_manage(user_id=1):
    with session_scope() as session:
        group = auth_repo.ensure_group("rbac_manager_test", "test", session=session)
        auth_repo.ensure_group_entity(group.id, "rbac:manage", session=session)
        auth_repo.ensure_user_group(user_id, group.id, session=session)


def test_rbac_matrix_requires_permission(client, monkeypatch):
    _valid_token(monkeypatch)

    resp = client.get("/api/rbac/matrix")

    assert resp.status_code == 403


def test_rbac_matrix_returns_groups_and_entities(client, monkeypatch):
    _valid_token(monkeypatch)
    _grant_rbac_manage()

    resp = client.get("/api/rbac/matrix")

    assert resp.status_code == 200
    body = resp.json()
    entity_codes = [item["code"] for item in body["entities"]]
    group_names = [item["name"] for item in body["groups"]]
    assert "rbac:manage" in entity_codes
    assert "settings:manage" in entity_codes
    assert "user" in group_names
    assert "operator" in group_names


def test_seed_prunes_stale_entity_bindings(client, monkeypatch):
    """seed 收敛：常量里已不存在的 code 残留绑定在 seed 时被清退。"""
    from ...services.rbac_service import seed_rbac_defaults

    _valid_token(monkeypatch)
    _grant_rbac_manage()
    # 模拟旧版本残留：user 组直接绑一个常量中不存在的 code
    with session_scope() as session:
        user_group = auth_repo.get_group("user", session=session)
        auth_repo.ensure_group_entity(user_group.id, "user:view", session=session)

    seed_rbac_defaults()

    resp = client.get("/api/rbac/matrix")
    assert resp.status_code == 200
    codes = [item["code"] for item in resp.json()["entities"]]
    assert "user:view" not in codes
    with session_scope(commit=False) as session:
        bound = auth_repo.list_group_entity_codes(session=session).get(user_group.id, set())
    assert "user:view" not in bound


def test_update_rbac_group_entities_replaces_user_group_permissions(client, monkeypatch):
    _valid_token(monkeypatch)
    _grant_rbac_manage()
    with session_scope(commit=False) as session:
        user_group = auth_repo.get_group("user", session=session)
        group_id = user_group.id

    resp = client.post(
        f"/api/rbac/groups/{group_id}/entities",
        json={"entity_codes": ["machine:view", "image:view"]},
    )

    assert resp.status_code == 200
    assert resp.json()["group"]["entity_codes"] == ["machine:view", "image:view"]
    with session_scope(commit=False) as session:
        assert auth_repo.group_has_entity(group_id, "machine:view", session=session)
        assert not auth_repo.group_has_entity(group_id, "container:create", session=session)


def test_update_rbac_group_entities_rejects_unknown_entity(client, monkeypatch):
    _valid_token(monkeypatch)
    _grant_rbac_manage()
    with session_scope(commit=False) as session:
        user_group = auth_repo.get_group("user", session=session)

    resp = client.post(
        f"/api/rbac/groups/{user_group.id}/entities",
        json={"entity_codes": ["missing:permission"]},
    )

    assert resp.status_code == 400
    assert resp.json()["error_reason"] == "unknown_auth_entity"


def test_update_operator_keeps_locked_bypass_entities(client, monkeypatch):
    _valid_token(monkeypatch)
    _grant_rbac_manage()
    with session_scope(commit=False) as session:
        operator_group = auth_repo.get_group("operator", session=session)
        group_id = operator_group.id

    resp = client.post(
        f"/api/rbac/groups/{group_id}/entities",
        json={"entity_codes": ["machine:view"]},
    )

    assert resp.status_code == 200
    codes = set(resp.json()["group"]["entity_codes"])
    assert {"machine:view", "bypass_auth_entity", "bypass_resource"} <= codes


def test_create_rbac_group_uses_requested_permissions(client, monkeypatch):
    _valid_token(monkeypatch)
    _grant_rbac_manage()

    resp = client.post(
        "/api/rbac/groups",
        json={
            "name": "teacher",
            "description": "教师",
            "entity_codes": ["machine:view", "container:create", "image:view"],
        },
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["group"]["name"] == "teacher"
    assert body["group"]["entity_codes"] == ["machine:view", "container:create", "image:view"]
    with session_scope(commit=False) as session:
        group = auth_repo.get_group("teacher", session=session)
        assert group is not None
        assert auth_repo.group_has_entity(group.id, "container:create", session=session)


def test_create_rbac_group_rejects_duplicate_name(client, monkeypatch):
    _valid_token(monkeypatch)
    _grant_rbac_manage()

    first = client.post("/api/rbac/groups", json={"name": "teacher", "entity_codes": []})
    second = client.post("/api/rbac/groups", json={"name": "teacher", "entity_codes": []})

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error_reason"] == "group_exists"


def test_manage_entity_implies_same_domain_entities():
    with session_scope() as session:
        group = auth_repo.ensure_group("container_manager_test", "test", session=session)
        auth_repo.ensure_group_entity(group.id, "container:manage", session=session)
        auth_repo.ensure_user_group(7, group.id, session=session)

    assert user_has_entity(7, "container:manage") is True
    assert user_has_entity(7, "container:view") is True
    assert user_has_entity(7, "container:create") is True
    assert user_has_entity(7, "container:operation") is True


def test_bypass_auth_entity_does_not_imply_bypass_resource():
    with session_scope() as session:
        group = auth_repo.ensure_group("auth_bypass_only_test", "test", session=session)
        auth_repo.ensure_group_entity(group.id, "bypass_auth_entity", session=session)
        auth_repo.ensure_user_group(7, group.id, session=session)

    assert user_has_entity(7, "container:create") is True
    assert user_has_entity(7, "bypass_auth_entity") is True
    assert user_has_entity(7, "bypass_resource") is False
    assert "bypass_resource" not in list_user_entities(7)


def test_two_bypass_entities_are_reported_when_both_granted():
    with session_scope() as session:
        group = auth_repo.ensure_group("both_bypass_test", "test", session=session)
        auth_repo.ensure_group_entity(group.id, "bypass_auth_entity", session=session)
        auth_repo.ensure_group_entity(group.id, "bypass_resource", session=session)
        auth_repo.ensure_user_group(7, group.id, session=session)

    entities = set(list_user_entities(7))
    assert "bypass_auth_entity" in entities
    assert "bypass_resource" in entities
