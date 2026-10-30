"""Anvil identity/settings 缺口测试。

测试只在 per-test SQLite 隔离库运行；Node HTTP、SMTP、后台调度是允许替换的
外部边界。目标判定（RBAC、野容器、日志时序、快照派生）使用真实 service/repo
代码路径，不以 monkeypatch 目标函数替代。
"""

from datetime import datetime, timedelta
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import OperationalError
from starlette.testclient import TestClient

from ...constant import ContainerStatus, ROLE
from ...extensions import session_scope
from ...models.authentications import Authentication
from ...models.container_cleanup_reminder import NEVER_REMINDED, ContainerCleanupReminder
from ...models.container_ssh_login import ContainerSSHLogin
from ...models.deleted_container_restore_snapshot import DeletedContainerRestoreSnapshot
from ...models.operation_log import OperationLog
from ...models.registration_code import RegistrationCode
from ...models.user import User
from ...repositories import (
    auth_repo,
    authentications_repo,
    container_cleanup_reminder_repo,
    container_ssh_login_repo,
    image_repo,
    operation_log_repo,
    registration_code_repo,
    user_repo,
    usercontainer_repo,
)
from ...services import container_tasks, machine_tasks, operation_log_tasks, settings_tasks, user_tasks
from ...services.container_module import collaborators as collaborator_utils
from ...services.container_module import node_comms
from ...services.container_module import passwords as password_utils
from ..factories import (
    bind_user_container,
    create_auth,
    create_container,
    create_container_graph,
    create_machine,
    create_user,
)

OPLOG_FIELDS = {
    "id",
    "operator_user_id",
    "operation",
    "target_type",
    "target_id",
    "detail",
    "success",
    "error_reason",
    "created_at",
    "target_name",
    "target_display_name",
    "root_owner",
}


def _issue_code(email: str, code: str = "123456", *, minutes: int = 3) -> None:
    with session_scope() as session:
        registration_code_repo.create_code(
            email=email,
            school_domain=email.rsplit("@", 1)[-1].lower(),
            code=code,
            expires_at=datetime.utcnow() + timedelta(minutes=minutes),
            session=session,
        )


def _run_now(_name, target, *args):
    target(*args)
    return SimpleNamespace(join=lambda: None)


def _bind_group(user: User, codes: list[str], name: str) -> int:
    with session_scope() as session:
        group = auth_repo.ensure_group(name, name, session=session)
        for code in codes:
            auth_repo.ensure_group_entity(group.id, code, session=session)
        auth_repo.ensure_user_group(user.id, group.id, session=session)
        return group.id


def _add_group_entity(group_id: int, code: str) -> None:
    with session_scope() as session:
        auth_repo.ensure_group_entity(group_id, code, session=session)


def _permissions(client: TestClient, token: str) -> dict:
    client.cookies.set("auth_token", token)
    resp = client.get("/api/users/me/permissions")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _list_container_names(client: TestClient, token: str) -> set[str]:
    client.cookies.set("auth_token", token)
    resp = client.post("/api/containers/list_all_container_bref_information", json={})
    assert resp.status_code == 200, resp.text
    return {item["container_name"] for item in resp.json()["containers_info"]}


def _oplog_text(log: OperationLog) -> str:
    return f"{json.dumps(log.detail, ensure_ascii=False)}|{log.error_reason}"


def _node_success(_url, _payload, timeout=5.0):
    return {"success": 1}


def _sqlite_tables(session) -> set[str]:
    return set(session.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).scalars().all())


# ── 认证 ──────────────────────────────────────────────────────────────


def test_login_cleans_expired_tokens_and_issues_new_token(db_session):
    user = create_user(username="login_cleanup_user", password="Password_123")
    db_session.add(
        Authentication(
            token="expired-cleanup-token",
            user_id=user.id,
            expires_at=datetime.utcnow() - timedelta(minutes=5),
        )
    )
    db_session.commit()

    success, returned_user, token = user_tasks.Login("login_cleanup_user", "Password_123")

    assert success is True
    assert returned_user.id == user.id
    assert token
    db_session.expire_all()
    assert db_session.scalars(
        select(Authentication).where(Authentication.token == "expired-cleanup-token")
    ).first() is None
    assert authentications_repo.is_token_valid(token, session=db_session) is True
    assert authentications_repo.is_token_valid("expired-cleanup-token", session=db_session) is False


