from datetime import datetime, timedelta

import pytest

from ...constant import ContainerStatus, MachineStatus, ROLE
from ...extensions import session_scope
from ...repositories import usercontainer_repo, container_ssh_login_repo, long_term_container_repo, machine_permission_repo
from ...models.containers import Container

from ...services import container_tasks
from ..factories import create_container, create_machine, create_user
from .conftest import NODE_STATUS_404, NODE_STATUS_OFFLINE, NODE_STATUS_ONLINE


def test_get_container_detail_reads_status_from_db(db_session, container_graph):
    # getter 对外返回 effective_status；基础事实仍来自 WSS 落库的 container_status 字段
    _root, machine, container = container_graph
    container.container_status = ContainerStatus.OFFLINE
    db_session.commit()

    info = container_tasks.get_container_detail_information(container.id)

    assert info["container_id"] == container.id
    assert info["effective_status"] == ContainerStatus.OFFLINE.value


def test_get_container_detail_keeps_default_status_from_db(db_session, container_graph):
    # 工厂默认 ONLINE：不写 DB 状态时读默认值，不触发任何 Node 调用
    _root, _machine, container = container_graph

    info = container_tasks.get_container_detail_information(container.id)

    assert info["container_id"] == container.id
    assert info["effective_status"] == ContainerStatus.ONLINE.value


def test_get_container_detail_includes_cached_runtime_metrics(monkeypatch, db_session, container_graph):
    from ...services.container_module import node_comms

    _root, machine, container = container_graph
    runtime = {"cpu_usage_percent": 12.5, "gpu": {"devices": [{"index": 0, "utilization_gpu_percent": 70}]}}
    monkeypatch.setattr(
        node_comms,
        "get_cached_container_runtime_metrics",
        lambda machine_id, container_name: runtime
        if machine_id == machine.id and container_name == container.name else None,
    )

    info = container_tasks.get_container_detail_information(container.id)

    assert info["runtime_metrics"] == runtime


def test_get_container_detail_includes_ssh_and_cleanup_info(db_session, container_graph):
    # 详情与列表同一口径：上次 SSH 登录时间 + 清理倒计时由 ssh 快照落库派生
    _root, machine, container = container_graph
    last_time = (datetime.utcnow() - timedelta(days=1)).isoformat()
    container_ssh_login_repo.upsert_last_ssh_login_time(machine.id, container.id, last_time, session=db_session)

    db_session.commit()

    info = container_tasks.get_container_detail_information(container.id)

    assert info["last_ssh_login_time"] == last_time
    assert info["cleanup_status"] == "countdown"
    assert info["seconds_until_cleanup"] > 0


def test_get_container_detail_derives_ssh_port_mapping_from_port(db_session, container_graph):
    _root, _machine, container = container_graph
    container.port = 22122
    container.port_mappings = None
    db_session.commit()

    info = container_tasks.get_container_detail_information(container.id)

    assert info["port"] == 22122
    assert info["port_mappings"] == [
        {"container_port": 22, "host_port": 22122, "protocol": "tcp"}
    ]


def test_list_container_bref_operator_can_filter_by_user(monkeypatch, db_session):
    operator = create_user(operator=True)
    target = create_user()
    _root, machine, container = container_tasks_test_graph_for_user(target, db_session)

    db_session.commit()

    result = container_tasks.list_all_container_bref_information(
        machine_id=None,
        request_user_id=operator.id,
        page_number=0,
        page_size=10,
        user_id=target.id,
    )

    assert [c.container_id for c in result["containers"]] == [container.id]


def test_list_container_bref_includes_cached_runtime_metrics(monkeypatch, db_session):
    from ...services.container_module import node_comms

    operator = create_user(operator=True)
    machine = create_machine()
    container = create_container(machine=machine, name="metrics_bref")
    runtime = {"memory_usage_percent": 33.3, "gpu": {"device_ids": ["0"]}}
    monkeypatch.setattr(
        node_comms,
        "get_cached_container_runtime_metrics",
        lambda machine_id, container_name: runtime
        if machine_id == machine.id and container_name == container.name else None,
    )

    result = container_tasks.list_all_container_bref_information(
        machine_id=machine.id,
        request_user_id=operator.id,
        page_number=0,
        page_size=10,
    )

    assert result["containers"][0].runtime_metrics == runtime


