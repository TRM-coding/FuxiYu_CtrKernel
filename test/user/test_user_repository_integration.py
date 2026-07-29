from ...constant import ContainerStatus, ROLE
from ...models.authentications import Authentication
from ...models.long_term_container import LongTermContainer
from ...models.user import User
from ...services import user_tasks
from ..factories import bind_user_container, create_container, create_machine


def test_register_and_login_with_real_repositories(db_session):
    success, registered_user, token = user_tasks.Register(
        "repo_user",
        "repo_user@bjtu.edu.cn",
        "Password_123",
        "2026",
    )

    assert success is True
    assert token is None
    assert User.query.filter_by(username="repo_user").first().id == registered_user.id

    success, login_user, token = user_tasks.Login("repo_user", "Password_123")

    assert success is True
    assert login_user.id == registered_user.id
    assert Authentication.query.filter_by(token=token, user_id=registered_user.id).first() is not None


def test_user_detail_counts_with_real_usercontainer_and_long_term_rows(db_session):
    success, user, _ = user_tasks.Register(
        "repo_counts_user",
        "repo_counts_user@bjtu.edu.cn",
        "Password_123",
        "2026",
    )
    assert success is True
    machine = create_machine()
    online_container = create_container(machine=machine, status=ContainerStatus.ONLINE)
    offline_container = create_container(machine=machine, status=ContainerStatus.OFFLINE)
    bind_user_container(user, online_container, role=ROLE.ROOT)
    bind_user_container(user, offline_container, role=ROLE.COLLABORATOR)
    db_session.add(LongTermContainer(container_id=online_container.id, created_by_user_id=user.id))
    db_session.commit()

    info = user_tasks.Get_user_detail_information(user.id)

    assert info.amount_of_container == 2
    assert info.amount_of_functional_container == 1
    assert info.amount_of_managed_container == 1
    assert info.amount_of_long_term_container == 1
