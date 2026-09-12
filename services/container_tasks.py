from ..constant import OperationType, ROLE
from ..utils.Container import Container_info
from . import settings_tasks
from .container_module.exceptions import NodeServiceError

# container_module 工具族：按"容器操作族"分组导入。
# 每族对外只暴露 _load_ / _ensure_ / _build_ / _request_ / _persist_ / _audit_ 这类步骤函数，
# 本文件的门户只负责把这些步骤按正确顺序串起来（业务编排留在门户，动作细节在各族文件）。
from .container_module.queries import (      # 查询：容器/机器/冻结/清理态的读侧工具
    _parse_query_container_id,
    _read_disk_container,
    _read_last_ssh_record,
    _load_detail_container,
    _get_container_bindings,
    _get_container_machine,
    _get_container_freeze_state,
    _get_container_cleanup_state,
    _get_owner_names,
    _get_visible_container_ids,
    _query_container_page,
    _get_user_long_term_quota,
)
from .container_module.information import (  # 出参组装：详情 / 列表项 / 分页结构
    _build_disk_usage_response,
    _build_detail_disk_usage,
    _build_container_detail,
    _build_container_brief,
    _build_container_page,
)
from .container_module.pydantic_models import container_detail_information
from .container_module.utils import (        # 通用工具：清理倒计时 / 长期态
    build_cleanup_info,
    build_long_term_container_state,
)
from .container_module.deleted_containers import (  # 已删容器的快照、列表与清理入参解析
    build_container_restore_snapshot,
    build_deleted_container_page,
    resolve_mount_cleanup_request,
)
from .container_module.creation import (     # 创建族
    _ensure_create_target,
    _validate_create_params,
    _select_gpu_cards,
    _build_create_payload,
    _ensure_create_name_available,
    _request_node_create,
    _persist_container_record,
    _bind_owner_and_restored_accounts,
    _seed_initial_ssh_record,
    _audit_create,
)
from .container_module.deletion import (     # 删除族
    _load_removal_container,
    _request_node_removal,
    _persist_container_deletion,
    _audit_removal,
)
from .container_module.actions import (      # 冻结 / 解冻族（磁盘超限动作）
    _load_pause_container,
    _ensure_pause_allowed,
    _request_pause_action,
    _persist_paused_status,
    _grant_unpause_grace,
)
from .container_module.restore import (      # 恢复族（复活软删容器）
    _load_restore_target,
    _load_restore_accounts,
    _build_restore_container,
    _get_restored_container_id,
    _restore_long_term_state,
    _delete_restore_artifacts,
    _audit_restore_success,
    _audit_restore_failure,
    _audit_mount_preflight_failure,
)
from .container_module.mount_cleanup import clean_mount_path  # 挂载清理动作（手动/定时/升级共用）
from .container_module.long_term import (    # 长期容器族
    _load_long_term_target,
    _ensure_long_term_capacity,
    _persist_long_term_state,
    _audit_long_term,
)
from .container_module.collaborators import (  # 协作者与角色族
    _load_collaborator_account,
    _is_root_binding,
    _build_collaborator_payload,
    _request_collaborator_action,
    _add_collaborator_binding,
    _remove_collaborator_binding,
    _update_collaborator_binding,
    _collaborator_role_change,
    _audit_collaborator,
)
from .container_module.lifecycle import (    # 启停族
    _load_container_target,
    _ensure_container_action,
    _request_lifecycle_action,
    _audit_container_action,
)


####################################################
# 容器创建
# 门户保留原始出入参；顺序即契约：守卫 → 参数校验 → 选卡 → 组包 → 重名检查 → 请求 Node
# → 落库 → 绑定 → SSH 记录 → 审计。其中"Node 成功才落库"是不可调换的次序。
####################################################

