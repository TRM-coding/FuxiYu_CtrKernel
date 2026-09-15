import pytest
from sqlalchemy import select

from ...constant import ContainerStatus, ROLE
from ...models.containers import Container
from ...models.long_term_container import LongTermContainer
from ...models.user import User
from ...repositories import usercontainer_repo
from ...services import user_tasks
from ..factories import bind_user_container, create_container, create_machine, create_user


def test_register_success(db_session):
    success, user, token = user_tasks.Register("reg_user", "reg_user@bjtu.edu.cn", "Password_123", "2026")

    assert success is True
    assert user.username == "reg_user"
    assert token is None
    assert db_session.scalars(select(User).where(User.username == "reg_user")).first() is not None
    assert user.password_hash != "Password_123"


@pytest.mark.parametrize(
    ("username", "email", "password", "expected"),
    [
        ("u" * 76, "long_name@bjtu.edu.cn", "Password_123", "username_too_long"),
        ("email_long", f"{'e' * 116}@bjtu.edu.cn", "Password_123", "email_too_long"),
        ("bad-name", "bad_name@bjtu.edu.cn", "Password_123", "invalid_username"),
        ("中文", "unicode_name@bjtu.edu.cn", "Password_123", "invalid_username"),
        ("unicode_email", "unicode邮箱@bjtu.edu.cn", "Password_123", "no_none_ascii"),
        ("unicode_password", "unicode_password@bjtu.edu.cn", "密码", "no_none_ascii"),
    ],
)
def test_register_rejects_invalid_inputs(db_session, username, email, password, expected):
    success, reason, token = user_tasks.Register(username, email, password, "2026")

    assert success is False
    assert reason == expected
    assert token is None


def test_register_rejects_duplicate_username(db_session):
    create_user(username="dup_user", email="dup1@bjtu.edu.cn")

    success, reason, _ = user_tasks.Register("dup_user", "dup2@bjtu.edu.cn", "Password_123", "2026")

    assert success is False
    assert reason == "username_exists"


def test_register_rejects_duplicate_email(db_session):
    create_user(username="dup_email_user1", email="dup_email@bjtu.edu.cn")

    success, reason, _ = user_tasks.Register("dup_email_user2", "dup_email@bjtu.edu.cn", "Password_123", "2026")

    assert success is False
    assert reason == "email_exists"


def test_delete_user_success_unbinds_before_delete(monkeypatch, db_session):
    user = create_user(username="delete_user")
    user_id = user.id
    calls = []

    monkeypatch.setattr(user_tasks.usercontainer_repo, "remove_user_from_all_containers", lambda user_id, **kwargs: calls.append(user_id) or {"ok": True})

    assert user_tasks.Delete_user(user.id) is True
    assert calls == [user_id]
    db_session.expire_all()
    assert db_session.get(User, user_id) is None


def test_delete_user_returns_false_when_unbind_fails(monkeypatch, db_session):
    user = create_user(username="delete_fail_user")

    monkeypatch.setattr(user_tasks.usercontainer_repo, "remove_user_from_all_containers", lambda user_id, **kwargs: {"ok": False})

    assert user_tasks.Delete_user(user.id) is False
    assert db_session.get(User, user.id) is not None


def test_delete_user_raises_wild_containers(monkeypatch, db_session):
    user = create_user(username="delete_wild_user")

    monkeypatch.setattr(
        user_tasks.usercontainer_repo,
        "remove_user_from_all_containers",
        lambda user_id, **kwargs: {"ok": False, "wild_containers": [144]},
    )

    with pytest.raises(Exception) as excinfo:
        user_tasks.Delete_user(user.id)

    assert getattr(excinfo.value, "wild_containers") == [144]
    assert db_session.get(User, user.id) is not None