def test_403_preserves_other_tokens_and_container_state_is_irrelevant(client, db_session):
    user = create_user(username="forbidden_keep_user")
    token_a = create_auth(user, token="forbidden-keep-a").token
    token_b = create_auth(user, token="forbidden-keep-b").token

    client.cookies.set("auth_token", token_a)
    resp = client.get("/api/rbac/matrix")
    assert resp.status_code == 403
    assert resp.json()["error_reason"] == "insufficient_permission"

    assert authentications_repo.is_token_valid(token_a, session=db_session) is True
    assert authentications_repo.is_token_valid(token_b, session=db_session) is True

    _root, _machine, container = create_container_graph(root_user=user)
    container.container_status = ContainerStatus.OFFLINE
    db_session.commit()
    assert authentications_repo.is_token_valid(token_a, session=db_session) is True
    assert authentications_repo.is_token_valid(token_b, session=db_session) is True


def test_internal_runtime_source_gate_uses_real_client_host(app, db_session):
    machine = create_machine()
    token = node_comms._read_internal_token()
    assert token
    payload = {
        "machine_id": machine.id,
        "snapshot": {"token_c": {"runtime_metrics": {"cpu_usage_percent": 1.0}}},
    }

    local = TestClient(app, client=("127.0.0.1", 50001))
    missing = local.post("/api/internal/runtime/containers", json=payload)
    assert missing.status_code == 401
    assert missing.json()["error_reason"] == "invalid_token"

    wrong = local.post(
        "/api/internal/runtime/containers",
        json=payload,
        headers={"X-Internal-Token": "wrong-token"},
    )
    assert wrong.status_code == 401
    assert wrong.json()["error_reason"] == "invalid_token"

    ok = local.post(
        "/api/internal/runtime/containers",
        json=payload,
        headers={"X-Internal-Token": token},
    )
    assert ok.status_code == 200
    assert ok.json()["success"] == 1

    remote = TestClient(app, client=("203.0.113.9", 50002))
    forbidden = remote.post(
        "/api/internal/runtime/containers",
        json=payload,
        headers={"X-Internal-Token": token},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error_reason"] == "forbidden"


def test_internal_runtime_token_is_not_persisted_as_authentication(app, db_session):
    machine = create_machine()
    token = node_comms._read_internal_token()
    assert token
    client = TestClient(app, client=("127.0.0.1", 50003))

    resp = client.post(
        "/api/internal/runtime/machines",
        json={"machine_id": machine.id, "snapshot": {}},
        headers={"X-Internal-Token": token},
    )

    assert resp.status_code == 200
    assert db_session.scalars(select(Authentication)).all() == []


# ── 用户与权限快照 ────────────────────────────────────────────────────


def test_delete_user_real_sole_root_container_blocks_and_keeps_tokens(db_session):
    user = create_user(username="wild_real_owner")
    create_auth(user, token="wild-real-token")
    _root, _machine, container = create_container_graph(root_user=user)

    with pytest.raises(Exception) as excinfo:
        user_tasks.Delete_user(user.id)

    assert getattr(excinfo.value, "wild_containers") == [container.id]
    db_session.expire_all()
    assert db_session.get(User, user.id) is not None
    assert authentications_repo.is_token_valid("wild-real-token", session=db_session) is True


def test_register_api_response_omits_password_hash(client, db_session):
    email = "api_no_hash@bjtu.edu.cn"
    _issue_code(email)

    resp = client.post(
        "/api/register",
        json={
            "username": "api_no_hash",
            "email": email,
            "password": "Password_123",
            "graduation_year": "2026",
            "registration_code": "123456",
        },
    )

    assert resp.status_code == 201, resp.text
    assert "password_hash" not in resp.text
    user = db_session.scalars(select(User).where(User.username == "api_no_hash")).one()
    assert user.password_hash != "Password_123"


def test_bypass_resource_does_not_grant_method_entities(client, db_session):
    user = create_user(username="resource_only_method")
    _bind_group(user, ["bypass_resource"], "resource_only_method_group")
    token = create_auth(user, token="resource-only-method-token").token

    body = _permissions(client, token)
    assert body["container_resource_unrestricted"] is True
    assert body["image_resource_unrestricted"] is True
    entities = set(body["entities"])
    assert "bypass_auth_entity" not in entities
    assert "container:manage" not in entities
    assert "image:manage" not in entities

    client.cookies.set("auth_token", token)
    denied = client.get("/api/rbac/matrix")
    assert denied.status_code == 403
    assert denied.json()["error_reason"] == "insufficient_permission"


def test_container_resource_snapshot_agrees_with_container_list_scope(client, db_session):
    machine = create_machine()
    unbound = create_container(machine=machine, name="scope_unbound")

    method_only = create_user(username="scope_method_only")
    _bind_group(method_only, ["bypass_auth_entity", "container:view"], "scope_method_only_group")

    resource_only = create_user(username="scope_resource_only")
    resource_group = _bind_group(resource_only, ["bypass_resource"], "scope_resource_only_group")

    direct_manage = create_user(username="scope_direct_manage")
    _bind_group(direct_manage, ["container:manage", "container:view"], "scope_direct_manage_group")

    method_token = create_auth(method_only, token="scope-method-token").token
    resource_token = create_auth(resource_only, token="scope-resource-token").token
    direct_token = create_auth(direct_manage, token="scope-direct-token").token

    method_body = _permissions(client, method_token)
    assert method_body["container_resource_unrestricted"] is False
    assert unbound.name not in _list_container_names(client, method_token)

    resource_body = _permissions(client, resource_token)
    assert resource_body["container_resource_unrestricted"] is True
    client.cookies.set("auth_token", resource_token)
    without_view = client.post("/api/containers/list_all_container_bref_information", json={})
    assert without_view.status_code == 403
    _add_group_entity(resource_group, "container:view")
    assert unbound.name in _list_container_names(client, resource_token)

    direct_body = _permissions(client, direct_token)
    assert direct_body["container_resource_unrestricted"] is True
    assert direct_body["image_resource_unrestricted"] is False
    assert unbound.name in _list_container_names(client, direct_token)


def test_permission_snapshot_is_derived_per_request_without_schema_change(client, db_session):
    user = create_user(username="derived_snapshot_user")
    token = create_auth(user, token="derived-snapshot-token").token
    tables_before = _sqlite_tables(db_session)

    assert _permissions(client, token)["container_resource_unrestricted"] is False
    _bind_group(user, ["bypass_resource"], "derived_snapshot_group")
    assert _permissions(client, token)["container_resource_unrestricted"] is True
    with session_scope() as session:
        auth_repo.replace_user_groups(user.id, [], session=session)
    assert _permissions(client, token)["container_resource_unrestricted"] is False
    assert _sqlite_tables(db_session) == tables_before


def test_root_binding_does_not_create_resource_wildcard(client, db_session):
    user = create_user(username="root_binding_user")
    _bind_group(user, ["container:view"], "root_binding_group")
    _root, machine, bound = create_container_graph(root_user=user)
    unbound = create_container(machine=machine, name="root_binding_unbound")
    token = create_auth(user, token="root-binding-token").token

    body = _permissions(client, token)
    assert body["container_resource_unrestricted"] is False
    names = _list_container_names(client, token)
    assert bound.name in names
    assert unbound.name not in names


def test_users_table_has_no_resource_unrestricted_columns(db_session):
    columns = {row[1] for row in db_session.execute(text("PRAGMA table_info(users)")).all()}
    assert "container_resource_unrestricted" not in columns
    assert "image_resource_unrestricted" not in columns


def test_rejected_registration_does_not_create_user_row(db_session):
    def user_count() -> int:
        return int(db_session.scalar(select(func.count()).select_from(User)) or 0)

    def assert_no_user(username: str) -> None:
        db_session.expire_all()
        assert db_session.scalars(select(User).where(User.username == username)).first() is None

    _issue_code("reject_bad_code@bjtu.edu.cn")
    before = user_count()
    success, reason, _user = user_tasks.Register_with_code(
        "reject_bad_code", "reject_bad_code@bjtu.edu.cn", "Password_123", "2026", "bad",
    )
    assert (success, reason) == (False, "registration_code_invalid")
    assert_no_user("reject_bad_code")
    assert user_count() == before

    _issue_code("reject_expired@bjtu.edu.cn", minutes=-5)
    before = user_count()
    success, reason, _user = user_tasks.Register_with_code(
        "reject_expired", "reject_expired@bjtu.edu.cn", "Password_123", "2026", "123456",
    )
    assert (success, reason) == (False, "registration_code_invalid")
    assert_no_user("reject_expired")
    assert user_count() == before

    _issue_code("reject_bad_name@bjtu.edu.cn")
    before = user_count()
    success, reason, _user = user_tasks.Register_with_code(
        "bad-name", "reject_bad_name@bjtu.edu.cn", "Password_123", "2026", "123456",
    )
    assert (success, reason) == (False, "invalid_username")
    assert_no_user("bad-name")
    assert user_count() == before

    _issue_code("reject_nonascii@bjtu.edu.cn")
    before = user_count()
    success, reason, _user = user_tasks.Register_with_code(
        "reject_nonascii", "reject_nonascii@bjtu.edu.cn", "密码123", "2026", "123456",
    )
    assert (success, reason) == (False, "no_none_ascii")
    assert_no_user("reject_nonascii")
    assert user_count() == before

    create_user(username="duplicate_real_name", email="duplicate_real_name@bjtu.edu.cn")
    _issue_code("duplicate_new_email@bjtu.edu.cn")
    before = user_count()
    success, reason, _user = user_tasks.Register_with_code(
        "duplicate_real_name", "duplicate_new_email@bjtu.edu.cn", "Password_123", "2026", "123456",
    )
    assert (success, reason) == (False, "username_exists")
    assert user_count() == before

    create_user(username="duplicate_email_owner", email="duplicate_email_owner@bjtu.edu.cn")
    _issue_code("duplicate_email_owner@bjtu.edu.cn")
    before = user_count()
    success, reason, _user = user_tasks.Register_with_code(
        "duplicate_email_new", "duplicate_email_owner@bjtu.edu.cn", "Password_123", "2026", "123456",
    )
    assert (success, reason) == (False, "email_exists")
    assert user_count() == before


# ── 注册码与设置 ──────────────────────────────────────────────────────


def test_registration_code_stores_hash_not_plaintext(db_session):
    email = "hash_only@bjtu.edu.cn"
    plaintext = "654321"
    _issue_code(email, plaintext)

    row = db_session.scalars(select(RegistrationCode).where(RegistrationCode.email == email)).one()
    assert row.code_hash != plaintext
    assert plaintext not in {row.email, row.school_domain, row.code_hash}
    assert registration_code_repo.verify_code(
        email, plaintext, "bjtu.edu.cn", session=db_session,
    ) is True


def test_expired_registration_code_response_does_not_echo_hash(client, db_session):
    email = "expired_response@bjtu.edu.cn"
    _issue_code(email, minutes=-5)
    row = db_session.scalars(select(RegistrationCode).where(RegistrationCode.email == email)).one()
    code_hash = row.code_hash

    resp = client.post(
        "/api/register",
        json={
            "username": "expired_response",
            "email": email,
            "password": "Password_123",
            "graduation_year": "2026",
            "registration_code": "123456",
        },
    )

    assert resp.status_code == 400
    assert resp.json()["error_reason"] == "registration_code_invalid"
    assert code_hash not in resp.text
    assert db_session.scalars(select(User).where(User.username == "expired_response")).first() is None


def test_stale_registration_transaction_leaves_no_second_user(db_session):
    email = "stale_reader@bjtu.edu.cn"
    _issue_code(email)
    with session_scope(commit=False) as session:
        first = registration_code_repo.find_valid_code(
            email, "123456", "bjtu.edu.cn", session=session,
        )
        assert first is not None
        first_id = first.id
    with session_scope(commit=False) as session:
        second = registration_code_repo.find_valid_code(
            email, "123456", "bjtu.edu.cn", session=session,
        )
        assert second is not None
        second_id = second.id

    with session_scope() as session:
        assert registration_code_repo.consume_code(first_id, session=session) is True
        user_repo.create_user(
            "stale_first", "stale_first@bjtu.edu.cn", "x", "2026", session=session,
        )

    with session_scope() as session:
        if registration_code_repo.consume_code(second_id, session=session):
            user_repo.create_user(
                "stale_second", "stale_second@bjtu.edu.cn", "x", "2026", session=session,
            )

    assert db_session.scalars(select(User).where(User.username == "stale_first")).first() is not None
    assert db_session.scalars(select(User).where(User.username == "stale_second")).first() is None
    row = db_session.scalars(select(RegistrationCode).where(RegistrationCode.email == email)).one()
    assert row.consumed_at is not None


@pytest.mark.parametrize(("value", "fragment"), [(-1, ">= 1"), (101, "<= 100")])
def test_integer_setting_rejects_values_outside_declared_range(db_session, value, fragment):
    key = "container.disk_soft_limit_percent"
    before = settings_tasks.get_setting_value(key)

    with pytest.raises(ValueError, match=fragment):
        settings_tasks.update_settings({key: value})

    assert settings_tasks.get_setting_value(key) == before


# ── 操作日志 ──────────────────────────────────────────────────────────


def test_operation_log_repo_filters_by_target_type_and_id(db_session):
    for target_type, target_id, operation in (
        ("container", 10, "create_container"),
        ("container", 11, "start_container"),
        ("user", 10, "change_password"),
    ):
        operation_log_repo.write(
            session=db_session,
            operation=operation,
            target_type=target_type,
            target_id=target_id,
            detail={},
            success=True,
        )
    db_session.commit()

    rows, _pages = operation_log_repo.list_logs(
        session=db_session, target_type="container", target_id=10,
    )

    assert [(row.target_type, row.target_id) for row in rows] == [("container", 10)]


def test_operation_log_list_keeps_existing_response_fields(db_session):
    operation_log_repo.write(
        session=db_session,
        operation="create_container",
        target_type="container",
        target_id=999999,
        detail={"name": "ghost"},
        success=True,
    )
    db_session.commit()

    row = operation_log_tasks.list_operation_logs(page=1, page_size=10)["logs"][0]

    assert set(row.keys()) == OPLOG_FIELDS


def test_reset_password_success_log_has_target_and_no_secret(db_session, monkeypatch):
    root, _machine, container = create_container_graph()
    target = create_user(username="reset_log_target")
    bind_user_container(target, container, role=ROLE.COLLABORATOR, username=target.username)
    monkeypatch.setattr(password_utils, "spawn_background", _run_now)
    monkeypatch.setattr(node_comms, "send", _node_success)

    result = container_tasks.start_reset_container_password(container.id, target.id, root.id)

    db_session.expire_all()
    logs = list(db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "reset_container_password")
    ).all())
    assert len(logs) == 1
    log = logs[0]
    assert log.success is True
    assert log.target_type == "container"
    assert log.target_id == container.id
    assert log.detail["user_id"] == target.id
    assert log.detail["login_name"] == target.username
    assert result["password"] not in _oplog_text(log)
    assert "credentials" not in log.detail


