import pytest
from sqlalchemy import select

from ...constant import AnnouncementStatus, ContainerStatus, ROLE
from ...extensions import SessionRegistry, session_scope
from ...models.announcement import Announcement, AnnouncementDraft, AnnouncementTemplate
from ...models.authentications import Authentication
from ...models.containers import Container
from ...models.long_term_container import LongTermContainer
from ...models.user import User
from ...repositories import announcement_repo, usercontainer_repo
from ...services import user_tasks
from ..factories import bind_user_container, create_auth, create_container, create_machine, create_user


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


def _token_count(user_id):
    return len(SessionRegistry.scalars(
        select(Authentication).where(Authentication.user_id == user_id)
    ).all())


def test_delete_user_removes_its_authentication_tokens(monkeypatch, db_session):
    """Q05：有 token、无容器时用户删除成功，同一事务里 token 一并删掉。"""
    user = create_user(username="delete_token_user")
    user_id = user.id
    create_auth(user, token="del-token-1")
    create_auth(user, token="del-token-2")
    assert _token_count(user_id) == 2

    monkeypatch.setattr(
        user_tasks.usercontainer_repo,
        "remove_user_from_all_containers",
        lambda user_id, **kwargs: {"ok": True},
    )

    assert user_tasks.Delete_user(user_id) is True

    db_session.expire_all()
    assert db_session.get(User, user_id) is None
    assert _token_count(user_id) == 0


def test_delete_user_wild_container_keeps_user_and_tokens(monkeypatch, db_session):
    """Q05：容器阻止删除时保留 wild_container 归因，用户与 token 都不动（事务不半提交）。"""
    user = create_user(username="wild_keep_token_user")
    user_id = user.id
    create_auth(user, token="wild-keep-token")

    monkeypatch.setattr(
        user_tasks.usercontainer_repo,
        "remove_user_from_all_containers",
        lambda user_id, **kwargs: {"ok": False, "wild_containers": [144, 145]},
    )

    with pytest.raises(Exception) as excinfo:
        user_tasks.Delete_user(user_id)

    assert getattr(excinfo.value, "wild_containers") == [144, 145]
    db_session.expire_all()
    assert db_session.get(User, user_id) is not None
    assert _token_count(user_id) == 1


def test_delete_user_leaves_other_users_tokens_untouched(monkeypatch, db_session):
    """Q05：级联删除只作用于目标用户，别人的 token 不动。"""
    target = create_user(username="cascade_target_user")
    other = create_user(username="cascade_other_user")
    target_id, other_id = target.id, other.id
    create_auth(target, token="cascade-target-token")
    create_auth(other, token="cascade-other-token")

    monkeypatch.setattr(
        user_tasks.usercontainer_repo,
        "remove_user_from_all_containers",
        lambda user_id, **kwargs: {"ok": True},
    )

    assert user_tasks.Delete_user(target_id) is True

    db_session.expire_all()
    assert _token_count(target_id) == 0
    assert _token_count(other_id) == 1


