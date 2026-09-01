from sqlalchemy import select

from ...api import container_api, deps
from ...models.container_mount_cleanup import ContainerMountCleanup
from ...models.deleted_container_restore_snapshot import DeletedContainerRestoreSnapshot
from ...repositories import container_mount_cleanup_repo
from ...services import container_tasks
from ..factories import create_container_graph, create_machine
from .conftest import NODE_REMOVE_SUCCESS


def _auth(monkeypatch, *, valid=True, user_id=1):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: valid)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: user_id)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_entity", lambda uid, code: True)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_resource", lambda uid, rtype, rid: True)


def test_remove_container_records_deleted_snapshot_and_mount_cleanup(db_session, mock_node_send):
    root, machine, container = create_container_graph()
    container.bind_mount_path = f"/home/{root.username}/containers/{container.name}_data"
    container.port_mappings = [{"container_port": 22, "host_port": container.port, "protocol": "tcp"}]
    db_session.commit()
    mock_node_send(NODE_REMOVE_SUCCESS)

    assert container_tasks.remove_container(container.id, operator_user_id=root.id) is True

    cleanup_rows = db_session.scalars(select(ContainerMountCleanup)).all()
    snapshot_rows = db_session.scalars(select(DeletedContainerRestoreSnapshot)).all()
    assert len(cleanup_rows) == 1
    assert len(snapshot_rows) == 1
    assert cleanup_rows[0].mount_path.endswith("_data")
    assert snapshot_rows[0].mount_cleanup_id == cleanup_rows[0].id
    assert snapshot_rows[0].snapshot["container_name"] == container.name
    assert snapshot_rows[0].snapshot["accounts"][0]["user_id"] == root.id


def test_list_deleted_containers_returns_cleanup_state(db_session, mock_node_send):
    root, _machine, container = create_container_graph()
    container.bind_mount_path = f"/home/{root.username}/containers/{container.name}_data"
    db_session.commit()
    mock_node_send(NODE_REMOVE_SUCCESS)
    container_tasks.remove_container(container.id, operator_user_id=root.id)

    result = container_tasks.list_deleted_containers(page_number=1, page_size=20)

    assert result["total_number"] == 1
    record = result["records"][0]
    assert record["container_name"] == container.name
    assert record["mount_cleanup_id"] is not None
    assert record["data_recoverable"] is True


def test_list_deleted_containers_includes_cleanup_only_records(db_session):
    machine = create_machine(machine_ip="127.0.0.8")
    row = container_mount_cleanup_repo.insert(
        container_id=21,
        container_name="legacy_deleted",
        machine_id=machine.id,
        mount_path="/home/u/containers/legacy_deleted",
        session=db_session,
    )
    db_session.commit()

    result = container_tasks.list_deleted_containers(page_number=1, page_size=20)

    assert result["total_number"] == 1
    record = result["records"][0]
    assert record["deleted_id"] == f"mount-{row.id}"
    assert record["container_name"] == "legacy_deleted"
    assert record["snapshot"] == {}


def test_clean_deleted_container_mount_calls_node_and_marks_cleaned(db_session, monkeypatch):
    machine = create_machine(machine_ip="127.0.0.9")
    row = container_mount_cleanup_repo.insert(
        container_id=11,
        container_name="deleted_c",
        machine_id=machine.id,
        mount_path="/home/u/containers/deleted_c",
        session=db_session,
    )
    db_session.commit()
    sent = []

    def _send(url, payload, timeout=5.0):
        sent.append((url, payload, timeout))
        return {"success": 1}

    monkeypatch.setattr(container_tasks, "send", _send)

    result = container_tasks.clean_deleted_container_mount(row.id, operator_user_id=1)

    db_session.expire_all()
    assert result["cleaned"] is True
    assert sent[0][0].endswith("/clean_mount")
    assert sent[0][1]["config"]["mount_path"] == "/home/u/containers/deleted_c"
    assert db_session.get(ContainerMountCleanup, row.id).cleaned_at is not None


def test_list_deleted_containers_api(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(
        container_api.container_service,
        "list_deleted_containers",
        lambda **kwargs: {"records": [{"deleted_id": 1}], "total_number": 1, "total_page": 1},
    )

    resp = client.post("/api/containers/list_deleted_containers", json={"page_number": 1, "page_size": 20})

    assert resp.status_code == 200
    assert resp.json()["records"][0]["deleted_id"] == 1


def test_clean_deleted_container_mount_api(client, monkeypatch):
    _auth(monkeypatch)
    monkeypatch.setattr(
        container_api.container_service,
        "clean_deleted_container_mount",
        lambda **kwargs: {"mount_cleanup_id": kwargs["mount_cleanup_id"], "cleaned": True},
    )

    resp = client.post("/api/containers/clean_deleted_container_mount", json={"mount_cleanup_id": 7})

    assert resp.status_code == 200
    assert resp.json()["mount_cleanup_id"] == 7