def test_add_collaborator_success_log_has_user_and_role(db_session, monkeypatch):
    root, _machine, container = create_container_graph()
    target = create_user(username="add_log_target")
    monkeypatch.setattr(collaborator_utils, "spawn_background", _run_now)
    monkeypatch.setattr(node_comms, "send", _node_success)

    result = container_tasks.start_add_collaborator(container.id, target.id, ROLE.ADMIN, root.id)

    db_session.expire_all()
    logs = list(db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "add_collaborator")
    ).all())
    assert len(logs) == 1
    log = logs[0]
    assert log.success is True
    assert log.target_type == "container"
    assert log.target_id == container.id
    assert log.detail["user_id"] == target.id
    assert log.detail["username"] == target.username
    assert log.detail["role"] == ROLE.ADMIN.value
    assert result["password"] not in _oplog_text(log)


def test_root_handover_logs_distinguish_each_step(db_session, monkeypatch):
    root, _machine, container = create_container_graph()
    target = create_user(username="handover_log_target")
    bind_user_container(target, container, role=ROLE.COLLABORATOR, username=target.username)
    monkeypatch.setattr(collaborator_utils, "spawn_background", _run_now)
    monkeypatch.setattr(node_comms, "send", _node_success)

    result = container_tasks.start_root_handover(container.id, target.id, root.id)

    db_session.expire_all()
    logs = list(db_session.scalars(
        select(OperationLog).where(
            OperationLog.operation == "update_collaborator_role",
            OperationLog.success.is_(True),
        )
    ).all())
    assert len(logs) == 2
    by_user = {log.detail["user_id"]: log.detail for log in logs}
    assert by_user[root.id]["old_role"] == ROLE.ROOT.value
    assert by_user[root.id]["new_role"] == ROLE.ADMIN.value
    assert by_user[target.id]["old_role"] == ROLE.COLLABORATOR.value
    assert by_user[target.id]["new_role"] == ROLE.ROOT.value
    assert all(
        password not in json.dumps(detail, ensure_ascii=False)
        for detail in by_user.values()
        for password in (item["password"] for item in result["credentials"])
    )
    assert db_session.scalar(
        select(func.count()).select_from(OperationLog).where(OperationLog.operation == "create_container")
    ) == 0


