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