"""容器密码交付合同测试（按 test-plan 的 contract test 命名）。"""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from ...api import container_api, deps
from ...constant import ContainerStatus, MachineStatus, ROLE
from ...models.containers import Container
from ...models.operation_log import OperationLog
from ...models.usercontainer import UserContainer
from ...repositories import usercontainer_repo
from ...services import container_tasks
from ...services.container_module import collaborators as collaborator_utils
from ...services.container_module import passwords as password_utils
from ...services.image_tasks import ImageUsability
from ..factories import bind_user_container, create_container_graph, create_user


def _run_now(name, target, *args):
    target(*args)
    return SimpleNamespace(join=lambda: None)


def _auth(monkeypatch, user_id=1):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: True)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: user_id)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_entity", lambda uid, code: True)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_resource", lambda uid, rtype, rid: True)
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.repositories.containers_repo.get_machine_id_by_container_id",
        lambda cid, session: 1,
    )


def _root_user_ids(container_id, db_session):
    db_session.expire_all()
    rows = db_session.scalars(
        select(UserContainer).where(UserContainer.container_id == container_id)
    ).all()
    return [
        row.user_id for row in rows
        if getattr(row.role, "value", row.role) == ROLE.ROOT.value
    ]


def _assert_no_password_in_logs_or_files(db_session, passwords):
    db_session.expire_all()
    logs = list(db_session.scalars(select(OperationLog)).all())
    for log in logs:
        text = f"{log.detail}|{log.error_reason}"
        for password in passwords:
            assert password not in text
    log_dir = Path(os.environ["CTRL_LOG_DIR"])
    log_files = [path for path in log_dir.rglob("*") if path.is_file()]
    assert log_files
    for log_file in log_files:
        text = log_file.read_text(encoding="utf-8", errors="ignore")
        for password in passwords:
            assert password not in text


def _mock_image(monkeypatch):
    build = SimpleNamespace(
        payload={"image_tag": "fuxi/contract:tag"},
        version_at=None,
        dockerfile_parts=None,
    )
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.image_tasks.Can_use_image_for_container",
        lambda uid, iid: ImageUsability.OK,
    )
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.image_tasks.resolve_image_build",
        lambda iid, mid: build,
    )