def test_delete_user_token_delete_failure_rolls_back_user(monkeypatch, db_session):
    """Q05：token 删除失败时整个删除事务回滚，用户仍在（不留半删除状态）。"""
    user = create_user(username="rollback_token_user")
    user_id = user.id
    create_auth(user, token="rollback-token")

    monkeypatch.setattr(
        user_tasks.usercontainer_repo,
        "remove_user_from_all_containers",
        lambda user_id, **kwargs: {"ok": True},
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("token delete failed")

    monkeypatch.setattr(user_tasks.authentications_repo, "delete_tokens_by_user_id", _boom)

    with pytest.raises(RuntimeError, match="token delete failed"):
        user_tasks.Delete_user(user_id)

    db_session.expire_all()
    assert db_session.get(User, user_id) is not None
    assert _token_count(user_id) == 1


def _save_owner_draft(user, *, title, session):
    return announcement_repo.save_draft(
        title=title,
        content=f"{title}-content",
        created_by=user.id,
        session=session,
    )


def _save_announcement_and_template(session, *, suffix):
    announcement = announcement_repo.create_announcement(
        title=f"kept-announcement-{suffix}",
        content=f"kept-content-{suffix}",
        raw_content=f"kept-raw-{suffix}",
        status=AnnouncementStatus.SENT,
        targets="[]",
        target_snapshot="[]",
        recipient_count=1,
        session=session,
    )
    template = announcement_repo.create_template(
        name=f"kept-template-{suffix}",
        subject_template=f"kept-subject-{suffix}",
        body_template=f"kept-body-{suffix}",
        description=f"kept-description-{suffix}",
        session=session,
    )
    return announcement, template


def _announcement_template_snapshot():
    with session_scope(commit=False) as session:
        announcements = session.scalars(
            select(Announcement).order_by(Announcement.id)
        ).all()
        templates = session.scalars(
            select(AnnouncementTemplate).order_by(AnnouncementTemplate.id)
        ).all()
        return (
            tuple(
                (
                    row.id,
                    row.title,
                    row.content,
                    row.raw_content,
                    row.status,
                    row.targets,
                    row.target_snapshot,
                    row.recipient_count,
                    row.success_count,
                    row.fail_count,
                    row.created_at,
                    row.sent_at,
                    row.source_draft_id,
                    row.template_id,
                )
                for row in announcements
            ),
            tuple(
                (
                    row.id,
                    row.name,
                    row.category,
                    row.description,
                    row.subject_template,
                    row.body_template,
                    row.source_announcement_id,
                    row.created_at,
                    row.updated_at,
                )
                for row in templates
            ),
        )


def test_delete_user_cascades_own_drafts_and_keeps_others(monkeypatch, db_session):
    target = create_user(username="cascade_draft_target")
    other = create_user(username="cascade_draft_other")
    target_id = target.id
    create_auth(target, token="cascade-draft-token")

    with session_scope() as session:
        target_draft = _save_owner_draft(target, title="target", session=session)
        other_draft = _save_owner_draft(other, title="other", session=session)
        announcement, template = _save_announcement_and_template(session, suffix="cascade")
        target_draft_id = target_draft.id
        other_draft_id = other_draft.id
        announcement_id = announcement.id
        template_id = template.id

    content_before = _announcement_template_snapshot()

    monkeypatch.setattr(
        user_tasks.usercontainer_repo,
        "remove_user_from_all_containers",
        lambda user_id, **kwargs: {"ok": True},
    )
    delete_draft_calls = []

    def _must_not_delete_draft(*args, **kwargs):
        delete_draft_calls.append((args, kwargs))
        raise AssertionError("service must not delete drafts manually")

    monkeypatch.setattr(announcement_repo, "delete_draft", _must_not_delete_draft)

    assert user_tasks.Delete_user(target_id) is True

    db_session.expire_all()
    assert db_session.get(User, target_id) is None
    assert db_session.get(AnnouncementDraft, target_draft_id) is None
    assert db_session.get(AnnouncementDraft, other_draft_id) is not None
    assert db_session.get(Announcement, announcement_id) is not None
    assert db_session.get(AnnouncementTemplate, template_id) is not None
    assert _token_count(target_id) == 0
    assert delete_draft_calls == []
    assert _announcement_template_snapshot() == content_before


def test_delete_user_cascade_rolls_back_on_transaction_failure(monkeypatch, db_session):
    target = create_user(username="cascade_rollback_target")
    other = create_user(username="cascade_rollback_other")
    target_id = target.id
    create_auth(target, token="cascade-rollback-token")

    with session_scope() as session:
        target_draft = _save_owner_draft(target, title="target", session=session)
        other_draft = _save_owner_draft(other, title="other", session=session)
        _save_announcement_and_template(session, suffix="rollback")
        target_draft_id = target_draft.id
        other_draft_id = other_draft.id

    content_before = _announcement_template_snapshot()

    monkeypatch.setattr(
        user_tasks.usercontainer_repo,
        "remove_user_from_all_containers",
        lambda user_id, **kwargs: {"ok": True},
    )
    original_delete_user = user_tasks.delete_user

    def _delete_then_fail(user_id, *, session):
        original_delete_user(user_id=user_id, session=session)
        raise RuntimeError("fail after database cascade")

    monkeypatch.setattr(user_tasks, "delete_user", _delete_then_fail)

    with pytest.raises(RuntimeError, match="fail after database cascade"):
        user_tasks.Delete_user(target_id)

    db_session.expire_all()
    assert db_session.get(User, target_id) is not None
    assert db_session.get(AnnouncementDraft, target_draft_id) is not None
    assert db_session.get(AnnouncementDraft, other_draft_id) is not None
    assert _token_count(target_id) == 1
    assert _announcement_template_snapshot() == content_before


def test_delete_user_wild_container_keeps_drafts(monkeypatch, db_session):
    target = create_user(username="wild_draft_target")
    other = create_user(username="wild_draft_other")
    create_auth(target, token="wild-draft-token")
    with session_scope() as session:
        draft = _save_owner_draft(target, title="wild", session=session)
        other_draft = _save_owner_draft(other, title="wild-other", session=session)
        _save_announcement_and_template(session, suffix="wild")
        draft_id = draft.id
        other_draft_id = other_draft.id

    content_before = _announcement_template_snapshot()

    monkeypatch.setattr(
        user_tasks.usercontainer_repo,
        "remove_user_from_all_containers",
        lambda user_id, **kwargs: {"ok": False, "wild_containers": [144]},
    )

    with pytest.raises(Exception) as excinfo:
        user_tasks.Delete_user(target.id)

    assert getattr(excinfo.value, "wild_containers") == [144]
    db_session.expire_all()
    assert db_session.get(User, target.id) is not None
    assert db_session.get(AnnouncementDraft, draft_id) is not None
    assert db_session.get(AnnouncementDraft, other_draft_id) is not None
    assert _token_count(target.id) == 1
    assert _announcement_template_snapshot() == content_before


def test_user_delete_is_blocked_by_token_without_explicit_cleanup(db_session):
    """机制证据：测试库真的开了 PRAGMA foreign_keys=ON。

    有 authentications 行时直接删 users 行会 IntegrityError——这正是旧 Delete_user
    不先清 token 就失败、随后被 API 层误归因为 wild_container 的原因。
    """
    from sqlalchemy.exc import IntegrityError

    user = create_user(username="fk_evidence_user")
    create_auth(user, token="fk-evidence-token")

    with pytest.raises(IntegrityError):
        db_session.delete(user)
        db_session.flush()
    db_session.rollback()


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


def test_update_user_blank_graduation_year_does_not_clear(db_session):
    """Q54：服务层也忽略空字符串，已保存年份保持原值。"""

    user = create_user(username="blank_year_update_user", graduation_year="2026")

    updated = user_tasks.Update_user(
        user.id,
        username="blank_year_updated",
        graduation_year="",
    )
    assert updated.username == "blank_year_updated"

    db_session.expire_all()
    refreshed = db_session.get(type(user), user.id)
    assert refreshed.graduation_year == "2026"


def test_graduation_year_column_stays_not_nullable():
    """Q54：不因允许空输入而放宽 users.graduation_year 的非空约束。"""

    from ...models.user import User

    assert User.__table__.c.graduation_year.nullable is False


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