def test_restore_writes_exactly_one_create_container_log(db_session, monkeypatch):
    root, machine, container = create_container_graph()
    template = image_repo.get_by_id(1, session=db_session)
    assert template is not None
    container.image_id = 1
    container.last_build_at = template.updated_at
    container.bind_mount_path = f"/tmp/anvil_restore_{container.id}"
    db_session.commit()
    monkeypatch.setattr(node_comms, "send", _node_success)

    assert container_tasks.remove_container(container.id, operator_user_id=root.id) is True
    snapshot = db_session.scalars(select(DeletedContainerRestoreSnapshot)).one()
    result = container_tasks.resurrect_container(snapshot.id, operator_user_id=root.id)

    db_session.expire_all()
    logs = list(db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "create_container")
    ).all())
    assert len(logs) == 1
    log = logs[0]
    assert log.success is True
    assert log.target_id == result["container_id"]
    assert log.detail["trigger"] == "resurrect"
    assert result["root_password"] not in _oplog_text(log)


def test_accepted_password_operation_keeps_existing_logs_unchanged(db_session, monkeypatch):
    root, _machine, container = create_container_graph()
    target = create_user(username="accepted_log_target")
    bind_user_container(target, container, role=ROLE.COLLABORATOR, username=target.username)
    baseline = operation_log_repo.write(
        session=db_session,
        operator_user_id=root.id,
        operation="create_container",
        target_type="container",
        target_id=999,
        detail={"marker": "keep"},
        success=True,
    )
    db_session.commit()
    baseline_id = baseline.id
    captured = {}

    def _capture(_name, target_fn, *args):
        captured["target"] = target_fn
        captured["args"] = args
        return SimpleNamespace(join=lambda: None)

    monkeypatch.setattr(password_utils, "spawn_background", _capture)
    monkeypatch.setattr(node_comms, "send", _node_success)

    container_tasks.start_reset_container_password(container.id, target.id, root.id)

    db_session.expire_all()
    assert db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "reset_container_password")
    ).all() == []
    kept = db_session.get(OperationLog, baseline_id)
    assert kept.detail == {"marker": "keep"}

    captured["target"](*captured["args"])
    db_session.expire_all()
    assert len(db_session.scalars(
        select(OperationLog).where(
            OperationLog.operation == "reset_container_password",
            OperationLog.success.is_(True),
        )
    ).all()) == 1
    assert db_session.get(OperationLog, baseline_id).detail == {"marker": "keep"}


