"""公告系统 API 路由。

全部端点要求 Operator 权限。认证模式沿用项目现有风格：
- token 来自请求头
- authentications_repo.is_token_valid + user_repo.check_permission
"""

from flask import jsonify, request

from ..constant import AnnouncementStatus, AnnouncementTemplateCategory, PERMISSION
from ..repositories import announcement_repo, authentications_repo, user_repo
from ..services import announcement_tasks

from . import api_bp


# ── 工具函数 ──────────────────────────────────────────────────────────


def _get_token() -> str:
    """从请求中提取 token（cookie）。"""
    return request.cookies.get("auth_token", "")


def _require_operator():
    """校验 Operator 权限；通过返回 None，失败返回 (response, status_code)。"""
    token = _get_token()
    if not authentications_repo.is_token_valid(token):
        return jsonify({"success": 0, "message": "invalid token", "error_reason": "invalid_token"}), 401
    if not user_repo.check_permission(token, required_permission=PERMISSION.OPERATOR):
        return jsonify({"success": 0, "message": "insufficient permissions", "error_reason": "insufficient_permission"}), 403
    return None


def _current_user_id() -> int:
    """返回当前 token 对应的 user_id。调用前必须已通过 _require_operator 校验。"""
    return authentications_repo.get_user_id_by_token(_get_token())


# ── 模板 CRUD ─────────────────────────────────────────────────────────


@api_bp.get("/announcements/templates")
def list_templates_api():
    err = _require_operator()
    if err:
        return err
    category = request.args.get("category")
    limit = request.args.get("limit", 100, type=int)
    offset = request.args.get("offset", 0, type=int)

    rows, total = announcement_repo.list_templates(category=category, limit=limit, offset=offset)
    return jsonify(
        {
            "success": 1,
            "templates": [
                {
                    "id": t.id,
                    "name": t.name,
                    "category": t.category.value if hasattr(t.category, "value") else t.category,
                    "description": t.description,
                    "subject_template": t.subject_template,
                    "body_template": t.body_template,
                    "source_announcement_id": t.source_announcement_id,
                    "created_by": t.created_by,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                    "updated_at": t.updated_at.isoformat() if t.updated_at else None,
                }
                for t in rows
            ],
            "total": total,
        }
    ), 200


@api_bp.post("/announcements/templates")
def create_template_api():
    err = _require_operator()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    subject_template = data.get("subject_template")
    body_template = data.get("body_template")

    if not name:
        return jsonify({"success": 0, "message": "name is required", "error_reason": "missing_field"}), 400
    if not subject_template or not body_template:
        return jsonify({"success": 0, "message": "subject_template and body_template are required", "error_reason": "missing_field"}), 400

    try:
        template = announcement_repo.create_template(
            name=name,
            subject_template=subject_template,
            body_template=body_template,
            created_by=_current_user_id(),
            description=data.get("description"),
            category=data.get("category", "custom"),
        )
    except Exception:
        return jsonify({"success": 0, "message": "template name may already exist", "error_reason": "duplicate_entry"}), 409

    return jsonify(
        {
            "success": 1,
            "template": {
                "id": template.id,
                "name": template.name,
                "category": template.category.value if hasattr(template.category, "value") else template.category,
                "description": template.description,
                "subject_template": template.subject_template,
                "body_template": template.body_template,
            },
        }
    ), 200


@api_bp.get("/announcements/templates/<int:template_id>")
def get_template_api(template_id: int):
    err = _require_operator()
    if err:
        return err
    template = announcement_repo.get_template_by_id(template_id)
    if template is None:
        return jsonify({"success": 0, "message": "template not found", "error_reason": "not_found"}), 404
    return jsonify(
        {
            "success": 1,
            "template": {
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
            },
        }
    ), 200


@api_bp.put("/announcements/templates/<int:template_id>")
def update_template_api(template_id: int):
    err = _require_operator()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    template = announcement_repo.update_template(
        template_id,
        **{k: v for k, v in data.items() if v is not None},
    )
    if template is None:
        return jsonify({"success": 0, "message": "template not found", "error_reason": "not_found"}), 404
    return jsonify(
        {
            "success": 1,
            "template": {
                "id": template.id,
                "name": template.name,
                "category": template.category.value if hasattr(template.category, "value") else template.category,
            },
        }
    ), 200


@api_bp.delete("/announcements/templates/<int:template_id>")
def delete_template_api(template_id: int):
    err = _require_operator()
    if err:
        return err
    template = announcement_repo.get_template_by_id(template_id)
    if template is None:
        return jsonify({"success": 0, "message": "template not found", "error_reason": "not_found"}), 404
    if template.category == AnnouncementTemplateCategory.SYSTEM:
        return jsonify({"success": 0, "message": "cannot delete system template", "error_reason": "cannot_delete_system_template"}), 400
    announcement_repo.delete_template(template_id)
    return jsonify({"success": 1, "message": "template deleted"}), 200


