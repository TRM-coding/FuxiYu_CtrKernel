"""ROOT 交接的确定性对抗性回归。

后台任务多数由 ``_JobQueue`` 捕获后按测试显式顺序执行；另用真实线程 + barrier 验证同进程
互斥，用独立子进程验证 POSIX 文件锁。目标不是把当前实现固化成期望，而是用可复现顺序探测：

- 同一目标重复受理、两个不同目标交错受理/执行；
- 受理后调用者权限被收回；
- 目标已是 ROOT、容器没有旧 ROOT；
- 畸形 ID/role/flag 被拒绝且无角色/Node 副作用；
- Node 超时/异常、绑定写入失败、机器中途维护；
- 审计/DB 异常不会整批回滚已提交步骤。

当前互斥边界是“同一 Ctrl 主机”：POSIX 文件锁覆盖同机跨进程，线程 RLock 覆盖同进程；
Windows 开发无 fcntl 时仅线程锁。多 Ctrl 主机不承诺。旧的双 ROOT 缺口已由
``root_handover_stale`` 拒绝后执行任务收住，不能把该测试改成接受两个 ROOT。
"""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from ...constant import MachineStatus, ROLE
from ...models.operation_log import OperationLog
from ...models.usercontainer import UserContainer
from ...repositories import machine_permission_repo, usercontainer_repo
from ...services import container_tasks
from ...services.container_module import collaborators as collaborator_utils
from ...utils import container_lock
from ..factories import bind_user_container, create_container_graph, create_user


def _auth(monkeypatch, user_id):
    from ...api import deps

    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: True)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: user_id)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_entity", lambda uid, code: True)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_resource", lambda uid, rtype, rid: True)
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.repositories.containers_repo.get_machine_id_by_container_id",
        lambda cid, session: 1,
    )


def _install_node(monkeypatch, responses=None):
    """记录 Node wire；responses 项可为 dict 或异常实例。"""

    calls = []
    sequence = list(responses or [{"success": 1}])

    def _send(url, payload, timeout=5.0):
        calls.append({"url": url, "payload": payload, "timeout": timeout})
        item = sequence[min(len(calls) - 1, len(sequence) - 1)]
        if isinstance(item, Exception):
            raise item
        return dict(item)

    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.container_module.node_comms.send", _send,
    )
    return calls


class _JobQueue:
    """捕获后台任务，由测试显式决定执行顺序；不启动真实线程。"""

    def __init__(self):
        self.jobs = []

    def spawn(self, name, target, *args):
        self.jobs.append((name, target, args))
        return SimpleNamespace(join=lambda: None)

    def run(self, index=0):
        _name, target, args = self.jobs.pop(index)
        target(*args)

    def __len__(self):
        return len(self.jobs)


def _post_root(client, container_id, user_id, **extra):
    body = {
        "container_id": container_id,
        "user_id": user_id,
        "updated_role": "ROOT",
    }
    body.update(extra)
    return client.post("/api/containers/update_role", json=body)


def _root_ids(db_session, container_id):
    db_session.expire_all()
    rows = db_session.scalars(
        select(UserContainer).where(
            UserContainer.container_id == container_id,
        )
    ).all()
    return sorted(
        row.user_id for row in rows
        if getattr(row.role, "value", row.role) == ROLE.ROOT.value
    )


def _binding_state(db_session, container_id, user_id):
    db_session.expire_all()
    binding = usercontainer_repo.get_binding(user_id, container_id, session=db_session)
    assert binding is not None
    return (
        getattr(binding["role"], "value", binding["role"]),
        binding["username"],
    )


def _assert_no_password_in_logs(db_session, credentials):
    db_session.expire_all()
    logs = list(db_session.scalars(select(OperationLog)).all())
    for credential in credentials:
        password = credential["password"]
        for log in logs:
            text = f"{log.detail}|{log.error_reason}"
            assert password not in text


def _stale_logs(db_session):
    db_session.expire_all()
    return list(db_session.scalars(
        select(OperationLog).where(
            OperationLog.operation == "update_collaborator_role",
            OperationLog.success.is_(False),
            OperationLog.error_reason == "root_handover_stale",
        )
    ).all())


def _graph_with_collaborators(*usernames):
    root, machine, container = create_container_graph()
    users = []
    for username in usernames:
        user = create_user(username=username)
        bind_user_container(user, container, role=ROLE.COLLABORATOR, username=user.username)
        users.append(user)
    return root, machine, container, users


