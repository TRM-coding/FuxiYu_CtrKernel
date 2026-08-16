import logging
from datetime import datetime

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
) -> tuple[list[OperationLog], int]:
    """分页查询操作日志，按 id 倒序（新的在前）。返回 (rows, total_pages)。

    start / end 接受 ISO 字符串（建议由前端先转 UTC 再传，
    与库内 naive UTC 的 created_at 保持一致口径）。
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
        try:
            q = q.filter(OperationLog.created_at >= datetime.fromisoformat(start))
        except Exception:
            pass
    if end:
        try:
            q = q.filter(OperationLog.created_at <= datetime.fromisoformat(end))
        except Exception:
            pass

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


def stats(start: str | None = None, end: str | None = None) -> dict:
    """按时间范围聚合统计（图表用）。

    返回 {"total": n, "succeeded": n, "failed": n,
          "by_operation": {op: n}, "by_target_type": {t: n}}
    """
    q = OperationLog.query
    if start:
        try:
            q = q.filter(OperationLog.created_at >= datetime.fromisoformat(start))
        except Exception:
            pass
    if end:
        try:
            q = q.filter(OperationLog.created_at <= datetime.fromisoformat(end))
        except Exception:
            pass

    total = q.count()
    succeeded = q.filter(OperationLog.success.is_(True)).count()
    failed = total - succeeded

    by_operation: dict[str, int] = {}
    by_target_type: dict[str, int] = {}
    for row in q.with_entities(OperationLog.operation, OperationLog.target_type).all():
        op = row.operation or "unknown"
        tt = row.target_type or "unknown"
        by_operation[op] = by_operation.get(op, 0) + 1
        by_target_type[tt] = by_target_type.get(tt, 0) + 1

    return {
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "by_operation": by_operation,
        "by_target_type": by_target_type,
    }
