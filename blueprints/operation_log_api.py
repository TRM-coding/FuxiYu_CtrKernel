from flask import request, jsonify

from . import api_bp
from ..repositories import authentications_repo, user_repo
from ..services import operation_log_tasks
from ..utils.parsers import parse_bool
from ..constant import PERMISSION


def _require_operator():
    """鉴权失败时返回 (response, status)，成功返回 None。"""
    token = request.cookies.get("auth_token", "")
    if not authentications_repo.is_token_valid(token):
        return jsonify({"success": 0, "message": "invalid or missing token", "error_reason": "invalid_token"}), 401
    if not user_repo.check_permission(token, required_permission=PERMISSION.OPERATOR):
        return jsonify({"success": 0, "message": "insufficient permissions", "error_reason": "insufficient_permission"}), 403
    return None


def _int_or_none(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except Exception:
        return None


@api_bp.get("/admin/operation_logs")
def list_operation_logs_api():
    """操作日志查询（operator-only）。

    query 参数：page / page_size / operation / target_type /
    operator_user_id / success(true|false) / start / end /
    tz_offset_minutes（分钟；start/end 按前端本地时间原样传，
    由后端按该偏移解析成库内 naive UTC 口径）
    """
    denied = _require_operator()
    if denied:
        return denied

    try:
        result = operation_log_tasks.list_operation_logs(
            page=_int_or_none("page") or 1,
            page_size=_int_or_none("page_size") or 20,
            operator_user_id=_int_or_none("operator_user_id"),
            operation=request.args.get("operation") or None,
            target_type=request.args.get("target_type") or None,
            success=parse_bool(request.args.get("success")),
            start=request.args.get("start") or None,
            end=request.args.get("end") or None,
            tz_offset_minutes=_int_or_none("tz_offset_minutes"),
        )
    except Exception as e:
        return jsonify({"success": 0, "message": f"query failed: {e}", "error_reason": "list_failed"}), 500

    return jsonify({"success": 1, **result}), 200


@api_bp.get("/admin/operation_logs/stats")
def operation_log_stats_api():
    """操作日志统计（operator-only）。query 参数：start / end / tz_offset_minutes。

    tz_offset_minutes 同时影响窗口解析与 by_day 分桶日（本地日），
    使绿墙日期轴与前端 UTC+8 渲染一致。
    """
    denied = _require_operator()
    if denied:
        return denied

    try:
        result = operation_log_tasks.operation_log_stats(
            start=request.args.get("start") or None,
            end=request.args.get("end") or None,
            tz_offset_minutes=_int_or_none("tz_offset_minutes"),
        )
    except Exception as e:
        return jsonify({"success": 0, "message": f"stats failed: {e}", "error_reason": "list_failed"}), 500

    return jsonify({"success": 1, **result}), 200
