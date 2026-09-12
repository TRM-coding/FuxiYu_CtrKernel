"""操作日志服务层：蓝图 → service → repo 的分层入口。"""

import logging
from datetime import datetime

from sqlalchemy import select

from ..extensions import session_scope
from ..models.containers import Container
from ..models.usercontainer import UserContainer
from ..repositories import auth_repo, image_repo, machine_repo, user_repo
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

    try:
        with session_scope() as session:
            result = _repo_write(
                session=session,
                operator_user_id=operator_user_id,
                operation=operation,
                target_type=target_type,
                target_id=target_id,
                detail=detail,
                success=success,
                error_reason=error_reason,
            )
    except Exception as e:
        logger.warning("failed to write operation log: %s", e)
        result = None
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


def _enrich_write_detail(
    *,
    target_type: str,
    target_id: int,
    detail: dict | None,
    container_name: str | None = None,
    machine_id: int | None = None,
) -> dict:
    """补齐写入时可确定的资源信息，保留调用方显式传入的字段。"""
    merged_detail = dict(detail or {})
    if container_name:
        merged_detail.setdefault("name", container_name)
        merged_detail.setdefault("container_name", container_name)
        merged_detail.setdefault("original_container_name", container_name)
    if machine_id is not None:
        merged_detail.setdefault("machine_id", machine_id)

    if target_type != "container":
        return merged_detail

    container_id = target_id or merged_detail.get("container_id")
    if not container_id:
        return merged_detail

    try:
        with session_scope(commit=False) as session:
            container = session.get(Container, int(container_id))
        if container is not None:
            name = getattr(container, "name", None)
            merged_detail.setdefault("name", name)
            merged_detail.setdefault("container_name", name)
            merged_detail.setdefault("original_container_name", name)
            merged_detail.setdefault("machine_id", getattr(container, "machine_id", None))
    except Exception:
        # 日志补充信息失败不应影响主操作或日志本身的写入。
        pass
    return merged_detail


def log_success(
    *,
    operator_user_id: int | None = None,
    operation: str,
    target_type: str,
    target_id: int,
    detail: dict | None = None,
    container_name: str | None = None,
    machine_id: int | None = None,
):
    return write_operation_log(
        success=True,
        operator_user_id=operator_user_id,
        operation=operation,
        target_type=target_type,
        target_id=target_id,
        detail=_enrich_write_detail(
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            container_name=container_name,
            machine_id=machine_id,
        ),
    )


def log_failure(
    operation: str,
    target_id: int,
    *,
    operator_user_id: int | None = None,
    target_type: str,
    error_reason: str,
    detail: dict | None = None,
    container_name: str | None = None,
    machine_id: int | None = None,
):
    return write_operation_log(
        success=False,
        operator_user_id=operator_user_id,
        operation=operation,
        target_type=target_type,
        target_id=target_id,
        detail=_enrich_write_detail(
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            container_name=container_name,
            machine_id=machine_id,
        ),
        error_reason=error_reason,
    )


def log_result(
    *,
    success: bool,
    operator_user_id: int | None = None,
    operation: str,
    target_type: str,
    target_id: int,
    detail: dict | None = None,
    error_reason: str | None = None,
    container_name: str | None = None,
    machine_id: int | None = None,
):
    if success:
        return log_success(
            operator_user_id=operator_user_id,
            operation=operation,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            container_name=container_name,
            machine_id=machine_id,
        )
    return log_failure(
        operator_user_id=operator_user_id,
        operation=operation,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        error_reason=error_reason or "operation_failed",
        container_name=container_name,
        machine_id=machine_id,
    )


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
    with session_scope(commit=False) as session:
        rows, total_pages = _repo_list(
            session=session,
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
    """给每条日志附加目标的可读信息（target_name/target_display_name；容器额外带 root_owner）。

    批量取目标 id 后逐条查名（单页最多 page_size 条，N+1 可接受）。
    target_name 仅用于当前仍可导航的目标；目标已删除时保留 detail 中的历史名称到
    target_display_name，前端展示名称但不提供错误导航。
    """
    for r in logs:
        r["target_name"] = None
        r["target_display_name"] = None
        r["root_owner"] = None

    for r in logs:
        try:
            detail = r.get("detail") or {}
            tid = r.get("target_id")
            tt = r.get("target_type")
            if isinstance(detail, dict):
                if tt in {"machine", "container", "image", "rbac_group", "container_mount_cleanup", "mail", "announcement"}:
                    r["target_display_name"] = detail.get("name") or detail.get("container_name")
                elif tt == "user":
                    r["target_display_name"] = detail.get("username") or detail.get("name")
                elif tt == "system_setting":
                    r["target_display_name"] = detail.get("name")
                    if not r["target_display_name"]:
                        keys = detail.get("setting_keys") or []
                        if keys:
                            r["target_display_name"] = ", ".join(str(key) for key in keys)
            if tid is None:
                continue
            if tt == "machine":
                with session_scope(commit=False) as session:
                    m = machine_repo.get_by_id(tid, session=session)
                if m:
                    r["target_name"] = getattr(m, "machine_name", None)
                    r["target_display_name"] = r["target_display_name"] or r["target_name"]
            elif tt == "container":
                with session_scope(commit=False) as session:
                    c = session.get(Container, int(tid))
                    if c:
                        # 身份校验（id 复用 2026-09）：日志早于容器创建 = 上一代容器日志，
                        # 不映射名称/超管，前端回退显示保存的历史名称、不做错误导航。
                        log_dt = None
                        if r.get("created_at"):
                            try:
                                log_dt = datetime.fromisoformat(str(r["created_at"]))
                            except ValueError:
                                log_dt = None
                        c_created = getattr(c, "created_at", None)
                        if c_created is not None and log_dt is not None and log_dt < c_created:
                            r["target_name"] = None
                            r["root_owner"] = None
                            continue
                        r["target_display_name"] = r["target_display_name"] or getattr(c, "name", None)
                        if getattr(c, "is_valid", True):
                            r["target_name"] = getattr(c, "name", None)
                        else:
                            r["target_name"] = None
                    binding = session.scalars(
                        select(UserContainer).where(
                            UserContainer.container_id == int(tid),
                            UserContainer.role == ROLE.ROOT,
                        )
                    ).first()
                    if binding:
                        r["root_owner"] = user_repo.get_name_by_id(binding.user_id, session=session)
            elif tt == "user":
                with session_scope(commit=False) as session:
                    if user_repo.get_by_id(tid, session=session) is not None:
                        r["target_name"] = r["target_display_name"] or user_repo.get_name_by_id(tid, session=session)
            elif tt == "image":
                with session_scope(commit=False) as session:
                    image = image_repo.get_by_id(tid, session=session)
                if image:
                    r["target_name"] = r["target_display_name"] or getattr(image, "name", None)
            elif tt == "rbac_group":
                with session_scope(commit=False) as session:
                    group = auth_repo.get_group_by_id(tid, session=session)
                if group:
                    r["target_name"] = r["target_display_name"] or getattr(group, "name", None)
            elif tt in {"container_mount_cleanup", "system_setting"}:
                if isinstance(detail, dict):
                    r["target_name"] = r["target_display_name"]
                    if not r["target_name"] and tt == "system_setting":
                        keys = detail.get("setting_keys") or []
                        if keys:
                            r["target_name"] = ", ".join(str(key) for key in keys)
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
    with session_scope(commit=False) as session:
        return _repo_stats(session=session, start=start, end=end, tz_offset_minutes=tz_offset_minutes)