# ── 目标解析 ──────────────────────────────────────────────────────────


@api_bp.post("/announcements/resolve-targets")
def resolve_targets_api():
    err = _require_operator()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    raw_targets = data.get("targets") or []
    if not raw_targets:
        return jsonify({"success": 0, "message": "targets must not be empty", "error_reason": "empty_targets"}), 400

    targets = [announcement_tasks.TargetEntry(**t) for t in raw_targets]
    try:
        result = announcement_tasks.resolve_recipients(targets)
    except ValueError as e:
        return jsonify({"success": 0, "message": str(e), "error_reason": str(e)}), 400

    return jsonify(
        {
            "success": 1,
            "recipient_count": result.total_count,
            "summary": [s.model_dump() for s in result.summary],
            "preview_emails": [r.email for r in result.recipients[:10]],
        }
    ), 200


# ── 公告（已发送）查询与操作 ──────────────────────────────────────────


@api_bp.get("/announcements/list")
def list_announcements_api():
    err = _require_operator()
    if err:
        return err
    status = request.args.getlist("status") or None
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)

    rows, total = announcement_repo.list_announcements(status=status, limit=limit, offset=offset)

    # 分别统计各类状态数量
    from ..models.announcement import Announcement as _Ann
    sent_count = _Ann.query.filter_by(status=AnnouncementStatus.SENT).count()
    partial_count = _Ann.query.filter_by(status=AnnouncementStatus.PARTIAL).count()
    failed_count = _Ann.query.filter_by(status=AnnouncementStatus.FAILED).count()

    return jsonify(
        {
            "success": 1,
            "announcements": [
                {
                    "id": a.id,
                    "title": a.title,
                    "content": a.content,
                    "raw_content": a.raw_content,
                    "created_by": a.created_by,
                    "status": a.status.value if hasattr(a.status, "value") else a.status,
                    "targets": a.targets,
                    "target_snapshot": a.target_snapshot,
                    "recipient_count": a.recipient_count,
                    "success_count": a.success_count,
                    "fail_count": a.fail_count,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                    "sent_at": a.sent_at.isoformat() if a.sent_at else None,
                    "source_draft_id": a.source_draft_id,
                    "template_id": a.template_id,
                }
                for a in rows
            ],
            "total": total,
            "sent_count": sent_count,
            "partial_count": partial_count,
            "failed_count": failed_count,
        }
    ), 200


@api_bp.get("/announcements/<int:announcement_id>")
def get_announcement_api(announcement_id: int):
    err = _require_operator()
    if err:
        return err
    ann = announcement_repo.get_announcement_by_id(announcement_id)
    if ann is None:
        return jsonify({"success": 0, "message": "announcement not found", "error_reason": "not_found"}), 404
    return jsonify(
        {
            "success": 1,
            "announcement": {
                "id": ann.id,
                "title": ann.title,
                "content": ann.content,
                "raw_content": ann.raw_content,
                "created_by": ann.created_by,
                "status": ann.status.value if hasattr(ann.status, "value") else ann.status,
                "targets": ann.targets,
                "target_snapshot": ann.target_snapshot,
                "recipient_count": ann.recipient_count,
                "success_count": ann.success_count,
                "fail_count": ann.fail_count,
                "created_at": ann.created_at.isoformat() if ann.created_at else None,
                "sent_at": ann.sent_at.isoformat() if ann.sent_at else None,
                "source_draft_id": ann.source_draft_id,
                "template_id": ann.template_id,
            },
        }
    ), 200


@api_bp.post("/announcements/<int:announcement_id>/resend")
def resend_announcement_api(announcement_id: int):
    err = _require_operator()
    if err:
        return err
    try:
        result = announcement_tasks.resend_announcement_service(announcement_id)
    except ValueError as e:
        reason = str(e)
        if reason == "announcement_still_sending":
            return jsonify({"success": 0, "message": reason, "error_reason": reason}), 409
        return jsonify({"success": 0, "message": reason, "error_reason": reason}), 404
    return jsonify({"success": 1, **result.model_dump()}), 200


@api_bp.post("/announcements/<int:announcement_id>/copy-as-draft")
def copy_announcement_as_draft_api(announcement_id: int):
    err = _require_operator()
    if err:
        return err
    try:
        draft = announcement_tasks.copy_announcement_as_draft_service(
            announcement_id, created_by=_current_user_id()
        )
    except ValueError as e:
        return jsonify({"success": 0, "message": str(e), "error_reason": str(e)}), 404
    return jsonify({"success": 1, "draft_id": draft.id}), 200


