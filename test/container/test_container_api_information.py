from ...api import container_api, deps
from ...constant import ContainerStatus
from ...models.containers import Container
from ...services import container_tasks
from ..factories import create_container


def _auth(monkeypatch, *, valid=True, user_id=1):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: valid)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: user_id)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_entity", lambda uid, code: True)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_resource", lambda uid, rtype, rid: True)
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.repositories.containers_repo.get_machine_id_by_container_id",
        lambda cid, session: 1,
    )


def test_get_container_detail_api_not_found(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(
        container_api.container_service,
        "get_container_detail_information",
        lambda **kwargs: (_ for _ in ()).throw(ValueError("missing")),
    )

    resp = client.post("/api/containers/get_container_detail_information", json={"container_id": 1} )

    assert resp.status_code == 404


def test_get_container_detail_api_success(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(
        container_api.container_service,
        "get_container_detail_information",
        lambda **kwargs: {"container_id": 1, "container_name": "c"},
    )

    resp = client.post("/api/containers/get_container_detail_information", json={"container_id": 1} )

    assert resp.status_code == 200
    assert resp.json()["container_info"]["container_name"] == "c"


def test_container_status_api_missing_fields_returns_400(client, monkeypatch):
    _auth(monkeypatch)

    resp = client.post("/api/containers/container_status", json={} )

    assert resp.status_code == 400
    assert resp.json()["error_reason"] == "invalid_resource_id"


def test_container_status_api_blank_machine_id_returns_400(client, monkeypatch):
    _auth(monkeypatch)

    resp = client.post(
        "/api/containers/container_status",
        json={"machine_id": "", "container_name": "pending-container"},
    )

    assert resp.status_code == 400
    assert resp.json()["error_reason"] == "invalid_resource_id"


def test_container_status_api_success(client, monkeypatch, db_session):
    _auth(monkeypatch)
    container = create_container()
    runtime = {"cpu_usage_percent": 12.5, "memory_usage_percent": 33.0}
    monkeypatch.setattr(
        "FuxiYu_CtrKernel.services.container_module.node_comms.get_cached_container_runtime_metrics",
        lambda machine_id, container_name: runtime,
    )

    resp = client.post(
        "/api/containers/container_status",
        json={"container_id": container.id, "machine_id": container.machine_id, "container_name": container.name},
    )

    assert resp.status_code == 200
    assert resp.json()["container_status"] == container.container_status.value
    assert resp.json()["runtime_metrics"] == runtime


def test_container_status_api_query_key_is_container_id_not_name_machine(client, monkeypatch, db_session):
    """查询键与鉴权键统一为 container_id：name+machine 指向他容器不影响结果。"""
    _auth(monkeypatch)
    target = create_container(status=ContainerStatus.ONLINE)
    decoy = create_container(status=ContainerStatus.OFFLINE)

    resp = client.post(
        "/api/containers/container_status",
        json={"container_id": target.id, "machine_id": decoy.machine_id, "container_name": decoy.name},
    )

    assert resp.status_code == 200
    assert resp.json()["container_status"] == "online"


def test_container_status_api_without_container_id_rejected(client, monkeypatch, db_session):
    """只传 name+machine（无 container_id）在鉴权层被拒（400），不能探测他人容器。"""
    _auth(monkeypatch)
    container = create_container(status=ContainerStatus.ONLINE)

    resp = client.post(
        "/api/containers/container_status",
        json={"machine_id": container.machine_id, "container_name": container.name},
    )

    assert resp.status_code == 400
    assert resp.json()["error_reason"] == "invalid_resource_id"


def test_refresh_last_ssh_login_time_api_node_endpoint_missing_returns_502(client, monkeypatch, db_session):
    _auth(monkeypatch)
    container = create_container()

    def _raise(container_id):
        raise container_tasks.NodeServiceError("endpoint missing", reason="node_endpoint_not_found")

    monkeypatch.setattr(container_api.container_service, "get_container_last_ssh_login_time", _raise)

    resp = client.post(
        "/api/containers/refresh_last_ssh_login_time",
        json={"container_id": container.id}
    )

    assert resp.status_code == 502


def test_refresh_last_ssh_login_time_api_success(client, monkeypatch, db_session):
    _auth(monkeypatch)
    container = create_container()
    monkeypatch.setattr(container_api.container_service, "get_container_last_ssh_login_time", lambda container_id: "2026-05-25T10:00:00")

    resp = client.post(
        "/api/containers/refresh_last_ssh_login_time",
        json={"container_id": container.id}
    )

    assert resp.status_code == 200
    assert resp.json()["last_ssh_login_time"] == "2026-05-25T10:00:00"


def test_list_container_bref_api_includes_long_term_limit_when_user_filter_present(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(
        container_api.container_service,
        "list_all_container_bref_information",
        lambda **kwargs: {
            "containers": [],
            "total_page": 1,
            "long_term_container_remaining": 0,
            "long_term_container_limit": 1,
        },
    )

    resp = client.post(
        "/api/containers/list_all_container_bref_information",
        json={"user_id": 1, "page_number": 0, "page_size": 10}
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["long_term_container_remaining"] == 0
    assert payload["long_term_container_limit"] == 1


def test_list_container_bref_api_treats_blank_user_id_as_no_filter(client, monkeypatch):
    _auth(monkeypatch)
    captured = {}

    def _list(**kwargs):
        captured.update(kwargs)
        return {"containers": [], "total_page": 1}

    monkeypatch.setattr(container_api.container_service, "list_all_container_bref_information", _list)

    resp = client.post(
        "/api/containers/list_all_container_bref_information",
        json={"machine_id": "", "user_id": "", "container_search": "alpha", "page_number": 0, "page_size": 10},
    )

    assert resp.status_code == 200
    assert captured["machine_id"] is None
    assert captured["user_id"] is None
    assert captured["container_search"] == "alpha"


def test_get_container_operation_logs_api_filters_by_container(db_session, client, monkeypatch):
    """操作历史接口：按容器过滤 + 权限检查，返回 operator_username。"""
    from ...models.operation_log import OperationLog
    _auth(monkeypatch)
    container = create_container()
    other = create_container()
    # 造日志：本容器 2 条 + 他容器 1 条
    db_session.add_all([
        OperationLog(operator_user_id=1, operation="start_container",
                     target_type="container", target_id=container.id, detail={}, success=True),
        OperationLog(operator_user_id=1, operation="stop_container",
                     target_type="container", target_id=container.id, detail={}, success=False, error_reason="x"),
        OperationLog(operator_user_id=1, operation="start_container",
                     target_type="container", target_id=other.id, detail={}, success=True),
    ])
    db_session.commit()

    resp = client.post(
        "/api/containers/get_container_operation_logs",
        json={"container_id": container.id},
    )

    assert resp.status_code == 200
    logs = resp.json()["logs"]
    assert len(logs) == 2
    assert {log["operation"] for log in logs} == {"start_container", "stop_container"}
    assert all(log["target_id"] == container.id for log in logs)
    assert all("operator_username" in log for log in logs)
    failed = next(log for log in logs if not log["success"])
    assert failed["error_reason"] == "x"


def test_container_operation_logs_filters_old_id_reuse_logs(client, monkeypatch, db_session):
    """容器 id 复用（SQLite 删后复用）：op log 不级联删除，旧容器日志按 created_at 时间锚过滤。"""
    from datetime import datetime, timedelta

    from ...models.operation_log import OperationLog

    _auth(monkeypatch)
    container = create_container()
    container.created_at = datetime.utcnow() - timedelta(minutes=5)
    db_session.commit()
    now = container.created_at

    # 旧容器（同 id）的日志：早于当前容器 created_at → 应被过滤
    db_session.add(OperationLog(
        operator_user_id=1, operation="remove_container", target_type="container",
        target_id=container.id, success=True,
        detail={"name": "old_container"}, created_at=now - timedelta(hours=1),
    ))
    # 新容器自己的日志：晚于 created_at → 应保留
    db_session.add(OperationLog(
        operator_user_id=1, operation="start_container", target_type="container",
        target_id=container.id, success=True,
        detail={"name": container.name}, created_at=now + timedelta(minutes=1),
    ))
    db_session.commit()

    resp = client.post("/api/containers/get_container_operation_logs", json={"container_id": container.id})

    assert resp.status_code == 200
    ops = [log["operation"] for log in resp.json()["logs"]]
    assert ops == ["start_container"]