def test_create_restore_credentials_contract(client, monkeypatch, db_session, container_info, mock_node_send):
    original_create = container_tasks.Create_container
    # 创建成功：顶层 root_password + accepted/credentials + no-store
    _auth(monkeypatch)
    _mock_image(monkeypatch)
    captured = {}

    def _create(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(container_api.container_service, "Create_container", _create)
    resp = client.post(
        "/api/containers/create_container",
        json={"owner_user_id": 1, "machine_id": 1, "image_id": 1,
              "container": {"CPU_NUMBER": 1, "MEMORY": 1, "NAME": "pwd_contract"}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] == 1
    assert body["accepted"] is True
    assert len(body["credentials"]) == 1
    assert body["credentials"][0]["login_name"] == "root"
    assert body["credentials"][0]["password"]
    assert resp.headers["Cache-Control"] == "no-store"
    assert captured["root_password"] == body["credentials"][0]["password"]
    assert captured["root_password"] != "owner123"

    # 创建失败：没有凭据/密码
    def _fail(**kwargs):
        raise container_tasks.NodeServiceError("node failed", reason="create_failed")

    monkeypatch.setattr(container_api.container_service, "Create_container", _fail)
    fail = client.post(
        "/api/containers/create_container",
        json={"owner_user_id": 1, "machine_id": 1, "image_id": 1,
              "container": {"CPU_NUMBER": 1, "MEMORY": 1, "NAME": "pwd_fail"}},
    )
    assert fail.status_code == 500
    assert "credentials" not in fail.json()

    # 恢复成功：root 一项
    monkeypatch.setattr(
        container_api.container_service, "resurrect_container",
        lambda **kwargs: {"container_id": 9, "root_password": "RestorePwd_123"},
    )
    restored = client.post("/api/containers/resurrect_container", json={"deleted_id": 3})
    assert restored.status_code == 200, restored.text
    rb = restored.json()
    assert rb["accepted"] is True
    assert rb["credentials"] == [{"login_name": "root", "password": "RestorePwd_123"}]
    assert restored.headers["Cache-Control"] == "no-store"

    # requires_choice：不返回凭据
    monkeypatch.setattr(
        container_api.container_service, "resurrect_container",
        lambda **kwargs: {"requires_choice": True, "container_id": None,
                          "snapshot": {"dockerfile": "a"}, "template": {"dockerfile": "b"},
                          "sections": []},
    )
    choice = client.post("/api/containers/resurrect_container", json={"deleted_id": 3})
    assert choice.status_code == 200
    cb = choice.json()
    assert cb["requires_choice"] is True
    assert cb["accepted"] is False
    assert cb["credentials"] == []

    # Service 未显式给密码也必须生成非默认值
    monkeypatch.setattr(container_api.container_service, "Create_container", original_create)
    root, machine, _container = create_container_graph()
    calls = mock_node_send({"success": 1})
    assert container_tasks.Create_container(root.id, machine.id, container_info) is True
    sent = calls[0]["payload"]
    assert sent["root_password"]
    assert sent["root_password"] != f"{root.username}123"


def test_add_collaborator_password_contract(client, db_session, container_graph, mock_node_send, monkeypatch):
    root, _machine, container = container_graph
    calls = mock_node_send({"success": 1})
    monkeypatch.setattr(collaborator_utils, "spawn_background", _run_now)

    collab = create_user(username="add_pwd_collab")
    result = container_tasks.start_add_collaborator(
        container_id=container.id, user_id=collab.id, role=ROLE.COLLABORATOR,
        operator_user_id=root.id,
    )
    assert result["login_name"] == collab.username
    assert result["password"]
    assert calls[0]["payload"]["config"]["password"] == result["password"]
    assert calls[0]["payload"]["config"]["password"] != "add_pwd_collab123"
    binding = usercontainer_repo.get_binding(collab.id, container.id, session=db_session)
    assert binding and getattr(binding["role"], "value", binding["role"]) == ROLE.COLLABORATOR.value
    logs = list(db_session.scalars(select(OperationLog).where(OperationLog.operation == "add_collaborator")).all())
    assert len(logs) == 1
    assert result["password"] not in str(logs[0].detail)

    admin = create_user(username="add_pwd_admin")
    result2 = container_tasks.start_add_collaborator(
        container_id=container.id, user_id=admin.id, role=ROLE.ADMIN,
        operator_user_id=root.id,
    )
    assert result2["login_name"] == admin.username
    assert calls[1]["payload"]["config"]["password"] == result2["password"]

    # Node 失败：已受理返回凭据，但不写绑定/成功日志
    failed_user = create_user(username="add_pwd_failed")
    mock_node_send({"success": 0, "error_reason": "add_failed"})
    failed_result = container_tasks.start_add_collaborator(
        container_id=container.id, user_id=failed_user.id, role=ROLE.COLLABORATOR,
        operator_user_id=root.id,
    )
    assert failed_result["password"]
    assert usercontainer_repo.get_binding(failed_user.id, container.id, session=db_session) is None
    failed_logs = list(db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "add_collaborator", OperationLog.success.is_(False))
    ).all())
    assert failed_logs
    assert all(failed_result["password"] not in str(log.detail) for log in failed_logs)

    # 前置校验失败：离线容器不生成密码/不调 Node
    container.container_status = ContainerStatus.OFFLINE
    db_session.commit()
    calls.clear()
    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.start_add_collaborator(
            container_id=container.id, user_id=create_user().id, role=ROLE.COLLABORATOR,
            operator_user_id=root.id,
        )
    assert excinfo.value.reason == "container_offline"
    assert calls == []

    # API 受理响应：201 + accepted + 一项凭据 + no-store
    original_start = container_tasks.start_add_collaborator
    _auth(monkeypatch)
    monkeypatch.setattr(
        container_api.container_service, "start_add_collaborator",
        lambda **kwargs: {"login_name": "api_add", "password": "ApiAddPwd"},
    )
    resp = client.post("/api/containers/add_collaborator",
                       json={"container_id": container.id, "user_id": 99, "role": "ADMIN"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["accepted"] is True
    assert resp.json()["credentials"] == [{"login_name": "api_add", "password": "ApiAddPwd"}]
    assert resp.headers["Cache-Control"] == "no-store"
    monkeypatch.setattr(container_api.container_service, "start_add_collaborator", original_start)


def test_restore_accounts_password_contract(db_session, container_graph, container_info, mock_node_send):
    root, machine, _container = container_graph
    container_info.NAME = "restore_pwd_container"
    collaborator = create_user(username="restore_pwd_user")
    accounts = [{
        "user_id": collaborator.id,
        "system_username": collaborator.username,
        "container_username": collaborator.username,
        "role": ROLE.COLLABORATOR.value,
    }]
    original = [dict(item) for item in accounts]
    calls = mock_node_send({"success": 1})

    assert container_tasks.Create_container(
        root.id, machine.id, container_info, restore_accounts=accounts,
    ) is True
    sent = calls[0]["payload"]["restore_accounts"]
    assert len(sent) == 1
    assert sent[0]["password"]
    assert sent[0]["password"] != f"{collaborator.username}123"
    assert accounts == original  # 不把瞬时密码写回调用方/快照

    # Node 拒绝时不回退弱默认值
    container_info.NAME = "restore_pwd_container_fail"
    calls = mock_node_send({"success": 0, "error_reason": "bad_restore_password"})
    with pytest.raises(container_tasks.NodeServiceError):
        container_tasks.Create_container(
            root.id, machine.id, container_info, restore_accounts=accounts,
        )
    assert calls[0]["payload"]["restore_accounts"][0]["password"] != f"{collaborator.username}123"


def test_reset_permission_contract(client, monkeypatch, db_session, container_graph, mock_node_send):
    original_reset = container_tasks.start_reset_container_password
    root, machine, container = container_graph
    collaborator = create_user(username="reset_contract_user")
    bind_user_container(collaborator, container, role=ROLE.COLLABORATOR, username="reset_contract_user")
    monkeypatch.setattr(password_utils, "spawn_background", _run_now)

    # API 成功：accepted + 一项凭据 + no-store
    _auth(monkeypatch)
    monkeypatch.setattr(
        container_api.container_service, "start_reset_container_password",
        lambda **kwargs: {"login_name": "reset_contract_user", "password": "ResetPwd_API"},
    )
    resp = client.post("/api/containers/reset_container_password",
                       json={"container_id": container.id, "user_id": collaborator.id})
    assert resp.status_code == 200, resp.text
    assert resp.json()["accepted"] is True
    assert resp.json()["credentials"] == [{"login_name": "reset_contract_user", "password": "ResetPwd_API"}]
    assert resp.headers["Cache-Control"] == "no-store"

    # 仅实体通配/无资源权限：403
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_entity", lambda uid, code: True)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_resource", lambda uid, rtype, rid: False)
    denied = client.post("/api/containers/reset_container_password",
                         json={"container_id": container.id, "user_id": collaborator.id})
    assert denied.status_code == 403
    assert denied.json()["error_reason"] == "resource_access_denied"

    # 恢复资源放行（模拟资源层）
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_resource", lambda uid, rtype, rid: True)

    # 额外字段：400
    extra = client.post("/api/containers/reset_container_password",
                        json={"container_id": container.id, "user_id": collaborator.id, "login_name": "x"})
    assert extra.status_code == 400
    assert extra.json()["error_reason"] == "invalid_payload"

    # 错误 reason 映射且不拼原始错误体
    for reason, expected in (("not_found", 404), ("target_not_bound", 409), ("internal_error", 500)):
        def _raise(reason=reason, **kwargs):
            raise container_tasks.NodeServiceError("raw node body SECRET", reason=reason)

        monkeypatch.setattr(container_api.container_service, "start_reset_container_password", _raise)
        err = client.post("/api/containers/reset_container_password",
                          json={"container_id": container.id, "user_id": collaborator.id})
        assert err.status_code == expected, reason
        assert "SECRET" not in str(err.json())

    # Service：ROOT 绑定重置协作者，login_name 取绑定 username
    monkeypatch.setattr(container_api.container_service, "start_reset_container_password", original_reset)
    calls = mock_node_send({"success": 1})
    result = container_tasks.start_reset_container_password(
        container_id=container.id, user_id=collaborator.id, operator_user_id=root.id,
    )
    assert result["login_name"] == "reset_contract_user"
    assert calls[0]["payload"]["config"]["user_name"] == "reset_contract_user"
    assert calls[0]["payload"]["config"]["password"] == result["password"]

    # ROOT 绑定固定 root
    calls.clear()
    root_result = container_tasks.start_reset_container_password(
        container_id=container.id, user_id=root.id, operator_user_id=root.id,
    )
    assert root_result["login_name"] == "root"
    assert calls[0]["payload"]["config"]["user_name"] == "root"

    # 非 ROOT 绑定 username=root / 未绑定 / 机器离线 / 容器离线
    bad_user = create_user(username="reset_bad_user")
    bind_user_container(bad_user, container, role=ROLE.COLLABORATOR, username="root")
    with pytest.raises(container_tasks.NodeServiceError) as exc:
        container_tasks.start_reset_container_password(container.id, bad_user.id, root.id)
    assert exc.value.reason == "invalid_target_account"

    with pytest.raises(container_tasks.NodeServiceError) as exc:
        container_tasks.start_reset_container_password(container.id, create_user().id, root.id)
    assert exc.value.reason == "target_not_bound"

    machine.machine_status = MachineStatus.OFFLINE
    db_session.commit()
    with pytest.raises(container_tasks.NodeServiceError) as exc:
        container_tasks.start_reset_container_password(container.id, collaborator.id, root.id)
    assert exc.value.reason == "machine_offline"
    machine.machine_status = MachineStatus.ONLINE
    container.container_status = ContainerStatus.OFFLINE
    db_session.commit()
    with pytest.raises(container_tasks.NodeServiceError) as exc:
        container_tasks.start_reset_container_password(container.id, collaborator.id, root.id)
    assert exc.value.reason == "container_offline"


def test_root_handover_preflight_contract(
    db_session, container_graph_with_collaborator, mock_node_send, monkeypatch,
):
    root, collaborator, machine, container = container_graph_with_collaborator
    calls = mock_node_send({"success": 1})
    generated = []
    monkeypatch.setattr(
        collaborator_utils, "generate_container_password",
        lambda: generated.append(True) or "NeverUsedPwd_123",
    )
    monkeypatch.setattr(collaborator_utils, "spawn_background", _run_now)

    # 目标未绑定
    with pytest.raises(container_tasks.NodeServiceError) as exc:
        container_tasks.start_root_handover(container.id, create_user().id, root.id)
    assert exc.value.reason == "target_not_bound"

    # 容器离线
    container.container_status = ContainerStatus.OFFLINE
    db_session.commit()
    with pytest.raises(container_tasks.NodeServiceError) as exc:
        container_tasks.start_root_handover(container.id, collaborator.id, root.id)
    assert exc.value.reason == "container_offline"

    # 机器离线
    container.container_status = ContainerStatus.ONLINE
    machine.machine_status = MachineStatus.OFFLINE
    db_session.commit()
    with pytest.raises(container_tasks.NodeServiceError) as exc:
        container_tasks.start_root_handover(container.id, collaborator.id, root.id)
    assert exc.value.reason == "machine_offline"

    # 旧 ROOT 的系统用户名不可用（与保留账号 root 冲突）
    bad_root = create_user(username="root")
    _bad_root, _bad_machine, bad_container = create_container_graph(root_user=bad_root)
    bad_target = create_user(username="handover_bad_target")
    bind_user_container(bad_target, bad_container, role=ROLE.COLLABORATOR, username=bad_target.username)
    with pytest.raises(container_tasks.NodeServiceError) as exc:
        container_tasks.start_root_handover(bad_container.id, bad_target.id, bad_root.id)
    assert exc.value.reason == "invalid_root_owner_account"

    assert generated == []
    assert calls == []


def test_role_change_semantics_contract(db_session, container_graph_with_collaborator, mock_node_send, monkeypatch):
    root, collaborator, _machine, container = container_graph_with_collaborator
    monkeypatch.setattr(collaborator_utils, "spawn_background", _run_now)
    calls = mock_node_send({"success": 1})

    # 普通非 ROOT 互换：同步、无密码
    assert container_tasks.update_role(container.id, collaborator.id, ROLE.ADMIN, root.id) is True
    assert "password" not in calls[0]["payload"]["config"]
    assert "root_password" not in calls[0]["payload"]["config"]

    # ROOT 降 ADMIN：生成独立账号密码并返回一项凭据
    calls.clear()
    demote = container_tasks.start_root_demotion(container.id, root.id, root.id)
    assert demote["credentials"] and len(demote["credentials"]) == 1
    assert demote["credentials"][0]["login_name"] == root.username
    assert calls[0]["payload"]["config"]["password"] == demote["credentials"][0]["password"]
    binding = usercontainer_repo.get_binding(root.id, container.id, session=db_session)
    assert getattr(binding["role"], "value", binding["role"]) == ROLE.ADMIN.value
    assert binding["username"] == root.username


def test_root_handover_contract(db_session, mock_node_send, monkeypatch):
    root, machine, container = create_container_graph()
    target = create_user(username="handover_target")
    bind_user_container(target, container, role=ROLE.COLLABORATOR, username=target.username)
    monkeypatch.setattr(collaborator_utils, "spawn_background", _run_now)
    calls = mock_node_send({"success": 1})

    result = container_tasks.start_root_handover(container.id, target.id, root.id)
    assert len(result["credentials"]) == 2
    assert result["credentials"][0]["login_name"] == "root"
    assert result["credentials"][1]["login_name"] == root.username
    assert result["credentials"][0]["password"] != result["credentials"][1]["password"]
    assert [c["payload"]["config"]["updated_role"] for c in calls] == ["admin", "root"]
    assert calls[0]["payload"]["config"]["user_name"] == root.username
    assert calls[0]["payload"]["config"]["password"] == result["credentials"][1]["password"]
    assert calls[1]["payload"]["config"]["root_password"] == result["credentials"][0]["password"]
    assert all("transfer_root" not in c["payload"]["config"] for c in calls)
    old_binding = usercontainer_repo.get_binding(root.id, container.id, session=db_session)
    new_binding = usercontainer_repo.get_binding(target.id, container.id, session=db_session)
    assert getattr(old_binding["role"], "value", old_binding["role"]) == ROLE.ADMIN.value
    assert old_binding["username"] == root.username
    assert getattr(new_binding["role"], "value", new_binding["role"]) == ROLE.ROOT.value
    assert new_binding["username"] == "root"
    assert _root_user_ids(container.id, db_session) == [target.id]

    # 历史多 ROOT：root + 每个旧 ROOT 一项，逐个降级，目标成为唯一 ROOT
    root2, machine2, container2 = create_container_graph()
    target2 = create_user(username="handover_target2")
    old2 = create_user(username="handover_old2")
    bind_user_container(target2, container2, role=ROLE.COLLABORATOR, username=target2.username)
    bind_user_container(old2, container2, role=ROLE.ROOT, username="root")
    calls = mock_node_send({"success": 1})
    result2 = container_tasks.start_root_handover(container2.id, target2.id, root2.id)
    assert len(result2["credentials"]) == 3
    assert {c["login_name"] for c in result2["credentials"]} == {"root", root2.username, old2.username}
    assert len({c["password"] for c in result2["credentials"]}) == 3
    roles2 = [c["payload"]["config"]["updated_role"] for c in calls]
    assert len(calls) == 3
    assert roles2[-1] == "root"
    assert all(role == "admin" for role in roles2[:-1])
    assert succeeded_binding_role(container2.id, root2.id, db_session) == ROLE.ADMIN.value
    assert succeeded_binding_role(container2.id, old2.id, db_session) == ROLE.ADMIN.value
    assert succeeded_binding_role(container2.id, target2.id, db_session) == ROLE.ROOT.value
    assert _root_user_ids(container2.id, db_session) == [target2.id]

    # 调用者本身是旧 ROOT：后台仍完成后续步骤
    root3, machine3, container3 = create_container_graph()
    target3 = create_user(username="handover_target3")
    bind_user_container(target3, container3, role=ROLE.COLLABORATOR, username=target3.username)
    calls = mock_node_send({"success": 1})
    result3 = container_tasks.start_root_handover(container3.id, target3.id, root3.id)
    assert len(result3["credentials"]) == 2
    assert succeeded_binding_role(container3.id, target3.id, db_session) == ROLE.ROOT.value
    assert _root_user_ids(container3.id, db_session) == [target3.id]


def succeeded_binding_role(container_id, user_id, db_session):
    binding = usercontainer_repo.get_binding(user_id, container_id, session=db_session)
    return getattr(binding["role"], "value", binding["role"])


def _graph_with_target():
    root, machine, container = create_container_graph()
    target = create_user()
    bind_user_container(target, container, role=ROLE.COLLABORATOR, username=target.username)
    return root, machine, container, target


def _sequence_node(monkeypatch, responses):
    calls = []

    def _send(url, payload, timeout=5.0):
        calls.append({"url": url, "payload": payload, "timeout": timeout})
        return dict(responses[min(len(calls) - 1, len(responses) - 1)])

    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.container_module.node_comms.send", _send,
    )
    return calls


