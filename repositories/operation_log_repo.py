from ..extensions import db
from ..models.operation_log import OperationLog


def write(
    *,
    operator_user_id: int | None = None,
    operation: str,
    target_type: str,
    target_id: int,
    detail: dict | None = None,
    success: bool = True,
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
        print(f"[op-log] failed to write log: {e}")
        return None
