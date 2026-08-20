"""公告系统 API 路由。

全部端点要求 Operator 权限；认证由 FastAPI dependency 完成。
"""

from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import JSONResponse

from ..constant import AnnouncementStatus, AnnouncementTemplateCategory
from ..models.announcement import Announcement as AnnouncementModel
from ..repositories import announcement_repo
from ..services import announcement_tasks
from .deps import require_operator

router = APIRouter(prefix="/announcements", tags=["announcements"])


def _error(status_code: int, message: str, error_reason: str) -> JSONResponse:
    """返回 Ctrl 现有错误结构。"""

    return JSONResponse(
        status_code=status_code,
        content={"success": 0, "message": message, "error_reason": error_reason},
    )


def _model_data(model, *, exclude_none: bool = False) -> dict[str, Any]:
    """兼容 Pydantic v1/v2 的 model -> dict。"""

    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_none=exclude_none)
    return model.dict(exclude_none=exclude_none)


def _template_view(template) -> dict[str, Any]:
    return {
        "id": template.id,
        "name": template.name,
        "category": template.category.value if hasattr(template.category, "value") else template.category,
        "description": template.description,
        "subject_template": template.subject_template,
        "body_template": template.body_template,
        "source_announcement_id": template.source_announcement_id,
        "created_by": template.created_by,
        "created_at": template.created_at.isoformat() if template.created_at else None,
        "updated_at": template.updated_at.isoformat() if template.updated_at else None,
    }


def _announcement_view(announcement) -> dict[str, Any]:
    return {
        "id": announcement.id,
        "title": announcement.title,
        "content": announcement.content,
        "raw_content": announcement.raw_content,
        "created_by": announcement.created_by,
        "status": announcement.status.value if hasattr(announcement.status, "value") else announcement.status,
        "targets": announcement.targets,
        "target_snapshot": announcement.target_snapshot,
        "recipient_count": announcement.recipient_count,
        "success_count": announcement.success_count,
        "fail_count": announcement.fail_count,
        "created_at": announcement.created_at.isoformat() if announcement.created_at else None,
        "sent_at": announcement.sent_at.isoformat() if announcement.sent_at else None,
        "source_draft_id": announcement.source_draft_id,
        "template_id": announcement.template_id,
    }


def _draft_view(draft) -> dict[str, Any]:
    return {
        "id": draft.id,
        "title": draft.title,
        "content": draft.content,
        "raw_content": draft.raw_content,
        "created_by": draft.created_by,
        "targets": draft.targets,
        "template_id": draft.template_id,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
    }


@router.get("/templates")
def list_templates_api(
    request: Request,
    category: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1),
    offset: int = Query(default=0, ge=0),
    _: int = Depends(require_operator),
):
    """列出公告模板。"""

    with request.app.state.flask_app.app_context():
        rows, total = announcement_repo.list_templates(category=category, limit=limit, offset=offset)
    return {"success": 1, "templates": [_template_view(t) for t in rows], "total": total}


@router.post("/templates")
async def create_template_api(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
    operator_user_id: int = Depends(require_operator),
):
    """创建公告模板。"""

    name = payload.get("name")
    subject_template = payload.get("subject_template")
    body_template = payload.get("body_template")
    if not name:
        return _error(400, "name is required", "missing_field")
    if not subject_template or not body_template:
        return _error(400, "subject_template and body_template are required", "missing_field")

    try:
        with request.app.state.flask_app.app_context():
            template = announcement_repo.create_template(
                name=name,
                subject_template=subject_template,
                body_template=body_template,
                created_by=operator_user_id,
                description=payload.get("description"),
                category=payload.get("category", "custom"),
            )
            template_data = _template_view(template)
    except Exception:
        return _error(409, "template name may already exist", "duplicate_entry")

    return {"success": 1, "template": template_data}


@router.get("/templates/{template_id}")
def get_template_api(
    request: Request,
    template_id: int,
    _: int = Depends(require_operator),
):
    """查看单个模板。"""

    with request.app.state.flask_app.app_context():
        template = announcement_repo.get_template_by_id(template_id)
        if template is not None:
            template_data = _template_view(template)
    if template is None:
        return _error(404, "template not found", "not_found")
    return {"success": 1, "template": template_data}