@pytest.mark.parametrize(
    ("target_name", "old_root_name", "expected_reason"),
    [
        pytest.param("root", None, "invalid_target_account", id="target-root"),
        pytest.param("-help", None, "invalid_target_account", id="target-leading-dash"),
        pytest.param("adv_valid_target", "-oldroot", "invalid_root_owner_account", id="old-root-leading-dash"),
    ],
)
def test_root_handover_preflight_rejects_node_unusable_names(
    monkeypatch, target_name, old_root_name, expected_reason,
):
    if old_root_name is None:
        root, _machine, container = create_container_graph()
        target = create_user(username=target_name)
        bind_user_container(target, container, role=ROLE.COLLABORATOR, username=target.username)
    else:
        root = create_user(username=old_root_name)
        _root, _machine, container = create_container_graph(root_user=root)
        target = create_user(username=target_name)
        bind_user_container(target, container, role=ROLE.COLLABORATOR, username=target.username)

    generated = []
    monkeypatch.setattr(
        collaborator_utils, "generate_container_password",
        lambda: generated.append(True) or "NeverUsedPwd_123",
    )
    with pytest.raises(container_tasks.NodeServiceError) as exc:
        container_tasks.start_root_handover(container.id, target.id, root.id)
    assert exc.value.reason == expected_reason
    assert generated == []


def test_repeated_handover_to_same_target_keeps_one_root_and_stales_second(
    client, monkeypatch, db_session,
):
    root, _machine, container, (target,) = _graph_with_collaborators("adv_same_target")
    _auth(monkeypatch, root.id)
    jobs = _JobQueue()
    monkeypatch.setattr(collaborator_utils, "spawn_background", jobs.spawn)
    calls = _install_node(monkeypatch, [{"success": 1}])

    first = _post_root(client, container.id, target.id)
    second = _post_root(client, container.id, target.id)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert len(jobs) == 2
    first_creds = first.json()["credentials"]
    second_creds = second.json()["credentials"]
    assert [c["login_name"] for c in first_creds] == ["root", root.username]
    assert [c["login_name"] for c in second_creds] == ["root", root.username]

    # 第一次任务完成交接；第二次任务持锁后发现 ROOT 集合/目标角色已变化，必须 stale 退出。
    jobs.run(0)
    assert [c["payload"]["config"]["updated_role"] for c in calls] == ["admin", "root"]
    assert calls[0]["payload"]["config"]["password"] == first_creds[1]["password"]
    assert calls[1]["payload"]["config"]["root_password"] == first_creds[0]["password"]

    jobs.run(0)
    assert len(calls) == 2  # stale 任务在任何 Node 命令前退出
    assert all(cred["password"] not in json.dumps(calls) for cred in second_creds)

    assert _root_ids(db_session, container.id) == [target.id]
    assert _binding_state(db_session, container.id, root.id) == (
        ROLE.ADMIN.value, root.username,
    )
    assert _binding_state(db_session, container.id, target.id) == (
        ROLE.ROOT.value, "root",
    )
    stale_logs = _stale_logs(db_session)
    assert len(stale_logs) == 1
    assert stale_logs[0].detail["expected_root_ids"] == [root.id]
    assert stale_logs[0].detail["current_root_ids"] == [target.id]
    _assert_no_password_in_logs(db_session, first_creds + second_creds)


def test_interleaved_handover_to_two_targets_must_not_leave_two_roots(
    client, monkeypatch, db_session,
):
    """两个目标先后受理；后者持锁后发现快照已变，stale 退出，最终唯一 ROOT。

    固定执行顺序为：降 A -> 升 B -> 降 A -> 升 C。第二次任务在降 A 前就必须
    检测到当前 ROOT 是 B、目标角色已变，因此不会再调用 Node 升 C。
    """

    root, _machine, container, (target_b, target_c) = _graph_with_collaborators(
        "adv_interleave_b", "adv_interleave_c",
    )
    _auth(monkeypatch, root.id)
    jobs = _JobQueue()
    monkeypatch.setattr(collaborator_utils, "spawn_background", jobs.spawn)
    calls = _install_node(monkeypatch, [{"success": 1}])

    response_b = _post_root(client, container.id, target_b.id)
    response_c = _post_root(client, container.id, target_c.id)
    assert response_b.status_code == 200, response_b.text
    assert response_c.status_code == 200, response_c.text
    assert len(jobs) == 2

    jobs.run(0)  # B: 降 A，升 B
    jobs.run(0)  # C: 持锁后发现 ROOT 已变，stale 退出，不发 Node
    assert [c["payload"]["config"]["updated_role"] for c in calls] == ["admin", "root"]

    root_ids = _root_ids(db_session, container.id)
    assert len(root_ids) == 1, (
        "two accepted handovers to different targets left ROOTs "
        f"{root_ids}; expected exactly one final ROOT"
    )
    assert root_ids == [target_b.id]
    assert _binding_state(db_session, container.id, target_c.id) == (
        ROLE.COLLABORATOR.value, target_c.username,
    )
    stale_logs = _stale_logs(db_session)
    assert len(stale_logs) == 1
    assert stale_logs[0].detail["expected_root_ids"] == [root.id]
    assert stale_logs[0].detail["current_root_ids"] == [target_b.id]
    assert all(
        cred["password"] not in json.dumps(calls)
        for cred in response_c.json()["credentials"]
    )