@api_bp.post("/announcements/<int:announcement_id>/convert-to-template")
def convert_announcement_to_template_api(announcement_id: int):
    err = _require_operator()
    if err:
        return err
    try:
        template = announcement_tasks.convert_announcement_to_template_service(
            announcement_id, created_by=_current_user_id()
        )
    except ValueError as e:
        return jsonify({"success": 0, "message": str(e), "error_reason": str(e)}), 404
    return jsonify(
        {
            "success": 1,
            "template_id": template.id,
            "name": template.name,
            "body_template": template.body_template,
        }
    ), 200


@api_bp.delete("/announcements/<int:announcement_id>")
def delete_announcement_api(announcement_id: int):
    err = _require_operator()
    if err:
        return err
    ok = announcement_tasks.delete_announcement_service(announcement_id)
    if not ok:
        return jsonify({"success": 0, "message": "announcement not found", "error_reason": "not_found"}), 404
    return jsonify({"success": 1, "message": "announcement deleted"}), 200


@api_bp.post("/announcements/batch-delete")
def batch_delete_announcements_api():
    err = _require_operator()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    announcement_ids = data.get("announcement_ids") or []
    if not announcement_ids:
        return jsonify({"success": 0, "message": "announcement_ids required", "error_reason": "missing_field"}), 400
    result = announcement_tasks.batch_delete_announcements_service(announcement_ids)
    return jsonify({"success": 1, **result}), 200


# ── 草稿 CRUD ─────────────────────────────────────────────────────────


@api_bp.get("/announcements/drafts")
def list_drafts_api():
    err = _require_operator()
    if err:
        return err
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)

    rows, total = announcement_repo.list_drafts(created_by=_current_user_id(), limit=limit, offset=offset)
    return jsonify(
        {
            "success": 1,
            "drafts": [
                {
                    "id": d.id,
                    "title": d.title,
                    "content": d.content,
                    "raw_content": d.raw_content,
                    "created_by": d.created_by,
                    "targets": d.targets,
                    "template_id": d.template_id,
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                    "updated_at": d.updated_at.isoformat() if d.updated_at else None,
                }
                for d in rows
            ],
            "total": total,
        }
    ), 200


@api_bp.post("/announcements/drafts/save")
def save_draft_api():
    err = _require_operator()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    title = data.get("title")
    content = data.get("content")

    if not title or not content:
        return jsonify({"success": 0, "message": "title and content are required", "error_reason": "missing_field"}), 400

    try:
        draft = announcement_repo.save_draft(
            title=title,
            content=content,
            created_by=_current_user_id(),
            draft_id=data.get("draft_id"),
            raw_content=data.get("raw_content"),
            targets=data.get("targets"),
            template_id=data.get("template_id"),
        )
    except ValueError as e:
        return jsonify({"success": 0, "message": str(e), "error_reason": str(e)}), 404
    return jsonify({"success": 1, "draft_id": draft.id}), 200


@api_bp.get("/announcements/drafts/<int:draft_id>")
def get_draft_api(draft_id: int):
    err = _require_operator()
    if err:
        return err
    draft = announcement_repo.get_draft_by_id(draft_id)
    if draft is None:
        return jsonify({"success": 0, "message": "draft not found", "error_reason": "not_found"}), 404
    return jsonify(
        {
            "success": 1,
            "draft": {
                "id": draft.id,
                "title": draft.title,
                "content": draft.content,
                "raw_content": draft.raw_content,
                "created_by": draft.created_by,
                "targets": draft.targets,
                "template_id": draft.template_id,
                "created_at": draft.created_at.isoformat() if draft.created_at else None,
                "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
            },
        }
    ), 200


@api_bp.delete("/announcements/drafts/<int:draft_id>")
def delete_draft_api(draft_id: int):
    err = _require_operator()
    if err:
        return err
    ok = announcement_repo.delete_draft(draft_id)
    if not ok:
        return jsonify({"success": 0, "message": "draft not found", "error_reason": "not_found"}), 404
    return jsonify({"success": 1, "message": "draft deleted"}), 200


# ── 批量发送（唯一的发送入口）──────────────────────────────────────────


@api_bp.post("/announcements/drafts/batch-send")
def batch_send_drafts_api():
    err = _require_operator()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    draft_ids = data.get("draft_ids") or []
    raw_targets = data.get("targets") or []
    targets = [announcement_tasks.TargetEntry(**t) for t in raw_targets]

    try:
        result = announcement_tasks.batch_send_drafts_service(draft_ids, targets)
    except ValueError as e:
        reason = str(e)
        status_map = {
            "empty_targets": 400,
            "too_many_recipients": 400,
            "batch_too_large": 400,
        }
        return jsonify({"success": 0, "message": reason, "error_reason": reason}), status_map.get(reason, 400)

    return jsonify({"success": 1, **result.model_dump()}), 200
