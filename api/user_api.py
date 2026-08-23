from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from ..config import AppConfig
from ..extensions import session_scope
from ..repositories import user_repo
from ..schemas.common import SuccessMessageResponse
from ..schemas.user import (
    ChangePasswordRequest,
    DeleteUserResponse,
    ListUserBriefResponse,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    RequestRegisterCodeRequest,
    ResetPasswordResponse,
    UpdateUserRequest,
    UpdateUserResponse,
    UserDetailResponse,
    UserIdRequest,
)
from ..services import user_tasks
from .deps import require_current_user, require_permission, require_resource

router = APIRouter(tags=["users"])


def _model_data(model, *, exclude_none: bool = False) -> dict[str, Any]:
    """兼容 Pydantic v1/v2 的模型转 dict。"""

    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_none=exclude_none)
    if hasattr(model, "dict"):
        try:
            return model.dict(exclude_none=exclude_none)
        except TypeError:
            return model.dict()
    if isinstance(model, dict):
        return model
    return dict(getattr(model, "__dict__", {}))


def _error(status_code: int, message: str, error_reason: str | None = None) -> JSONResponse:
    """返回 Ctrl 现有错误结构。"""

    payload: dict[str, Any] = {"success": 0, "message": message}
    if error_reason is not None:
        payload["error_reason"] = error_reason
    return JSONResponse(status_code=status_code, content=payload)


#####################
# 注册


@router.post("/register", response_model=RegisterResponse, status_code=201)
def register(message: RegisterRequest, request: Request):
    """用户注册。"""

    data = _model_data(message)
    try:
        success, user_or_reason, _ = user_tasks.Register_with_code(
            data.get("username"),
            data.get("email"),
            data.get("password"),
            data.get("graduation_year"),
            data.get("registration_code"),
        )
    except Exception:
        return _error(500, "registration failed due to server error")

    if success:
        return {
            "success": 1,
            "message": "Registration successful",
            "user_id": user_or_reason.id,
            "username": user_or_reason.username,
            "email": user_or_reason.email,
        }

    error_reason = user_or_reason
    error_messages = {
        "username_exists": "Username already exists",
        "email_exists": "Email already exists",
        "no_none_ascii": "Input contains non-ASCII characters",
        "invalid_username": "Username may contain only letters, digits and underscore",
        "registration_code_required": "Verification code required",
        "registration_code_invalid": "Verification code invalid or expired",
        "mail_send_failed": "Failed to send verification email",
    }
    status_code = 409 if error_reason in {"username_exists", "email_exists"} else 400
    return _error(status_code, error_messages.get(error_reason, "Registration failed"), error_reason)


@router.post("/request_register_code", response_model=SuccessMessageResponse)
def request_register_code(message: RequestRegisterCodeRequest, request: Request):
    """发送注册验证码。"""

    success, reason = user_tasks.Request_register_code(message.email)
    if success:
        return {"success": 1, "message": "verification code sent"}
    status_code = 400 if reason == "email_domain_not_allowed" else 500
    return _error(status_code, reason, reason)


#####################
# 登录


@router.post("/login", response_model=LoginResponse)
def login(message: LoginRequest, response: Response, request: Request):
    """用户登录并设置 auth_token cookie。"""

    success, user_or_reason, token = user_tasks.Login(
        message.username,
        message.password,
        remember=message.remember,
    )
    ssl_enabled = getattr(AppConfig, "SSL_ENABLED", True)

    if success:
        max_age = 24 * 3600 * 30 if message.remember else None
        response.set_cookie(
            "auth_token",
            token,
            max_age=max_age,
            httponly=True,
            secure=ssl_enabled,
            samesite="Lax",
        )
        return {
            "success": 1,
            "message": "Login successful",
            "user_id": user_or_reason.id,
            "username": user_or_reason.username,
            "email": user_or_reason.email,
            "permission": user_or_reason.permission.value,
        }

    error_reason = user_or_reason
    error_messages = {
        "user_not_found": "User does not exist",
        "password_incorrect": "Password is incorrect",
    }
    status_code = 404 if error_reason == "user_not_found" else 400
    return _error(status_code, error_messages.get(error_reason, "Login failed"), error_reason)


#####################
# 用户详情