def test_threaded_handover_barrier_keeps_one_root_and_attributes_commands(
    client, monkeypatch, db_session,
):
    """真实线程 + barrier：同一容器两个交接只允许一个完成，另一个 stale 且零 Node。"""

    root, _machine, container, (target_b, target_c) = _graph_with_collaborators(
        "adv_thread_b", "adv_thread_c",
    )
    _auth(monkeypatch, root.id)
    jobs = _JobQueue()
    monkeypatch.setattr(collaborator_utils, "spawn_background", jobs.spawn)
    calls = _install_node(monkeypatch, [{"success": 1}])

    response_b = _post_root(client, container.id, target_b.id)
    response_c = _post_root(client, container.id, target_c.id)
    assert response_b.status_code == 200, response_b.text
    assert response_c.status_code == 200, response_c.text
    assert len(jobs) == 2

    barrier = threading.Barrier(2)
    errors = []

    def _worker(job):
        _name, target, args = job
        try:
            barrier.wait(timeout=5)
            target(*args)
        except Exception as exc:  # pragma: no cover - 失败时把异常带回主线程断言
            errors.append(exc)

    workers = [threading.Thread(target=_worker, args=(job,)) for job in list(jobs.jobs)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)

    assert not any(worker.is_alive() for worker in workers)
    assert errors == []
    root_ids = _root_ids(db_session, container.id)
    assert len(root_ids) == 1
    winner_id = root_ids[0]
    assert winner_id in {target_b.id, target_c.id}
    winner_response = response_b if winner_id == target_b.id else response_c
    loser_response = response_c if winner_id == target_b.id else response_b

    assert [c["payload"]["config"]["updated_role"] for c in calls] == ["admin", "root"]
    assert calls[1]["payload"]["config"]["root_password"] == (
        winner_response.json()["credentials"][0]["password"]
    )
    assert all(
        cred["password"] not in json.dumps(calls)
        for cred in loser_response.json()["credentials"]
    )
    stale_logs = _stale_logs(db_session)
    assert len(stale_logs) == 1
    _assert_no_password_in_logs(
        db_session,
        response_b.json()["credentials"] + response_c.json()["credentials"],
    )


def test_container_role_lock_nested_reentrant_and_empty_marker():
    lock_id = 987654
    with container_lock.container_role_lock(lock_id):
        with container_lock.container_role_lock(lock_id):
            if container_lock.CROSS_PROCESS_LOCK_SUPPORTED:
                marker = container_lock._lock_path(lock_id)
                assert marker.exists()
                assert marker.stat().st_size == 0
    if container_lock.CROSS_PROCESS_LOCK_SUPPORTED:
        assert marker.stat().st_size == 0


