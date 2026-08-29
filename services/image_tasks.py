"""镜像模板服务。

镜像第一阶段只管理 Ctrl 侧长期保存的基础镜像与用户业务 Dockerfile
片段；最终 Dockerfile 由构建器临时生成。
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from ..constant import ImageStatus, OperationType
from ..extensions import session_scope
from ..repositories import image_repo, userimage_repo
from . import settings_tasks
from .operation_log_tasks import write_operation_log as write_op_log


def _status_value(status) -> str:
    return status.value if hasattr(status, "value") else str(status)


def _coerce_status(value: str | ImageStatus | None) -> ImageStatus | None:
    if value is None:
        return None
    if isinstance(value, ImageStatus):
        return value
    try:
        return ImageStatus(str(value))
    except ValueError as exc:
        err = ValueError(f"invalid image status: {value}")
        setattr(err, "error_reason", "invalid_status")
        raise err from exc


def _serialize(image, *, include_content: bool = False) -> dict:
    """镜像概要序列化。大字段只在详情接口返回。

    include_content 仅详情用；列表不带内容，避免大字段进分页响应。
    """
    result = {
        "image_id": image.id,
        "name": image.name,
        "description": image.description,
        "base_image": image.base_image,
        "status": _status_value(image.status),
        "created_by_user_id": image.created_by_user_id,
        "created_at": image.created_at.isoformat() if image.created_at else None,
        "updated_at": image.updated_at.isoformat() if image.updated_at else None,
    }
    if include_content:
        result["dockerfile_body"] = image.dockerfile_body
    return result


def format_image_build_tag(image_id: int, updated_at: datetime | None) -> str:
    """把镜像模板映射为 Docker tag。"""

    version_time = updated_at or datetime.now(timezone.utc)
    if version_time.tzinfo is not None:
        version_time = version_time.astimezone(timezone.utc).replace(tzinfo=None)
    version_time = version_time.replace(microsecond=0)
    stamp = version_time.strftime("%Y%m%dT%H%M%SZ")
    return f"fuxi/image-{int(image_id)}:{stamp}"


def render_final_dockerfile(*, base_image: str, platform_injection: str, dockerfile_body: str | None = None) -> str:
    """拼出最终 Dockerfile 文本。"""

    parts: list[str] = [f"FROM {base_image}".strip()]
    injection = (platform_injection or "").strip()
    if injection:
        parts.append(injection)
    body = (dockerfile_body or "").strip()
    if body:
        parts.append(body)
    return "\n\n".join(parts).rstrip() + "\n"


def build_image_payload(image_id: int) -> dict | None:
    """按 image_id 生成给 Node 的构建 payload。"""

    with session_scope(commit=False) as session:
        image = image_repo.get_by_id(image_id, session=session)
        if image is None:
            return None
        platform_injection = settings_tasks.get_image_platform_injection_content()
        return {
            "image_id": image.id,
            "image_tag": format_image_build_tag(image.id, image.updated_at),
            "dockerfile_text": render_final_dockerfile(
                base_image=image.base_image,
                platform_injection=platform_injection,
                dockerfile_body=image.dockerfile_body,
            ),
            "base_image": image.base_image,
        }


def _visible_scope(viewer_user_id: int | None) -> tuple[set[int] | None, bool]:
    """返回 (visible_image_ids, include_public)。

    - 资源通配者：不过滤（None, False）
    - 普通用户：已授权 user_images 集合 + 系统内置镜像全员可见（created_by IS NULL）
    """
    if viewer_user_id is None:
        return set(), False
    from .rbac_service import _has_resource_manage_direct

    if _has_resource_manage_direct(viewer_user_id, "image"):
        return None, False
    with session_scope(commit=False) as session:
        return set(userimage_repo.list_image_ids_by_user(viewer_user_id, session=session)), True


def Create_image(
    *,
    name: str,
    base_image: str,
    dockerfile_body: str = "",
    description: str | None = None,
    operator_user_id: int | None = None,
) -> int:
    """创建镜像模板，并把创建者绑定到 user-i。"""

    try:
        with session_scope() as session:
            image = image_repo.create_image(
                name=name,
                description=description,
                base_image=base_image,
                dockerfile_body=dockerfile_body,
                status=ImageStatus.DRAFT,
                created_by_user_id=operator_user_id,
                session=session,
            )
            if operator_user_id is not None:
                userimage_repo.grant_image(operator_user_id, image.id, session=session)
            image_id = image.id
    except Exception as exc:
        write_op_log(
            success=False,
            operator_user_id=operator_user_id,
            operation=OperationType.CREATE_IMAGE,
            target_type="image",
            target_id=0,
            detail={"name": name},
            error_reason=getattr(exc, "error_reason", None) or str(exc),
        )
        raise
    write_op_log(
        success=True,
        operator_user_id=operator_user_id,
        operation=OperationType.CREATE_IMAGE,
        target_type="image",
        target_id=image_id,
        detail={"name": name},
    )
    return image_id


def Update_image(
    *,
    image_id: int,
    operator_user_id: int | None = None,
    name: str | None = None,
    description: str | None = None,
    base_image: str | None = None,
    dockerfile_body: str | None = None,
    status: str | ImageStatus | None = None,
) -> bool:
    """更新镜像模板元数据或内容。"""

    fields = {
        "name": name,
        "description": description,
        "base_image": base_image,
        "status": _coerce_status(status),
    }
    if dockerfile_body is not None:
        fields["dockerfile_body"] = dockerfile_body

    try:
        with session_scope() as session:
            ok = image_repo.update_image(image_id, session=session, **fields)
    except Exception as exc:
        write_op_log(
            success=False,
            operator_user_id=operator_user_id,
            operation=OperationType.UPDATE_IMAGE,
            target_type="image",
            target_id=image_id,
            detail={"name": name},
            error_reason=getattr(exc, "error_reason", None) or str(exc),
        )
        raise

    if ok:
        write_op_log(
            success=True,
            operator_user_id=operator_user_id,
            operation=OperationType.UPDATE_IMAGE,
            target_type="image",
            target_id=image_id,
            detail={"name": name},
        )
    return ok


def Delete_image(*, image_id: int, operator_user_id: int | None = None) -> bool:
    with session_scope() as session:
        image = image_repo.get_by_id(image_id, session=session)
        if image is None:
            return False
        image_repo.delete_image(image_id, session=session)

    write_op_log(
        success=True,
        operator_user_id=operator_user_id,
        operation=OperationType.DELETE_IMAGE,
        target_type="image",
        target_id=image_id,
        detail={},
    )
    return True


def Get_image_detail(image_id: int) -> dict | None:
    with session_scope(commit=False) as session:
        image = image_repo.get_by_id(image_id, session=session)
        if image is None:
            return None
        return _serialize(image, include_content=True)


def List_image_bref_information(
    *,
    page_number: int = 1,
    page_size: int = 20,
    image_search: str | None = None,
    viewer_user_id: int | None = None,
) -> dict:
    page_number = max(1, int(page_number or 1))
    page_size = max(1, int(page_size or 20))
    visible_ids, include_public = _visible_scope(viewer_user_id)
    with session_scope(commit=False) as session:
        total = image_repo.count_images(
            image_search=image_search,
            visible_image_ids=visible_ids,
            include_public=include_public,
            session=session,
        )
        images = image_repo.list_images(
            limit=page_size,
            offset=(page_number - 1) * page_size,
            image_search=image_search,
            visible_image_ids=visible_ids,
            include_public=include_public,
            session=session,
        )
        return {
            "images": [_serialize(image, include_content=False) for image in images],
            "total_page": math.ceil(total / page_size) if total else 0,
            "total_number": total,
        }


# ── 内置镜像 seed（幂等；create_app 建表后调用一次，与 RBAC seed 同模式） ──────

SEED_IMAGES: list[dict] = [
    {
        "name": "Ubuntu 22.04 · 基础",
        # 镜像构建契约（2026-08）：模板只表达业务环境；FROM 单独存，
        # 平台基础设施由构建注入保证，不在模板里预装。
        "description": "Ubuntu 22.04 通用环境模板（平台内置）。",
        "status": ImageStatus.READY,
        "base_image": "ubuntu:22.04",
        "dockerfile_body": "",
    },
]


def seed_image_defaults() -> None:
    """幂等 seed：写入内置镜像模板。

    - created_by_user_id 置空 → 系统镜像，全员可见（_visible_scope 的 include_public）
    - 同名已存在时跳过，不覆盖人工修改
    """
    for item in SEED_IMAGES:
        with session_scope() as session:
            if image_repo.get_by_name(item["name"], session=session) is not None:
                continue
            image_repo.create_image(
                name=item["name"],
                description=item["description"],
                base_image=item["base_image"],
                dockerfile_body=item["dockerfile_body"],
                status=item["status"],
                created_by_user_id=None,
                session=session,
            )
