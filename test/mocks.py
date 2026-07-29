import json
from datetime import datetime, timedelta

from .conftest import TEST_AUTH_TOKEN, TEST_OPERATOR_TOKEN
from .factories import create_auth, create_user
from ..constant import PERMISSION


def mock_auth_token(monkeypatch, module, *, user_id: int = 1, valid: bool = True, token: str = TEST_AUTH_TOKEN):
    monkeypatch.setattr(module.authentications_repo, "is_token_valid", lambda provided_token: valid)
    monkeypatch.setattr(module.authentications_repo, "get_user_id_by_token", lambda provided_token: user_id)
    return {"token": token}


def mock_operator_token(monkeypatch, module, *, user_id: int = 1, valid: bool = True, token: str = TEST_OPERATOR_TOKEN):
    headers = mock_auth_token(monkeypatch, module, user_id=user_id, valid=valid, token=token)
    if hasattr(module, "user_repo"):
        monkeypatch.setattr(module.user_repo, "check_permission", lambda provided_token, required_permission: valid)
    return headers


def mock_node_response(monkeypatch, module, response: dict):
    calls = []

    def _send(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return dict(response)

    monkeypatch.setattr(module, "send", _send)
    return calls


def mock_container_crypto(monkeypatch, module):
    payloads = []

    def _signature(payload):
        payloads.append(json.loads(payload))
        return b"signature"

    def _encryption(payload):
        return payload.encode("utf-8")

    monkeypatch.setattr(module, "signature", _signature)
    monkeypatch.setattr(module, "encryption", _encryption)
    return payloads


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
    return token, {"token": token}


def operator_user_factory(**overrides):
    return create_user(permission=PERMISSION.OPERATOR, **overrides)
