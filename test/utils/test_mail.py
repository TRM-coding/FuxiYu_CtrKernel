import importlib

from sqlalchemy import select

from ...models.operation_log import OperationLog
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


def test_mail_send_empty_recipient_returns_audited_failure(db_session, monkeypatch):
    importlib.reload(mail)
    _SMTP.sent = []
    monkeypatch.setattr(mail.smtplib, "SMTP", _SMTP)
    result = mail.send([], "subject", "content")
    assert result["ok"] is False
    assert result["error"] == "to must not be empty"
    assert _SMTP.sent == []
    log = db_session.scalars(select(OperationLog)).one()
    assert log.success is False
    assert log.error_reason == result["error"]


def test_batch_reuses_connection_and_audits_groups(db_session, monkeypatch):
    importlib.reload(mail)
    connections = []
    attempted = []

    class _MixedSMTP(_SMTP):
        def __init__(self, *args, **kwargs):
            connections.append(self)

        def send_message(self, msg, from_addr=None, to_addrs=None):
            attempted.append(to_addrs)
            if to_addrs == ["fail@example.test"]:
                raise RuntimeError("smtp refused")

    monkeypatch.setattr(mail.smtplib, "SMTP", _MixedSMTP)
    monkeypatch.setattr(mail.time, "sleep", lambda seconds: None)
    cfg = mail.MailConfig(host="smtp.example.test", password="real-password",
                          use_tls=False, use_ssl=False)
    messages = [dict(to=recipient, subject="subject", content="private body")
                for recipient in ("first@example.test", "fail@example.test", "last@example.test")]

    results = mail.send_batch(messages, config=cfg)

    assert len(connections) == 1
    assert attempted == [[message["to"]] for message in messages]
    assert [result["ok"] for result in results] == [True, False, True]
    logs = db_session.scalars(select(OperationLog).order_by(OperationLog.id)).all()
    assert len(logs) == 2
    assert [(log.success, log.detail["message_count"]) for log in logs] == [(True, 2), (False, 1)]
    assert logs[1].detail["messages"][0]["error_reason"] == "smtp refused"
