"""操作日志服务层：蓝图 → service → repo 的分层入口。"""

from ..repositories.operation_log_repo import (
    list_logs as _repo_list,
    serialize,
    stats as _repo_stats,
    write as _repo_write,
)

# TODO
def _maybe_raise_alert(
    *,
    operator_user_id: int | None,
    operation: str,
    target_type: str,
    target_id: int,
    detail: dict,
    success: bool,
    error_reason: str | None,
) -> None:
    """分级告警口岸（未实装）。

    所有操作成败都会流经 write_operation_log，这里是评估告警的唯一汇聚点。
    后续接入：告警规则（阈值/级别/目标范围）与通知渠道（邮件/站内）时，
    在本函数内实现评估逻辑；约定：本函数绝不抛异常、绝不阻塞主流程。

    与 RBAC 的配套关系：告警推送按角色/权限排列组合路由（如
    机器相关失败推给该机器权限持有者、平台级失败推给 operator），
    RBAC 落地后此函数按 operator_user_id / target_type 查收件人。
    """
    return None


def write_operation_log(
    *,
    operator_user_id: int | None = None,
    operation: str,
    target_type: str,
    target_id: int,
    detail: dict,
    success: bool,
    error_reason: str | None = None,
):
    """写操作日志统一入口。

    本身不抛异常，log失败只打 print，不影响主流程。
    """
    result = _repo_write(
        operator_user_id=operator_user_id,
        operation=operation,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        success=success,
        error_reason=error_reason,
    )
    # 分级告警口岸：无论日志是否写成功，告警评估都基于本次操作的事实执行
    _maybe_raise_alert(
        operator_user_id=operator_user_id,
        operation=operation,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        success=success,
        error_reason=error_reason,
    )
    return result


def list_operation_logs(
    *,
    page: int = 1,
    page_size: int = 20,
    operator_user_id: int | None = None,
    operation: str | None = None,
    target_type: str | None = None,
    success: bool | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """分页查询 + 序列化，返回 {"logs": [...], "total_pages": n}。"""
    rows, total_pages = _repo_list(
        page=page,
        page_size=page_size,
        operator_user_id=operator_user_id,
        operation=operation,
        target_type=target_type,
        success=success,
        start=start,
        end=end,
    )
    return {
        "logs": [serialize(r) for r in rows],
        "total_pages": total_pages,
    }


def operation_log_stats(start: str | None = None, end: str | None = None) -> dict:
    """时间范围内的统计聚合（图表用）。"""
    return _repo_stats(start=start, end=end)