def test_root_handover_steps_contract(db_session, monkeypatch):
    monkeypatch.setattr(collaborator_utils, "spawn_background", _run_now)

    # 两步成功：各一条真实日志
    root, _machine, container, target = _graph_with_target()
    calls = _sequence_node(monkeypatch, [{"success": 1}, {"success": 1}])
    result = container_tasks.start_root_handover(container.id, target.id, root.id)
    assert len(result["credentials"]) == 2
    assert len(calls) == 2
    assert [c["payload"]["config"]["updated_role"] for c in calls] == ["admin", "root"]
    assert all("transfer_root" not in c["payload"]["config"] for c in calls)
    logs = list(db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "update_collaborator_role",
                                   OperationLog.success.is_(True))
    ).all())
    assert len(logs) == 2
    assert all("password" not in str(log.detail).lower() for log in logs)

    # 第一步失败：不继续第二步
    root2, _m2, container2, target2 = _graph_with_target()
    calls = _sequence_node(monkeypatch, [{"success": 0, "error_reason": "admin_step_failed"}])
    container_tasks.start_root_handover(container2.id, target2.id, root2.id)
    assert len(calls) == 1
    assert succeeded_binding_role(container2.id, target2.id, db_session) == ROLE.COLLABORATOR.value

    # 历史多 ROOT：任一旧 ROOT 降级失败也立即停止，不提拔目标
    root2b, _m2b, container2b, target2b = _graph_with_target()
    historic_root = create_user(username="historic_root_demote_fail")
    bind_user_container(historic_root, container2b, role=ROLE.ROOT, username="root")
    calls = _sequence_node(
        monkeypatch,
        [{"success": 1}, {"success": 0, "error_reason": "second_admin_step_failed"}],
    )
    container_tasks.start_root_handover(container2b.id, target2b.id, root2b.id)
    assert len(calls) == 2
    assert [c["payload"]["config"]["updated_role"] for c in calls] == ["admin", "admin"]
    assert succeeded_binding_role(container2b.id, target2b.id, db_session) == ROLE.COLLABORATOR.value
    assert len(_root_user_ids(container2b.id, db_session)) == 1

    # 第二步失败：旧 ROOT 已 ADMIN 保留，目标不记 ROOT 成功
    root3, _m3, container3, target3 = _graph_with_target()
    calls = _sequence_node(monkeypatch, [{"success": 1}, {"success": 0, "error_reason": "root_step_failed"}])
    container_tasks.start_root_handover(container3.id, target3.id, root3.id)
    assert len(calls) == 2
    assert succeeded_binding_role(container3.id, root3.id, db_session) == ROLE.ADMIN.value
    assert succeeded_binding_role(container3.id, target3.id, db_session) == ROLE.COLLABORATOR.value
    fail_logs = list(db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "update_collaborator_role",
                                   OperationLog.success.is_(False))
    ).all())
    assert fail_logs

    # 绑定更新失败也停止后续
    root4, _m4, container4, target4 = _graph_with_target()
    calls = _sequence_node(monkeypatch, [{"success": 1}, {"success": 1}])
    original_update = collaborator_utils._update_collaborator_binding
    seen = {"n": 0}

    def _fail_second(*args, **kwargs):
        seen["n"] += 1
        if seen["n"] >= 2:
            return False
        return original_update(*args, **kwargs)

    monkeypatch.setattr(collaborator_utils, "_update_collaborator_binding", _fail_second)
    container_tasks.start_root_handover(container4.id, target4.id, root4.id)
    assert len(calls) == 2
    assert succeeded_binding_role(container4.id, root4.id, db_session) == ROLE.ADMIN.value
    assert succeeded_binding_role(container4.id, target4.id, db_session) == ROLE.COLLABORATOR.value
    monkeypatch.setattr(collaborator_utils, "_update_collaborator_binding", original_update)

    # 后台 guard 失败：不调 Node，只写失败
    root5, _m5, container5, target5 = _graph_with_target()
    captured = {}

    def _capture(name, target, *args):
        captured["target"], captured["args"] = target, args
        return SimpleNamespace(join=lambda: None)

    monkeypatch.setattr(collaborator_utils, "spawn_background", _capture)
    calls = _sequence_node(monkeypatch, [{"success": 1}])
    container_tasks.start_root_handover(container5.id, target5.id, root5.id)
    container5.container_status = ContainerStatus.OFFLINE
    db_session.commit()
    captured["target"](*captured["args"])
    assert calls == []
    assert succeeded_binding_role(container5.id, target5.id, db_session) == ROLE.COLLABORATOR.value


