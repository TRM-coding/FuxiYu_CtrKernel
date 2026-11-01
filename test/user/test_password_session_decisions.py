"""Q53：密码修改/重置不吊销该用户或其他用户的既有会话。"""

from sqlalchemy import select

from ...models.authentications import Authentication
from ...repositories import authentications_repo
from ...services import user_tasks
from ..factories import create_auth, create_user


def _tokens_for(db_session, user_id: int) -> set[str]:
    db_session.expire_all()
    return {
        row.token
        for row in db_session.scalars(
            select(Authentication).where(Authentication.user_id == user_id)
        ).all()
    }


def test_change_password_keeps_other_sessions(db_session):
    user = create_user(username="q53_change_user", password="old_password")
    other = create_user(username="q53_other_user", password="other_password")
    create_auth(user, token="q53-change-token-1")
    create_auth(user, token="q53-change-token-2")
    create_auth(other, token="q53-other-token")

    assert user_tasks.Change_password(user, "old_password", "new_password") is True

    assert _tokens_for(db_session, user.id) == {
        "q53-change-token-1",
        "q53-change-token-2",
    }
    assert _tokens_for(db_session, other.id) == {"q53-other-token"}
    assert authentications_repo.is_token_valid("q53-change-token-1", session=db_session)
    assert authentications_repo.is_token_valid("q53-change-token-2", session=db_session)


def test_reset_password_keeps_other_sessions(db_session):
    user = create_user(username="q53_reset_user", password="old_password")
    other = create_user(username="q53_reset_other", password="other_password")
    create_auth(user, token="q53-reset-token-1")
    create_auth(user, token="q53-reset-token-2")
    create_auth(other, token="q53-reset-other-token")

    new_password = user_tasks.Reset_password(user.id)

    assert new_password
    assert _tokens_for(db_session, user.id) == {
        "q53-reset-token-1",
        "q53-reset-token-2",
    }
    assert _tokens_for(db_session, other.id) == {"q53-reset-other-token"}
    assert authentications_repo.is_token_valid("q53-reset-token-1", session=db_session)
    assert authentications_repo.is_token_valid("q53-reset-token-2", session=db_session)