def test_reset_failure_writes_exactly_one_redacted_log(db_session, monkeypatch):
    root, _machine, container = create_container_graph()
    target = create_user(username="reset_failure_target")
    bind_user_container(target, container, role=ROLE.COLLABORATOR, username=target.username)
    monkeypatch.setattr(password_utils, "spawn_background", _run_now)
    raw_sentinel = "NODE_RAW_BODY_SENTINEL"
    payloads = []

    def _fail(_url, payload, timeout=5.0):
        payloads.append(payload)
        return {
            "success": 0,
            "error": f"{raw_sentinel} {json.dumps(payload)}",
            "error_reason": raw_sentinel,
        }

    monkeypatch.setattr(node_comms, "send", _fail)
    result = container_tasks.start_reset_container_password(container.id, target.id, root.id)

    db_session.expire_all()
    logs = list(db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "reset_container_password")
    ).all())
    assert len(logs) == 1
    log = logs[0]
    assert log.success is False
    assert log.error_reason == "reset_failed"
    assert log.target_type == "container"
    assert log.target_id == container.id
    assert log.detail["user_id"] == target.id
    assert log.detail["login_name"] == target.username
    text = _oplog_text(log)
    assert raw_sentinel not in text
    assert result["password"] not in text
    assert json.dumps(payloads[0], ensure_ascii=False) not in text


