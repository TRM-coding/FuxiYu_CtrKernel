import re

# Reject shell metacharacters and line breaks
_META_RE = re.compile(r"[;&|`$<>\\\n]")
# Reject obvious dangerous command keywords
_DANGEROUS_WORDS = re.compile(r"\b(rm|shutdown|reboot|init|mkfs|dd|curl|wget|nc|ncat|perl|python|bash|sh)\b", re.IGNORECASE)


def validate_shell_arg(value: str) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        raise ValueError("invalid argument type")
    if _META_RE.search(value):
        raise ValueError("argument contains shell metacharacters")
    if _DANGEROUS_WORDS.search(value):
        raise ValueError("argument contains dangerous keyword")
    return True


def validate_username(username: str) -> bool:
    if username is None:
        return True
    if not isinstance(username, str):
        raise ValueError("invalid username type")
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", username):
        raise ValueError("invalid characters in username")
    return True