def test_list_container_bref_filters_by_container_search_name(monkeypatch, db_session):
    operator = create_user(operator=True)
    machine = create_machine()
    target = create_container(machine=machine, name="alpha_target")
    create_container(machine=machine, name="beta_other")

    db_session.commit()

    result = container_tasks.list_all_container_bref_information(
        machine_id=machine.id,
        request_user_id=operator.id,
        page_number=0,
        page_size=10,
        container_search="target",
    )

    assert [c.container_id for c in result["containers"]] == [target.id]
    assert result["total_number"] == 1


def test_list_container_bref_container_search_matches_port_and_machine_ip(monkeypatch, db_session):
    operator = create_user(operator=True)
    target_machine = create_machine(machine_ip="10.10.10.8")
    other_machine = create_machine(machine_ip="10.10.10.9")
    target = create_container(machine=target_machine, name="alpha", port=2208)
    create_container(machine=other_machine, name="beta", port=2209)

    db_session.commit()

    by_port = container_tasks.list_all_container_bref_information(
        machine_id=None,
        request_user_id=operator.id,
        page_number=0,
        page_size=10,
        container_search="2208",
    )
    by_ip = container_tasks.list_all_container_bref_information(
        machine_id=None,
        request_user_id=operator.id,
        page_number=0,
        page_size=10,
        container_search="10.10.10.8",
    )

    assert [c.container_id for c in by_port["containers"]] == [target.id]
    assert [c.container_id for c in by_ip["containers"]] == [target.id]


def test_list_container_bref_includes_cleanup_info_from_ssh_record(monkeypatch, db_session, container_graph):
    from ...services.container_module import node_comms

    root, machine, container = container_graph
    last_time = (datetime.utcnow() - timedelta(days=1)).isoformat()
    container_ssh_login_repo.upsert_last_ssh_login_time(machine.id, container.id, last_time, session=db_session)

    db_session.commit()

    result = container_tasks.list_all_container_bref_information(
        machine_id=None,
        request_user_id=root.id,
        page_number=0,
        page_size=10,
        user_id=root.id,
    )

    info = result["containers"][0]
    assert info.last_ssh_login_time == last_time
    assert info.cleanup_status == "countdown"
    assert info.seconds_until_cleanup > 0


def test_list_container_bref_includes_long_term_remaining_when_user_filter_present(
    db_session,
    container_graph,
):
    root, _machine, container = container_graph
    long_term_container_repo.add(container.id, created_by_user_id=root.id, session=db_session)

    db_session.commit()

    result = container_tasks.list_all_container_bref_information(
        machine_id=None,
        request_user_id=root.id,
        page_number=0,
        page_size=10,
        user_id=root.id,
    )

    assert result["long_term_container_limit"] == 1
    assert result["long_term_container_remaining"] == 0


def container_tasks_test_graph_for_user(user, db_session):
    machine = create_machine()
    container = create_container(machine=machine)
    machine_permission_repo.add_permission(machine.id, user.id, session=db_session)
    with session_scope() as session:
        usercontainer_repo.add_binding(user.id, container.id, role=ROLE.ROOT, username="root", session=session)
    return user, machine, container


def test_container_detail_derives_trimmed_alloc_limits(db_session, container_graph):
    """机器上限 trim 后容器申请超限 → 展示派生砍后值，容器 DB 不动。"""
    _root, machine, container = container_graph
    machine.max_memory_gb = 4
    machine.max_cpu_core_number = 2
    # GPU 三集合（决策）：许可上限从 allow_list 派生；chosen 超出许可 → 砍
    machine.gpu_allow_list = [0]
    container.memory_gb = 8
    container.cpu_number = 4
    container.gpu_number = 2
    container.gpu_chosen_list = [0, 1]
    db_session.commit()

    info = container_tasks.get_container_detail_information(container.id)

    assert info["memory_gb"] == 8                # 原始值不动
    assert info["alloc_memory_gb"] == 4          # 派生砍后值
    assert info["alloc_cpu_number"] == 2
    assert info["alloc_gpu_number"] == 1
    assert info["alloc_degraded"] is True


def test_container_detail_no_trim_when_within_limits(db_session, container_graph):
    """申请未超上限 → alloc_* 与原始一致，不标记 degraded。"""
    _root, machine, container = container_graph
    machine.max_memory_gb = 16
    machine.max_cpu_core_number = 8
    machine.gpu_allow_list = [0, 1, 2, 3]
    container.memory_gb = 8
    container.cpu_number = 4
    container.gpu_number = 1
    container.gpu_chosen_list = [0]
    db_session.commit()

    info = container_tasks.get_container_detail_information(container.id)

    assert info["alloc_memory_gb"] == 8
    assert info["alloc_cpu_number"] == 4
    assert info["alloc_gpu_number"] == 1
    assert info["alloc_degraded"] is False


