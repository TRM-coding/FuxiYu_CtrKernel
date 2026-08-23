import json
import requests
import time
import base64
import logging
from datetime import datetime
import traceback
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from pydantic import BaseModel, Field
from ..config import AppConfig
from ..extensions import session_scope

from ..constant import *
from sqlalchemy.exc import IntegrityError
from ..repositories import containers_repo, machine_repo, machine_permission_repo, user_repo, long_term_container_repo
from .operation_log_tasks import write_operation_log as write_op_log
from ..repositories import containers_repo as container_repo
from ..repositories import container_ssh_login_repo
from ..repositories.machine_repo import *
from ..repositories.user_repo import *
from ..utils.Container import Container_info
from ..repositories.containers_repo import *
from ..repositories.usercontainer_repo import *
from ..models.containers import Container
import math
from ..utils import sanitizer as _sanitizer

from .container_module.node_comms import (
    send,
    get_full_url,
    _ensure_machine_online_for_operation,
)
from .container_module.exceptions import NodeServiceError, _raise_on_node_error
from .container_module.pydantic_models import (
    container_bref_information,
    container_detail_information,
    _derive_display_status,
    DISPLAY_STATUS_HOST_OFFLINE,
    DISPLAY_STATUS_HOST_MAINTENANCE,
)
from .container_module.utils import _parse_last_ssh_time, build_cleanup_info
from ..utils.permissions import _can_access_machine, _is_operator_user
from ..repositories.long_term_container_repo import get_long_term_container_limit
from ..repositories.containers_repo import _binding_role_value, _root_user_ids_from_bindings

logger = logging.getLogger(__name__)


def get_by_id(container_id: int):
    with session_scope(commit=False) as session:
        return containers_repo.get_by_id(container_id, session=session)


def get_status(container_id: int):
    with session_scope(commit=False) as session:
        return containers_repo.get_status(container_id, session=session)


def get_id_by_name_machine(container_name: str, machine_id: int) -> int | None:
    with session_scope(commit=False) as session:
        return containers_repo.get_id_by_name_machine(
            container_name=container_name,
            machine_id=machine_id,
            session=session,
        )


def get_machine_id_by_container_id(container_id: int) -> int | None:
    with session_scope(commit=False) as session:
        return containers_repo.get_machine_id_by_container_id(container_id, session=session)


def list_containers(
    limit: int = 50,
    offset: int = 0,
    machine_id: int | None = None,
    user_id: int | None = None,
    container_search: str | None = None,
):
    with session_scope(commit=False) as session:
        return containers_repo.list_containers(
            limit=limit,
            offset=offset,
            machine_id=machine_id,
            user_id=user_id,
            container_search=container_search,
            session=session,
        )


def count_containers(
    machine_id: int | None = None,
    user_id: int | None = None,
    container_search: str | None = None,
) -> int:
    with session_scope(commit=False) as session:
        return containers_repo.count_containers(
            machine_id=machine_id,
            user_id=user_id,
            container_search=container_search,
            session=session,
        )


def create_container(*args, **kwargs):
    with session_scope() as session:
        return containers_repo.create_container(*args, session=session, **kwargs)


def update_container(container_id: int, **fields):
    fields.pop("commit", None)
    with session_scope() as session:
        return containers_repo.update_container(container_id, session=session, **fields)


def delete_container(container_id: int) -> bool:
    with session_scope() as session:
        return containers_repo.delete_container(container_id, session=session)


def validate_create_params(machine_id: int, container: Container_info, public_key: str | None = None) -> None:
    with session_scope(commit=False) as session:
        return containers_repo.validate_create_params(
            machine_id,
            container,
            public_key,
            session=session,
        )


def add_binding(*args, **kwargs):
    kwargs.pop("commit", None)
    with session_scope() as session:
        return usercontainer_repo.add_binding(*args, session=session, **kwargs)


def remove_binding(*args, **kwargs):
    kwargs.pop("commit", None)
    with session_scope() as session:
        return usercontainer_repo.remove_binding(*args, session=session, **kwargs)


def get_binding(user_id: int, container_id: int):
    with session_scope(commit=False) as session:
        return usercontainer_repo.get_binding(user_id, container_id, session=session)


def get_user_bindings(user_id: int):
    with session_scope(commit=False) as session:
        return usercontainer_repo.get_user_bindings(user_id, session=session)


def get_container_bindings(container_id: int):
    with session_scope(commit=False) as session:
        return usercontainer_repo.get_container_bindings(container_id, session=session)


def update_binding(*args, **kwargs):
    kwargs.pop("commit", None)
    with session_scope() as session:
        return usercontainer_repo.update_binding(*args, session=session, **kwargs)


def get_name_by_id(user_id: int) -> str | None:
    with session_scope(commit=False) as session:
        return user_repo.get_name_by_id(user_id, session=session)


def get_container_root_owner_emails(container_id: int) -> list[str]:
    with session_scope(commit=False) as session:
        return containers_repo.get_container_root_owner_emails(container_id, session=session)


def _is_long_term_container(container_id: int) -> bool:
    with session_scope(commit=False) as session:
        return long_term_container_repo.is_long_term(container_id, session=session)


def _count_long_term_by_user(user_id: int) -> int:
    with session_scope(commit=False) as session:
        return long_term_container_repo.count_by_user(user_id, session=session)


def _get_long_term_container_remaining(user_id: int) -> int:
    with session_scope(commit=False) as session:
        return long_term_container_repo.get_long_term_container_remaining(user_id, session=session)


def get_machine_ip_by_id(machine_id: int) -> str:
    with session_scope(commit=False) as session:
        return machine_repo.get_machine_ip_by_id(machine_id, session=session)


def get_the_first_free_port(machine_id: int) -> int:
    with session_scope(commit=False) as session:
        return machine_repo.get_the_first_free_port(machine_id, session=session)


