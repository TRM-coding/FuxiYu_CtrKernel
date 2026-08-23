"""user_has_resource 的容器角色资源点（container:<role>）判定。"""

from ...constant import ROLE
from ...services import rbac_service
from ..factories import bind_user_container, create_container_graph, create_user


def test_container_role_resource_points(db_session):
    """container:root / container:admin / container:collaborator 精确角色判定。"""
    root, _machine, container = create_container_graph()  # root 绑定为 ROOT
    admin = create_user()
    collab = create_user()
    bind_user_container(admin, container, role=ROLE.ADMIN, username=admin.username)
    bind_user_container(collab, container, role=ROLE.COLLABORATOR, username=collab.username)

    # 可见性：任意绑定
    assert rbac_service.user_has_resource(root.id, "container", container.id)
    assert rbac_service.user_has_resource(collab.id, "container", container.id)

    # 角色层级：ROOT > ADMIN > COLLABORATOR，高角色满足低角色要求（向上兼容）
    assert rbac_service.user_has_resource(root.id, "container:root", container.id)
    assert rbac_service.user_has_resource(root.id, "container:admin", container.id)
    assert rbac_service.user_has_resource(root.id, "container:collaborator", container.id)

    assert rbac_service.user_has_resource(admin.id, "container:admin", container.id)
    assert rbac_service.user_has_resource(admin.id, "container:collaborator", container.id)
    assert not rbac_service.user_has_resource(admin.id, "container:root", container.id)

    assert rbac_service.user_has_resource(collab.id, "container:collaborator", container.id)
    assert not rbac_service.user_has_resource(collab.id, "container:admin", container.id)
    assert not rbac_service.user_has_resource(collab.id, "container:root", container.id)

    # 无绑定
    stranger = create_user()
    assert not rbac_service.user_has_resource(stranger.id, "container", container.id)
    assert not rbac_service.user_has_resource(stranger.id, "container:root", container.id)

    # 单类型 manage 通配：持有 container:manage → 对任意容器放行（无需绑定）
    manager = create_user()
    bind_user_container(manager, container, role=ROLE.COLLABORATOR, username=manager.username)
    from ...repositories import auth_repo
    from ...extensions import session_scope as _ss
    with _ss() as session:
        ent = auth_repo.ensure_entity("container:manage", "t", session=session)
        group = auth_repo.ensure_group("container_manager_test", "t", session=session)
        auth_repo.ensure_group_entity(group.id, ent.id, session=session)
        auth_repo.ensure_user_group(manager.id, group.id, session=session)
    assert rbac_service.user_has_resource(manager.id, "container:admin", container.id)
    assert rbac_service.user_has_resource(manager.id, "container", container.id)

    # 单类型 manage 不影响其他类型（machine 判定不走 container:manage）
    assert not rbac_service.user_has_resource(manager.id, "machine", 999999)

    # user 资源：被授权管理者（教师/助教）对目标学生有访问权
    from ...models.user_managed_user import UserManagedUser
    with _ss() as session:
        session.add(UserManagedUser(manager_user_id=manager.id, managed_user_id=stranger.id))
        session.commit()
    assert rbac_service.user_has_resource(manager.id, "user", stranger.id)
    assert not rbac_service.user_has_resource(stranger.id, "user", manager.id)
