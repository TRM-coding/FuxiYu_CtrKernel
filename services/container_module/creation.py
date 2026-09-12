from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from ...constant import ContainerStatus, OperationType, ROLE
from ...extensions import session_scope
from ...repositories import containers_repo, machine_repo, user_repo, usercontainer_repo
from ...repositories import container_ssh_login_repo
from ...utils.Container import Container_info
from ..operation_log_tasks import log_success
from .deleted_containers import restore_role_api_value
from .exceptions import NodeServiceError, _raise_on_node_error
from . import node_comms
from .node_comms import get_full_url, _ensure_machine_online_for_operation
from .utils import select_gpu_allowance

logger = logging.getLogger(__name__)

####################################################
# 创建工具族
# 本文件只放步骤函数，不含业务流程；门户 Create_container 在 services/container_tasks.py。
# 函数在文件里的排列顺序 = 门户调用顺序，便于对照阅读：
#   守卫 → 参数校验 → 选卡 → 组包 → 重名检查 → 请求 Node → 落库 → 绑定 → SSH 记录 → 审计
# 命名约定：_ensure_ 守卫/校验 · _build_ 组包（纯函数）· _request_ 网络出口 · _persist_ 落库 · _audit_ 审计
####################################################

def _ensure_create_target(
    owner_user_id: int, machine_id: int, reuse_container_id: int | None,
) -> tuple[str, str]:
    """守卫：机器必须在线；恢复路径额外校验被复用的容器行确实处于软删状态。"""
    _ensure_machine_online_for_operation(machine_id, "create")
    with session_scope(commit=False) as session:
        machine_ip = machine_repo.get_machine_ip_by_id(machine_id, session=session)
    full_url = get_full_url(machine_ip, "/create_container")
    with session_scope(commit=False) as session:
        owner_name = user_repo.get_name_by_id(owner_user_id, session=session)
    if not owner_name:
        raise NodeServiceError(f"owner user {owner_user_id} not found", reason="invalid_payload")
    if reuse_container_id is not None:
        with session_scope(commit=False) as session:
            target = containers_repo.get_by_id(int(reuse_container_id), session=session, include_invalid=True)
        if target is None:
            raise NodeServiceError("container record to restore not found", reason="data_not_recoverable")
        if bool(getattr(target, "is_valid", True)):
            raise NodeServiceError("container record to restore is already valid", reason="container_exists")
    return full_url, owner_name


def _validate_create_params(container: Container_info, machine_id: int, public_key) -> None:
    """参数校验：委托仓库层；IntegrityError 原样上抛（api 层据此回 409），其余映射为 reason。"""
    try:
        logger.debug("validating create params for container %s on machine %s", container.NAME, machine_id)
        with session_scope(commit=False) as session:
            containers_repo.validate_create_params(machine_id, container, public_key, session=session)
    except IntegrityError:
        raise
    except Exception as exc:
        reason = getattr(exc, "error_reason", None)
        if not reason:
            reason = "invalid_payload" if isinstance(exc, ValueError) else "invalid_config"
        raise NodeServiceError(str(exc), reason=reason)


def _select_gpu_cards(container: Container_info, machine_id: int, restore_mount_path: str | None) -> None:
    """选卡：按申请数量在机器 allow_list 内轮转选卡（系统决定物理卡，替换前端占位）。"""
    if getattr(container, "GPU_LIST", None) and not restore_mount_path:
        try:
            with session_scope(commit=False) as session:
                machine = machine_repo.get_by_id(machine_id, session=session)
            if machine is not None:
                container.GPU_LIST = select_gpu_allowance(machine, len(container.GPU_LIST))
        except Exception as exc:
            logger.warning("select_gpu_allowance failed (fallback to raw GPU_LIST): %s", exc)


def _build_create_payload(
    container: Container_info,
    owner_name: str,
    public_key=None,
    image_build: dict | None = None,
    restore_mount_path: str | None = None,
    restore_accounts: list[dict] | None = None,
) -> dict:
    """组包：构造发给 Node 的创建载荷。纯函数，不碰 DB/网络，可直接单测。"""
    payload = {"owner_name": owner_name, "config": container.get_config()}
    if public_key:
        payload["public_key"] = public_key
    if image_build:
        payload["image_build"] = image_build
    if restore_mount_path:
        payload["restore_mount_path"] = restore_mount_path
    if restore_accounts:
        payload["restore_accounts"] = [
            {
                "user_name": account.get("container_username") or account.get("system_username"),
                "role": restore_role_api_value(account.get("role")),
            }
            for account in restore_accounts
            if account.get("container_username") or account.get("system_username")
        ]
    return payload


