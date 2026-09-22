from types import SimpleNamespace

from ...api import machine_api, deps
from ...constant import MachineStatus
from ..factories import create_machine


def test_list_machine_bref_resolves_token_from_header(client, monkeypatch):
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_entity", lambda uid, code: True)
    captured = {}
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: True)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: 7)
    def _list(page_number, page_size, user_id=None, machine_search=None):
        captured["user_id"] = user_id
        return [], 0

    monkeypatch.setattr(machine_api.machine_service, "List_all_machine_bref_information", _list)

    resp = client.post("/api/machines/list_all_machine_bref_information", json={})

    assert resp.status_code == 200
    assert captured["user_id"] == 7


def test_list_machine_bref_resolves_token_from_cookie(client, monkeypatch):
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_entity", lambda uid, code: True)
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: True)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: 7)
    monkeypatch.setattr(machine_api.machine_service, "List_all_machine_bref_information", lambda page_number, page_size, user_id=None, machine_search=None: ([], 0))

    resp = client.post("/api/machines/list_all_machine_bref_information", json={})

    assert resp.status_code == 200


def test_list_machine_bref_requires_token(client, monkeypatch):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: False)

    resp = client.post("/api/machines/list_all_machine_bref_information", json={})

    assert resp.status_code == 401


def test_list_machine_bref_success_passes_user_id_to_service(client, monkeypatch):
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_entity", lambda uid, code: True)
    captured = {}
    runtime = {"cpu": {"usage_percent": 20.0}}
    machine = SimpleNamespace(
        id=1,
        machine_name="m",
        machine_ip="127.0.0.1",
        machine_type="GPU",
        machine_status="online",
        runtime_snapshot=runtime,
    )
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: True)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: 42)

    def _list(page_number, page_size, user_id=None, machine_search=None):
        captured.update(page_number=page_number, page_size=page_size, user_id=user_id, machine_search=machine_search)
        return [machine], 1

    monkeypatch.setattr(machine_api.machine_service, "List_all_machine_bref_information", _list)

    resp = client.post(
        "/api/machines/list_all_machine_bref_information",
        json={"page_number": 2, "page_size": 5, "machine_search": "127"}
    )

    assert resp.status_code == 200
    assert captured == {"page_number": 2, "page_size": 5, "user_id": 42, "machine_search": "127"}
    assert resp.json()["machines"][0]["machine_name"] == "m"
    assert resp.json()["machines"][0]["runtime_snapshot"] == runtime


def test_machine_status_api_reads_db_and_runtime_buffer(client, monkeypatch, db_session):
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_entity", lambda uid, code: True)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_resource", lambda uid, rtype, rid: True)
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: True)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: 7)
    machine = create_machine(machine_status=MachineStatus.ONLINE)
    runtime = {"cpu": {"usage_percent": 21.5}, "gpu": [{"index": 0, "utilization_gpu_percent": 66}]}
    monkeypatch.setattr(machine_api.node_comms, "get_cached_machine_runtime_snapshot", lambda machine_id: runtime)

    resp = client.post("/api/machines/machine_status", json={"machine_id": machine.id})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["machine_status"] == "online"
    assert payload["runtime_snapshot"] == runtime