def get_name_by_id(user_id: int) -> str | None:
    with session_scope(commit=False) as session:
        return user_repo.get_name_by_id(user_id, session=session)


def get_by_name(username: str):
    with session_scope(commit=False) as session:
        return user_repo.get_by_name(username, session=session)


def get_container_last_ssh_login_time(container_id: int, timeout: float = 5.0) -> str | None:
    """读容器上次 SSH 登录时间。

    WSS 推送已接管采集（last_ssh 快照落库 container_ssh_login_records），getter 只查库。
    """
    try:
        container_id = int(container_id)
    except Exception:
        logger.warning("Invalid container id for SSH login time query: %s", container_id)
        return None

    try:
        with session_scope(commit=False) as session:
            record = container_ssh_login_repo.get_by_container(container_id, session=session)
    except Exception:
        logger.error("Error querying ssh login record for id=%s: %s", container_id, traceback.format_exc())
        return None

    return record.last_ssh_login_time if record else None



#Function Implementation
####################################################


# 将user_id作为admin，创建新容器
def Create_container(owner_name:str,machine_id:int,container:Container_info,public_key=None, operator_user_id:int|None=None)->bool:
    if operator_user_id is not None and not _can_access_machine(operator_user_id, machine_id):
        raise NodeServiceError(f'Machine {machine_id} not accessible for user {operator_user_id}', reason='machine_permission_denied')
    # ensure machine is online before attempting creation
    _ensure_machine_online_for_operation(machine_id, 'create')
    machine_ip=get_machine_ip_by_id(machine_id)
    full_url = get_full_url(machine_ip, "/create_container")

    free_port = get_the_first_free_port(machine_id=machine_id)
    container.set_port(free_port)

    ### 参数检查 (delegated to repositories.container_repo helpers) ###
    try:
        logger.debug("DEBUG: validating create params for container %s on machine %s", container.NAME, machine_id)
        validate_create_params(machine_id, container, public_key)
    except IntegrityError:
        # let DB integrity errors bubble up as-is so API callers can handle duplicate entries
        raise
    except Exception as e:
        # preserve any repository-provided error_reason if present
        reason = getattr(e, 'error_reason', None)
        if reason:
            raise NodeServiceError(str(e), reason=reason)
        # ValueError generally indicates invalid payload/params from client
        if isinstance(e, ValueError):
            raise NodeServiceError(str(e), reason='invalid_payload')
        # fallback: treat as invalid_config if it's a validation-like issue, else unexpected_response
        raise NodeServiceError(str(e), reason='invalid_config')

    ### container构建 ###

    container_info=dict()
    container_info['owner_name']=owner_name
    container_info['config']=container.get_config()
    if public_key:
        container_info['public_key']=public_key
    # 名称/长度/格式等校验已在参数检查阶段由 container_repo.validate_create_params 完成

    # check duplicate container name on this machine before sending to Node
    try:
        existing_id = get_id_by_name_machine(container_name=container.NAME, machine_id=machine_id)
        if existing_id:
            # raise IntegrityError so callers can handle duplicate-name consistently
            orig_msg = f"container name '{container.NAME}' already exists on machine {machine_id} (id={existing_id})"
            raise IntegrityError(orig_msg, params=None, orig=orig_msg)
    except IntegrityError:
        # re-raise IntegrityError to propagate
        raise
    except Exception as e:
        # If the check fails unexpectedly, log and continue to avoid blocking creation due to DB issues
        logger.warning("failed to check existing container name: %s", e)
    res=send(full_url, container_info)
    logger.debug("Create_container: NODE response: %s", res)
    # 检查Node是否返回错误，如果有则抛出异常；如果没有则继续后续流程（写DB记录、建立绑定、启动心跳等）
    _raise_on_node_error(res, 'create')
    if res.get('success') != 1:
        # unexpected response from Node; abort to avoid DB inconsistency
        raise NodeServiceError(f"NODE create returned failure or unexpected response: {res}", reason=res.get('error_reason') or "unexpected_response")

    gpu_list = getattr(container, 'GPU_LIST', None)
    gpu_count = len(gpu_list) if gpu_list else 0
    # 写入容器记录
    create_container(name=container.NAME,
                     image=container.image,
                     machine_id=machine_id,
                     memory_gb=container.MEMORY,
                     shared_gb=int(getattr(container, 'SHARED_MEMORY', getattr(container, 'shared_memory', 0)) or 0),
                     gpu_number=gpu_count,
                     cpu_number=container.CPU_NUMBER,
                     port=free_port,
                     status=ContainerStatus.CREATING
                     )

    # 建立用户绑定（包含必须的 role/username/public_key）
    container_id=get_id_by_name_machine(container_name=container.NAME, machine_id=machine_id)
    user = get_by_name(owner_name)
    add_binding(user_id=user.id,
                container_id=container_id,
                public_key=public_key,
                username='root', # 强制使用 root 作为用户名
                role=ROLE.ROOT) # 这里在创建时，自动变成 ROOT

    # 写入初始 SSH 登录记录，以创建时间作为 last_ssh_login_time，防止无法清退
    with session_scope() as session:
        container_ssh_login_repo.upsert_last_ssh_login_time(
            machine_id=machine_id,
            container_id=container_id,
            last_ssh_login_time=datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S'),
            session=session,
        )

    # 状态推进已由 WSS 推送接管（status_cache 转换态 → Ctrl 落库），心跳轮询已退役
    write_op_log(success=True,
        operator_user_id=operator_user_id,
        operation=OperationType.CREATE_CONTAINER,
        target_type="container",
        target_id=container_id,
        detail={
            "name": container.NAME,
            "machine_id": machine_id,
            "image": container.image,
            "port": free_port,
            "memory_gb": container.MEMORY,
            "cpu_number": container.CPU_NUMBER,
            "gpu_number": gpu_count,
        },
    )
    return True

