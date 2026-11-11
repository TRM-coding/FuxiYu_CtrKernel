"""operation_log 管理端 API 契约测试（只测鉴权与响应形状，数据查询在 repo 测试覆盖）。"""

from ...api import operation_log_api, deps
from ...services import operation_log_tasks


def _auth(monkeypatch, *, valid=True, operator=True):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: valid)
    from ...services import rbac_service
    monkeypatch.setattr(rbac_service, "_has_entity_direct", lambda uid, entity: operator)


def _fake_log_dict():
    return {
        "id": 1,
        "operator_user_id": 2,
        "operation": "create_container",
        "target_type": "container",
        "target_id": 3,
        "detail": {"name": "c1"},
        "success": True,
        "error_reason": None,
        "created_at": "2026-08-16T08:00:00",
    }


def test_requires_token(client, monkeypatch):
    _auth(monkeypatch, valid=False)
    resp = client.get("/api/admin/operation_logs")
    assert resp.status_code == 401


def test_requires_operator(client, monkeypatch):
    _auth(monkeypatch, operator=False)
    resp = client.get("/api/admin/operation_logs")
    assert resp.status_code == 403
    assert resp.json()["error_reason"] == "insufficient_permission"


def test_list_shape(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(operation_log_tasks, "list_operation_logs",
                        lambda **kw: {"logs": [_fake_log_dict()], "total_pages": 1})

    resp = client.get("/api/admin/operation_logs?page=1&page_size=20")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] == 1
    assert data["total_pages"] == 1
    row = data["logs"][0]
    assert row["operation"] == "create_container"
    assert row["target_type"] == "container"
    assert row["success"] is True
    assert row["detail"] == {"name": "c1"}
    assert row["created_at"] == "2026-08-16T08:00:00"


def test_list_passes_filters(client, monkeypatch):
    _auth(monkeypatch)
    captured = {}
    monkeypatch.setattr(operation_log_tasks, "list_operation_logs",
                        lambda **kw: captured.update(kw) or {"logs": [], "total_pages": 0})

    resp = client.get(
        "/api/admin/operation_logs"
        "?operation=create_container&target_type=container&operator_user_id=7&success=false"
        "&start=2026-08-01T00:00:00&end=2026-08-16T00:00:00"
    )

    assert resp.status_code == 200
    assert captured["operation"] == "create_container"
    assert captured["target_type"] == ["container"]
    assert captured["operator_user_id"] == 7
    assert captured["success"] is False
    assert captured["start"] == "2026-08-01T00:00:00"
    assert captured["end"] == "2026-08-16T00:00:00"


def test_list_accepts_repeated_target_types(client, monkeypatch):
    """Q44：重复 target_type 参数按多选传给服务层，顺序保持不变。"""

    _auth(monkeypatch)
    captured = {}
    monkeypatch.setattr(operation_log_tasks, "list_operation_logs",
                        lambda **kw: captured.update(kw) or {"logs": [], "total_pages": 0})

    resp = client.get(
        "/api/admin/operation_logs?target_type=container&target_type=machine&target_type=user"
    )

    assert resp.status_code == 200
    assert captured["target_type"] == ["container", "machine", "user"]


def test_list_without_target_type_passes_none(client, monkeypatch):
    _auth(monkeypatch)
    captured = {}
    monkeypatch.setattr(operation_log_tasks, "list_operation_logs",
                        lambda **kw: captured.update(kw) or {"logs": [], "total_pages": 0})

    resp = client.get("/api/admin/operation_logs")

    assert resp.status_code == 200
    assert captured["target_type"] is None


def test_list_does_not_expose_target_id_filter(client, monkeypatch):
    """Q44：管理端不新增 target_id 过滤；未知查询参数不会传给服务层。"""

    _auth(monkeypatch)
    captured = {}
    monkeypatch.setattr(operation_log_tasks, "list_operation_logs",
                        lambda **kw: captured.update(kw) or {"logs": [], "total_pages": 0})

    resp = client.get("/api/admin/operation_logs?target_id=99")

    assert resp.status_code == 200
    assert "target_id" not in captured


def test_stats_requires_operator(client, monkeypatch):
    _auth(monkeypatch, operator=False)
    resp = client.get("/api/admin/operation_logs/stats")
    assert resp.status_code == 403


def test_stats_shape(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(operation_log_tasks, "operation_log_stats",
                        lambda start=None, end=None, tz_offset_minutes=None: {
                            "total": 5, "succeeded": 4, "failed": 1,
                            "by_operation": {"create_container": 2},
                            "by_target_type": {"container": 3},
                        })

    resp = client.get("/api/admin/operation_logs/stats?start=2026-08-01T00:00:00&end=2026-08-16T00:00:00")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] == 1
    assert data["total"] == 5
    assert data["succeeded"] == 4
    assert data["by_operation"]["create_container"] == 2


def test_list_failure_keeps_list_failed(client, monkeypatch):
    _auth(monkeypatch)

    def fail(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(operation_log_tasks, "list_operation_logs", fail)
    resp = client.get("/api/admin/operation_logs")

    assert resp.status_code == 500
    body = resp.json()
    assert body["success"] == 0
    assert body["error_reason"] == "list_failed"
    assert body["message"] == "query failed: boom"


def test_stats_failure_uses_stats_failed(client, monkeypatch):
    _auth(monkeypatch)

    def fail(*, start=None, end=None, tz_offset_minutes=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(operation_log_tasks, "operation_log_stats", fail)
    resp = client.get("/api/admin/operation_logs/stats")

    assert resp.status_code == 500
    body = resp.json()
    assert body["success"] == 0
    assert body["error_reason"] == "stats_failed"
    assert body["message"] == "stats failed: boom"
