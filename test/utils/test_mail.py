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


def test_batch_builds_plain_and_html_alternative(db_session, monkeypatch):
    importlib.reload(mail)
    _SMTP.sent = []
    monkeypatch.setattr(mail.smtplib, "SMTP", _SMTP)
    cfg = mail.MailConfig(host="smtp.example.test", password="real-password",
                          use_tls=False, use_ssl=False)
    results = mail.send_batch(
        [dict(to="to@example.test", subject="subject", content="plain body\n",
              html_content="<p>html body</p>")],
        config=cfg,
    )

    assert results[0]["ok"] is True
    msg = _SMTP.sent[0][0]
    assert msg.get_content_type() == "multipart/alternative"
    parts = msg.get_payload()
    assert [part.get_content_type() for part in parts] == ["text/plain", "text/html"]
    assert msg.get_body(("plain",)).get_content() == "plain body\n"
    assert msg.get_body(("html",)).get_content().rstrip("\n") == "<p>html body</p>"


def test_batch_without_html_keeps_plain_text(db_session, monkeypatch):
    importlib.reload(mail)
    _SMTP.sent = []
    monkeypatch.setattr(mail.smtplib, "SMTP", _SMTP)
    cfg = mail.MailConfig(host="smtp.example.test", password="real-password",
                          use_tls=False, use_ssl=False)
    results = mail.send_batch(
        [dict(to="to@example.test", subject="subject", content="plain only\n")],
        config=cfg,
    )

    assert results[0]["ok"] is True
    msg = _SMTP.sent[0][0]
    assert msg.get_content_type() == "text/plain"
    assert msg.get_content() == "plain only\n"
    assert not msg.is_multipart()


def test_send_without_html_remains_plain_text(db_session, monkeypatch):
    importlib.reload(mail)
    _SMTP.sent = []
    monkeypatch.setattr(mail.smtplib, "SMTP", _SMTP)
    cfg = mail.MailConfig(host="smtp.example.test", password="real-password",
                          use_tls=False, use_ssl=False)

    result = mail.send("to@example.test", "subject", "plain body\n", config=cfg)

    assert result["ok"] is True
    msg = _SMTP.sent[0][0]
    assert msg.get_content_type() == "text/plain"
    assert msg.get_content() == "plain body\n"
    assert not msg.is_multipart()


def test_batch_html_with_attachment_keeps_alternative_first(db_session, monkeypatch, tmp_path):
    importlib.reload(mail)
    _SMTP.sent = []
    monkeypatch.setattr(mail.smtplib, "SMTP", _SMTP)
    attachment = tmp_path / "note.txt"
    attachment.write_text("attachment", encoding="utf-8")
    cfg = mail.MailConfig(host="smtp.example.test", password="real-password",
                          use_tls=False, use_ssl=False)
    results = mail.send_batch(
        [dict(to="to@example.test", subject="subject", content="plain body\n",
              html_content="<p>html body</p>", attachments=[str(attachment)])],
        config=cfg,
    )

    assert results[0]["ok"] is True
    msg = _SMTP.sent[0][0]
    assert msg.get_content_type() == "multipart/mixed"
    parts = msg.get_payload()
    assert [part.get_content_type() for part in parts] == [
        "multipart/alternative",
        "application/octet-stream",
    ]
    alternative = parts[0]
    assert [part.get_content_type() for part in alternative.get_payload()] == [
        "text/plain",
        "text/html",
    ]
    assert alternative.get_payload()[0].get_content() == "plain body\n"
    assert alternative.get_payload()[1].get_content().rstrip("\n") == "<p>html body</p>"
    assert parts[1].get_filename() == "note.txt"