#删除容器并删除其所有者记录
def remove_container(container_id:int, operator_user_id:int|None=None)->bool:
    machine_id = get_machine_id_by_container_id(container_id)
    if operator_user_id is not None and not _can_access_machine(operator_user_id, machine_id):
        raise NodeServiceError(f'Machine {machine_id} not accessible for user {operator_user_id}', reason='machine_permission_denied')
    if not machine_id:
        raise ValueError("Container not found or not associated with any machine")
    # 使得只在机器在线时执行
    _ensure_machine_online_for_operation(machine_id, 'remove')
    machine_ip=get_machine_ip_by_id(machine_id)
    full_url = get_full_url(machine_ip, "/remove_container")

    container_name = get_by_id(container_id).name
    data={
        "config":{
            "container_name":container_name
        }
    }        
    
    container_info=data
    res=send(full_url, container_info)
    logger.debug("remove_container: NODE response: %s", res)
    # 先看看远程调用层面是否有错误（网络/请求/远程处理错误等），如果有则抛出异常；如果没有则根据 Node 的返回内容来决定是否继续本地删除（Node 返回 NOTFOUND 则本地也删除，Node 返回 FAILED 则不删除并抛出异常）
    _raise_on_node_error(res, 'remove')
    # Node remove_container currently returns numeric code in 'success': 0=SUCCESS,1=NOTFOUND,2=FAILED
    NODE_code = res.get('success')
    if NODE_code is None:
        raise Exception(f"NODE remove returned unexpected response: {res}")
    if NODE_code == 2:
        # FAILED
        raise NodeServiceError(f"NODE remove reported failure: {res}", reason=res.get('error_reason') or 'remove_failed')
    # treat 0 (SUCCESS) and 1 (NOTFOUND) as acceptable success for local cleanup

    if 'error' in res:
        logger.error("远程调用失败: %s", res['error'])
        raise Exception(f"远程调用失败: {res['error']}")
    
    # 记录操作日志（删前写，保留容器名称等信息）
    try:
        container = get_by_id(container_id)
    except Exception:
        container = None
    write_op_log(success=True,
        operator_user_id=operator_user_id,
        operation=OperationType.DELETE_CONTAINER,
        target_type="container",
        target_id=container_id,
        detail={
            "name": getattr(container, 'name', '?') if container else '?',
            "machine_id": machine_id,
            "trigger": "api" if operator_user_id else "cleanup",
        },
    )

    # 移除所有绑定并删除容器
    remove_binding(0, container_id, all=True)

    # 记录 mount 清理信息（删前捕获路径）
    _bind_mount = getattr(container, 'bind_mount_path', None) if container else None
    _container_name = getattr(container, 'name', '?') if container else '?'

    delete_container(container_id)

    # 插入 mount 清理追踪（14 天后由定期任务清理）
    if _bind_mount:
        try:
            from ..repositories.container_mount_cleanup_repo import insert as insert_mount_cleanup
            from datetime import datetime as dt
            insert_mount_cleanup(
                container_id=container_id,
                container_name=_container_name,
                machine_id=machine_id,
                mount_path=_bind_mount,
                escalation=False,
                removed_at=dt.utcnow(),
            )
            logger.info("remove_container: mount cleanup recorded for container %s path=%s", container_id, _bind_mount)
        except Exception as e:
            logger.warning("remove_container: failed to record mount cleanup for %s: %s", container_id, e)

    return True

def pause_container(container_id: int, operator_user_id: int | None = None, extra_detail: dict | None = None) -> bool:
    """冻结容器（磁盘超限等场景）。与 unpause_container 对称。

    *extra_detail* 供调用方补充操作详情（如磁盘处置的 reason/usage），合并进 op-log。
    """
    try:
        container_id = int(container_id)
    except Exception:
        return False

    container = get_by_id(container_id)
    if not container:
        return False

    machine_id = container.machine_id
    if operator_user_id is not None and not _can_access_machine(operator_user_id, machine_id):
        raise NodeServiceError(f'Machine {machine_id} not accessible', reason='machine_permission_denied')

    machine_ip = get_machine_ip_by_id(machine_id)
    url = get_full_url(machine_ip, "/pause_container")
    payload = {"config": {"container_name": container.name, "action": "pause"}}
    try:
        res = send(url, payload, timeout=10.0)
    except Exception as e:
        logger.error("pause_container send error: %s", e)
        write_op_log(success=False, operator_user_id=operator_user_id, operation=OperationType.PAUSE_CONTAINER,
                     target_type="container", target_id=container.id,
                     detail={"name": container.name, "machine_id": machine_id, **(extra_detail or {})},
                     error_reason=getattr(e, 'reason', None) or str(e))
        return False

    _raise_on_node_error(res, 'pause')
    if res.get('success') == 1:
        # 更新本地状态为 paused
        try:
            update_container(container.id, container_status=ContainerStatus.PAUSED)
        except Exception as e:
            logger.warning("pause: failed to update container %s status to PAUSED: %s", container.id, e)
        write_op_log(success=True, operator_user_id=operator_user_id, operation=OperationType.PAUSE_CONTAINER,
                     target_type="container", target_id=container.id,
                     detail={"name": container.name, "machine_id": machine_id, **(extra_detail or {})})
        return True
    return False