def test_delete_user_root_password_contract(db_session, monkeypatch):
    from ...services import user_tasks

    root, _machine, container, target = _graph_with_target()
    calls = _sequence_node(monkeypatch, [{"success": 1}, {"success": 1}, {"success": 1}])
    assert user_tasks.Delete_user(root.id) is True
    assert calls[0]["payload"]["config"]["updated_role"] == "root"
    assert calls[0]["payload"]["config"]["root_password"]
    assert calls[0]["payload"]["config"]["root_password"] != f"{root.username}123"
    assert "transfer_root" not in calls[0]["payload"]["config"]
    assert succeeded_binding_role(container.id, target.id, db_session) == ROLE.ROOT.value

    # 内部提升失败不回退弱密码：删除失败，用户保留
    root2, _m2, container2, target2 = _graph_with_target()
    calls = _sequence_node(monkeypatch, [{"success": 0, "error_reason": "transfer_root_failed"}])
    assert user_tasks.Delete_user(root2.id) is False
    assert calls[0]["payload"]["config"]["root_password"] != f"{root2.username}123"
    assert usercontainer_repo.get_binding(root2.id, container2.id, session=db_session) is not None


def test_password_persistence_contract(db_session, container_graph, monkeypatch, mock_node_send):
    root, _machine, container = container_graph
    target = create_user()
    bind_user_container(target, container, role=ROLE.COLLABORATOR, username=target.username)
    monkeypatch.setattr(password_utils, "spawn_background", _run_now)
    mock_node_send({"success": 1})
    result = container_tasks.start_reset_container_password(container.id, target.id, root.id)

    # 密码不落库/审计；表结构无密码列
    for model in (UserContainer, Container, OperationLog):
        columns = {c.key for c in model.__table__.columns}
        assert "password" not in columns
    logs = list(db_session.scalars(select(OperationLog)).all())
    assert all(result["password"] not in str(log.detail) for log in logs)
    assert all(result["password"] not in str(log.error_reason) for log in logs)

    # 无密码回查 GET 端点
    for route in container_api.router.routes:
        methods = getattr(route, "methods", set()) or set()
        if "password" in getattr(route, "path", ""):
            assert "GET" not in methods

    # Node 错误体包含 secret：审计仍不含
    secret_user = create_user()
    bind_user_container(secret_user, container, role=ROLE.COLLABORATOR, username=secret_user.username)
    holder = {}

    def _bad_send(url, payload, timeout=5.0):
        holder["pwd"] = payload["config"]["password"]
        return {"success": 0, "error": f"failed {holder['pwd']}", "error_reason": "reset_failed"}

    monkeypatch.setattr("FuxiYu_CtrKernel.services.container_module.node_comms.send", _bad_send)
    bad = container_tasks.start_reset_container_password(container.id, secret_user.id, root.id)
    fail_logs = list(db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "reset_container_password",
                                   OperationLog.success.is_(False))
    ).all())
    assert fail_logs
    assert all(holder["pwd"] not in str(log.detail) for log in fail_logs)
    assert all(bad["password"] not in str(log.detail) for log in fail_logs)