def Create_container(
    owner_user_id: int,
    machine_id: int,
    container: Container_info,
    public_key=None,
    operator_user_id: int | None = None,
    image_build: dict | None = None,
    restore_mount_path: str | None = None,
    restore_accounts: list[dict] | None = None,
    reuse_container_id: int | None = None,
) -> bool:
    full_url, owner_name = _ensure_create_target(owner_user_id, machine_id, reuse_container_id)
    _validate_create_params(container, machine_id, public_key)
    _select_gpu_cards(container, machine_id, restore_mount_path)
    payload = _build_create_payload(
        container, owner_name, public_key, image_build, restore_mount_path, restore_accounts,
    )
    _ensure_create_name_available(container.NAME, machine_id)
    _request_node_create(full_url, payload)
    container_id = _persist_container_record(
        container, machine_id, image_build, restore_mount_path, reuse_container_id,
    )
    _bind_owner_and_restored_accounts(container_id, owner_user_id, public_key, restore_accounts)
    _seed_initial_ssh_record(machine_id, container_id)
    _audit_create(container_id, container, machine_id, operator_user_id, reuse_container_id)
    return True


####################################################
# 长期容器
####################################################

def get_long_term_container_limit() -> int:
    return settings_tasks.get_long_term_container_limit()


def set_long_term_container(
    container_id: int, is_long_term: bool, operator_user_id: int | None = None,
) -> dict:
    container, bindings, existing = _load_long_term_target(container_id)
    if is_long_term and not existing:
        _ensure_long_term_capacity(bindings)
    _persist_long_term_state(container.id, is_long_term, existing, operator_user_id)
    state = build_long_term_container_state(container.id, bindings)
    _audit_long_term(container.id, is_long_term, operator_user_id)
    return {"container_id": container.id, **state}


####################################################
# 容器删除 / 恢复 / 挂载清理
# 删除是软删（is_valid=false，保留原行与原 id）；恢复走同一 Create_container，
# 用 reuse_container_id 复活原行；mount 清理动作统一委托 clean_mount_path。
####################################################

def remove_container(container_id: int, operator_user_id: int | None = None) -> bool:
    container = None
    trigger = "api" if operator_user_id else "cleanup"
    try:
        container = _load_removal_container(container_id)
        _ensure_container_action(container, "remove")
        _request_node_removal(container)
        _persist_container_deletion(container_id, trigger, operator_user_id)
    except Exception as exc:
        _audit_removal(container_id, container, trigger, operator_user_id, error=exc)
        raise
    _audit_removal(container_id, container, trigger, operator_user_id)
    return True


def resurrect_container(deleted_id: int, operator_user_id: int | None = None) -> dict:
    """恢复软删容器：走 container:manage 方法级权限，不做资源级鉴权（已删记录无法通过在线资源校验）。"""
    try:
        target = _load_restore_target(deleted_id)
        root_account, accounts = _load_restore_accounts(target.snapshot)
        container, renamed = _build_restore_container(target)
        Create_container(
            owner_user_id=int(root_account["user_id"]), machine_id=target.machine_id,
            container=container, public_key=root_account.get("public_key"),
            operator_user_id=operator_user_id, restore_mount_path=target.mount_path,
            restore_accounts=accounts, reuse_container_id=target.container_id,
        )
        container_id = _get_restored_container_id(container.NAME, target.machine_id)
        _restore_long_term_state(container_id, target.snapshot, operator_user_id)
        _delete_restore_artifacts(int(deleted_id), target.mount_cleanup_id)
        _audit_restore_success(
            int(deleted_id), target, container_id, container, renamed, len(accounts) + 1, operator_user_id,
        )
        return {"container_id": container_id}
    except Exception as exc:
        _audit_restore_failure(deleted_id, operator_user_id, exc)
        raise