def test_add_collaborator_failure_writes_only_one_log(db_session, monkeypatch):
    root, _machine, container = create_container_graph()
    target = create_user(username="add_failure_target")
    monkeypatch.setattr(collaborator_utils, "spawn_background", _run_now)
    monkeypatch.setattr(
        node_comms,
        "send",
        lambda _url, _payload, timeout=5.0: {"success": 0, "error_reason": "add_failed"},
    )

    result = container_tasks.start_add_collaborator(container.id, target.id, ROLE.COLLABORATOR, root.id)

    db_session.expire_all()
    logs = list(db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "add_collaborator")
    ).all())
    assert len(logs) == 1
    log = logs[0]
    assert log.success is False
    assert log.error_reason == "add_failed"
    assert log.detail["user_id"] == target.id
    assert log.detail["username"] == target.username
    assert result["password"] not in _oplog_text(log)
    assert usercontainer_repo.get_binding(target.id, container.id, session=db_session) is None


def test_unknown_node_result_writes_failure_not_success(db_session, monkeypatch):
    root, _machine, container = create_container_graph()
    target = create_user(username="unknown_result_target")
    bind_user_container(target, container, role=ROLE.COLLABORATOR, username=target.username)
    monkeypatch.setattr(password_utils, "spawn_background", _run_now)
    monkeypatch.setattr(
        node_comms,
        "send",
        lambda _url, _payload, timeout=5.0: {"success": "maybe"},
    )

    result = container_tasks.start_reset_container_password(container.id, target.id, root.id)

    db_session.expire_all()
    logs = list(db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "reset_container_password")
    ).all())
    assert len(logs) == 1
    assert logs[0].success is False
    assert logs[0].error_reason == "reset_failed"
    assert result["password"] not in _oplog_text(logs[0])


