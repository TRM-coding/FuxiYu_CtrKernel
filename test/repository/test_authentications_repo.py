from datetime import datetime, timedelta

from ...repositories import authentications_repo
from ..factories import create_user


def test_auth_repo_create_validate_delete_token(db_session):
    user = create_user()
    authentications_repo.create_auth("repo-token", user.id, datetime.utcnow() + timedelta(hours=1))

    assert authentications_repo.is_token_valid("repo-token") is True
    assert authentications_repo.delete_auth("repo-token") is True
    assert authentications_repo.is_token_valid("repo-token") is False


def test_auth_repo_expired_token_is_invalid(db_session):
    user = create_user()
    authentications_repo.create_auth("expired-token", user.id, datetime.utcnow() - timedelta(seconds=1))

    assert authentications_repo.is_token_valid("expired-token") is False


def test_auth_repo_get_user_id_by_token(db_session):
    user = create_user()
    authentications_repo.create_auth("owner-token", user.id, datetime.utcnow() + timedelta(hours=1))

    assert authentications_repo.get_user_id_by_token("owner-token") == user.id