def clean_deleted_container_mount(
    deleted_id: int | None = None,
    operator_user_id: int | None = None,
    *,
    mount_cleanup_id: int | None = None,
) -> dict:
    """手动清理已删容器的挂载目录：走 container:manage 方法级权限（已删记录无法通过在线资源校验）。"""
    try:
        deleted_id, cleanup = resolve_mount_cleanup_request(deleted_id, mount_cleanup_id)
    except Exception as exc:
        _audit_mount_preflight_failure(deleted_id, mount_cleanup_id, operator_user_id, exc)
        raise
    if cleanup is None:
        return {
            "deleted_id": int(deleted_id), "mount_cleanup_id": None,
            "cleaned": False, "already_cleaned": True,
        }
    return clean_mount_path(cleanup.id, operator_user_id=operator_user_id, trigger="manual_clean_mount")


####################################################
# 容器生命周期：启停 / 冻结 / 解冻
####################################################

def start_container(container_id: int, operator_user_id: int | None = None) -> bool:
    container, machine_ip = _load_container_target(container_id)
    _ensure_container_action(container, "start")
    _request_lifecycle_action(machine_ip, container.name, "start")
    _audit_container_action(container, OperationType.START_CONTAINER, operator_user_id)
    return True


def pause_container(
    container_id: int, operator_user_id: int | None = None, extra_detail: dict | None = None,
) -> bool:
    """冻结容器（磁盘超限动作）；调用方传入的磁盘策略明细一并进审计。"""
    operation = OperationType.PAUSE_CONTAINER
    container = _load_pause_container(container_id, operation, operator_user_id, extra_detail)
    if container is None:
        return False
    _ensure_pause_allowed(container, "pause", operation, operator_user_id, extra_detail)
    if not _request_pause_action(container, "pause", operation, operator_user_id, extra_detail):
        return False
    _persist_paused_status(container.id)
    _audit_container_action(container, operation, operator_user_id, extra_detail)
    return True


def unpause_container(container_id: int, operator_user_id: int | None = None) -> bool:
    """解冻容器：重开磁盘宽限，但保留原冻结升级期限（不重置升级倒计时）。"""
    operation = OperationType.UNPAUSE_CONTAINER
    container = _load_pause_container(container_id, operation, operator_user_id)
    if container is None:
        return False
    _ensure_pause_allowed(container, "unpause", operation, operator_user_id)
    if not _request_pause_action(container, "unpause", operation, operator_user_id):
        return False
    _audit_container_action(container, operation, operator_user_id)
    _grant_unpause_grace(container)
    return True


def stop_container(container_id: int, operator_user_id: int | None = None) -> bool:
    container, machine_ip = _load_container_target(container_id)
    _ensure_container_action(container, "stop")
    _request_lifecycle_action(machine_ip, container.name, "stop")
    _audit_container_action(container, OperationType.STOP_CONTAINER, operator_user_id)
    return True


def restart_container(container_id: int, operator_user_id: int | None = None) -> bool:
    container, machine_ip = _load_container_target(container_id)
    _ensure_container_action(container, "restart")
    _request_lifecycle_action(machine_ip, container.name, "restart")
    _audit_container_action(container, OperationType.RESTART_CONTAINER, operator_user_id)
    return True


####################################################
# 协作者与角色
####################################################

def add_collaborator(
    container_id: int, user_id: int, role: ROLE, operator_user_id: int | None = None,
) -> bool:
    container, machine_ip = _load_container_target(container_id)
    _ensure_container_action(container, "add_collaborator", require_online=True)
    user_name, _ = _load_collaborator_account(user_id, container_id)
    if role == ROLE.ROOT:
        return False
    payload = _build_collaborator_payload(container.name, user_name, role=role)
    _request_collaborator_action(machine_ip, "add_collaborator", payload)
    _add_collaborator_binding(container_id, user_id, user_name, role)
    _audit_collaborator(
        container, user_id, user_name, OperationType.ADD_COLLABORATOR, operator_user_id,
        role=role.value if hasattr(role, "value") else str(role),
    )
    return True


