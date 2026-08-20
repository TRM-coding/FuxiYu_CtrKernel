from fastapi import Cookie, Depends, HTTPException, Request

from ..constant import PERMISSION
from ..extensions import session_scope
from ..repositories import authentications_repo, user_repo


def auth_token_from_cookie(auth_token: str = Cookie(default="")) -> str:
    """读取 Ctrl 现有 opaque token cookie。"""

    return auth_token or ""


def require_current_user(
    request: Request,
    auth_token: str = Depends(auth_token_from_cookie),
) -> int:
    """校验登录态并返回 user_id。"""

    with session_scope(commit=False) as session:
        if not authentications_repo.is_token_valid(auth_token):
            raise HTTPException(
                status_code=401,
                detail={"success": 0, "message": "invalid or missing token", "error_reason": "invalid_token"},
            )
        return authentications_repo.get_user_id_by_token(auth_token, session=session)


def require_operator(
    request: Request,
    user_id: int = Depends(require_current_user),
    auth_token: str = Depends(auth_token_from_cookie),
) -> int:
    """校验 operator 权限并返回 user_id。"""

    with session_scope(commit=False) as session:
        if not user_repo.check_permission(auth_token, required_permission=PERMISSION.OPERATOR, session=session):
            raise HTTPException(
                status_code=403,
                detail={"success": 0, "message": "insufficient permissions", "error_reason": "insufficient_permission"},
            )
    return user_id


# ── RBAC 两层模型挂载（fuxi平台继续开发.md「RBAC · 两层模型」） ──────────

def require_permission(entity_code: str):
    """第一层 · 方法级判别：用户须持有 authEntity（含 operator 过渡兼容）。

    用法：user_id: int = Depends(require_permission("container:create"))
    """
    def dep(request: Request, user_id: int = Depends(require_current_user)) -> int:
        from ..services.rbac_service import user_has_entity
        if not user_has_entity(user_id, entity_code):
            raise HTTPException(
                status_code=403,
                detail={"success": 0, "message": "insufficient permissions",
                        "error_reason": "insufficient_permission"},
            )
        return user_id

    return dep


def require_resource(resource_type: str, id_field: str = "id"):
    """第二层 · 资源级判别：用户对指定资源有访问权。

    *id_field*: 从 path 参数/请求体读取资源 id 的字段名（如 "container_id"/"machine_id"）。

    用法：Depends(require_resource("container", "container_id"))
    """
    async def dep(request: Request, user_id: int = Depends(require_current_user)) -> int:
        rid = request.path_params.get(id_field)
        if rid is None and request.method in ("POST", "PUT", "PATCH"):
            try:
                body = await request.json()
                rid = body.get(id_field) if isinstance(body, dict) else None
            except Exception:
                rid = None
        if rid is None:
            raise HTTPException(status_code=400,
                                detail={"success": 0, "message": f"missing resource id field {id_field!r}",
                                        "error_reason": "invalid_resource_id"})
        from ..services.rbac_service import user_has_resource
        if not user_has_resource(user_id, resource_type, int(rid)):
            raise HTTPException(
                status_code=403,
                detail={"success": 0, "message": "resource access denied",
                        "error_reason": "resource_access_denied"},
            )
        return user_id

    return dep
