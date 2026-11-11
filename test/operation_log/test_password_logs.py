"""密码类操作 oplog 合同。"""

from types import SimpleNamespace

from sqlalchemy import select

from ...constant import ContainerStatus, ROLE
from ...models.operation_log import OperationLog
from ...services import container_tasks, operation_log_tasks
from ...services.container_module import collaborators as collaborator_utils
from ...services.container_module import passwords as password_utils
from ..factories import bind_user_container, create_container_graph, create_user


def _run_now(name, target, *args):
    target(*args)
    return SimpleNamespace(join=lambda: None)


def _capture_spawn(monkeypatch):
    captured = {}

    def _capture(name, target, *args):
        captured["target"], captured["args"] = target, args
        return SimpleNamespace(join=lambda: None)

    monkeypatch.setattr(password_utils, "spawn_background", _capture)
    monkeypatch.setattr(collaborator_utils, "spawn_background", _capture)
    return captured


def _logs(db_session, operation=None, success=None):
    stmt = select(OperationLog)
    if operation:
        stmt = stmt.where(OperationLog.operation == operation)
    if success is not None:
        stmt = stmt.where(OperationLog.success.is_(success))
    return list(db_session.scalars(stmt).all())


def test_password_log_codes_contract(db_session, monkeypatch):
    root, machine, container = create_container_graph()
    target = create_user()
    bind_user_container(target, container, role=ROLE.COLLABORATOR, username=target.username)
    monkeypatch.setattr(password_utils, "spawn_background", _run_now)
    monkeypatch.setattr(collaborator_utils, "spawn_background", _run_now)

    # 重置：一条 reset_container_password
    calls = []
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.container_module.node_comms.send",
        lambda url, payload, timeout=5.0: calls.append(payload) or {"success": 1},
    )
    reset = container_tasks.start_reset_container_password(container.id, target.id, root.id)
    reset_logs = _logs(db_session, "reset_container_password")
    assert len(reset_logs) == 1 and reset_logs[0].success is True
    assert reset["password"] not in str(reset_logs[0].detail)

    # 新增协作者：只一条 add_collaborator，无密码专用码
    add_user = create_user()
    add = container_tasks.start_add_collaborator(container.id, add_user.id, ROLE.ADMIN, root.id)
    add_logs = _logs(db_session, "add_collaborator")
    assert len(add_logs) == 1 and add_logs[0].success is True
    assert add["password"] not in str(add_logs[0].detail)
    assert not _logs(db_session, "reset_container_password", False)

    # ROOT 交接：每步一条 update_collaborator_role，无整体伪成功/密码
    hand_root, hand_machine, hand_container = create_container_graph()
    hand_target = create_user()
    bind_user_container(hand_target, hand_container, role=ROLE.COLLABORATOR, username=hand_target.username)
    hand = container_tasks.start_root_handover(hand_container.id, hand_target.id, hand_root.id)
    role_logs = _logs(db_session, "update_collaborator_role")
    assert len(role_logs) == 2 and all(log.success for log in role_logs)
    assert all(item["password"] not in str(log.detail) for item in hand["credentials"] for log in role_logs)

    # 创建：只有一条 create_container
    from ...utils.Container import Container_info

    create_root, create_machine_obj, _create_container = create_container_graph()
    info = Container_info(gpu_list=[], cpu_number=1, memory=1, shared_memory=0,
                          name="pwd_log_create", image="ubuntu:22.04")
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.container_module.node_comms.send",
        lambda url, payload, timeout=5.0: {"success": 1},
    )
    container_tasks.Create_container(create_root.id, create_machine_obj.id, info)
    create_logs = _logs(db_session, "create_container")
    assert len(create_logs) == 1
    assert all("root_password" not in str(log.detail) for log in create_logs)

    # Node 错误体含 secret：审计 detail 不含它
    secret_user = create_user()
    bind_user_container(secret_user, container, role=ROLE.COLLABORATOR, username=secret_user.username)
    secret_holder = {}

    def _secret_send(url, payload, timeout=5.0):
        secret = payload["config"]["password"]
        secret_holder["value"] = secret
        return {"success": 0, "error": f"bad password {secret}", "error_reason": "reset_failed"}

    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.container_module.node_comms.send", _secret_send,
    )
    secret_result = container_tasks.start_reset_container_password(container.id, secret_user.id, root.id)
    secret_logs = _logs(db_session, "reset_container_password", False)
    assert secret_holder["value"] == secret_result["password"]
    assert all(secret_result["password"] not in str(log.detail) for log in secret_logs)


