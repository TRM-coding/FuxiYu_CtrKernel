####################################################
# 辅助工具

_MONTH_ABBR_TO_NUM = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _parse_last_ssh_time(raw: str | None) -> datetime | None:
    """
    尝试把 Node 返回的 last ssh 时间解析为 datetime。
    支持：
    - ISO/常见 datetime 字符串
    - syslog 风格：`Mar 20 12:34:56 ...`
    - `last` 输出中的日期片段：`Fri Mar 20 12:34 ...`
    """
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None

    # 1) 直接尝试 fromisoformat / 通用格式
    try:
        v = s.replace("Z", "+00:00")
        return datetime.fromisoformat(v)
    except Exception:
        pass

    # 2) 提取 "Mon DD HH:MM[:SS]" 片段（无年份时使用当前年）
    m = re.search(r"\b([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{2}:\d{2}(?::\d{2})?)\b", s)
    if not m:
        return None
    mon = _MONTH_ABBR_TO_NUM.get(m.group(1))
    if not mon:
        return None
    day = int(m.group(2))
    hhmmss = m.group(3)
    parts = hhmmss.split(":")
    hour = int(parts[0])
    minute = int(parts[1])
    second = int(parts[2]) if len(parts) > 2 else 0
    now = datetime.utcnow()
    try:
        return datetime(now.year, mon, day, hour, minute, second)
    except Exception:
        return None


def build_cleanup_info(last_ssh_login_time: str | None, cleanup_after_days: int) -> dict:
    """
    基于上次 SSH 登录时间计算清理时间信息（仅计算，不执行清理）。
    """
    # logger.debug("DEBUG: build_cleanup_info called with last_ssh_login_time='%s' and cleanup_after_days=%s", last_ssh_login_time, cleanup_after_days)
    if cleanup_after_days <= 0:
        cleanup_after_days = 1

    last_dt = _parse_last_ssh_time(last_ssh_login_time)
    if last_dt is None:
        return {
            "cleanup_after_days": cleanup_after_days,
            "cleanup_at": None,
            "seconds_until_cleanup": None,
            "cleanup_status": "unknown",
        }

    cleanup_at = last_dt + timedelta(days=cleanup_after_days)
    seconds_left = int((cleanup_at - datetime.utcnow()).total_seconds())
    if seconds_left <= 0:
        status = "due"
        seconds_left = 0
    else:
        status = "countdown"

    return {
        "cleanup_after_days": cleanup_after_days,
        "cleanup_at": cleanup_at.isoformat(),
        "seconds_until_cleanup": seconds_left,
        "cleanup_status": status,
    }