@pytest.mark.parametrize(
    "transfer_root",
    [
        pytest.param(None, id="omitted"),
        pytest.param(False, id="false"),
        pytest.param(True, id="true"),
    ],
)
def test_update_role_root_always_handover_contract(
    client, monkeypatch, db_session, transfer_root,
):
    _auth(monkeypatch)
    root, _machine, container, target = _graph_with_target()
    monkeypatch.setattr(collaborator_utils, "spawn_background", _run_now)
    calls = _sequence_node(monkeypatch, [{"success": 1}, {"success": 1}])
    body = {"container_id": container.id, "user_id": target.id, "updated_role": "ROOT"}
    if transfer_root is not None:
        # 旧客户端兼容输入；值不得改变交接编排。
        body["transfer_root"] = transfer_root

    resp = client.post("/api/containers/update_role", json=body)

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["accepted"] is True
    assert resp.headers["Cache-Control"] == "no-store"
    credentials = payload["credentials"]
    assert len(credentials) == 2
    assert credentials[0]["login_name"] == "root"
    assert credentials[1]["login_name"] == root.username
    assert credentials[0]["password"] != credentials[1]["password"]
    assert [c["payload"]["config"]["updated_role"] for c in calls] == ["admin", "root"]
    assert calls[0]["payload"]["config"]["user_name"] == root.username
    assert calls[0]["payload"]["config"]["password"] == credentials[1]["password"]
    assert calls[1]["payload"]["config"]["root_password"] == credentials[0]["password"]
    assert all("transfer_root" not in c["payload"]["config"] for c in calls)

    db_session.expire_all()
    old_binding = usercontainer_repo.get_binding(root.id, container.id, session=db_session)
    new_binding = usercontainer_repo.get_binding(target.id, container.id, session=db_session)
    assert getattr(old_binding["role"], "value", old_binding["role"]) == ROLE.ADMIN.value
    assert old_binding["username"] == root.username
    assert getattr(new_binding["role"], "value", new_binding["role"]) == ROLE.ROOT.value
    assert new_binding["username"] == "root"
    assert _root_user_ids(container.id, db_session) == [target.id]

    passwords = [item["password"] for item in credentials]
    _assert_no_password_in_logs_or_files(db_session, passwords)
    for row in db_session.scalars(
        select(UserContainer).where(UserContainer.container_id == container.id)
    ).all():
        for column in UserContainer.__table__.columns:
            value = str(getattr(row, column.key))
            assert all(password not in value for password in passwords)


