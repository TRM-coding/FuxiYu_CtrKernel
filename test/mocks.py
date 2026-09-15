import json
from datetime import datetime, timedelta

from .conftest import TEST_AUTH_TOKEN, TEST_OPERATOR_TOKEN
from .factories import create_auth, create_user
from ..api import deps


def mock_auth_token(monkeypatch, module, *, user_id: int = 1, valid: bool = True, token: str = TEST_AUTH_TOKEN):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda provided_token, **kwargs: valid)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda provided_token, **kwargs: user_id)
    if hasattr(module, "authentications_repo"):
        monkeypatch.setattr(module.authentications_repo, "is_token_valid", lambda provided_token, **kwargs: valid)
        monkeypatch.setattr(module.authentications_repo, "get_user_id_by_token", lambda provided_token, **kwargs: user_id)
    return {}


def mock_operator_token(monkeypatch, module, *, user_id: int = 1, valid: bool = True, token: str = TEST_OPERATOR_TOKEN):
    headers = mock_auth_token(monkeypatch, module, user_id=user_id, valid=valid, token=token)
    from ..services import rbac_service
    monkeypatch.setattr(rbac_service, "_has_entity_direct", lambda uid, entity: valid)
    return headers


def mock_node_response(monkeypatch, module, response: dict):
    calls = []

    def _send(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return dict(response)

    monkeypatch.setattr(module, "send", _send)
    return calls



def mock_mail_success(monkeypatch, module):
    calls = []

    def _send(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        to = kwargs.get("to")
        if to is None and args:
            to = args[0]
        recipients = [to] if isinstance(to, str) else list(to or [])
        return {"ok": True, "to": recipients}

    monkeypatch.setattr(module, "send_mail", _send)
    return calls


def auth_token_factory(user=None, *, expired: bool = False, token: str = TEST_AUTH_TOKEN):
    user = user or create_user()
    expires_at = datetime.utcnow() - timedelta(seconds=1) if expired else datetime.utcnow() + timedelta(hours=1)
    create_auth(user, token=token, expires_at=expires_at)
    return token


def operator_user_factory(**overrides):
    return create_user(operator=True, **overrides)
