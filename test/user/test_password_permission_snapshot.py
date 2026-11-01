"""容器资源通配权限快照合同。"""

from sqlalchemy import inspect

from ...api import deps
from ...extensions import session_scope
from ...models.user import User
from ...repositories import auth_repo
from ..factories import create_user


def _auth(monkeypatch, user_id):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: True)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: user_id)


def _bind_entities(user, codes, *, group_name):
    with session_scope() as session:
        group = auth_repo.ensure_group(group_name, group_name, session=session)
        for code in codes:
            auth_repo.ensure_group_entity(group.id, code, session=session)
        auth_repo.ensure_user_group(user.id, group.id, session=session)


def test_container_resource_snapshot_contract(client, monkeypatch, db_session):
    # 只有方法实体通配：entities 可含 container:manage，但资源位 false
    entity_only = create_user()
    _bind_entities(entity_only, ("bypass_auth_entity",), group_name="pwd_entity_only")
    _auth(monkeypatch, entity_only.id)
    body = client.get("/api/users/me/permissions").json()
    assert "container:manage" in body["entities"]
    assert body["container_resource_unrestricted"] is False
    assert body["image_resource_unrestricted"] is False

    # 直持 container:manage：容器 true，镜像 false
    manager = create_user()
    _bind_entities(manager, ("container:manage",), group_name="pwd_container_manage")
    _auth(monkeypatch, manager.id)
    body = client.get("/api/users/me/permissions").json()
    assert body["container_resource_unrestricted"] is True
    assert body["image_resource_unrestricted"] is False

    # bypass_resource：两者都 true
    wildcard = create_user()
    _bind_entities(wildcard, ("bypass_resource",), group_name="pwd_resource_all")
    _auth(monkeypatch, wildcard.id)
    body = client.get("/api/users/me/permissions").json()
    assert body["container_resource_unrestricted"] is True
    assert body["image_resource_unrestricted"] is True

    # 镜像方法通配：image false，container false
    image_entity = create_user()
    _bind_entities(image_entity, ("bypass_auth_entity",), group_name="pwd_image_entity_only")
    _auth(monkeypatch, image_entity.id)
    body = client.get("/api/users/me/permissions").json()
    assert "image:manage" in body["entities"]
    assert body["image_resource_unrestricted"] is False

    # 直持 container:manage + bypass_auth_entity：容器 true
    combo = create_user()
    _bind_entities(combo, ("container:manage", "bypass_auth_entity"), group_name="pwd_combo")
    _auth(monkeypatch, combo.id)
    body = client.get("/api/users/me/permissions").json()
    assert body["container_resource_unrestricted"] is True

    # 派生字段不落库
    assert "container_resource_unrestricted" not in {c.key for c in inspect(User).columns}
