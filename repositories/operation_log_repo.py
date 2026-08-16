import logging
from datetime import datetime, timedelta, timezone

from ..extensions import db
from ..models.operation_log import OperationLog

logger = logging.getLogger(__name__)


def write(
    *,
    operator_user_id: int | None = None,
    operation: str,
    target_type: str,
    target_id: int,
    detail: dict,
    success: bool,
    error_reason: str | None = None,
) -> OperationLog:
    """写操作日志。本身不抛异常，失败只打 print。"""
    try:
        row = OperationLog(
            operator_user_id=operator_user_id,
            operation=operation,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            success=success,
            error_reason=error_reason,
        )
        db.session.add(row)
        db.session.commit()
        return row
    except Exception as e:
        db.session.rollback()
        logger.warning("failed to write operation log: %s", e)
        return None


def _parse_naive_utc(s: str, tz_offset_minutes: int | None = None) -> datetime | None:
    """把请求时间串归一化为 naive UTC（与库内 created_at 口径一致）。

    - 带偏移的 ISO 串（如 2026-08-11T00:00:00+08:00 / 结尾 Z）→ 转 UTC 去时区；
    - naive 串 + tz_offset_minutes（分钟，UTC = 本地 - 偏移）→ 减偏移得 UTC；
    - 仅 naive 串 → 视为已是 UTC（兼容不传偏移的旧客户端）。
    解析失败返回 None（调用方按"该边界不过滤"处理）。
    """
    s = (s or "").strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = f"{s[:-1]}+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    if tz_offset_minutes:
        return dt - timedelta(minutes=tz_offset_minutes)
    return dt


def list_logs(
    *,
    page: int = 1,
    page_size: int = 20,
    operator_user_id: int | None = None,
    operation: str | None = None,
    target_type: str | None = None,
    success: bool | None = None,
    start: str | None = None,
    end: str | None = None,
    tz_offset_minutes: int | None = None,
) -> tuple[list[OperationLog], int]:
    """分页查询操作日志，按 id 倒序（新的在前）。返回 (rows, total_pages)。

    start / end 接受 ISO 字符串：前端按"所见即所得"的本地时间原样传，
    并附 tz_offset_minutes（本地相对 UTC 的分钟偏移，如北京时间 +480），
    由本层解析成库内 naive UTC 口径后再过滤（见 _parse_naive_utc）。
    """
    q = OperationLog.query
    if operator_user_id is not None:
        q = q.filter(OperationLog.operator_user_id == operator_user_id)
    if operation:
        q = q.filter(OperationLog.operation == operation)
    if target_type:
        q = q.filter(OperationLog.target_type == target_type)
    if success is not None:
        q = q.filter(OperationLog.success.is_(success))
    if start:
        start_dt = _parse_naive_utc(start, tz_offset_minutes)
        if start_dt is not None:
            q = q.filter(OperationLog.created_at >= start_dt)
    if end:
        end_dt = _parse_naive_utc(end, tz_offset_minutes)
        if end_dt is not None:
            q = q.filter(OperationLog.created_at <= end_dt)

    total = q.count()
    page = max(1, int(page))
    page_size = min(100, max(1, int(page_size)))
    total_pages = (total + page_size - 1) // page_size
    rows = (
        q.order_by(OperationLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return rows, total_pages


def serialize(row: OperationLog) -> dict:
    """行 → 对外 JSON 结构（序列化收敛在 repo 层）。"""
    return {
        "id": row.id,
        "operator_user_id": row.operator_user_id,
        "operation": row.operation,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "detail": row.detail,
        "success": bool(row.success),
        "error_reason": row.error_reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def stats(
    start: str | None = None,
    end: str | None = None,
    tz_offset_minutes: int | None = None,
) -> dict:
    """按时间范围聚合统计（图表用）。

    start / end 与 tz_offset_minutes 的口径同 list_logs。
    by_day 的分桶日随 tz_offset_minutes 偏移：传偏移时按"本地日"分桶
    （如北京时间：库内 8/16 16:03 → 桶 8/17），使前端 UTC+8 的日期轴对齐。

    返回 {"total": n, "succeeded": n, "failed": n,
          "by_day": {"YYYY-MM-DD": {"success": n, "failed": n}},
          "by_operation": {op: n}, "by_target_type": {t: n}}
    """
    q = OperationLog.query
    if start:
        start_dt = _parse_naive_utc(start, tz_offset_minutes)
        if start_dt is not None:
            q = q.filter(OperationLog.created_at >= start_dt)
    if end:
        end_dt = _parse_naive_utc(end, tz_offset_minutes)
        if end_dt is not None:
            q = q.filter(OperationLog.created_at <= end_dt)

    day_offset = timedelta(minutes=tz_offset_minutes) if tz_offset_minutes else None

    total = q.count()
    succeeded = q.filter(OperationLog.success.is_(True)).count()
    failed = total - succeeded

    by_operation: dict[str, int] = {}
    by_target_type: dict[str, int] = {}
    by_day: dict[str, dict] = {}
    for row in q.with_entities(
        OperationLog.operation,
        OperationLog.target_type,
        OperationLog.created_at,
        OperationLog.success,
    ).all():
        op, tt, created_at, ok = row
        op = op or "unknown"
        tt = tt or "unknown"
        by_operation[op] = by_operation.get(op, 0) + 1
        by_target_type[tt] = by_target_type.get(tt, 0) + 1

        day_dt = (created_at + day_offset) if (created_at and day_offset) else created_at
        day = day_dt.strftime("%Y-%m-%d") if day_dt else "unknown"
        bucket = by_day.setdefault(day, {"success": 0, "failed": 0})
        if ok:
            bucket["success"] += 1
        else:
            bucket["failed"] += 1

    return {
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "by_day": by_day,
        "by_operation": by_operation,
        "by_target_type": by_target_type,
    }