def unpause_container(container_id: int, operator_user_id: int | None = None) -> bool:
    """解冻因磁盘超限被 pause 的容器。"""
    try:
        container_id = int(container_id)
    except Exception:
        return False

    container = get_by_id(container_id)
    if not container:
        return False

    machine_id = container.machine_id
    if operator_user_id is not None and not _can_access_machine(operator_user_id, machine_id):
        raise NodeServiceError(f'Machine {machine_id} not accessible', reason='machine_permission_denied')

    machine_ip = get_machine_ip_by_id(machine_id)
    url = get_full_url(machine_ip, "/pause_container")
    payload = {"config": {"container_name": container.name, "action": "unpause"}}
    try:
        res = send(url, payload, timeout=10.0)
    except Exception as e:
        logger.error("unpause_container send error: %s", e)
        write_op_log(success=False, operator_user_id=operator_user_id, operation=OperationType.UNPAUSE_CONTAINER,
                     target_type="container", target_id=container.id,
                     detail={"name": container.name, "machine_id": machine_id},
                     error_reason=getattr(e, 'reason', None) or str(e))
        return False

    _raise_on_node_error(res, 'unpause')
    if res.get('success') == 1:
        # 更新本地状态为 online
        try:
            update_container(container.id, container_status=ContainerStatus.ONLINE)
        except Exception as e:
            logger.warning("unpause: failed to update container %s status to ONLINE: %s", container.id, e)
        write_op_log(success=True, operator_user_id=operator_user_id, operation=OperationType.UNPAUSE_CONTAINER,
                     target_type="container", target_id=container.id,
                     detail={"name": container.name, "machine_id": machine_id})

        # 磁盘超限冻结宽限期：管理员解冻后给予宽限
        try:
            from ..repositories import container_disk_freeze_state_repo
            with session_scope() as session:
                freeze_state = container_disk_freeze_state_repo.get(container_id, session=session)
                if freeze_state is not None:
                    grace_days = getattr(AppConfig, "CONTAINER_DISK_FREEZE_GRACE_DAYS", 3)
                    container_disk_freeze_state_repo.set_grace(container_id, grace_days, session=session)
            if freeze_state is not None:
                logger.info(
                    "[disk-check] grace period set for container %s (%s) (%s days, until %s)",
                    container_id, getattr(container, 'name', '?'), grace_days, freeze_state.grace_until,
                )
        except Exception as e:
            logger.warning("[disk-check] failed to set grace for container %s: %s", container_id, e)

        return True
    return False


def get_container_disk_usage(container_id: int, timeout: float = 20.0) -> dict | None:
    """读容器磁盘用量（WSS 推送落库 disk_* 字段，getter 只查库）。

    返回形状兼容原 Node 响应：{"success": 1, "container": {...}}。
    """
    try:
        container_id = int(container_id)
    except Exception:
        logger.warning("Invalid container id for disk usage query: %s", container_id)
        return None

    try:
        container = get_by_id(container_id)
    except Exception:
        logger.error("Error querying container info for id=%s: %s", container_id, traceback.format_exc())
        return None

    if not container:
        return None

    return {
        "success": 1,
        "container": {
            "overlay_rw_bytes": getattr(container, 'disk_overlay_rw_bytes', None),
            "bind_mount_bytes": getattr(container, 'disk_bind_mount_bytes', None),
            "total_bytes": getattr(container, 'disk_total_bytes', None),
            "bind_mount_path": getattr(container, 'bind_mount_path', None),
        },
    }


####################################################


def build_container_restore_snapshot(container_id: int, cleanup_context: dict | None = None) -> dict:
    """
    Build a pre-removal snapshot with enough metadata to recreate the container and bindings.

    # 注：字段集将来可能被 image 蓝图（Dockerfile + 脚本 + pre_build）参考，
    # image 域（FuxiYu_Global/fuxi平台继续开发.md「新增需求」）落地时评估是否吸收。
    """
    container = get_by_id(container_id)
    if not container:
        return {
            "container_id": container_id,
            "snapshot_status": "container_not_found",
            "cleanup_context": cleanup_context or {},
        }

    try:
        with session_scope(commit=False) as session:
            machine = machine_repo.get_by_id(container.machine_id, session=session)
    except Exception:
        machine = None

    bindings = get_container_bindings(container_id) or []
    accounts = []
    for binding in bindings:
        user_id = binding.get("user_id")
        role = binding.get("role")
        role_value = role.value if isinstance(role, ROLE) else str(role or "")
        accounts.append({
            "user_id": user_id,
            "system_username": get_name_by_id(user_id) if user_id is not None else None,
            "container_username": binding.get("username"),
            "role": role_value,
            "public_key": binding.get("public_key"),
            "granted_at": str(binding.get("granted_at")) if binding.get("granted_at") is not None else None,
        })

    status = container.container_status
    status_value = status.value if isinstance(status, ContainerStatus) else str(status or "")
    snapshot = {
        "container_id": container.id,
        "container_name": container.name,
        "image": container.image,
        "machine_id": container.machine_id,
        "machine_ip": getattr(machine, "machine_ip", None),
        "machine_name": getattr(machine, "machine_name", None),
        "container_status": status_value,
        "port": container.port,
        "memory_gb": container.memory_gb,
        "shared_gb": container.shared_gb,
        "gpu_number": container.gpu_number,
        "cpu_number": container.cpu_number,
        "is_long_term": _is_long_term_container(container.id),
        "accounts": accounts,
        "cleanup_context": cleanup_context or {},
    }
    return snapshot


def _build_long_term_container_state(container_id: int, bindings: list | None = None) -> dict:
    bindings = bindings if bindings is not None else (get_container_bindings(container_id) or [])
    is_long_term = _is_long_term_container(container_id)
    user_ids = _root_user_ids_from_bindings(bindings)
    remaining_by_user = {
        uid: _get_long_term_container_remaining(uid)
        for uid in user_ids
    }
    blocked_user_ids = [] if is_long_term else [
        uid for uid, remaining in remaining_by_user.items() if remaining <= 0
    ]
    return {
        "is_long_term": is_long_term,
        "long_term_container_can_enable": len(blocked_user_ids) == 0,
        "long_term_container_blocked_user_ids": blocked_user_ids,
        "long_term_container_remaining_by_user": remaining_by_user,
    }


