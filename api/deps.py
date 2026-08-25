from fastapi import Cookie, Depends, HTTPException, Request

from ..extensions import session_scope
from ..repositories import authentications_repo


def auth_token_from_cookie(auth_token: str = Cookie(default="")) -> str:
    """读取 Ctrl 现有 opaque token cookie。"""

    return auth_token or ""


def require_current_user(
    request: Request,
    auth_token: str = Depends(auth_token_from_cookie),
) -> int:
    """校验登录态并返回 user_id。"""

    with session_scope(commit=False) as session:
        if not authentications_repo.is_token_valid(auth_token, session=session):
            raise HTTPException(
                status_code=401,
                detail={"success": 0, "message": "invalid or missing token", "error_reason": "invalid_token"},
            )
        return authentications_repo.get_user_id_by_token(auth_token, session=session)


def require_operator(
    request: Request,
    user_id: int = Depends(require_current_user),
) -> int:
    """校验管理权限（实体通配 bypass_auth_entity）并返回 user_id。"""

    from ..services.rbac_service import _has_entity_direct

    if not _has_entity_direct(user_id, "bypass_auth_entity"):
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



async def _read_resource_id(request: Request, id_field: str):
    """从 path / POST body / query 读取资源 id（依赖层与路由参数隔离，只能走 request）。"""
    rid = request.path_params.get(id_field)
    if rid is None and request.method in ("POST", "PUT", "PATCH"):
        try:
            body = await request.json()
            rid = body.get(id_field) if isinstance(body, dict) else None
        except Exception:
            rid = None
    if rid is None:
        rid = request.query_params.get(id_field)
    if rid == "":
        return None
    return rid



def require_resource(resource_type: str, id_field: str = "id", subject_id_field: str | None = None):
    """第二层 · 资源级判别：用户对指定资源有访问权。

    用法：user_id: int = Depends(require_resource("container", "container_id"))
    主体（subject）默认是当前用户；subject_id_field 用于「主体不是当前用户」的场景
    （如 user 资源：管理/被管理关系按目标用户判定），从请求读取该字段作为主体。
    """
    async def dep(request: Request, user_id: int = Depends(require_current_user)) -> int:
        rid = await _read_resource_id(request, id_field)
        if rid is None:
            raise HTTPException(status_code=400,
                                detail={"success": 0, "message": f"missing resource id field {id_field!r}",
                                        "error_reason": "invalid_resource_id"})
        subject_user_id = user_id
        if subject_id_field is not None:
            subject_user_id = await _read_resource_id(request, subject_id_field)
            if subject_user_id is None:
                raise HTTPException(status_code=400,
                                    detail={"success": 0, "message": f"missing subject id field {subject_id_field!r}",
                                            "error_reason": "invalid_payload"})

        from ..services.rbac_service import user_has_resource
        if not user_has_resource(int(subject_user_id), resource_type, int(rid)):
            raise HTTPException(
                status_code=403,
                detail={"success": 0, "message": "resource access denied",
                        "error_reason": "resource_access_denied"},
            )
        return int(subject_user_id)

    return dep



def require_machine_of_container(id_field: str = "container_id"):
    """容器操作共用层：对容器所在机器有访问权（机器权限语义：可申请/管理该机器）。

    每个容器方法都叠加此层——操作容器 = 在机器上做事，须先确认机器访问权。
    """
    async def dep(request: Request, user_id: int = Depends(require_current_user)) -> int:
        rid = await _read_resource_id(request, id_field)
        if rid is None:
            raise HTTPException(status_code=400,
                                detail={"success": 0, "message": f"missing resource id field {id_field!r}",
                                        "error_reason": "invalid_resource_id"})
        from ..repositories.containers_repo import get_machine_id_by_container_id
        with session_scope(commit=False) as session:
            machine_id = get_machine_id_by_container_id(int(rid), session=session)
        if machine_id is None:
            raise HTTPException(status_code=404,
                                detail={"success": 0, "message": "container not found",
                                        "error_reason": "container_not_found"})
        from ..services.rbac_service import user_has_resource
        if not user_has_resource(user_id, "machine", machine_id):
            raise HTTPException(
                status_code=403,
                detail={"success": 0, "message": "machine access denied",
                        "error_reason": "machine_access_denied"},
            )
        return user_id

    return dep