@router.put("/templates/{template_id}")
async def update_template_api(
    request: Request,
    template_id: int,
    payload: dict[str, Any] = Body(default_factory=dict),
    _: int = Depends(require_operator),
):
    """更新模板。"""

    with request.app.state.flask_app.app_context():
        template = announcement_repo.update_template(
            template_id,
            **{k: v for k, v in payload.items() if v is not None},
        )
        if template is not None:
            template_data = _template_view(template)
    if template is None:
        return _error(404, "template not found", "not_found")
    return {"success": 1, "template": template_data}


@router.delete("/templates/{template_id}")
def delete_template_api(
    request: Request,
    template_id: int,
    _: int = Depends(require_operator),
):
    """删除模板。"""

    with request.app.state.flask_app.app_context():
        template = announcement_repo.get_template_by_id(template_id)
        if template is None:
            return _error(404, "template not found", "not_found")
        if template.category == AnnouncementTemplateCategory.SYSTEM:
            return _error(400, "cannot delete system template", "cannot_delete_system_template")
        announcement_repo.delete_template(template_id)
    return {"success": 1, "message": "template deleted"}


@router.post("/resolve-targets")
async def resolve_targets_api(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
    _: int = Depends(require_operator),
):
    """解析公告目标。"""

    raw_targets = payload.get("targets") or []
    if not raw_targets:
        return _error(400, "targets must not be empty", "empty_targets")

    try:
        with request.app.state.flask_app.app_context():
            targets = [announcement_tasks.TargetEntry(**target) for target in raw_targets]
            result = announcement_tasks.resolve_recipients(targets)
    except ValueError as e:
        return _error(400, str(e), str(e))

    return {
        "success": 1,
        "recipient_count": result.total_count,
        "summary": [_model_data(item) for item in result.summary],
        "preview_emails": [recipient.email for recipient in result.recipients[:10]],
    }


@router.get("/list")
def list_announcements_api(
    request: Request,
    status: list[str] | None = Query(default=None),
    limit: int = Query(default=50, ge=1),
    offset: int = Query(default=0, ge=0),
    _: int = Depends(require_operator),
):
    """分页查询公告。"""

    with request.app.state.flask_app.app_context():
        rows, total = announcement_repo.list_announcements(status=status, limit=limit, offset=offset)
        announcements = [_announcement_view(row) for row in rows]
        sent_count = AnnouncementModel.query.filter_by(status=AnnouncementStatus.SENT).count()
        partial_count = AnnouncementModel.query.filter_by(status=AnnouncementStatus.PARTIAL).count()
        failed_count = AnnouncementModel.query.filter_by(status=AnnouncementStatus.FAILED).count()

    return {
        "success": 1,
        "announcements": announcements,
        "total": total,
        "sent_count": sent_count,
        "partial_count": partial_count,
        "failed_count": failed_count,
    }


@router.get("/{announcement_id:int}")
def get_announcement_api(
    request: Request,
    announcement_id: int,
    _: int = Depends(require_operator),
):
    """查看单个公告。"""

    with request.app.state.flask_app.app_context():
        ann = announcement_repo.get_announcement_by_id(announcement_id)
        if ann is not None:
            announcement_data = _announcement_view(ann)
    if ann is None:
        return _error(404, "announcement not found", "not_found")
    return {"success": 1, "announcement": announcement_data}


@router.post("/{announcement_id:int}/resend")
def resend_announcement_api(
    request: Request,
    announcement_id: int,
    _: int = Depends(require_operator),
):
    """重新发送公告。"""

    try:
        with request.app.state.flask_app.app_context():
            result = announcement_tasks.resend_announcement_service(announcement_id)
    except ValueError as e:
        reason = str(e)
        if reason == "announcement_still_sending":
            return _error(409, reason, reason)
        return _error(404, reason, reason)
    return {"success": 1, **_model_data(result)}


@router.post("/{announcement_id:int}/copy-as-draft")
def copy_announcement_as_draft_api(
    request: Request,
    announcement_id: int,
    operator_user_id: int = Depends(require_operator),
):
    """复制公告为草稿。"""

    with request.app.state.flask_app.app_context():
        try:
            draft = announcement_tasks.copy_announcement_as_draft_service(
                announcement_id,
                created_by=operator_user_id,
            )
            draft_id = draft.id
        except ValueError as e:
            return _error(404, str(e), str(e))
    return {"success": 1, "draft_id": draft_id}


