from datetime import datetime, timedelta

from ...repositories import authentications_repo
from ..factories import create_user


def test_auth_repo_create_validate_delete_token(db_session):
    user = create_user()
    authentications_repo.create_auth("repo-token", user.id, datetime.utcnow() + timedelta(hours=1), session=db_session)

    assert authentications_repo.is_token_valid("repo-token", session=db_session) is True
    assert authentications_repo.delete_auth("repo-token", session=db_session) is True
    assert authentications_repo.is_token_valid("repo-token", session=db_session) is False


def test_auth_repo_expired_token_is_invalid(db_session):
    user = create_user()
    authentications_repo.create_auth("expired-token", user.id, datetime.utcnow() - timedelta(seconds=1), session=db_session)

    assert authentications_repo.is_token_valid("expired-token", session=db_session) is False


def test_auth_repo_get_user_id_by_token(db_session):
    user = create_user()
    authentications_repo.create_auth("owner-token", user.id, datetime.utcnow() + timedelta(hours=1), session=db_session)

    assert authentications_repo.get_user_id_by_token("owner-token", session=db_session) == user.id


def test_auth_repo_delete_tokens_by_user_id_only_touches_that_user(db_session):
    """用户删除用的按 user_id 清 token：只删目标用户，返回真实删除行数。"""
    target = create_user()
    other = create_user()
    expires = datetime.utcnow() + timedelta(hours=1)
    authentications_repo.create_auth("target-token-1", target.id, expires, session=db_session)
    authentications_repo.create_auth("target-token-2", target.id, expires, session=db_session)
    authentications_repo.create_auth("other-token", other.id, expires, session=db_session)

    removed = authentications_repo.delete_tokens_by_user_id(target.id, session=db_session)

    assert removed == 2
    assert authentications_repo.is_token_valid("target-token-1", session=db_session) is False
    assert authentications_repo.is_token_valid("target-token-2", session=db_session) is False
    assert authentications_repo.is_token_valid("other-token", session=db_session) is True


def test_auth_repo_delete_tokens_by_user_id_is_noop_without_tokens(db_session):
    user = create_user()

    assert authentications_repo.delete_tokens_by_user_id(user.id, session=db_session) == 0