def remove_collaborator(
    container_id: int, user_id: int, operator_user_id: int | None = None,
) -> bool:
    container, machine_ip = _load_container_target(container_id)
    _ensure_container_action(container, "remove_collaborator", require_online=True)
    user_name, binding = _load_collaborator_account(user_id, container_id)
    if _is_root_binding(binding):
        return False
    payload = _build_collaborator_payload(container.name, user_name)
    _request_collaborator_action(machine_ip, "remove_collaborator", payload)
    _remove_collaborator_binding(container_id, user_id)
    _audit_collaborator(container, user_id, user_name, OperationType.REMOVE_COLLABORATOR, operator_user_id)
    return True


def update_role(
    container_id: int, user_id: int, updated_role: ROLE, operator_user_id: int | None = None,
) -> bool:
    container, machine_ip = _load_container_target(container_id)
    _ensure_container_action(container, "update_role", require_online=True)
    user_name, old_binding = _load_collaborator_account(user_id, container_id)
    payload = _build_collaborator_payload(container.name, user_name, updated_role=updated_role)
    _request_collaborator_action(machine_ip, "update_role", payload)
    _update_collaborator_binding(container_id, user_id, user_name, updated_role)
    _audit_collaborator(
        container, user_id, user_name, OperationType.UPDATE_COLLABORATOR_ROLE, operator_user_id,
        **_collaborator_role_change(old_binding, updated_role),
    )
    return True


####################################################
# 查询与列表（只读：全部读 WSS 落库快照，不打 Node）
####################################################

def list_deleted_containers(page_number: int = 1, page_size: int = 20) -> dict:
    return build_deleted_container_page(page_number=page_number, page_size=page_size)


def get_container_disk_usage(container_id: int, timeout: float = 20.0) -> dict | None:
    """读 WSS 落库的磁盘快照；timeout 仅为保持对外签名兼容，不发起 Node 请求。"""
    container_id = _parse_query_container_id(container_id, "disk usage")
    if container_id is None:
        return None
    container = _read_disk_container(container_id)
    if container is None:
        return None
    return _build_disk_usage_response(container)


def get_container_last_ssh_login_time(container_id: int, timeout: float = 5.0) -> str | None:
    """读 WSS 落库的 SSH 登录快照，不联系 Node。"""
    container_id = _parse_query_container_id(container_id, "SSH login time")
    if container_id is None:
        return None
    record = _read_last_ssh_record(container_id)
    return record.last_ssh_login_time if record else None


def get_container_detail_information(container_id: int) -> container_detail_information:
    container = _load_detail_container(container_id)
    bindings = _get_container_bindings(container.id)
    long_term = build_long_term_container_state(container.id, bindings)
    machine = _get_container_machine(container.machine_id)
    disk_usage = _build_detail_disk_usage(container, machine)
    freeze = _get_container_freeze_state(container.id, ignore_errors=True)
    cleanup = _get_container_cleanup_state(container, ignore_errors=True)
    owners = _get_owner_names(bindings)
    return _build_container_detail(container, machine, bindings, long_term, cleanup, freeze, disk_usage, owners)


def list_all_container_bref_information(
    machine_id: int | None,
    request_user_id: int,
    page_number: int,
    page_size: int,
    user_id: int | None = None,
    container_search: str | None = None,
    viewer_user_id: int | None = None,
) -> dict:
    container_search = (container_search or "").strip() or None
    visible_ids = _get_visible_container_ids(viewer_user_id)
    containers, total_count = _query_container_page(
        machine_id, user_id, container_search, visible_ids, page_number, page_size,
    )
    items = []
    for container in containers:
        bindings = _get_container_bindings(container.id)
        long_term = build_long_term_container_state(container.id, bindings)
        freeze = _get_container_freeze_state(container.id)
        cleanup = _get_container_cleanup_state(container)
        machine = _get_container_machine(container.machine_id)
        items.append(_build_container_brief(container, machine, bindings, long_term, cleanup, freeze))
    result = _build_container_page(items, total_count, page_size)
    if user_id is not None:
        result.update(_get_user_long_term_quota(user_id))
    return result