def test_get_user_detail_information_returns_counts_and_long_term_count(db_session):
    user = create_user(username="detail_user")
    machine = create_machine()
    online_container = create_container(machine=machine, status=ContainerStatus.ONLINE)
    offline_container = create_container(machine=machine, status=ContainerStatus.OFFLINE)
    bind_user_container(user, online_container, role=ROLE.ROOT)
    bind_user_container(user, offline_container, role=ROLE.COLLABORATOR)
    db_session.add(LongTermContainer(container_id=online_container.id, created_by_user_id=user.id))
    db_session.commit()

    info = user_tasks.Get_user_detail_information(user.id)

    assert info.user_id == user.id
    assert set(info.containers) == {online_container.id, offline_container.id}
    assert info.amount_of_container == 2
    assert info.amount_of_functional_container == 1
    assert info.amount_of_managed_container == 1
    assert info.amount_of_long_term_container == 1


def test_get_user_detail_information_missing_user_returns_none(db_session):
    assert user_tasks.Get_user_detail_information(None) is None
    assert user_tasks.Get_user_detail_information("not-int") is None
    assert user_tasks.Get_user_detail_information(999999) is None


def test_list_all_user_bref_information_normalizes_pagination_and_returns_counts(db_session):
    user = create_user(username="list_user")
    container = create_container(status=ContainerStatus.ONLINE)
    bind_user_container(user, container, role=ROLE.ROOT)

    users = user_tasks.List_all_user_bref_information(page_number="bad", page_size="bad")

    match = next(u for u in users if u.user_id == user.id)
    assert match.amount_of_container == 1
    assert match.amount_of_functional_container == 1
    assert match.amount_of_managed_container == 1


def test_list_all_user_bref_information_filters_by_user_search(db_session):
    target = create_user(username="search_user", email="search_user@bjtu.edu.cn", graduation_year="2031")
    create_user(username="other_user", email="other_user@bjtu.edu.cn", graduation_year="2032")

    by_name = user_tasks.List_all_user_bref_information(page_number=1, page_size=10, user_search="search_user")
    by_email = user_tasks.List_all_user_bref_information(page_number=1, page_size=10, user_search="search_user@bjtu")
    by_year = user_tasks.List_all_user_bref_information(page_number=1, page_size=10, user_search="2031")
    by_id = user_tasks.List_all_user_bref_information(page_number=1, page_size=10, user_search=str(target.id))

    assert [u.user_id for u in by_name] == [target.id]
    assert [u.user_id for u in by_email] == [target.id]
    assert [u.user_id for u in by_year] == [target.id]
    assert target.id in [u.user_id for u in by_id]


def test_update_user_filters_forbidden_fields(db_session):
    user = create_user(username="update_user", email="update@bjtu.edu.cn", password="old")
    original_hash = user.password_hash

    updated = user_tasks.Update_user(
        user.id,
        username="updated_user",
        email="changed@bjtu.edu.cn",
        password_hash="plain",
        graduation_year="2027",
    )

    assert updated.username == "updated_user"
    assert updated.email == "update@bjtu.edu.cn"
    assert updated.password_hash == original_hash
    assert updated.graduation_year == "2027"


def test_update_user_rejects_invalid_username(db_session):
    user = create_user(username="invalid_update_user")

    with pytest.raises(ValueError, match="invalid_username"):
        user_tasks.Update_user(user.id, username="bad-name")


def test_update_user_rejects_non_ascii_field(db_session):
    user = create_user(username="non_ascii_update_user")

    with pytest.raises(ValueError, match="no_none_ascii"):
        user_tasks.Update_user(user.id, graduation_year="二零二六")


def test_compute_user_container_counts_handles_real_bindings(db_session):
    user = create_user(username="count_user")
    online = create_container(status=ContainerStatus.ONLINE)
    offline = create_container(status=ContainerStatus.OFFLINE)
    bind_user_container(user, online, role=ROLE.ROOT)
    bind_user_container(user, offline, role=ROLE.COLLABORATOR)

    counts = usercontainer_repo.compute_user_container_counts(user.id, session=db_session)

    assert counts["total"] == 2
    assert counts["functional"] == 1
    assert counts["managed"] == 1
