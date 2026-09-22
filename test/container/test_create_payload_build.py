"""creation._build_create_payload 的单元测试（纯函数，无 DB / 无网络）。

组包是创建流程里唯一"可以完全脱离环境验证"的一步：入参决定发给 Node 的载荷，
恢复路径的账号过滤与 role 映射出错会直接影响恢复出来的权限，所以单独锁一遍。
"""

from ...constant import ROLE
from ...services.container_module.creation import _build_create_payload
from ...utils.Container import Container_info


def _container() -> Container_info:
    return Container_info(
        gpu_list=[0, 1],
        cpu_number=4,
        memory=16,
        shared_memory=4,
        name="payload_c",
        image="ubuntu:22.04",
    )


def test_base_payload_always_carries_owner_and_config():
    payload = _build_create_payload(_container(), "alice")

    assert payload["owner_name"] == "alice"
    config = payload["config"]
    assert config["name"] == "payload_c"
    assert config["image"] == "ubuntu:22.04"
    assert config["cpu_number"] == 4
    assert config["memory"] == 16
    assert config["shared_memory"] == 4
    assert config["gpu_list"] == [0, 1]


def test_optional_keys_are_omitted_when_absent():
    payload = _build_create_payload(_container(), "alice")

    assert "public_key" not in payload
    assert "image_build" not in payload
    assert "restore_mount_path" not in payload
    assert "restore_accounts" not in payload


def test_optional_keys_are_included_when_present():
    payload = _build_create_payload(
        _container(),
        "alice",
        public_key="ssh-rsa AAAA",
        image_build={"base_image": "ubuntu:22.04"},
        restore_mount_path="/home/alice/containers/payload_c_data",
    )

    assert payload["public_key"] == "ssh-rsa AAAA"
    assert payload["image_build"] == {"base_image": "ubuntu:22.04"}
    assert payload["restore_mount_path"] == "/home/alice/containers/payload_c_data"


def test_restore_accounts_are_projected_to_user_name_and_role():
    payload = _build_create_payload(
        _container(),
        "alice",
        restore_accounts=[
            {"user_id": 7, "container_username": "bob", "role": ROLE.ADMIN.value},
            {"user_id": 8, "system_username": "carol", "role": ROLE.COLLABORATOR.value},
        ],
    )

    assert payload["restore_accounts"] == [
        {"user_name": "bob", "role": "admin"},
        {"user_name": "carol", "role": "collaborator"},
    ]


def test_restore_accounts_without_any_user_name_are_dropped():
    """两个用户名字段都缺的账号不进载荷：Node 侧无法建号，带过去只会整单失败。"""
    payload = _build_create_payload(
        _container(),
        "alice",
        restore_accounts=[
            {"user_id": 7, "role": ROLE.ADMIN.value},
            {"user_id": 8, "container_username": "carol", "role": ROLE.COLLABORATOR.value},
        ],
    )

    assert payload["restore_accounts"] == [{"user_name": "carol", "role": "collaborator"}]


def test_container_username_wins_over_system_username():
    payload = _build_create_payload(
        _container(),
        "alice",
        restore_accounts=[
            {"user_id": 7, "container_username": "container_bob", "system_username": "sys_bob"},
        ],
    )

    assert payload["restore_accounts"] == [{"user_name": "container_bob", "role": "collaborator"}]


def test_unknown_role_falls_back_to_collaborator():
    """快照里 role 缺失或非法时按最小权限恢复，不能凭空给出 admin。"""
    payload = _build_create_payload(
        _container(),
        "alice",
        restore_accounts=[
            {"user_id": 7, "container_username": "bob"},
            {"user_id": 8, "container_username": "carol", "role": "root"},
            {"user_id": 9, "container_username": "dave", "role": "garbage"},
        ],
    )

    assert payload["restore_accounts"] == [
        {"user_name": "bob", "role": "collaborator"},
        {"user_name": "carol", "role": "collaborator"},
        {"user_name": "dave", "role": "collaborator"},
    ]