@router.get("/users/get_user_detail_information", response_model=UserDetailResponse)
def get_user_detail_information_api(
    request: Request,
    user_id: int = Query(..., ge=1),
    _: int = Depends(require_resource("user", "user_id")),
):
    """查询用户详情。"""

    info = user_tasks.Get_user_detail_information(user_id)
    if not info:
        return _error(404, "user not found", "user_not_found")
    return {"success": 1, "user_info": _model_data(info)}


@router.get("/users/me/permissions")
def my_permissions_api(
    request: Request,
    user_id: int = Depends(require_current_user),
):
    """当前用户持有的全部权限点（前端导航/按钮按 manage 过滤）。"""

    from ..services.rbac_service import list_user_entities
    return {"success": 1, "entities": list_user_entities(user_id)}


@router.get("/users/list_all_user_bref_information", response_model=ListUserBriefResponse)
def list_all_user_bref_information_api(
    request: Request,
    page_number: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1),
    user_search: str | None = Query(default=None),
    viewer_user_id: int = Depends(require_current_user),
):
    """分页查询用户概要（内部按查看者资源级过滤）。"""

    try:
        users = user_tasks.List_all_user_bref_information(
            page_number=int(page_number),
            page_size=int(page_size),
            user_search=(user_search or "").strip() or None,
            viewer_user_id=viewer_user_id,
        )
    except Exception:
        return _error(500, "failed to list users", "list_failed")

    return {"success": 1, "users": [_model_data(u) for u in users]}


#####################
# 修改密码


@router.post("/users/change_password", response_model=SuccessMessageResponse)
def change_password_user(
    message: ChangePasswordRequest,
    request: Request,
    _: int = Depends(require_current_user),
):
    """修改用户密码。"""

    with session_scope(commit=False) as session:
        user = user_repo.get_by_id(message.user_id, session=session)
        if not user:
            return _error(404, "user not found", "user_not_found")
        try:
            ok = user_tasks.Change_password(user, message.old_password, message.new_password)
        except ValueError as e:
            if str(e) == "no_none_ascii":
                return _error(400, "None ascii not allowed (Chinese not accepted)", "no_none_ascii")
            raise

    if ok:
        return {"success": 1, "message": "password changed"}
    return _error(400, "old password incorrect", "old_password_incorrect")


#####################
# 删除用户


@router.post("/users/delete_user", response_model=DeleteUserResponse)
def delete_user_api(
    message: UserIdRequest,
    request: Request,
    _: int = Depends(require_permission("user:manage")),
):
    """删除用户。"""

    try:
        ok = user_tasks.Delete_user(message.user_id)
    except Exception as e:
        payload: dict[str, Any] = {
            "success": 0,
            "message": "Wild container NOT allowed. Must remove all affected containers first.",
            "error_reason": "wild_container",
        }
        wild = getattr(e, "wild_containers", None)
        if wild:
            payload["wild_containers"] = wild
        return JSONResponse(status_code=400, content=payload)

    if ok:
        return {"success": 1, "message": "user deleted"}
    return _error(404, "user not found", "user_not_found")


#####################
# 更新用户


@router.post("/users/update_user", response_model=UpdateUserResponse)
def update_user_api(
    message: UpdateUserRequest,
    request: Request,
    _: int = Depends(require_resource("user", "user_id")),
):
    """更新用户基础字段（user 资源判定 或 operator，deps 并集门禁）。"""

    fields = _model_data(message.fields, exclude_none=True)
    if not fields:
        return _error(400, "user_id and fields required", "missing_fields")

    try:
        user = user_tasks.Update_user(message.user_id, **fields)
    except ValueError as e:
        if str(e) == "no_none_ascii":
            return _error(400, "禁止非ASCII字符（请勿输入中文）", "no_none_ascii")
        if str(e) == "invalid_username":
            return _error(400, "用户名仅允许字母、数字和下划线", "invalid_username")
        return _error(400, str(e), "invalid_fields")

    if user:
        return {"success": 1, "message": "user updated", "user": user.username}
    return _error(404, "user not found", "user_not_found")


#####################
# 重置密码


@router.post("/users/reset_password", response_model=ResetPasswordResponse)
def reset_password_api(
    message: UserIdRequest,
    request: Request,
    _: int = Depends(require_permission("user:manage")),
):
    """重置用户密码（管理操作；本人改密走 change_password）。"""

    new_password = user_tasks.Reset_password(message.user_id)
    if new_password:
        return {"success": 1, "message": "password reset", "new_password": new_password}
    return _error(404, "user not found", "user_not_found")
