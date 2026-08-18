"""操作日志服务层：蓝图 → service → repo 的分层入口。"""

import logging

from ..repositories import machine_repo, user_repo, containers_repo, usercontainer_repo
from ..repositories.operation_log_repo import (
    list_logs as _repo_list,
    serialize,
    stats as _repo_stats,
    write as _repo_write,
)
from ..constant import ROLE

logger = logging.getLogger(__name__)

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
    .log 与 op-log 表同源：本函数是唯一写入点，成功/失败按级别落日志文件。
    """
    _op = getattr(operation, 'value', operation)
    if success:
        logger.info("op success: op=%s target=%s/%s user=%s detail=%s",
                    _op, target_type, target_id, operator_user_id, detail)
    else:
        logger.error("op failed: op=%s target=%s/%s user=%s reason=%s detail=%s",
                     _op, target_type, target_id, operator_user_id, error_reason, detail)

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
    tz_offset_minutes: int | None = None,
) -> dict:
    """分页查询 + 序列化 + 目标关联，返回 {"logs": [...], "total_pages": n}。

    start/end 按前端本地时间原样传，配合 tz_offset_minutes 由 repo 层解析。
    """
    rows, total_pages = _repo_list(
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
    logs = [serialize(r) for r in rows]
    _enrich_targets(logs)
    return {
        "logs": logs,
        "total_pages": total_pages,
    }


def _enrich_targets(logs: list[dict]) -> None:
    """给每条日志附加目标的可读信息（target_name；容器额外带 root_owner）。

    批量取目标 id 后逐条查名（单页最多 page_size 条，N+1 可接受）。
    目标已被删除时保持 None，前端回退显示 ID。
    """
    for r in logs:
        r["target_name"] = None
        r["root_owner"] = None

    for r in logs:
        try:
            tid = r.get("target_id")
            if tid is None:
                continue
            tt = r.get("target_type")
            if tt == "machine":
                m = machine_repo.get_by_id(tid)
                if m:
                    r["target_name"] = getattr(m, "machine_name", None)
            elif tt == "container":
                c = containers_repo.get_by_id(tid)
                if c:
                    r["target_name"] = getattr(c, "name", None)
                bindings = usercontainer_repo.get_container_bindings(tid) or []
                for b in bindings:
                    role_raw = b.get("role")
                    role_val = role_raw.value if hasattr(role_raw, "value") else str(role_raw or "")
                    if str(role_val).upper() == ROLE.ROOT.value.upper():
                        root_id = b.get("user_id")
                        r["root_owner"] = user_repo.get_name_by_id(root_id) if root_id else None
                        break
            elif tt == "user":
                r["target_name"] = user_repo.get_name_by_id(tid)
        except Exception:
            # 目标关联失败不影响日志主流程
            continue


def operation_log_stats(
    start: str | None = None,
    end: str | None = None,
    tz_offset_minutes: int | None = None,
) -> dict:
    """时间范围内的统计聚合（图表用）。

    tz_offset_minutes 影响窗口解析与 by_day 分桶口径（本地日），见 repo 层。
    """
    return _repo_stats(start=start, end=end, tz_offset_minutes=tz_offset_minutes)