def set_long_term_container(container_id: int, is_long_term: bool, operator_user_id: int | None = None) -> dict:
    try:
        container_id = int(container_id)
    except Exception:
        raise NodeServiceError("invalid container_id", reason="invalid_payload")

    container = get_by_id(container_id)
    if not container:
        raise NodeServiceError("Container not found", reason="container_not_found")

    bindings = get_container_bindings(container_id) or []
    root_user_ids = _root_user_ids_from_bindings(bindings)
    if operator_user_id is not None and operator_user_id not in root_user_ids and not _is_operator_user(operator_user_id):
        raise NodeServiceError(
            f"User {operator_user_id} is not owner of container {container_id}",
            reason="container_permission_denied",
        )

    existing = _is_long_term_container(container_id)
    if is_long_term:
        if not existing:
            limit = get_long_term_container_limit()
            for uid in root_user_ids:
                if _count_long_term_by_user(uid) >= limit:
                    raise NodeServiceError(
                        f"User {uid} has reached long-term container limit",
                        reason="long_term_limit_reached",
                    )
            with session_scope() as session:
                long_term_container_repo.add(container_id, created_by_user_id=operator_user_id, session=session)
    else:
        with session_scope() as session:
            long_term_container_repo.remove(container_id, session=session)

    long_term_state = _build_long_term_container_state(container_id, bindings)
    write_op_log(success=True, operator_user_id=operator_user_id,
                 operation=OperationType.SET_LONG_TERM,
                 target_type="container", target_id=container_id,
                 detail={"name": getattr(get_by_id(container_id), 'name', None),
                         "is_long_term": is_long_term})
    return {
        "container_id": container_id,
        **long_term_state,
    }
#将container_id对应的容器新增user_id作为collaborator,其权限为role

def add_collaborator(container_id:int,user_id:int,role:ROLE, operator_user_id:int|None=None)->bool:
    machine_id = get_machine_id_by_container_id(container_id)
    if operator_user_id is not None and not _can_access_machine(operator_user_id, machine_id):
        raise NodeServiceError(f'Machine {machine_id} not accessible for user {operator_user_id}', reason='machine_permission_denied')
    if not machine_id:
        raise ValueError("Container not found or not associated with any machine")
    machine_ip=get_machine_ip_by_id(machine_id)
    full_url = get_full_url(machine_ip, "/add_collaborator")

    container_name = get_by_id(container_id).name
    # operation guard: machine must be online
    _ensure_machine_online_for_operation(machine_id, 'add_collaborator')
    # Ensure container is online before attempting collaborator changes
    container_obj = get_by_id(container_id)
    if not container_obj:
        raise ValueError("Container not found")
    if container_obj.container_status != ContainerStatus.ONLINE:
        raise NodeServiceError(f"Container {container_id} is not online", reason="container_offline")

    user_name=get_name_by_id(user_id)
    # validate inputs to avoid passing unsafe values to Node
    try:
        _sanitizer.validate_username(user_name)
    except Exception as e:
        raise ValueError(f"unsafe user_name: {e}")
    # Do not allow adding a collaborator as ROOT via this API/task
    if role == ROLE.ROOT:
        # Reject silently (caller/API will return failure)
        return False
    data={
        "config":{
            "container_name":container_name,
            "user_name":user_name,
            "role":role.value
        }
           
    }
    container_info=data
    res=send(full_url, container_info)

    _raise_on_node_error(res, 'add_collaborator')
    if res.get('success') not in (1, True):
        raise NodeServiceError(f"NODE add_collaborator returned failure: {res}", reason=res.get('error_reason') or 'add_failed')
    # 直接通过绑定表建立关联
    add_binding(user_id=user_id,
                container_id=container_id,
                username=user_name,
                public_key=None,
                role=role)
    
    write_op_log(success=True, operator_user_id=operator_user_id, operation=OperationType.ADD_COLLABORATOR,
                 target_type="container", target_id=container_id,
                 detail={"user_id": user_id, "username": user_name,
                         "role": role.value if hasattr(role, 'value') else str(role),
                         "container_name": container_name})
    return True
#从container_id中移除user_id对应的用户访问权

def remove_collaborator(container_id:int,user_id:int,operator_user_id:int|None=None)->bool:
    machine_id = get_machine_id_by_container_id(container_id)
    if operator_user_id is not None and not _can_access_machine(operator_user_id, machine_id):
        raise NodeServiceError(f'Machine {machine_id} not accessible for user {operator_user_id}', reason='machine_permission_denied')
    if not machine_id:
        raise ValueError("Container not found or not associated with any machine")
    machine_ip=get_machine_ip_by_id(machine_id)
    full_url = get_full_url(machine_ip, "/remove_collaborator")

    container_name = get_by_id(container_id).name
    # operation guard: machine must be online
    _ensure_machine_online_for_operation(machine_id, 'remove_collaborator')
    # Ensure container is online before attempting collaborator changes
    container_obj = get_by_id(container_id)
    if not container_obj:
        raise ValueError("Container not found")
    if container_obj.container_status != ContainerStatus.ONLINE:
        raise NodeServiceError(f"Container {container_id} is not online", reason="container_offline")
    user_name = get_name_by_id(user_id)
    try:
        _sanitizer.validate_username(user_name)
    except Exception as e:
        raise ValueError(f"unsafe user_name: {e}")

    # prevent removing ROOT owners
    try:
        binding = get_binding(user_id, container_id)
    except Exception:
        binding = None
    if binding:
        role_val = _binding_role_value(binding)
        if role_val.upper() == ROLE.ROOT.value.upper():
            # 不可移除 ROOT 用户
            return False

    user_name=get_name_by_id(user_id)
    data={
        "config":{
            "container_name":container_name,
            "user_name":user_name
        }
    }
    container_info=data
    res=send(full_url, container_info)
    
    _raise_on_node_error(res, 'remove_collaborator')
    if res.get('success') not in (1, True):
        raise NodeServiceError(f"NODE remove_collaborator returned failure: {res}", reason=res.get('error_reason') or 'remove_failed')
    # 仅删除绑定
    remove_binding(user_id,container_id)

    write_op_log(success=True, operator_user_id=operator_user_id, operation=OperationType.REMOVE_COLLABORATOR,
                 target_type="container", target_id=container_id,
                 detail={"user_id": user_id, "username": user_name,
                         "container_name": container_name})
    return True