@router.post("/{announcement_id:int}/convert-to-template")
def convert_announcement_to_template_api(
    request: Request,
    announcement_id: int,
    operator_user_id: int = Depends(require_operator),
):
    """将公告转成模板。"""

    with request.app.state.flask_app.app_context():
        try:
            template = announcement_tasks.convert_announcement_to_template_service(
                announcement_id,
                created_by=operator_user_id,
            )
            template_data = {
                "template_id": template.id,
                "name": template.name,
                "body_template": template.body_template,
            }
        except ValueError as e:
            return _error(404, str(e), str(e))
    return {"success": 1, **template_data}


@router.delete("/{announcement_id:int}")
def delete_announcement_api(
    request: Request,
    announcement_id: int,
    _: int = Depends(require_operator),
):
    """删除公告。"""

    with request.app.state.flask_app.app_context():
        ok = announcement_tasks.delete_announcement_service(announcement_id)
    if not ok:
        return _error(404, "announcement not found", "not_found")
    return {"success": 1, "message": "announcement deleted"}


@router.post("/batch-delete")
async def batch_delete_announcements_api(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
    _: int = Depends(require_operator),
):
    """批量删除公告。"""

    announcement_ids = payload.get("announcement_ids") or []
    if not announcement_ids:
        return _error(400, "announcement_ids required", "missing_field")

    with request.app.state.flask_app.app_context():
        result = announcement_tasks.batch_delete_announcements_service(announcement_ids)
    return {"success": 1, **result}


@router.get("/drafts")
def list_drafts_api(
    request: Request,
    limit: int = Query(default=50, ge=1),
    offset: int = Query(default=0, ge=0),
    operator_user_id: int = Depends(require_operator),
):
    """列出当前 Operator 的草稿。"""

    with request.app.state.flask_app.app_context():
        rows, total = announcement_repo.list_drafts(
            created_by=operator_user_id,
            limit=limit,
            offset=offset,
        )
        drafts = [_draft_view(row) for row in rows]
    return {"success": 1, "drafts": drafts, "total": total}


@router.post("/drafts/save")
async def save_draft_api(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
    operator_user_id: int = Depends(require_operator),
):
    """保存或更新草稿。"""

    title = payload.get("title")
    content = payload.get("content")
    if not title or not content:
        return _error(400, "title and content are required", "missing_field")

    with request.app.state.flask_app.app_context():
        try:
            draft = announcement_repo.save_draft(
                title=title,
                content=content,
                created_by=operator_user_id,
                draft_id=payload.get("draft_id"),
                raw_content=payload.get("raw_content"),
                targets=payload.get("targets"),
                template_id=payload.get("template_id"),
            )
            draft_id = draft.id
        except ValueError as e:
            return _error(404, str(e), str(e))
    return {"success": 1, "draft_id": draft_id}


@router.get("/drafts/{draft_id}")
def get_draft_api(
    request: Request,
    draft_id: int,
    _: int = Depends(require_operator),
):
    """查看草稿。"""

    with request.app.state.flask_app.app_context():
        draft = announcement_repo.get_draft_by_id(draft_id)
        if draft is not None:
            draft_data = _draft_view(draft)
    if draft is None:
        return _error(404, "draft not found", "not_found")
    return {"success": 1, "draft": draft_data}


@router.delete("/drafts/{draft_id}")
def delete_draft_api(
    request: Request,
    draft_id: int,
    _: int = Depends(require_operator),
):
    """删除草稿。"""

    with request.app.state.flask_app.app_context():
        ok = announcement_repo.delete_draft(draft_id)
    if not ok:
        return _error(404, "draft not found", "not_found")
    return {"success": 1, "message": "draft deleted"}


@router.post("/drafts/batch-send")
async def batch_send_drafts_api(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
    _: int = Depends(require_operator),
):
    """批量发送草稿。"""

    draft_ids = payload.get("draft_ids") or []
    raw_targets = payload.get("targets") or []
    targets = [announcement_tasks.TargetEntry(**target) for target in raw_targets]

    try:
        with request.app.state.flask_app.app_context():
            result = announcement_tasks.batch_send_drafts_service(draft_ids, targets)
    except ValueError as e:
        reason = str(e)
        status_map = {
            "empty_targets": 400,
            "too_many_recipients": 400,
            "batch_too_large": 400,
        }
        return _error(status_map.get(reason, 400), reason, reason)

    return {"success": 1, **_model_data(result)}