def test_operation_log_write_failure_does_not_raise_or_leak_password(db_session, monkeypatch):
    root, _machine, container = create_container_graph()
    target = create_user(username="oplog_failure_target")
    bind_user_container(target, container, role=ROLE.COLLABORATOR, username=target.username)
    calls = []

    def _success(url, payload, timeout=5.0):
        calls.append((url, payload))
        return {"success": 1}

    monkeypatch.setattr(password_utils, "spawn_background", _run_now)
    monkeypatch.setattr(node_comms, "send", _success)
    engine = db_session.get_bind()

    def _fail_oplog_insert(_conn, _cursor, statement, parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("INSERT INTO OPERATION_LOGS"):
            raise OperationalError(statement, parameters, RuntimeError("oplog write failed"))

    event.listen(engine, "before_cursor_execute", _fail_oplog_insert)
    try:
        result = container_tasks.start_reset_container_password(container.id, target.id, root.id)
    finally:
        event.remove(engine, "before_cursor_execute", _fail_oplog_insert)

    assert calls
    assert result["password"]
    assert db_session.scalars(select(OperationLog)).all() == []
    assert all(
        result["password"] not in json.dumps(log.detail, ensure_ascii=False)
        for log in db_session.scalars(select(OperationLog)).all()
    )


# ── SSH 登录记录 ──────────────────────────────────────────────────────


def test_machine_unavailable_deferral_keeps_last_ssh_anchor(db_session):
    _root, machine, container = create_container_graph()
    last_ssh = "2026-01-01T00:00:00"
    container_ssh_login_repo.upsert_last_ssh_login_time(
        machine.id, container.id, last_ssh, session=db_session,
    )
    db_session.commit()
    machine.unavailable_since = datetime.utcnow() - timedelta(hours=3)
    db_session.commit()

    machine_tasks.refresh_unavailable_window(machine.id, session=db_session)
    db_session.commit()

    record = container_ssh_login_repo.get_by_machine_container(
        machine.id, container.id, session=db_session,
    )
    assert record.last_ssh_login_time == last_ssh
    assert record.deferral_seconds is not None
    assert record.deferral_seconds >= 3 * 3600 - 5


def test_new_ssh_login_resets_deferral_and_cleanup_reminder(db_session):
    _root, machine, container = create_container_graph()
    db_session.add(
        ContainerSSHLogin(
            machine_id=machine.id,
            container_id=container.id,
            last_ssh_login_time="2026-01-01T00:00:00",
            deferral_seconds=3600,
        )
    )
    container_cleanup_reminder_repo.mark_sent(
        container.id,
        "12h",
        datetime.utcnow() + timedelta(hours=12),
        "owner@example.test",
        session=db_session,
    )
    db_session.commit()

    container_ssh_login_repo.upsert_last_ssh_login_time(
        machine.id, container.id, "2026-02-01T00:00:00", session=db_session,
    )
    db_session.commit()

    record = container_ssh_login_repo.get_by_machine_container(
        machine.id, container.id, session=db_session,
    )
    reminder = db_session.scalars(
        select(ContainerCleanupReminder).where(ContainerCleanupReminder.container_id == container.id)
    ).one()
    assert record.deferral_seconds == 0
    assert reminder.reminder_key == NEVER_REMINDED
