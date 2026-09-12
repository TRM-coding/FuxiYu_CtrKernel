"""information.py 出参组装工具的单元测试。

这一族是"纯拼装"，最容易被误改：磁盘上限口径、无快照的降级、分页兜底都在这里。
纯函数用 SimpleNamespace 直接喂入参；只有公共字段骨架需要真实容器/机器/绑定。
"""

from types import SimpleNamespace

from ...constant import ROLE
from ...services.container_module import information
from ..factories import create_container_graph

_GB = 1024 ** 3


def _fake_container(**overrides):
    values = dict(
        id=1, name="c1", image="ubuntu:22.04", created_at=None, machine_id=2, port=0,
        port_mappings=None, gpu_chosen_list=None, container_status="online",
        failed_reason=None, failed_detail=None,
        disk_total_bytes=2 * _GB, disk_overlay_rw_bytes=_GB, disk_bind_mount_bytes=_GB,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _fake_machine(**overrides):
    values = dict(id=2, machine_ip="10.0.0.2", max_disk_size_gb=4, cpu_core_number=8,
                  memory_size_gb=16, gpu_number=0)
    values.update(overrides)
    return SimpleNamespace(**values)


# ── 磁盘上限口径 ─────────────────────────────────────────────────────

def test_disk_limit_bytes_converts_gb():
    assert information._disk_limit_bytes(_fake_machine(max_disk_size_gb=4)) == 4 * _GB


def test_disk_limit_bytes_treats_unset_as_no_limit():
    """未配置（None / 0 / 负数）一律视为未设限 = 0，不能当成 0 字节上限。"""
    assert information._disk_limit_bytes(_fake_machine(max_disk_size_gb=None)) == 0
    assert information._disk_limit_bytes(_fake_machine(max_disk_size_gb=0)) == 0
    assert information._disk_limit_bytes(_fake_machine(max_disk_size_gb=-1)) == 0


# ── 列表项磁盘字段 ───────────────────────────────────────────────────

def test_brief_disk_usage_reports_none_when_no_snapshot():
    usage = information._build_brief_disk_usage(_fake_container(disk_total_bytes=None), _fake_machine())

    assert usage["disk_total_gb"] is None
    assert usage["disk_usage_percent"] == 0


def test_brief_disk_usage_zero_limit_does_not_divide_by_zero():
    """未设限机器上使用率给 0（不是除零，也不是 100%）。"""
    usage = information._build_brief_disk_usage(
        _fake_container(disk_total_bytes=10 * _GB), _fake_machine(max_disk_size_gb=0),
    )

    assert usage["disk_limit_gb"] is None
    assert usage["disk_usage_percent"] == 0


def test_brief_disk_usage_reports_percent_against_limit():
    usage = information._build_brief_disk_usage(
        _fake_container(disk_total_bytes=2 * _GB), _fake_machine(max_disk_size_gb=4),
    )

    assert usage == {"disk_total_gb": 2.0, "disk_limit_gb": 4.0, "disk_usage_percent": 50.0}


# ── 详情磁盘字段 ─────────────────────────────────────────────────────

def test_detail_disk_usage_is_none_without_snapshot():
    assert information._build_detail_disk_usage(_fake_container(disk_total_bytes=None), _fake_machine()) is None
    assert information._build_detail_disk_usage(_fake_container(disk_total_bytes=-1), _fake_machine()) is None


def test_detail_disk_usage_breaks_down_overlay_and_bind_mount():
    usage = information._build_detail_disk_usage(
        _fake_container(
            disk_overlay_rw_bytes=int(1.5 * _GB),
            disk_bind_mount_bytes=int(0.5 * _GB),
            disk_total_bytes=2 * _GB,
        ),
        _fake_machine(max_disk_size_gb=4),
    )

    assert usage == {
        "overlay_rw_gb": 1.5, "bind_mount_gb": 0.5,
        "total_gb": 2.0, "limit_gb": 4.0, "usage_percent": 50.0,
    }


# ── 分页结构 ─────────────────────────────────────────────────────────

def test_container_page_rounds_up_and_keeps_at_least_one_page():
    assert information._build_container_page([], 0, 10)["total_page"] == 1
    assert information._build_container_page([], 1, 10)["total_page"] == 1
    assert information._build_container_page([], 11, 10)["total_page"] == 2


def test_container_page_carries_items_and_total():
    page = information._build_container_page([{"a": 1}], 21, 10)

    assert page["containers"] == [{"a": 1}]
    assert page["total_number"] == 21


# ── 公共字段骨架（详情与列表共用） ────────────────────────────────────

def test_common_fields_carry_identity_accounts_and_effective_status(db_session):
    root, machine, container = create_container_graph()

    fields = information._build_container_common_fields(container, machine, [
        {"user_id": root.id, "username": "root", "role": ROLE.ROOT.value},
    ])

    assert fields["container_id"] == container.id
    assert fields["container_name"] == container.name
    assert fields["container_image"] == container.image
    assert fields["machine_id"] == machine.id
    assert fields["machine_ip"] == machine.machine_ip
    assert fields["accounts"] == [
        {"user_id": root.id, "username": "root", "role": ROLE.ROOT.value},
    ]
    assert fields["effective_status"]
    # 实时运行指标来自内存缓存；没有推送过就是 None，不能因此报错
    assert "runtime_metrics" in fields
