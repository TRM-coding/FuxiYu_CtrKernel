#这个纯粹是为了方便统一异常处置流程
def _raise_on_node_error(res: dict, action: str):
    '''
    检查远端（Node）提供的响应的具体内容
    
    '''
    
    if not isinstance(res, dict):
        raise NodeServiceError(f"NODE {action} unexpected response: {res}", reason="unexpected_response")
    # network-level error
    if 'error' in res:
        err = res.get('error')
        err_reason = res.get('error_reason')
        raise NodeServiceError(f"NODE {action} failed: {err}", reason=err_reason or "NODE_error")
    # Node may include error_reason even without 'error'
    if 'error_reason' in res and res.get('success') != 1:
        raise NodeServiceError(f"NODE {action} failed: reason={res.get('error_reason')}", reason=res.get('error_reason'))


class NodeServiceError(Exception):
    '''
    提高一些Node侧错误上下文。只是为了z增加可读性
    '''
    
    def __init__(self, message: str, reason: str | None = None):
        super().__init__(message)
        self.reason = reason


# 密码类路径只允许这些既有稳定 reason 进入 oplog/HTTP/日志；
# Node 的 error_reason 或异常文本可能回显 secret，未知一律降级到固定默认值。
SAFE_REASON_CODES = frozenset({
    "container_exists", "invalid_payload", "invalid_signature", "invalid_json",
    "invalid_config", "docker_init_failed", "docker_check_failed",
    "unexpected_response", "not_found", "duplicate_entry", "create_failed",
    "delete_failed", "start_failed", "stop_failed", "restart_failed",
    "container_offline", "container_busy", "container_paused", "container_failed",
    "container_host_offline", "container_host_maintenance", "container_status_unknown",
    "node_endpoint_not_found", "machine_maintenance", "machine_offline",
    "image_not_found", "image_access_denied", "image_not_ready",
    "machine_not_found", "container_not_found", "machine_permission_denied",
    "container_permission_denied", "insufficient_permission",
    "long_term_limit_reached", "disk_usage_over_limit", "data_not_recoverable",
    "target_not_bound", "invalid_target_account", "target_changed", "reset_not_accepted",
    "add_not_accepted", "reset_failed", "add_failed", "remove_failed",
    "update_failed", "update_role_failed", "add_collaborator_failed",
    "role_change_not_accepted", "invalid_root_owner_account",
    "role_binding_failed", "root_handover_binding_failed", "node_error",
    "internal_error",
})


def safe_reason(value, default: str) -> str:
    """把 Node/异常 reason 收敛到固定白名单；绝不拼接原始异常文本。"""

    if isinstance(value, Exception):
        value = getattr(value, "reason", None) or getattr(value, "error_reason", None)
    text = str(value or "").strip()
    return text if text in SAFE_REASON_CODES else default