def _ensure_create_name_available(container_name: str, machine_id: int) -> None:
    """重名检查：同机器重名抛 IntegrityError（api 层据此回 409）；查库异常只告警不拦截。"""
    try:
        with session_scope(commit=False) as session:
            existing_id = containers_repo.get_id_by_name_machine(
                container_name=container_name, machine_id=machine_id, session=session,
            )
        if existing_id:
            message = f"container name '{container_name}' already exists on machine {machine_id} (id={existing_id})"
            raise IntegrityError(message, params=None, orig=message)
    except IntegrityError:
        raise
    except Exception as exc:
        logger.warning("failed to check existing container name: %s", exc)


####################################################
# 以下为有副作用的步骤：网络请求 / 落库 / 绑定 / 审计
# 次序不可调换——"Node 创建成功才落库"是创建流程的核心不变量。
####################################################

def _request_node_create(full_url: str, payload: dict) -> None:
    """唯一网络出口：POST /create_container；Node 报错或非 success=1 一律上抛。"""
    response = node_comms.send(full_url, payload)
    logger.debug("Create_container: NODE response: %s", response)
    _raise_on_node_error(response, "create")
    if response.get("success") != 1:
        raise NodeServiceError(
            f"NODE create returned failure or unexpected response: {response}",
            reason=response.get("error_reason") or "unexpected_response",
        )


def _persist_container_record(
    container: Container_info,
    machine_id: int,
    image_build: dict | None,
    restore_mount_path: str | None,
    reuse_container_id: int | None,
) -> int:
    """落库：新建容器行；恢复路径（reuse_container_id）改为复活原软删行，返回 container_id。"""
    gpu_list = getattr(container, "GPU_LIST", None)
    # 端口由 docker 自动分配，先占位 0，创建后由 WSS 快照回填。
    values = dict(
        name=container.NAME,
        image=container.image,
        machine_id=machine_id,
        memory_gb=container.MEMORY,
        shared_gb=int(getattr(container, "SHARED_MEMORY", getattr(container, "shared_memory", 0)) or 0),
        gpu_number=len(gpu_list) if gpu_list else 0,
        cpu_number=container.CPU_NUMBER,
        port=0,
        status=ContainerStatus.BUILDING if image_build else ContainerStatus.CREATING,
        gpu_chosen_list=list(gpu_list) if gpu_list else None,
        bind_mount_path=restore_mount_path,
    )
    with session_scope() as session:
        if reuse_container_id is not None:
            record = containers_repo.restore_container_record(int(reuse_container_id), **values, session=session)
            if record is None:
                raise NodeServiceError("container record to restore not found", reason="not_found")
        else:
            record = containers_repo.create_container(**values, session=session)
        return record.id


def _bind_owner_and_restored_accounts(
    container_id: int, owner_user_id: int, public_key, restore_accounts: list[dict] | None,
) -> None:
    """绑定：owner 强制 root 绑定；恢复路径按快照补回原协作者（跳过 owner 与 root 角色）。"""
    with session_scope() as session:
        usercontainer_repo.add_binding(
            user_id=owner_user_id, container_id=container_id, public_key=public_key,
            username="root", role=ROLE.ROOT, session=session,
        )
        for account in restore_accounts or []:
            user_id = account.get("user_id")
            if user_id is None or int(user_id) == int(owner_user_id):
                continue
            role_value = account.get("role") or ROLE.COLLABORATOR.value
            role = ROLE(role_value) if not isinstance(role_value, ROLE) else role_value
            if role == ROLE.ROOT:
                continue
            usercontainer_repo.add_binding(
                user_id=int(user_id), container_id=container_id,
                public_key=account.get("public_key"),
                username=account.get("container_username") or account.get("system_username"),
                role=role, session=session,
            )


def _seed_initial_ssh_record(machine_id: int, container_id: int) -> None:
    """初始 SSH 记录：以创建时间作 last_ssh_login_time，避免新容器立刻被判龄清退。"""
    with session_scope() as session:
        container_ssh_login_repo.upsert_last_ssh_login_time(
            machine_id=machine_id, container_id=container_id,
            last_ssh_login_time=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"), session=session,
        )


def _audit_create(
    container_id: int, container: Container_info, machine_id: int,
    operator_user_id: int | None, reuse_container_id: int | None,
) -> None:
    """审计：恢复路径不在这里记账（resurrect_container 待长期态与快照清退完成后统一记一次）。"""
    if reuse_container_id is None:
        log_success(
            operator_user_id=operator_user_id, operation=OperationType.CREATE_CONTAINER,
            target_type="container", target_id=container_id,
            detail={
                "name": container.NAME, "machine_id": machine_id, "image": container.image,
                "memory_gb": container.MEMORY, "cpu_number": container.CPU_NUMBER,
                "gpu_number": len(getattr(container, "GPU_LIST", None) or []),
            },
        )