def test_password_log_timing_contract(db_session, monkeypatch):
    root, _machine, container = create_container_graph()
    target = create_user()
    bind_user_container(target, container, role=ROLE.COLLABORATOR, username=target.username)
    captured = _capture_spawn(monkeypatch)
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.container_module.node_comms.send",
        lambda url, payload, timeout=5.0: {"success": 1},
    )
    result = container_tasks.start_reset_container_password(container.id, target.id, root.id)
    assert _logs(db_session, "reset_container_password") == []  # 受理时不写结果
    captured["target"](*captured["args"])
    assert len(_logs(db_session, "reset_container_password")) == 1

    # 重置失败：一条失败，无成功
    fail_user = create_user()
    bind_user_container(fail_user, container, role=ROLE.COLLABORATOR, username=fail_user.username)
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.container_module.node_comms.send",
        lambda url, payload, timeout=5.0: {"success": 0, "error_reason": "reset_failed"},
    )
    captured = _capture_spawn(monkeypatch)
    container_tasks.start_reset_container_password(container.id, fail_user.id, root.id)
    captured["target"](*captured["args"])
    assert len(_logs(db_session, "reset_container_password", False)) >= 1

    # 新增协作者失败：只失败，无成功
    add_fail = create_user()
    monkeypatch.setattr(password_utils, "spawn_background", _run_now)
    monkeypatch.setattr(collaborator_utils, "spawn_background", _run_now)
    container_tasks.start_add_collaborator(container.id, add_fail.id, ROLE.COLLABORATOR, root.id)
    assert not _logs(db_session, "add_collaborator", True)
    assert _logs(db_session, "add_collaborator", False)

    # ROOT 交接部分失败：旧 ROOT 成功保留，目标失败，无整体成功
    hroot, _hm, hcontainer = create_container_graph()
    htarget = create_user()
    bind_user_container(htarget, hcontainer, role=ROLE.COLLABORATOR, username=htarget.username)
    responses = [{"success": 1}, {"success": 0, "error_reason": "root_step_failed"}]
    calls = []

    def _send(url, payload, timeout=5.0):
        calls.append(payload)
        return responses[min(len(calls) - 1, 1)]

    monkeypatch.setattr("FuxiYu_CtrKernel.services.container_module.node_comms.send", _send)
    monkeypatch.setattr(collaborator_utils, "spawn_background", _run_now)
    container_tasks.start_root_handover(hcontainer.id, htarget.id, hroot.id)
    hand_logs = _logs(db_session, "update_collaborator_role")
    assert any(log.success for log in hand_logs)
    assert any(not log.success for log in hand_logs)

    # 超时/未知结果：写失败，不写成功
    timeout_user = create_user()
    bind_user_container(timeout_user, hcontainer, role=ROLE.COLLABORATOR, username=timeout_user.username)
    captured = _capture_spawn(monkeypatch)

    def _timeout(*args, **kwargs):
        raise TimeoutError("node timeout")

    monkeypatch.setattr("FuxiYu_CtrKernel.services.container_module.node_comms.send", _timeout)
    container_tasks.start_reset_container_password(hcontainer.id, timeout_user.id, hroot.id)
    captured["target"](*captured["args"])
    timeout_logs = _logs(db_session, "reset_container_password", False)
    assert timeout_logs
    assert all("timeout" not in str(log.detail).lower() for log in timeout_logs)

    # 日志写入失败不抛回调用方（沿用 write_operation_log 吞异常）
    monkeypatch.setattr(operation_log_tasks, "_repo_write", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("db")))
    assert operation_log_tasks.log_success(
        operation="create_container", target_type="container", target_id=1, detail={},
    ) is None
