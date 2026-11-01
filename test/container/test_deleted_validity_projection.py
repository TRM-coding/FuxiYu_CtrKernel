from types import SimpleNamespace

import pytest

from ...schemas.container import DeletedContainerRecord
from ...services.container_module import deleted_containers


@pytest.mark.parametrize("valid", [True, False, None])
def test_deleted_record_projects_original_container_validity(monkeypatch, valid):
    monkeypatch.setattr(deleted_containers, "_resolve_image_name", lambda _image_id: None)
    row = SimpleNamespace(
        id=11, original_container_id=7, container_name="test", snapshot={},
        machine_id=1, mount_cleanup_id=None, removed_at=None, removed_trigger="api",
        mount_cleaned=True,
    )
    container = None if valid is None else SimpleNamespace(is_valid=valid, image_id=None)
    result = deleted_containers.serialize_deleted_container_record(
        row, None, context={"container": container, "mount_path": "/home/u/containers/test"}
    )
    assert result["original_container_is_valid"] is valid
    assert DeletedContainerRecord(**result).original_container_is_valid is valid
