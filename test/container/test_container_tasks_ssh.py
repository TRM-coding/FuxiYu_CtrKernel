from datetime import datetime, timedelta

import pytest

from ...repositories import container_ssh_login_repo
from ...services import container_tasks
from .conftest import NODE_ENDPOINT_404_HTML, NODE_LAST_SSH_FOUND, NODE_LAST_SSH_NOT_FOUND


# ── _parse_last_ssh_time ──────────────────────────────────────────────

class TestParseLastSSHTime:
    def test_iso_8601(self):
        dt = container_tasks._parse_last_ssh_time("2026-06-17T03:40:00")
        assert dt == datetime(2026, 6, 17, 3, 40, 0)

    def test_iso_with_Z(self):
        from datetime import timezone
        dt = container_tasks._parse_last_ssh_time("2026-06-17T03:40:00Z")
        assert dt == datetime(2026, 6, 17, 3, 40, 0, tzinfo=timezone.utc)

    def test_iso_with_microseconds(self):
        dt = container_tasks._parse_last_ssh_time("2026-06-17T03:40:00.123456")
        assert dt == datetime(2026, 6, 17, 3, 40, 0, 123456)

    def test_raw_last_output(self):
        raw = "root     pts/9        10.60.4.87       Wed Jun 17 11:40   still logged in"
        dt = container_tasks._parse_last_ssh_time(raw)
        assert dt == datetime(datetime.utcnow().year, 6, 17, 11, 40, 0)

    def test_raw_last_gone_no_logout(self):
        raw = "root     pts/1        202.205.102.121  Mon Jun 15 13:29    gone - no logout"
        dt = container_tasks._parse_last_ssh_time(raw)
        assert dt == datetime(datetime.utcnow().year, 6, 15, 13, 29, 0)

    def test_none_input(self):
        assert container_tasks._parse_last_ssh_time(None) is None

    def test_empty_string(self):
        assert container_tasks._parse_last_ssh_time("") is None
        assert container_tasks._parse_last_ssh_time("   ") is None

    def test_malformed_iso(self):
        # "June" 是 4 字母，不是有效月份
        assert container_tasks._parse_last_ssh_time("2026-06-13T18:June:23") is None

    def test_unrecognizable_text(self):
        assert container_tasks._parse_last_ssh_time("some random text") is None


# ── build_cleanup_info ────────────────────────────────────────────────

class TestBuildCleanupInfo:
    def test_iso_utc_time_countdown(self):
        # 3 天前的 SSH → cleanup_at = 3 天前 + 7 天 = 4 天后
        past = datetime.utcnow() - timedelta(days=3)
        info = container_tasks.build_cleanup_info(
            past.strftime("%Y-%m-%dT%H:%M:%S"), cleanup_after_days=7
        )
        assert info["cleanup_status"] == "countdown"
        assert info["seconds_until_cleanup"] > 0
        # 约 4 天剩余（误差在几秒内）
        expected = 4 * 24 * 3600
        assert abs(info["seconds_until_cleanup"] - expected) < 10

    def test_old_login_due(self):
        # 10 天前的 SSH → cleanup_at 已过期
        past = datetime.utcnow() - timedelta(days=10)
        info = container_tasks.build_cleanup_info(
            past.strftime("%Y-%m-%dT%H:%M:%S"), cleanup_after_days=7
        )
        assert info["cleanup_status"] == "due"
        assert info["seconds_until_cleanup"] == 0

    def test_none_time_unknown(self):
        info = container_tasks.build_cleanup_info(None, cleanup_after_days=7)
        assert info["cleanup_status"] == "unknown"
        assert info["cleanup_at"] is None
        assert info["seconds_until_cleanup"] is None

    def test_cleanup_after_days_clamped(self):
        past = datetime.utcnow() - timedelta(days=1)
        info = container_tasks.build_cleanup_info(
            past.strftime("%Y-%m-%dT%H:%M:%S"), cleanup_after_days=0
        )
        # cleanup_after_days <= 0 应 clamp 到 1
        assert info["cleanup_after_days"] == 1


# ── get_container_last_ssh_login_time 归一化 ───────────────────────────

def test_get_last_ssh_time_normalizes_raw_output_to_iso(
    db_session,
    container_graph,
    mock_node_send,

):
    """Node 返回 raw last 文本 → Ctrl 归一化为 ISO UTC 存入 DB。"""
    _root, machine, container = container_graph
    # Node 响应（TZ=UTC 后，last 输出 UTC 时间）
    mock_node_send({"success": 1, "last_ssh_connect_time": "root pts/0 10.0.0.1 Wed Jun 17 03:40 still logged in"})

    last_time = container_tasks.get_container_last_ssh_login_time(container.id)

    # 返回值和 DB 存储都应该是 ISO 格式
    assert last_time == "2026-06-17T03:40:00"
    record = container_ssh_login_repo.get_by_machine_container(machine.id, container.id)
    assert record.last_ssh_login_time == "2026-06-17T03:40:00"


def test_get_last_ssh_time_passes_through_iso(
    db_session,
    container_graph,
    mock_node_send,

):
    """Node 返回已是 ISO 格式 → 直接存储，不重复转换。"""
    _root, machine, container = container_graph
    mock_node_send({"success": 1, "last_ssh_connect_time": "2026-06-17T03:40:00"})

    last_time = container_tasks.get_container_last_ssh_login_time(container.id)

    assert last_time == "2026-06-17T03:40:00"
    record = container_ssh_login_repo.get_by_machine_container(machine.id, container.id)
    assert record.last_ssh_login_time == "2026-06-17T03:40:00"


def test_get_last_ssh_time_not_found_does_not_overwrite(
    db_session,
    container_graph,
    mock_node_send,

):
    """Node 返回 not_found → 不覆写已有值。"""
    _root, machine, container = container_graph
    # 先设一个初始值
    initial_time = "2026-06-13T18:06:23"
    container_ssh_login_repo.upsert_last_ssh_login_time(
        machine.id, container.id, initial_time
    )

    mock_node_send(NODE_LAST_SSH_NOT_FOUND)
    last_time = container_tasks.get_container_last_ssh_login_time(container.id)

    # Node 返回 not_found，但 DB 已有初始值 → 兜底返回 DB 值
    assert last_time == initial_time
    record = container_ssh_login_repo.get_by_machine_container(machine.id, container.id)
    # 数据库里的值没有被 None 覆写
    assert record.last_ssh_login_time == initial_time


def test_get_last_ssh_time_invalid_container_id_returns_none(db_session):
    assert container_tasks.get_container_last_ssh_login_time("bad") is None
    assert container_tasks.get_container_last_ssh_login_time(999999) is None


def test_get_last_ssh_time_endpoint_404_raises_node_endpoint_not_found(
    db_session,
    container_graph,
    mock_node_send,

):
    _root, _machine, container = container_graph
    mock_node_send(NODE_ENDPOINT_404_HTML)

    with pytest.raises(container_tasks.NodeServiceError) as excinfo:
        container_tasks.get_container_last_ssh_login_time(container.id)

    assert excinfo.value.reason == "node_endpoint_not_found"
