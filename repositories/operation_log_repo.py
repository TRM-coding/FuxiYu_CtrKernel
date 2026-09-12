"""操作日志 repo：只接收 session，不提交事务。"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.operation_log import OperationLog

logger = logging.getLogger(__name__)


def write(
    *,
    session: Session,
    operator_user_id: int | None = None,
    operation: str,
    target_type: str,
    target_id: int,
    detail: dict,
    success: bool,
    error_reason: str | None = None,
) -> OperationLog:
    """追加一条操作日志，事务由 service 控制。"""

    row = OperationLog(
        operator_user_id=operator_user_id,
        operation=operation,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        success=success,
        error_reason=error_reason,
    )
    session.add(row)
    session.flush()
    return row


def _parse_naive_utc(s: str, tz_offset_minutes: int | None = None) -> datetime | None:
    """把请求时间归一成 naive UTC，解析失败返回 None。"""

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


def _filtered_stmt(
    *,
    operator_user_id: int | None = None,
    operation: str | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    success: bool | None = None,
    start: str | None = None,
    end: str | None = None,
    tz_offset_minutes: int | None = None,
):
    stmt = select(OperationLog)
    if operator_user_id is not None:
        stmt = stmt.where(OperationLog.operator_user_id == operator_user_id)
    if operation:
        stmt = stmt.where(OperationLog.operation == operation)
    if target_type:
        stmt = stmt.where(OperationLog.target_type == target_type)
    if target_id is not None:
        stmt = stmt.where(OperationLog.target_id == int(target_id))
    if success is not None:
        stmt = stmt.where(OperationLog.success.is_(success))
    if start:
        start_dt = _parse_naive_utc(start, tz_offset_minutes)
        if start_dt is not None:
            stmt = stmt.where(OperationLog.created_at >= start_dt)
    if end:
        end_dt = _parse_naive_utc(end, tz_offset_minutes)
        if end_dt is not None:
            stmt = stmt.where(OperationLog.created_at <= end_dt)
    return stmt


def list_logs(
    *,
    session: Session,
    page: int = 1,
    page_size: int = 20,
    operator_user_id: int | None = None,
    operation: str | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    success: bool | None = None,
    start: str | None = None,
    end: str | None = None,
    tz_offset_minutes: int | None = None,
) -> tuple[list[OperationLog], int]:
    """分页查询操作日志，按 id 倒序返回。"""

    stmt = _filtered_stmt(
        operator_user_id=operator_user_id,
        operation=operation,
        target_type=target_type,
        target_id=target_id,
        success=success,
        start=start,
        end=end,
        tz_offset_minutes=tz_offset_minutes,
    )
    total = int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    page = max(1, int(page))
    page_size = min(100, max(1, int(page_size)))
    total_pages = (total + page_size - 1) // page_size
    rows = list(
        session.scalars(
            stmt.order_by(OperationLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return rows, total_pages


def serialize(row: OperationLog) -> dict:
    """OperationLog 行转 API JSON 结构。"""

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
    *,
    session: Session,
    start: str | None = None,
    end: str | None = None,
    tz_offset_minutes: int | None = None,
) -> dict:
    """按时间范围聚合操作日志统计。"""

    stmt = _filtered_stmt(start=start, end=end, tz_offset_minutes=tz_offset_minutes)
    rows = list(
        session.execute(
            stmt.with_only_columns(
                OperationLog.operation,
                OperationLog.target_type,
                OperationLog.created_at,
                OperationLog.success,
            )
        ).all()
    )

    day_offset = timedelta(minutes=tz_offset_minutes) if tz_offset_minutes else None
    total = len(rows)
    succeeded = sum(1 for row in rows if row.success)
    failed = total - succeeded

    by_operation: dict[str, int] = {}
    by_target_type: dict[str, int] = {}
    by_day: dict[str, dict] = {}
    for row in rows:
        op = row.operation or "unknown"
        target_type = row.target_type or "unknown"
        by_operation[op] = by_operation.get(op, 0) + 1
        by_target_type[target_type] = by_target_type.get(target_type, 0) + 1

        day_dt = (row.created_at + day_offset) if (row.created_at and day_offset) else row.created_at
        day = day_dt.strftime("%Y-%m-%d") if day_dt else "unknown"
        bucket = by_day.setdefault(day, {"success": 0, "failed": 0})
        if row.success:
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
