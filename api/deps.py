from fastapi import Cookie, Depends, HTTPException, Request

from ..constant import PERMISSION
from ..repositories import authentications_repo, user_repo


def auth_token_from_cookie(auth_token: str = Cookie(default="")) -> str:
    """读取 Ctrl 现有 opaque token cookie。"""

    return auth_token or ""


def require_current_user(
    request: Request,
    auth_token: str = Depends(auth_token_from_cookie),
) -> int:
    """校验登录态并返回 user_id。"""

    with request.app.state.flask_app.app_context():
        if not authentications_repo.is_token_valid(auth_token):
            raise HTTPException(
                status_code=401,
                detail={"success": 0, "message": "invalid or missing token", "error_reason": "invalid_token"},
            )
        return authentications_repo.get_user_id_by_token(auth_token)


def require_operator(
    request: Request,
    user_id: int = Depends(require_current_user),
    auth_token: str = Depends(auth_token_from_cookie),
) -> int:
    """校验 operator 权限并返回 user_id。"""

    with request.app.state.flask_app.app_context():
        if not user_repo.check_permission(auth_token, required_permission=PERMISSION.OPERATOR):
            raise HTTPException(
                status_code=403,
                detail={"success": 0, "message": "insufficient permissions", "error_reason": "insufficient_permission"},
            )
    return user_id
