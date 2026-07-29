import pytest

from ...services import container_tasks


def test_raise_on_node_error_rejects_non_dict():
    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks._raise_on_node_error("bad", "create")

    assert excinfo.value.reason == "unexpected_response"


def test_raise_on_node_error_maps_network_error():
    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks._raise_on_node_error({"error": "timeout"}, "create")

    assert excinfo.value.reason == "NODE_error"


def test_raise_on_node_error_maps_error_reason():
    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks._raise_on_node_error({"success": 0, "error_reason": "docker_init_failed"}, "create")

    assert excinfo.value.reason == "docker_init_failed"


def test_raise_on_node_error_allows_success_response():
    container_tasks._raise_on_node_error({"success": 1}, "create")