def test_update_role_legacy_transfer_root_does_not_affect_non_root(
    client, monkeypatch, db_session,
):
    _auth(monkeypatch)
    _root, _machine, container, target = _graph_with_target()
    called = []
    monkeypatch.setattr(
        container_api.container_service, "update_role",
        lambda **kwargs: called.append(kwargs) or True,
    )

    resp = client.post(
        "/api/containers/update_role",
        json={
            "container_id": container.id, "user_id": target.id,
            "updated_role": "ADMIN", "transfer_root": True,
        },
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] == 1
    assert called == [{
        "container_id": container.id,
        "user_id": target.id,
        "updated_role": ROLE.ADMIN,
        "operator_user_id": 1,
    }]


def test_reset_background_contract(client, monkeypatch, db_session, container_graph, mock_node_send):
    root, _machine, container = container_graph
    collaborator = create_user(username="reset_bg_user")
    bind_user_container(collaborator, container, role=ROLE.COLLABORATOR, username="reset_bg_user")
    captured = {}

    def _capture(name, target, *args):
        captured["target"] = target
        captured["args"] = args
        return SimpleNamespace(join=lambda: None)

    monkeypatch.setattr(password_utils, "spawn_background", _capture)
    calls = mock_node_send({"success": 1})

    result = container_tasks.start_reset_container_password(container.id, collaborator.id, root.id)
    assert result["password"] in captured["args"]
    assert calls == []  # 受理时还没执行 Node
    captured["target"](*captured["args"])
    assert calls and calls[0]["url"].endswith("/api/reset_container_password")
    logs = list(db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "reset_container_password")
    ).all())
    assert logs and logs[-1].success is True
    assert result["password"] not in str(logs[-1].detail)

    # Node 失败：后台写失败 oplog，不写成功
    failed = create_user(username="reset_bg_failed")
    bind_user_container(failed, container, role=ROLE.COLLABORATOR, username="reset_bg_failed")
    mock_node_send({"success": 0, "error_reason": "reset_failed"})
    captured.clear()
    failed_result = container_tasks.start_reset_container_password(container.id, failed.id, root.id)
    captured["target"](*captured["args"])
    fail_logs = list(db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "reset_container_password",
                                   OperationLog.success.is_(False))
    ).all())
    assert fail_logs
    assert all(failed_result["password"] not in str(log.detail) for log in fail_logs)

    # 后台最小 guard 失败：不调 Node，只写失败
    guarded = create_user(username="reset_bg_guard")
    bind_user_container(guarded, container, role=ROLE.COLLABORATOR, username="reset_bg_guard")
    calls = mock_node_send({"success": 1})
    captured.clear()
    guard_result = container_tasks.start_reset_container_password(container.id, guarded.id, root.id)
    container.container_status = ContainerStatus.OFFLINE
    db_session.commit()
    captured["target"](*captured["args"])
    assert calls == []
    guard_logs = list(db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "reset_container_password",
                                   OperationLog.success.is_(False))
    ).all())
    assert guard_logs and all(guard_result["password"] not in str(log.detail) for log in guard_logs)