@pytest.mark.skipif(
    not container_lock.CROSS_PROCESS_LOCK_SUPPORTED,
    reason="fcntl unavailable; Windows dev only has the in-process lock",
)
def test_container_role_lock_cross_process(tmp_path):
    """独立子进程持锁时，另一个子进程必须阻塞；释放后才获得锁。"""

    repo_root = Path(__file__).resolve().parents[2]
    holder_ready = tmp_path / "holder.ready"
    release = tmp_path / "release"
    contender_ready = tmp_path / "contender.ready"
    lock_id = "987654321"

    holder_code = """
import sys, time
from pathlib import Path
from FuxiYu_CtrKernel.utils.container_lock import container_role_lock

with container_role_lock(int(sys.argv[1])):
    Path(sys.argv[2]).write_text("held")
    while not Path(sys.argv[3]).exists():
        time.sleep(0.02)
"""
    contender_code = """
import sys
from pathlib import Path
from FuxiYu_CtrKernel.utils.container_lock import container_role_lock

with container_role_lock(int(sys.argv[1])):
    Path(sys.argv[2]).write_text("acquired")
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        str(repo_root.parent) + os.pathsep + env.get("PYTHONPATH", "")
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_code, lock_id, str(holder_ready), str(release)],
        cwd=str(repo_root), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    contender = None
    try:
        deadline = time.time() + 5
        while not holder_ready.exists():
            assert holder.poll() is None, "holder process exited before acquiring lock"
            assert time.time() < deadline, "holder did not acquire lock in time"
            time.sleep(0.02)

        contender = subprocess.Popen(
            [sys.executable, "-c", contender_code, lock_id, str(contender_ready)],
            cwd=str(repo_root), env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(0.3)
        assert contender.poll() is None
        assert not contender_ready.exists()

        release.write_text("1")
        assert contender.wait(timeout=5) == 0
        assert holder.wait(timeout=5) == 0
        assert contender_ready.exists()
    finally:
        release.write_text("1")
        for process in (contender, holder):
            if process is not None and process.poll() is None:
                process.terminate()
        for process in (contender, holder):
            if process is not None and process.poll() is None:
                process.wait(timeout=5)


def test_accepted_handover_survives_caller_permission_revocation(
    client, monkeypatch, db_session,
):
    root, machine, container, (target,) = _graph_with_collaborators("adv_old_perm_target")
    _auth(monkeypatch, root.id)
    jobs = _JobQueue()
    monkeypatch.setattr(collaborator_utils, "spawn_background", jobs.spawn)
    _install_node(monkeypatch, [{"success": 1}])

    response = _post_root(client, container.id, target.id)
    assert response.status_code == 200, response.text

    # 受理后收回机器权限；已受理的后台步骤不应因此中断。
    machine_permission_repo.remove_permission(machine.id, root.id, session=db_session)
    db_session.commit()

    jobs.run(0)
    assert _root_ids(db_session, container.id) == [target.id]
    assert _binding_state(db_session, container.id, target.id) == (ROLE.ROOT.value, "root")


def test_handover_to_already_root_target_demotes_other_roots(
    client, monkeypatch, db_session,
):
    root, _machine, container = create_container_graph()
    target = create_user(username="adv_already_root")
    bind_user_container(target, container, role=ROLE.ROOT, username="root")
    _auth(monkeypatch, root.id)
    jobs = _JobQueue()
    monkeypatch.setattr(collaborator_utils, "spawn_background", jobs.spawn)
    calls = _install_node(monkeypatch, [{"success": 1}])

    response = _post_root(client, container.id, target.id)
    assert response.status_code == 200, response.text
    assert [c["login_name"] for c in response.json()["credentials"]] == ["root", root.username]
    jobs.run(0)

    assert [c["payload"]["config"]["updated_role"] for c in calls] == ["admin", "root"]
    assert _root_ids(db_session, container.id) == [target.id]
    assert _binding_state(db_session, container.id, root.id) == (ROLE.ADMIN.value, root.username)


def test_handover_without_old_root_promotes_target_with_one_root_credential(
    client, monkeypatch, db_session,
):
    root, _machine, container = create_container_graph()
    target = create_user(username="adv_no_old_root")
    bind_user_container(target, container, role=ROLE.COLLABORATOR, username=target.username)
    assert usercontainer_repo.remove_binding(root.id, container.id, session=db_session) is True
    db_session.commit()

    _auth(monkeypatch, root.id)
    jobs = _JobQueue()
    monkeypatch.setattr(collaborator_utils, "spawn_background", jobs.spawn)
    calls = _install_node(monkeypatch, [{"success": 1}])

    response = _post_root(client, container.id, target.id)
    assert response.status_code == 200, response.text
    credentials = response.json()["credentials"]
    assert [c["login_name"] for c in credentials] == ["root"]
    jobs.run(0)

    assert [c["payload"]["config"]["updated_role"] for c in calls] == ["root"]
    assert _root_ids(db_session, container.id) == [target.id]
    assert _binding_state(db_session, container.id, target.id) == (ROLE.ROOT.value, "root")


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param({"container_id": 0}, id="zero-container"),
        pytest.param({"container_id": -1}, id="negative-container"),
        pytest.param({"container_id": "not-int"}, id="nonint-container"),
        pytest.param({"container_id": True}, id="bool-container"),
        pytest.param({"user_id": 0}, id="zero-user"),
        pytest.param({"user_id": -1}, id="negative-user"),
        pytest.param({"user_id": "not-int"}, id="nonint-user"),
        pytest.param({"user_id": True}, id="bool-user"),
        pytest.param({"updated_role": "OWNER"}, id="unknown-role"),
        pytest.param({"updated_role": None}, id="null-role"),
        pytest.param({"transfer_root": "not-a-bool"}, id="malformed-flag"),
    ],
)
def test_malformed_root_request_has_no_role_or_node_side_effects(
    client, monkeypatch, db_session, mutation,
):
    root, _machine, container, (target,) = _graph_with_collaborators("adv_malformed_target")
    _auth(monkeypatch, root.id)
    jobs = _JobQueue()
    monkeypatch.setattr(collaborator_utils, "spawn_background", jobs.spawn)
    calls = _install_node(monkeypatch, [{"success": 1}])

    before_roots = _root_ids(db_session, container.id)
    before_old = _binding_state(db_session, container.id, root.id)
    before_target = _binding_state(db_session, container.id, target.id)

    body = {
        "container_id": container.id,
        "user_id": target.id,
        "updated_role": "ROOT",
    }
    body.update(mutation)
    # 不让 TestClient 把未处理异常直接抛成测试错误；生产语义应返回可判定的 4xx。
    safe_client = TestClient(client.app, raise_server_exceptions=False)
    response = safe_client.post("/api/containers/update_role", json=body)

    assert calls == [], f"malformed {mutation!r} reached Node"
    assert len(jobs) == 0, f"malformed {mutation!r} spawned {len(jobs)} handover job(s)"
    assert _root_ids(db_session, container.id) == before_roots
    assert _binding_state(db_session, container.id, root.id) == before_old
    assert _binding_state(db_session, container.id, target.id) == before_target

    if mutation == {"container_id": "not-int"}:
        # 只挂 require_machine_of_container 的入口也必须命中同一固定 4xx。
        machine_only = client.post(
            "/api/containers/unpause_container",
            json={"container_id": "not-int"},
        )
        assert machine_only.status_code == 400
        assert machine_only.json()["error_reason"] == "invalid_resource_id"

    # 非整数 container_id 应在依赖层被收敛为固定 4xx，而不是 ValueError→500。
    assert response.status_code in (400, 422), (
        f"malformed {mutation!r} was not rejected cleanly: "
        f"{response.status_code} {response.text}"
    )
    if response.headers.get("content-type", "").startswith("application/json"):
        assert "credentials" not in response.json()


@pytest.mark.parametrize(
    "error",
    [TimeoutError("node timeout"), RuntimeError("node exploded")],
    ids=["timeout", "exception"],
)
def test_node_failure_during_demotion_stops_before_promotion(
    client, monkeypatch, db_session, error,
):
    root, _machine, container, (target,) = _graph_with_collaborators("adv_node_fail_target")
    _auth(monkeypatch, root.id)
    jobs = _JobQueue()
    monkeypatch.setattr(collaborator_utils, "spawn_background", jobs.spawn)
    calls = _install_node(monkeypatch, [error])

    response = _post_root(client, container.id, target.id)
    assert response.status_code == 200, response.text
    credentials = response.json()["credentials"]
    jobs.run(0)

    assert [c["payload"]["config"]["updated_role"] for c in calls] == ["admin"]
    assert _root_ids(db_session, container.id) == [root.id]
    assert _binding_state(db_session, container.id, target.id) == (
        ROLE.COLLABORATOR.value, target.username,
    )
    db_session.expire_all()
    failures = list(db_session.scalars(
        select(OperationLog).where(
            OperationLog.operation == "update_collaborator_role",
            OperationLog.success.is_(False),
        )
    ).all())
    assert failures
    _assert_no_password_in_logs(db_session, credentials)


def test_binding_failure_during_demotion_stops_before_promotion(
    client, monkeypatch, db_session,
):
    root, _machine, container, (target,) = _graph_with_collaborators("adv_bind_fail_target")
    _auth(monkeypatch, root.id)
    jobs = _JobQueue()
    monkeypatch.setattr(collaborator_utils, "spawn_background", jobs.spawn)
    calls = _install_node(monkeypatch, [{"success": 1}])
    monkeypatch.setattr(collaborator_utils, "_update_collaborator_binding", lambda *args, **kwargs: False)

    response = _post_root(client, container.id, target.id)
    assert response.status_code == 200, response.text
    credentials = response.json()["credentials"]
    jobs.run(0)

    assert [c["payload"]["config"]["updated_role"] for c in calls] == ["admin"]
    assert _root_ids(db_session, container.id) == [root.id]
    assert _binding_state(db_session, container.id, root.id) == (ROLE.ROOT.value, "root")
    assert _binding_state(db_session, container.id, target.id) == (
        ROLE.COLLABORATOR.value, target.username,
    )
    _assert_no_password_in_logs(db_session, credentials)


def test_machine_offline_between_steps_keeps_first_committed_fact(
    client, monkeypatch, db_session,
):
    root, machine, container, (target,) = _graph_with_collaborators("adv_guard_target")
    _auth(monkeypatch, root.id)
    jobs = _JobQueue()
    monkeypatch.setattr(collaborator_utils, "spawn_background", jobs.spawn)
    calls = []

    def _send(url, payload, timeout=5.0):
        calls.append({"url": url, "payload": payload, "timeout": timeout})
        if len(calls) == 1:
            machine.machine_status = MachineStatus.OFFLINE
            db_session.commit()
        return {"success": 1}

    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.container_module.node_comms.send", _send,
    )
    response = _post_root(client, container.id, target.id)
    assert response.status_code == 200, response.text
    credentials = response.json()["credentials"]
    jobs.run(0)

    assert [c["payload"]["config"]["updated_role"] for c in calls] == ["admin"]
    assert _binding_state(db_session, container.id, root.id) == (
        ROLE.ADMIN.value, root.username,
    )
    assert _binding_state(db_session, container.id, target.id) == (
        ROLE.COLLABORATOR.value, target.username,
    )
    assert _root_ids(db_session, container.id) == []
    db_session.expire_all()
    logs = list(db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "update_collaborator_role")
    ).all())
    assert sum(1 for log in logs if log.success) == 1
    assert sum(1 for log in logs if not log.success) == 1
    _assert_no_password_in_logs(db_session, credentials)


@pytest.mark.parametrize("failure_mode", ["binding", "audit"])
def test_db_or_audit_exception_does_not_rollback_committed_step(
    client, monkeypatch, db_session, failure_mode,
):
    root, _machine, container, (target,) = _graph_with_collaborators(
        f"adv_{failure_mode}_failure_target",
    )
    _auth(monkeypatch, root.id)
    jobs = _JobQueue()
    monkeypatch.setattr(collaborator_utils, "spawn_background", jobs.spawn)
    calls = _install_node(monkeypatch, [{"success": 1}])

    counter = {"n": 0}
    if failure_mode == "binding":
        original_update = usercontainer_repo.update_binding

        def _update(*args, **kwargs):
            counter["n"] += 1
            if counter["n"] == 2:
                raise RuntimeError("db down")
            return original_update(*args, **kwargs)

        monkeypatch.setattr(usercontainer_repo, "update_binding", _update)
    else:
        original_log_success = collaborator_utils.log_success

        def _log_success(*args, **kwargs):
            counter["n"] += 1
            if counter["n"] == 2:
                raise RuntimeError("audit down")
            return original_log_success(*args, **kwargs)

        monkeypatch.setattr(collaborator_utils, "log_success", _log_success)

    response = _post_root(client, container.id, target.id)
    assert response.status_code == 200, response.text
    credentials = response.json()["credentials"]
    jobs.run(0)

    assert len(calls) == 2
    assert _binding_state(db_session, container.id, root.id) == (
        ROLE.ADMIN.value, root.username,
    )
    expected_target = ROLE.ROOT.value if failure_mode == "audit" else ROLE.COLLABORATOR.value
    assert _binding_state(db_session, container.id, target.id) == (
        expected_target, "root" if expected_target == ROLE.ROOT.value else target.username,
    )
    db_session.expire_all()
    logs = list(db_session.scalars(
        select(OperationLog).where(OperationLog.operation == "update_collaborator_role")
    ).all())
    assert sum(1 for log in logs if log.success) == 1
    assert sum(1 for log in logs if not log.success) >= 1
    _assert_no_password_in_logs(db_session, credentials)