#修改user_id对container_id的访问权

def update_role(container_id:int,user_id:int,updated_role:ROLE,operator_user_id:int|None=None)->bool:
    machine_id = get_machine_id_by_container_id(container_id)
    if operator_user_id is not None and not _can_access_machine(operator_user_id, machine_id):
        raise NodeServiceError(f'Machine {machine_id} not accessible for user {operator_user_id}', reason='machine_permission_denied')
    if not machine_id:
        raise ValueError("Container not found or not associated with any machine")
    machine_ip=get_machine_ip_by_id(machine_id)
    full_url = get_full_url(machine_ip, "/update_role")

    container_name = get_by_id(container_id).name

    # Ensure container is online before attempting role updates
    # operation guard: machine must be online
    _ensure_machine_online_for_operation(machine_id, 'update_role')
    container_obj = get_by_id(container_id)
    if not container_obj:
        raise ValueError("Container not found")
    if container_obj.container_status != ContainerStatus.ONLINE:
        raise NodeServiceError(f"Container {container_id} is not online", reason="container_offline")

    user_name=get_name_by_id(user_id)
    try:
        _sanitizer.validate_username(user_name)
    except Exception as e:
        raise ValueError(f"unsafe user_name: {e}")
    # 远侧处理ROOT相关的角色变更 可能需单独考察
    data={
        "config":{
            "container_name":container_name,
            "user_name":user_name,
            "updated_role":updated_role.value
        }
    }
    container_info=data
    # 使用 machine_ip 发送
    res=send(full_url, container_info)

    _raise_on_node_error(res, 'update_role')
    if res.get('success') not in (1, True):
        raise NodeServiceError(f"NODE update_role returned failure: {res}", reason=res.get('error_reason') or 'update_failed')
    if updated_role == ROLE.ROOT:
        # 强制使用 root 作为用户名
        username = 'root'
    else:
        username = user_name

    # 记录旧角色，便于审计"从什么改到什么"
    try:
        old_binding = get_binding(user_id, container_id)
        old_role = _binding_role_value(old_binding) if old_binding else None
    except Exception:
        old_role = None

    # 更新绑定时同时传入 username 和 role，确保数据库中的 username 在变更为 ROOT 时被设置为 'root'
    update_binding(user_id, container_id, username=username, role=updated_role)

    write_op_log(success=True, operator_user_id=operator_user_id, operation=OperationType.UPDATE_COLLABORATOR_ROLE,
                 target_type="container", target_id=container_id,
                 detail={"user_id": user_id, "username": user_name,
                         "old_role": old_role,
                         "new_role": updated_role.value if hasattr(updated_role, 'value') else str(updated_role),
                         "container_name": container_name})
    return True


def start_container(container_id:int, operator_user_id:int|None=None)->bool:
    """发送start到对应容器所在node,启动后心跳机制监控状态，直到状态变为ONLINE或失败"""
    machine_id = get_machine_id_by_container_id(container_id)
    if operator_user_id is not None and not _can_access_machine(operator_user_id, machine_id):
        raise NodeServiceError(f'Machine {machine_id} not accessible for user {operator_user_id}', reason='machine_permission_denied')
    if not machine_id:
        raise ValueError("Container not found or not associated with any machine")
    _ensure_machine_online_for_operation(machine_id, 'start')
    machine_ip = get_machine_ip_by_id(machine_id)
    full_url = get_full_url(machine_ip, "/start_container")

    container_name = get_by_id(container_id).name
    data = {"config": {"container_name": container_name}}
    container_info = data

    res = send(full_url, container_info)
    logger.debug("start_container: NODE response: %s", res)

    # Check node-level errors
    _raise_on_node_error(res, 'start')
    # Expect success truthy
    if res.get('success') in (1, True):
        # 状态推进由 WSS 推送接管（转换态 → Ctrl 落库），心跳轮询已退役
        write_op_log(success=True, operator_user_id=operator_user_id, operation=OperationType.START_CONTAINER,
                     target_type="container", target_id=container_id,
                     detail={"name": container_name})
        return True
    # Treat other responses as failure
    raise NodeServiceError(f"NODE start returned failure: {res}", reason=res.get('error_reason') or 'start_failed')


def stop_container(container_id:int, operator_user_id:int|None=None)->bool:
    """发送stop到对应容器所在node,停止后心跳机制监控状态，直到状态变为OFFLINE或失败"""
    machine_id = get_machine_id_by_container_id(container_id)
    if operator_user_id is not None and not _can_access_machine(operator_user_id, machine_id):
        raise NodeServiceError(f'Machine {machine_id} not accessible for user {operator_user_id}', reason='machine_permission_denied')
    if not machine_id:
        raise ValueError("Container not found or not associated with any machine")
    _ensure_machine_online_for_operation(machine_id, 'stop')
    machine_ip = get_machine_ip_by_id(machine_id)
    full_url = get_full_url(machine_ip, "/stop_container")

    container_name = get_by_id(container_id).name
    data = {"config": {"container_name": container_name}}
    container_info = data

    res = send(full_url, container_info)
    logger.debug("stop_container: NODE response: %s", res)

    _raise_on_node_error(res, 'stop')
    if res.get('success') in (1, True):
        # 状态推进由 WSS 推送接管，心跳轮询已退役
        write_op_log(success=True, operator_user_id=operator_user_id, operation=OperationType.STOP_CONTAINER,
                     target_type="container", target_id=container_id,
                     detail={"name": container_name})
        return True
    raise NodeServiceError(f"NODE stop returned failure: {res}", reason=res.get('error_reason') or 'stop_failed')


