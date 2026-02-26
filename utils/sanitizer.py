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


def is_valid_name(value: str) -> bool:
    """Return True if value is a strict name token (letters/digits/underscore/hyphen)."""
    if not isinstance(value, str):
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9_\-]+", value))


def is_valid_image_name(value: str) -> bool:
    """Return True if value looks like a container image name (allow dots, slashes, colon tags)."""
    if not isinstance(value, str):
        return False
    # examples: nginx:latest, registry.example.com/myorg/myimage:tag
    return bool(re.fullmatch(r"[A-Za-z0-9]+(?:[A-Za-z0-9._\-\/]*)?(?::[A-Za-z0-9._\-]+)?", value))


def validate_username(username: str) -> bool:
    """Validate username/container-name-like tokens: allow letters, digits, underscore, hyphen."""
    if username is None:
        return True
    if not isinstance(username, str):
        raise ValueError("invalid username type")
    if not is_valid_name(username):
        raise ValueError("invalid characters in username")
    return True


def validate_image_name(image_name: str) -> bool:
    """Validate container image names; raises ValueError if invalid."""
    if image_name is None:
        return True
    if not isinstance(image_name, str):
        raise ValueError("invalid image name type")
    if not is_valid_image_name(image_name):
        raise ValueError("invalid image name")
    return True