def test_untrusted_reason_redaction_contract(client, db_session, container_graph, monkeypatch):
    from ...services.container_module.exceptions import safe_reason

    # 异常 reason 即使含密码，也只允许白名单/固定默认
    secret = "ExceptionReasonPwd_123"
    exc = container_tasks.NodeServiceError(f"boom {secret}", reason=secret)
    assert safe_reason(exc, "reset_failed") == "reset_failed"

    root, machine, container = container_graph
    target = create_user()
    bind_user_container(target, container, role=ROLE.COLLABORATOR, username=target.username)
    monkeypatch.setattr(password_utils, "spawn_background", _run_now)

    # 重置：Node error_reason 直接回显密码 → oplog 只存白名单 reason
    secret_pwd = {}

    def _bad_reset(url, payload, timeout=5.0):
        secret_pwd["value"] = payload["config"]["password"]
        return {"success": 0, "error_reason": payload["config"]["password"]}

    monkeypatch.setattr("FuxiYu_CtrKernel.services.container_module.node_comms.send", _bad_reset)
    result = container_tasks.start_reset_container_password(container.id, target.id, root.id)
    logs = list(db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "reset_container_password",
                                   OperationLog.success.is_(False))
    ).all())
    assert logs
    assert all(log.error_reason == "reset_failed" for log in logs)
    assert all(secret_pwd["value"] not in str(log.error_reason) for log in logs)
    assert all(result["password"] not in str(log.detail) for log in logs)

    # 新增协作者：Node error_reason 回显密码 → 只存既有失败码
    add_user = create_user()
    add_pwd = {}

    def _bad_add(url, payload, timeout=5.0):
        add_pwd["value"] = payload["config"]["password"]
        return {"success": 0, "error_reason": payload["config"]["password"]}

    monkeypatch.setattr("FuxiYu_CtrKernel.services.container_module.node_comms.send", _bad_add)
    monkeypatch.setattr(collaborator_utils, "spawn_background", _run_now)
    container_tasks.start_add_collaborator(container.id, add_user.id, ROLE.COLLABORATOR, root.id)
    add_logs = list(db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "add_collaborator",
                                   OperationLog.success.is_(False))
    ).all())
    assert add_logs
    assert all(log.error_reason == "add_failed" for log in add_logs)
    assert all(add_pwd["value"] not in str(log.error_reason) for log in add_logs)

    # 创建：Node error_reason 回显密码 → 异常 reason/文本不含 secret
    create_secret = {}

    def _bad_create(url, payload, timeout=5.0):
        create_secret["value"] = payload["root_password"]
        return {"success": 0, "error": payload["root_password"], "error_reason": payload["root_password"]}

    monkeypatch.setattr("FuxiYu_CtrKernel.services.container_module.node_comms.send", _bad_create)
    from ...utils.Container import Container_info

    info = Container_info(gpu_list=[], cpu_number=1, memory=1, shared_memory=0,
                          name="redact_create", image="ubuntu:22.04")
    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.Create_container(root.id, machine.id, info)
    assert excinfo.value.reason == "create_failed"
    assert create_secret["value"] not in str(excinfo.value)
    assert create_secret["value"] not in str(excinfo.value.reason)

    # HTTP 错误也不回显 Node 未受信 reason
    _auth(monkeypatch)
    http_secret = "HttpSecretReason_123"

    def _raise_add(**kwargs):
        raise container_tasks.NodeServiceError("raw response", reason=http_secret)

    monkeypatch.setattr(container_api.container_service, "start_add_collaborator", _raise_add)
    resp = client.post("/api/containers/add_collaborator",
                       json={"container_id": container.id, "user_id": target.id, "role": "ADMIN"})
    assert resp.status_code == 500
    assert http_secret not in resp.text
    http_logs = list(db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "add_collaborator",
                                   OperationLog.success.is_(False))
    ).all())
    assert http_logs and http_logs[-1].error_reason == "add_collaborator_failed"
    assert all(http_secret not in str(log.error_reason) for log in http_logs)