def restart_container(container_id:int, operator_user_id:int|None=None)->bool:
    """发送restart到对应容器所在node,重启后心跳机制监控状态，直到状态变为ONLINE或失败"""
    machine_id = get_machine_id_by_container_id(container_id)
    if operator_user_id is not None and not _can_access_machine(operator_user_id, machine_id):
        raise NodeServiceError(f'Machine {machine_id} not accessible for user {operator_user_id}', reason='machine_permission_denied')
    if not machine_id:
        raise ValueError("Container not found or not associated with any machine")
    _ensure_machine_online_for_operation(machine_id, 'restart')
    machine_ip = get_machine_ip_by_id(machine_id)
    full_url = get_full_url(machine_ip, "/restart_container")

    container_name = get_by_id(container_id).name
    data = {"config": {"container_name": container_name}}
    container_info = data

    res = send(full_url, container_info)
    logger.debug("restart_container: NODE response: %s", res)

    _raise_on_node_error(res, 'restart')
    if res.get('success') in (1, True):
        # 状态推进由 WSS 推送接管（转换态 → Ctrl 落库），心跳轮询已退役
        write_op_log(success=True, operator_user_id=operator_user_id, operation=OperationType.RESTART_CONTAINER,
                     target_type="container", target_id=container_id,
                     detail={"name": container_name})
        return True
    raise NodeServiceError(f"NODE restart returned failure: {res}", reason=res.get('error_reason') or 'restart_failed')

#返回容器的细节信息
def get_container_detail_information(container_id:int)->container_detail_information:
    container=get_by_id(container_id)
    if not container:
        raise ValueError("Container not found")
    # 状态直接读 WSS 推送落库的 DB 字段（getter 只查库，不打 Node）。
    # 「容器在 Node 侧消失」的 404 删记录语义由 WSS delete 帧接管
    # （Node 对账发现消失 → 推送 delete → Ctrl 抹 DB）。
    owener_bindings= get_container_bindings(container_id)
    long_term_state = _build_long_term_container_state(container.id, owener_bindings)

    # 附加磁盘用量（从 DB 快照）
    disk_usage = None
    try:
        d_total = getattr(container, 'disk_total_bytes', None)
        if d_total is not None and d_total >= 0:
            limit_bytes = getattr(container, 'disk_limit_bytes', None) or 0
            limit_gb = limit_bytes / (1024**3) if limit_bytes else 0.0
            disk_usage = {
                "overlay_rw_gb": round((getattr(container, 'disk_overlay_rw_bytes', None) or 0) / (1024**3), 1),
                "bind_mount_gb": round((getattr(container, 'disk_bind_mount_bytes', None) or 0) / (1024**3), 1),
                "total_gb": round(d_total / (1024**3), 1),
                "limit_gb": round(limit_gb, 1),
                "usage_percent": round((d_total / limit_bytes * 100) if limit_bytes > 0 else 0, 1),
            }
    except Exception as e:
        logger.warning("failed to read DB disk snapshot for container %s: %s", container.id, e)

    # 冻结升级状态
    freeze_state_val = None
    try:
        from ..repositories import container_disk_freeze_state_repo
        with session_scope(commit=False) as session:
            fs = container_disk_freeze_state_repo.get(container.id, session=session)
        if fs:
            from datetime import datetime
            days_frozen = (datetime.utcnow() - fs.first_frozen_at).days if fs.first_frozen_at else 0
            escalation_days = int(getattr(AppConfig, "CONTAINER_DISK_FREEZE_ESCALATION_DAYS", 7) or 7)
            freeze_state_val = {
                "is_frozen": True,
                "first_frozen_at": fs.first_frozen_at.isoformat() if fs.first_frozen_at else None,
                "grace_until": fs.grace_until.isoformat() if fs.grace_until else None,
                "days_frozen": days_frozen,
                "escalation_days": escalation_days,
            }
    except Exception as e:
        logger.warning("failed to read freeze state for container %s: %s", container.id, e)

    res={
        "container_id": container.id,
        "container_name": container.name,
        "container_image": container.image,
        "machine_id": container.machine_id,
        "machine_ip": get_machine_ip_by_id(container.machine_id),
        "container_status": container.container_status.value,
        "display_status": _derive_display_status(container.container_status, container.machine_id),
        "memory_gb": container.memory_gb,
        "shared_gb": container.shared_gb,
        "gpu_number": container.gpu_number,
        "cpu_number": container.cpu_number,
        "port": container.port,
        **long_term_state,
        "disk_usage": disk_usage,
        "freeze_state": freeze_state_val,
        # 备忘：owners才是系统对应的用户名列表
        "owners": [get_name_by_id(binding['user_id']) for binding in owener_bindings],
        # 这里的变动是为了
        # 1. 语句写法 - 防止报错（针对API提取时的格式问题）
        # 2. username -> user_id 使得在页面层对应性更强，并避免可能存在的 user_name与username不同
        "accounts": [
            {"user_id": binding.get('user_id'), "username": binding.get("username"), "role": (ROLE(binding.get('role')).value if binding.get('role') is not None else None)}
            for binding in owener_bindings
        ],
    }
    return res

