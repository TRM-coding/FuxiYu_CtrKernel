import json

import pytest
from sqlalchemy import select

from ...models.operation_log import OperationLog
from ...utils import mail
from ...services.operation_log_tasks import list_operation_logs
from ..factories import create_container_graph


@pytest.mark.parametrize("outcome", ["success", "failure", "exception"])
def test_single_mail_audits_result_once_without_body_or_config(db_session, monkeypatch, outcome):
    owner, machine, container = create_container_graph()
    calls = []

    def send(**kwargs):
        calls.append(kwargs)
        if outcome == "exception":
            raise ValueError("invalid message")
        return {"ok": outcome == "success", "error": "smtp refused",
                "error_detail": {"smtp_code": 550, "exc_type": "SMTPDataError"}}

    monkeypatch.setattr(mail, "_send_smtp", send)
    result = mail.send(
        to="owner@example.test", subject="disk alert", content="secret-code-123456",
        target_type="container", target_id=container.id, operator_user_id=owner.id,
        detail={"mail_type": "disk_escalation", "name": container.name},
        cc=["cc@example.test"], bcc=["bcc@example.test"],
        attachments=["private-attachment"], config={"password": "secret-password"},
    )
    log = db_session.scalars(select(OperationLog)).one()
    assert log.success is (outcome == "success")
    assert result["ok"] is log.success
    assert log.operation == "send_mail"
    assert log.operator_user_id == owner.id
    assert log.target_id == container.id
    assert log.detail["name"] == container.name
    assert log.detail["machine_id"] == machine.id
    assert log.detail["recipient"] == "owner@example.test"
    assert log.detail["bcc"] == ["bcc@example.test"]
    assert len(calls) == 1
    assert calls[0]["content"] == "secret-code-123456"
    assert "target_id" not in calls[0]
    for private_value in ("secret-code-123456", "secret-password", "private-attachment"):
        assert private_value not in json.dumps(log.detail)


@pytest.mark.parametrize("outcomes", [
    [True, True, True],
    [False, False, False],
    [True, False, True, False],
])
def test_batch_groups_audit_and_keeps_individual_results(db_session, monkeypatch, outcomes):
    messages = [dict(to=email, subject="announcement", content="private body")
                for email in (f"owner{i}@example.test" for i in range(len(outcomes)))]
    messages[0]["bcc"] = ["bcc@example.test"]
    expected_results = [{"ok": ok, "error": f"refused-{i}", "mode": "development" if ok else "smtp"}
                        for i, ok in enumerate(outcomes)]
    calls = []

    def send_batch(batch, **kwargs):
        calls.append(batch)
        return expected_results

    monkeypatch.setattr(mail, "_send_batch_smtp", send_batch)
    results = mail.send_batch(messages, target_type="announcement", target_id=12,
                                   detail={"name": "Maintenance", "mail_type": "announcement"})
    logs = db_session.scalars(select(OperationLog).order_by(OperationLog.id)).all()
    assert len(calls) == 1
    assert len(logs) == len(set(outcomes))
    assert results is expected_results
    for log in logs:
        indices = [i for i, ok in enumerate(outcomes) if ok == log.success]
        entries = log.detail["messages"]
        assert log.detail["batch_total"] == len(messages)
        assert log.detail["message_count"] == len(indices)
        assert [entry["recipient"] for entry in entries] == [messages[i]["to"] for i in indices]
        assert log.target_id == 12
        assert "private body" not in json.dumps(log.detail)
        if 0 in indices:
            assert entries[0]["bcc"] == ["bcc@example.test"]
        if log.success:
            assert all("error_reason" not in entry and entry["mail_mode"] == "development" for entry in entries)
        else:
            assert log.error_reason == "mail_batch_failed"
            assert [entry["error_reason"] for entry in entries] == [f"refused-{i}" for i in indices]
    assert all(log["target_display_name"] == "Maintenance" for log in list_operation_logs()["logs"])


def test_batch_transport_exception_writes_one_failure_group(db_session, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("connection lost")

    monkeypatch.setattr(mail, "_send_batch_smtp", fail)
    messages = [dict(to=email, subject="announcement", content="body")
                for email in ("first@example.test", "second@example.test")]
    results = mail.send_batch(messages)
    assert len(results) == 2
    assert all(not result["ok"] for result in results)
    log = db_session.scalars(select(OperationLog)).one()
    assert log.success is False
    assert log.error_reason == "mail_batch_failed"
    assert log.detail["message_count"] == 2
    assert all(entry["error_reason"] == "connection lost" for entry in log.detail["messages"])


def test_development_mode_is_visible_and_no_extra_transport_attempt(db_session, monkeypatch):
    monkeypatch.setattr(mail, "_send_smtp", lambda **kwargs: {"ok": True, "mode": "development"})
    result = mail.send("owner@example.test", "subject", "body")
    assert result == {"ok": True, "mode": "development"}
    log = db_session.scalars(select(OperationLog)).one()
    assert log.detail["mail_mode"] == "development"


def test_empty_batch_does_not_write_audit(db_session):
    assert mail.send_batch([]) == []
    assert db_session.scalars(select(OperationLog)).all() == []


def test_short_batch_results_still_audit_every_message(db_session, monkeypatch):
    messages = [dict(to=email, subject="announcement", content="body")
                for email in ("first@example.test", "second@example.test")]
    short = [{"ok": True, "to": ["first@example.test"]}]

    monkeypatch.setattr(mail, "_send_batch_smtp", lambda batch, **kwargs: short)
    results = mail.send_batch(messages)

    # 调用方拿到的仍是传输层原样返回，不补不裁
    assert results is short
    logs = db_session.scalars(select(OperationLog).order_by(OperationLog.id)).all()
    assert [log.success for log in logs] == [True, False]
    assert all(log.detail["batch_total"] == 2 and log.detail["result_count"] == 1
               and log.detail["message_count"] == 1 for log in logs)
    # 配对缺失的那封仍进审计，按失败记，不被 zip 静默丢掉
    assert [entry["recipient"] for entry in logs[0].detail["messages"]] == ["first@example.test"]
    assert logs[1].detail["messages"][0]["recipient"] == "second@example.test"
    assert logs[1].detail["messages"][0]["error_reason"] == "result_missing"