def test_reset_binding_recheck_contract(db_session, container_graph, monkeypatch):
    root, _machine, container = container_graph
    monkeypatch.setattr(password_utils, "spawn_background", _capture)
    calls = []

    def _send(url, payload, timeout=5.0):
        calls.append(payload)
        return {"success": 1}

    monkeypatch.setattr("FuxiYu_CtrKernel.services.container_module.node_comms.send", _send)

    # 受理后解绑：不调用 Node，写稳定失败
    user = create_user()
    bind_user_container(user, container, role=ROLE.COLLABORATOR, username=user.username)
    captured = {}
    monkeypatch.setattr(password_utils, "spawn_background", lambda name, target, *args: captured.update(target=target, args=args) or SimpleNamespace(join=lambda: None))
    container_tasks.start_reset_container_password(container.id, user.id, root.id)
    usercontainer_repo.remove_binding(user.id, container.id, session=db_session)
    db_session.commit()
    captured["target"](*captured["args"])
    assert calls == []
    logs = list(db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "reset_container_password",
                                   OperationLog.success.is_(False))
    ).all())
    assert logs and logs[-1].error_reason == "target_not_bound"

    # 受理后 username 变化：target_changed，不调用 Node
    user2 = create_user()
    bind_user_container(user2, container, role=ROLE.COLLABORATOR, username=user2.username)
    calls.clear()
    captured = {}
    container_tasks.start_reset_container_password(container.id, user2.id, root.id)
    usercontainer_repo.update_binding(
        user2.id, container.id, username="changed_after_accept", session=db_session,
    )
    db_session.commit()
    captured["target"](*captured["args"])
    assert calls == []
    assert list(db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "reset_container_password",
                                   OperationLog.success.is_(False))
    ).all())[-1].error_reason == "target_changed"

    # 受理后 role 变化：target_changed，不调用 Node
    user3 = create_user()
    bind_user_container(user3, container, role=ROLE.COLLABORATOR, username=user3.username)
    calls.clear()
    captured = {}
    container_tasks.start_reset_container_password(container.id, user3.id, root.id)
    usercontainer_repo.update_binding(
        user3.id, container.id, role=ROLE.ROOT, username="root", session=db_session,
    )
    db_session.commit()
    captured["target"](*captured["args"])
    assert calls == []
    assert list(db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "reset_container_password",
                                   OperationLog.success.is_(False))
    ).all())[-1].error_reason == "target_changed"


def _capture(name, target, *args):
    _capture.captured = {"target": target, "args": args}
    return SimpleNamespace(join=lambda: None)