def list_all_container_bref_information(
    machine_id: int | None,
    request_user_id: int,
    page_number: int,
    page_size: int,
    user_id: int | None = None,
    container_search: str | None = None,
) -> dict:
    container_search = (container_search or "").strip() or None
    offset = page_number * page_size
    total_count = 0
    # 非管理员用户必须先通过机器权限表过滤可见机器
    if not _is_operator_user(request_user_id):
        with session_scope(commit=False) as session:
            allowed = set(machine_permission_repo.list_machine_ids_by_user(request_user_id, session=session))
        if machine_id is not None:
            if machine_id not in allowed:
                containers = []
                total_count = 0
            else:
                containers = list_containers(
                    limit=page_size,
                    offset=offset,
                    machine_id=machine_id,
                    user_id=request_user_id,
                    container_search=container_search,
                )
                total_count = count_containers(
                    machine_id=machine_id,
                    user_id=request_user_id,
                    container_search=container_search,
                )
        else:
            all_visible = [
                c for c in list_containers(
                    limit=99999,
                    offset=0,
                    machine_id=None,
                    user_id=request_user_id,
                    container_search=container_search,
                )
                if c.machine_id in allowed
            ]
            total_count = len(all_visible)
            containers = all_visible[offset:offset + page_size]
    elif user_id is not None:
        containers = list_containers(
            limit=page_size,
            offset=offset,
            machine_id=machine_id,
            user_id=user_id,
            container_search=container_search,
        )
        total_count = count_containers(
            machine_id=machine_id,
            user_id=user_id,
            container_search=container_search,
        )
    else:
        containers = list_containers(
            limit=page_size,
            offset=offset,
            machine_id=machine_id,
            user_id=None,
            container_search=container_search,
        )
        total_count = count_containers(
            machine_id=machine_id,
            user_id=None,
            container_search=container_search,
        )
    # WSS 推送已接管状态采集（apply_container_status_snapshot 落库 container_status）；
    # getter 只查库组装，不再实时打 Node。「容器在 Node 侧消失」由 WSS delete 帧处理。
    res = []
    for container in containers:
        bindings = get_container_bindings(container.id) or []
        long_term_state = _build_long_term_container_state(container.id, bindings)
        # 冻结升级状态
        from ..repositories import container_disk_freeze_state_repo
        with session_scope(commit=False) as session:
            freeze_state = container_disk_freeze_state_repo.get(container.id, session=session)
        freeze_first_frozen_at = freeze_state.first_frozen_at.isoformat() if (freeze_state and freeze_state.first_frozen_at) else None
        freeze_grace_until = freeze_state.grace_until.isoformat() if (freeze_state and freeze_state.grace_until) else None
        freeze_days_frozen = None
        freeze_escalation_days = None
        if freeze_state and freeze_state.first_frozen_at:
            from datetime import datetime
            freeze_days_frozen = (datetime.utcnow() - freeze_state.first_frozen_at).days
            freeze_escalation_days = int(getattr(AppConfig, "CONTAINER_DISK_FREEZE_ESCALATION_DAYS", 7) or 7)
        with session_scope(commit=False) as session:
            ssh_record = container_ssh_login_repo.get_by_machine_container(
                container.machine_id,
                container.id,
                session=session,
            )
        cleanup_days = 7
        cleanup_days = int(getattr(AppConfig, "CONTAINER_CLEANUP_AFTER_DAYS", 7) or 7)
        cleanup_info = build_cleanup_info(
            ssh_record.last_ssh_login_time if ssh_record else None,
            cleanup_days,
        )
        # 磁盘用量（从 DB 快照，不实时查 Node）
        d_total = getattr(container, 'disk_total_bytes', None)
        d_limit = getattr(container, 'disk_limit_bytes', None) or 0
        disk_total_gb = round(d_total / (1024**3), 1) if d_total is not None else None
        disk_limit_gb = round(d_limit / (1024**3), 1) if d_limit else None
        disk_usage_percent = round((d_total / d_limit * 100) if (d_total is not None and d_limit > 0) else 0, 1)

        try:
            machine_ip = get_machine_ip_by_id(container.machine_id)
        except Exception:
            machine_ip = ""

        info = container_bref_information(
            container_id=container.id,
            container_name=container.name,
            machine_id=container.machine_id,
            machine_ip=machine_ip,
            port=container.port,
            container_status=container.container_status.value,
            display_status=_derive_display_status(container.container_status, container.machine_id),
            accounts=[
                {"user_id": binding.get('user_id'), "username": binding.get("username"), "role": (ROLE(binding.get('role')).value if binding.get('role') is not None else None)}
                for binding in bindings
            ],
            last_ssh_login_time=ssh_record.last_ssh_login_time if ssh_record else None,
            cleanup_after_days=cleanup_info.get("cleanup_after_days"),
            cleanup_at=cleanup_info.get("cleanup_at"),
            seconds_until_cleanup=cleanup_info.get("seconds_until_cleanup"),
            disk_total_gb=disk_total_gb,
            disk_limit_gb=disk_limit_gb,
            disk_usage_percent=disk_usage_percent,
            cleanup_status=cleanup_info.get("cleanup_status"),
            freeze_first_frozen_at=freeze_first_frozen_at,
            freeze_grace_until=freeze_grace_until,
            freeze_days_frozen=freeze_days_frozen,
            freeze_escalation_days=freeze_escalation_days,
            **long_term_state,
        )
        res.append(info)

    # 这里计算总页数
    try: # 理论不会报错 但是被建议保留
        total_page = max(1, math.ceil(total_count / page_size))
    except Exception:
        total_page = 1

    result = {"containers": res, "total_page": total_page, "total_number": total_count}
    if user_id is not None:
        result["long_term_container_remaining"] = _get_long_term_container_remaining(user_id)
        result["long_term_container_limit"] = get_long_term_container_limit()
    return result

####################################################
