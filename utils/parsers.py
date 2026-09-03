"""请求参数解析小工具。"""


def parse_bool(raw) -> bool | None:
    """把请求里的布尔字符串解析成 bool；无法解析返回 None。"""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in ("true", "1"):
        return True
    if s in ("false", "0"):
        return False
    return None
