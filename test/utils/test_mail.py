import pytest
import importlib

from ...utils import mail


class _SMTP:
    sent = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def ehlo(self):
        return None

    def starttls(self):
        return None

    def login(self, username, password):
        return None

    def send_message(self, msg, from_addr=None, to_addrs=None):
        self.sent.append((msg, from_addr, to_addrs))


def test_mail_send_success_with_mock_smtp(monkeypatch):
    importlib.reload(mail)
    _SMTP.sent = []
    monkeypatch.setattr(mail.smtplib, "SMTP", _SMTP)
    cfg = mail.MailConfig(
        host="smtp.example.com",
        port=25,
        username="u",
        password="real-password",
        sender="sender@example.com",
        use_tls=False,
        use_ssl=False,
    )

    result = mail.send("to@example.com", "subject", "content", config=cfg)

    assert result["ok"] is True
    assert _SMTP.sent[0][2] == ["to@example.com"]


def test_mail_send_failure_with_mock_smtp_exception(monkeypatch):
    importlib.reload(mail)
    class _FailSMTP(_SMTP):
        def send_message(self, *args, **kwargs):
            raise RuntimeError("smtp failed")

    monkeypatch.setattr(mail.smtplib, "SMTP", _FailSMTP)
    cfg = mail.MailConfig(
        host="smtp.example.com",
        port=25,
        username="u",
        password="real-password",
        sender="sender@example.com",
        use_tls=False,
        use_ssl=False,
    )

    result = mail.send("to@example.com", "subject", "content", config=cfg)

    assert result["ok"] is False
    assert "smtp failed" in result["error"]


def test_mail_send_empty_recipient_raises():
    importlib.reload(mail)
    with pytest.raises(ValueError):
        mail.send([], "subject", "content")
