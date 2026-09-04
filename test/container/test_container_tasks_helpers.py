from datetime import datetime, timedelta

from ...config import CommsConfig
from ...services import container_tasks


def test_parse_last_ssh_time_accepts_iso():
    parsed = container_tasks._parse_last_ssh_time("2026-05-25T10:20:30")

    assert parsed == datetime(2026, 5, 25, 10, 20, 30)


def test_parse_last_ssh_time_accepts_syslog_fragment():
    parsed = container_tasks._parse_last_ssh_time("May 25 10:20:30 sshd[1]: accepted")

    assert parsed.month == 5
    assert parsed.day == 25
    assert parsed.hour == 10
    assert parsed.minute == 20
    assert parsed.second == 30


def test_parse_last_ssh_time_accepts_last_output_fragment():
    parsed = container_tasks._parse_last_ssh_time("Mon May 25 10:20 still logged in")

    assert parsed.month == 5
    assert parsed.day == 25
    assert parsed.hour == 10
    assert parsed.minute == 20


def test_parse_last_ssh_time_returns_none_for_empty_or_invalid():
    assert container_tasks._parse_last_ssh_time(None) is None
    assert container_tasks._parse_last_ssh_time("") is None
    assert container_tasks._parse_last_ssh_time("not a time") is None


def test_build_cleanup_info_unknown_when_no_last_ssh():
    info = container_tasks.build_cleanup_info(None, 7)

    assert info["cleanup_status"] == "unknown"
    assert info["cleanup_at"] is None
    assert info["seconds_until_cleanup"] is None


def test_build_cleanup_info_due_when_expired():
    old = (datetime.utcnow() - timedelta(days=8)).isoformat()

    info = container_tasks.build_cleanup_info(old, 7)

    assert info["cleanup_status"] == "due"
    assert info["seconds_until_cleanup"] == 0


def test_build_cleanup_info_countdown_when_not_expired():
    recent = (datetime.utcnow() - timedelta(days=1)).isoformat()

    info = container_tasks.build_cleanup_info(recent, 7)

    assert info["cleanup_status"] == "countdown"
    assert info["cleanup_at"] is not None
    assert info["seconds_until_cleanup"] > 0


def test_build_cleanup_info_clamps_invalid_cleanup_days_to_one():
    info = container_tasks.build_cleanup_info(None, 0)

    assert info["cleanup_after_days"] == 1


def test_get_full_url_uses_node_middle_path():
    # TLS 方案：Node uvicorn 已挂 ssl，URL 统一 https
    assert (
        container_tasks.get_full_url("127.0.0.1", "/create_container")
        == f"https://127.0.0.1{CommsConfig.NODE_URL_MIDDLE}/create_container"
    )
