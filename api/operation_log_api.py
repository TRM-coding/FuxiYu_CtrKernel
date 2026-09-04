from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ..schemas.operation_log import OperationLogListResponse, OperationLogStatsResponse
from ..services import operation_log_tasks
from .deps import require_operator

router = APIRouter(prefix="/admin/operation_logs", tags=["operation_logs"])


def _error(status_code: int, message: str, error_reason: str) -> JSONResponse:
    """返回 Ctrl 现有错误结构。"""

    return JSONResponse(
        status_code=status_code,
        content={"success": 0, "message": message, "error_reason": error_reason},
    )


@router.get("", response_model=OperationLogListResponse)
def list_operation_logs_api(
    _: int = Depends(require_operator),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1),
    operator_user_id: int | None = None,
    operation: str | None = None,
    target_type: str | None = None,
    success: bool | None = None,
    start: str | None = None,
    end: str | None = None,
    tz_offset_minutes: int | None = None,
):
    """操作日志查询。"""

    try:
        result = operation_log_tasks.list_operation_logs(
            page=page,
            page_size=page_size,
            operator_user_id=operator_user_id,
            operation=operation,
            target_type=target_type,
            success=success,
            start=start,
            end=end,
            tz_offset_minutes=tz_offset_minutes,
        )
    except Exception as e:
        return _error(500, f"query failed: {e}", "list_failed")

    return {"success": 1, **result}


@router.get("/stats", response_model=OperationLogStatsResponse)
def operation_log_stats_api(
    _: int = Depends(require_operator),
    start: str | None = None,
    end: str | None = None,
    tz_offset_minutes: int | None = None,
):
    """操作日志统计。"""

    try:
        result = operation_log_tasks.operation_log_stats(
            start=start,
            end=end,
            tz_offset_minutes=tz_offset_minutes,
        )
    except Exception as e:
        return _error(500, f"stats failed: {e}", "list_failed")

    return {"success": 1, **result}