def test_container_detail_gpu_allow_derives_chosen_outside_allow(db_session, container_graph):
    """GPU 三集合派生：chosen 超出 allow_list → degraded + 展示砍后数量（chosen ∩ allow）。"""
    _root, machine, container = container_graph
    machine.gpu_allow_list = [0, 1]
    container.gpu_chosen_list = [0, 2]
    db_session.commit()

    info = container_tasks.get_container_detail_information(container.id)

    assert info["gpu_chosen_list"] == [0, 2]      # 容器记录不动
    assert info["alloc_gpu_number"] == 1          # chosen ∩ allow = [0]
    assert info["alloc_degraded"] is True


def test_container_detail_gpu_allow_clean_when_chosen_within_allow(db_session, container_graph):
    """chosen 全在 allow 内 → 不 degraded。"""
    _root, machine, container = container_graph
    machine.gpu_allow_list = [0, 1, 2]
    container.gpu_chosen_list = [0, 2]
    db_session.commit()

    info = container_tasks.get_container_detail_information(container.id)

    assert info["alloc_gpu_number"] == 2
    assert info["alloc_degraded"] is False


def test_container_detail_disk_limit_derives_from_machine_max(db_session, container_graph):
    """统一口径（2026-09-01）：容器磁盘上限 = machine.max_disk_size_gb 现算派生。

    不再依赖任何 per-container 落库值（disk_limit_bytes 列已移除），
    disk-check 是否跑过都不影响展示。
    """
    _root, machine, container = container_graph
    machine.max_disk_size_gb = 50
    container.disk_total_bytes = int(10 * 1024**3)
    db_session.commit()

    info = container_tasks.get_container_detail_information(container.id)

    usage = info["disk_usage"]
    assert usage["limit_gb"] == 50.0
    assert usage["total_gb"] == 10.0
    assert usage["usage_percent"] == 20.0


def test_container_detail_disk_limit_unset_means_no_limit(db_session, container_graph):
    """max_disk_size_gb 未配置（<=0）→ 视为未设限：limit 0、percent 0。"""
    _root, machine, container = container_graph
    machine.max_disk_size_gb = None
    container.disk_total_bytes = int(5 * 1024**3)
    db_session.commit()

    info = container_tasks.get_container_detail_information(container.id)

    assert info["disk_usage"]["limit_gb"] == 0.0
    assert info["disk_usage"]["usage_percent"] == 0.0


def test_list_container_bref_disk_limit_derives_from_machine_max(monkeypatch, db_session):
    """列表容器卡片磁盘上限 = machine.max_disk_size_gb（无需 disk-check 落库）。"""
    from ...services.container_module import node_comms

    monkeypatch.setattr(node_comms, "get_cached_container_runtime_metrics", lambda machine_id, name: None)
    operator = create_user(operator=True)
    machine = create_machine(max_disk_size_gb=80)
    container = create_container(machine=machine, name="disk_limit_bref", image="ubuntu:24.04")
    container.disk_total_bytes = int(40 * 1024**3)
    db_session.commit()

    result = container_tasks.list_all_container_bref_information(
        machine_id=machine.id,
        request_user_id=operator.id,
        page_number=0,
        page_size=10,
    )

    item = result["containers"][0]
    assert item.disk_limit_gb == 80.0
    assert item.disk_usage_percent == 50.0
    # 卡片镜像名：bref 直接携带（前端 Home 卡片只消费 bref，无 detail 兜底）
    assert item.container_image == "ubuntu:24.04"


def test_list_container_bref_derives_ssh_port_mapping_from_port(monkeypatch, db_session):
    from ...services.container_module import node_comms

    monkeypatch.setattr(node_comms, "get_cached_container_runtime_metrics", lambda machine_id, name: None)
    operator = create_user(operator=True)
    machine = create_machine()
    container = create_container(machine=machine, name="port_mapping_bref", port=22123)
    container.port_mappings = None
    db_session.commit()

    result = container_tasks.list_all_container_bref_information(
        machine_id=machine.id,
        request_user_id=operator.id,
        page_number=0,
        page_size=10,
    )

    item = result["containers"][0]
    assert item.port == 22123
    assert item.port_mappings == [
        {"container_port": 22, "host_port": 22123, "protocol": "tcp"}
    ]
