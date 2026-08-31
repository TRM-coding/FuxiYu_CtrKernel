"""Container 仓储层。

repo 只接收显式 session，负责查询、写入和 flush；事务边界由 service/tasks
的 session_scope 决定。
"""

from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..constant import ROLE
from ..models.containers import Container
from ..models.machine import Machine
from ..models.user import User
from ..utils.Container import Container_info
from . import machine_repo, user_repo, usercontainer_repo


#####################
# 资源上限


def get_max_gpu_number(machine_id: int, *, session: Session) -> int:
    return machine_repo.get_max_gpu_number(machine_id, session=session)


def get_max_shared_gb(machine_id: int, *, session: Session) -> int:
    return machine_repo.get_max_shared_gb(machine_id, session=session)


def get_max_cpu_core_number(machine_id: int, *, session: Session) -> int:
    return machine_repo.get_max_cpu_core_number(machine_id, session=session)


def get_max_memory_gb(machine_id: int, *, session: Session) -> int:
    return machine_repo.get_max_memory_gb(machine_id, session=session)


#####################
# 基础 CRUD


def get_by_id(container_id: int, *, session: Session) -> Container | None:
    return session.get(Container, int(container_id))


def get_status(container_id: int, *, session: Session):
    """读容器状态（WSS 推送落库的 DB 字段；getter 用，不打 Node）。"""

    container = get_by_id(container_id, session=session)
    return getattr(container, "container_status", None) if container else None


def get_id_by_name_machine(container_name: str, machine_id: int, *, session: Session) -> int | None:
    container = session.scalars(
        select(Container).where(
            Container.name == container_name,
            Container.machine_id == int(machine_id),
        )
    ).first()
    return container.id if container else None


def get_by_container_name(container_name: str, *, session: Session) -> Container | None:
    """按容器名查询。Node 侧快照以 name 为键，解析层按名归位。"""

    return session.scalars(select(Container).where(Container.name == container_name)).first()


def get_machine_id_by_container_id(container_id: int, *, session: Session) -> int | None:
    container = get_by_id(container_id, session=session)
    return container.machine_id if container else None


def list_containers(
    limit: int = 50,
    offset: int = 0,
    machine_id: int | None = None,
    user_id: int | None = None,
    container_search: str | None = None,
    visible_container_ids: set[int] | None = None,
    *,
    session: Session,
) -> Sequence[Container]:
    stmt = select(Container)
    if machine_id is not None:
        stmt = stmt.where(Container.machine_id == int(machine_id))
    if user_id is not None:
        stmt = stmt.join(Container.users).where(User.id == int(user_id))
    if container_search:
        keyword = f"%{container_search}%"
        stmt = stmt.join(Machine, Machine.id == Container.machine_id)
        stmt = stmt.where(
            or_(
                Container.name.ilike(keyword),
                cast(Container.id, String).ilike(keyword),
                cast(Container.port, String).ilike(keyword),
                Machine.machine_ip.ilike(keyword),
            )
        )
    if visible_container_ids is not None:
        stmt = stmt.where(Container.id.in_(visible_container_ids))
    stmt = stmt.order_by(Container.id).offset(offset).limit(limit)
    return list(session.scalars(stmt).all())


def count_containers(
    machine_id: int | None = None,
    user_id: int | None = None,
    container_search: str | None = None,
    visible_container_ids: set[int] | None = None,
    *,
    session: Session,
) -> int:
    stmt = select(func.count()).select_from(Container)
    if machine_id is not None:
        stmt = stmt.where(Container.machine_id == int(machine_id))
    if user_id is not None:
        stmt = stmt.join(Container.users).where(User.id == int(user_id))
    if container_search:
        keyword = f"%{container_search}%"
        stmt = stmt.join(Machine, Machine.id == Container.machine_id)
        stmt = stmt.where(
            or_(
                Container.name.ilike(keyword),
                cast(Container.id, String).ilike(keyword),
                cast(Container.port, String).ilike(keyword),
                Machine.machine_ip.ilike(keyword),
            )
        )
    if visible_container_ids is not None:
        stmt = stmt.where(Container.id.in_(visible_container_ids))
    return int(session.scalar(stmt) or 0)


def create_container(
    name: str,
    image: str,
    machine_id: int,
    memory_gb: int,
    shared_gb: int,
    gpu_number: int,
    cpu_number: int,
    port: int,
    status=None,
    gpu_chosen_list: list | None = None,
    *,
    session: Session,
) -> Container:
    container = Container(
        name=name,
        image=image,
        machine_id=int(machine_id),
        memory_gb=memory_gb,
        shared_gb=shared_gb,
        gpu_number=gpu_number,
        cpu_number=cpu_number,
        port=port,
        gpu_chosen_list=gpu_chosen_list,
        created_at=datetime.utcnow(),
    )
    if status is not None:
        container.container_status = status
    session.add(container)
    session.flush()
    return container


def update_container(container_id: int, *, session: Session, **fields) -> Container | None:
    container = get_by_id(container_id, session=session)
    if not container:
        return None

    allowed = {
        "name",
        "image",
        "machine_id",
        "container_status",
        "failed_reason",
        "failed_detail",
        "disk_overlay_rw_bytes",
        "disk_bind_mount_bytes",
        "disk_total_bytes",
        "disk_checked_at",
        "bind_mount_path",
        "port",
        "port_mappings",
    }
    dirty = False
    nullable_clear_fields = {"failed_reason", "failed_detail"}
    for key, value in fields.items():
        if key not in allowed or (value is None and key not in nullable_clear_fields):
            continue
        if getattr(container, key) != value:
            setattr(container, key, value)
            dirty = True
    if dirty:
        session.flush()
    return container


def delete_container(container_id: int, *, session: Session) -> bool:
    container = get_by_id(container_id, session=session)
    if not container:
        return False
    session.delete(container)
    session.flush()
    return True


def attach_user(container_id: int, user_id: int, *, session: Session) -> bool:
    container = get_by_id(container_id, session=session)
    if not container:
        return False
    user = user_repo.get_by_id(user_id, session=session)
    if not user:
        return False
    if user in container.users:
        return True
    container.users.append(user)
    session.flush()
    return True


def detach_user(container_id: int, user_id: int, *, session: Session) -> bool:
    container = get_by_id(container_id, session=session)
    if not container:
        return False
    user = user_repo.get_by_id(user_id, session=session)
    if not user:
        return False
    if user in container.users:
        container.users.remove(user)
        session.flush()
    return True


def list_users_in_container(container_id: int, *, session: Session) -> Sequence[User]:
    container = get_by_id(container_id, session=session)
    if not container:
        return []
    return list(container.users)


#####################
# 创建前校验


def ensure_machine_exists(machine_id: int, *, session: Session) -> Any:
    """Return machine object or raise ValueError with error_reason."""

    machine = machine_repo.get_by_id(machine_id, session=session)
    if not machine:
        error = ValueError(f"Target machine {machine_id} not found")
        setattr(error, "error_reason", "invalid_payload")
        raise error
    return machine


def validate_gpu_request(machine: Machine, container: Container_info, *, session: Session) -> None:
    # max_gpu_number 已退役（GPU 三集合决策）：许可数量 = allow_list 长度（配置时）
    # 或 gpu_number（未配置回退）。GPU_LIST 具体 id 由系统在 allow_list 内生成，不做 id 校验。
    allow = machine.gpu_allow_list or []
    max_gpu = len(allow) if allow else int(getattr(machine, "gpu_number", 0) or 0)
    try:
        gpu_list = getattr(container, "GPU_LIST", []) or []
    except Exception:
        gpu_list = []

    try:
        machine_type = machine.machine_type.value if hasattr(machine.machine_type, "value") else str(getattr(machine, "machine_type", "")).upper()
    except Exception:
        machine_type = str(getattr(machine, "machine_type", "")).upper()

    if str(machine_type).upper() != "GPU":
        try:
            container.GPU_LIST = []
        except Exception:
            pass
        return

    if len(gpu_list) > max_gpu:
        error = ValueError(f"Requested GPU count {len(gpu_list)} exceeds machine GPU allowance {max_gpu}")
        setattr(error, "error_reason", "invalid_config")
        raise error


def validate_shared_request(
    machine: Machine,
    container: Container_info,
    requested_memory: int | None = None,
    *,
    session: Session,
) -> int:
    if requested_memory is None:
        requested_memory = validate_memory_request(machine, container, session=session)

    try:
        requested_shared = int(getattr(container, "SHARED_MEMORY", getattr(container, "shared_memory", 0)) or 0)
    except Exception:
        error = ValueError(f"shared_memory must be an integer: {getattr(container, 'SHARED_MEMORY', None)}")
        setattr(error, "error_reason", "invalid_config")
        raise error

    machine_max_shared = int(get_max_shared_gb(machine.id, session=session) or 0)
    if requested_shared < 0 or requested_shared > machine_max_shared:
        error = ValueError(f"Requested shared_memory {requested_shared}GB out of allowed range (0-{machine_max_shared} GB)")
        setattr(error, "error_reason", "invalid_config")
        raise error

    if requested_shared > requested_memory:
        error = ValueError(f"Requested shared_memory {requested_shared}GB cannot exceed requested memory {requested_memory}GB")
        setattr(error, "error_reason", "invalid_config")
        raise error

    return requested_shared


def validate_cpu_request(machine: Machine, container: Container_info, *, session: Session) -> int:
    try:
        requested_cpus = int(getattr(container, "CPU_NUMBER", getattr(container, "cpu_number", 0) or 0))
    except Exception:
        error = ValueError(f"cpu_number must be an integer: {getattr(container, 'CPU_NUMBER', None)}")
        setattr(error, "error_reason", "invalid_config")
        raise error

    machine_max_cpus = int(get_max_cpu_core_number(machine.id, session=session) or 0)
    if requested_cpus <= 0:
        error = ValueError(f"Requested cpu_number must be > 0: {requested_cpus}")
        setattr(error, "error_reason", "invalid_config")
        raise error
    if requested_cpus > machine_max_cpus:
        error = ValueError(f"Requested cpu_number {requested_cpus} exceeds machine cpu cores {machine_max_cpus}")
        setattr(error, "error_reason", "invalid_config")
        raise error
    return requested_cpus


def validate_memory_request(machine: Machine, container: Container_info, *, session: Session) -> int:
    try:
        requested_memory = int(getattr(container, "MEMORY", getattr(container, "memory", 0) or 0))
    except Exception:
        error = ValueError(f"memory must be an integer (GB): {getattr(container, 'MEMORY', None)}")
        setattr(error, "error_reason", "invalid_config")
        raise error

    machine_memory_gb = int(get_max_memory_gb(machine.id, session=session) or 0)
    if requested_memory <= 0:
        error = ValueError(f"Requested memory must be > 0 GB: {requested_memory}")
        setattr(error, "error_reason", "invalid_config")
        raise error
    if requested_memory > machine_memory_gb:
        error = ValueError(f"Requested memory {requested_memory}GB exceeds machine memory {machine_memory_gb}GB")
        setattr(error, "error_reason", "invalid_config")
        raise error
    return requested_memory


def validate_names_and_lengths(container: Container_info, public_key: str | None = None) -> None:
    if getattr(container, "NAME", None) and len(container.NAME) > 115:
        raise ValueError(f"container name too long (max 115): length={len(container.NAME)}")
    if getattr(container, "image", None) and len(container.image) > 195:
        raise ValueError(f"container image name too long (max 195): length={len(container.image)}")
    if public_key and len(public_key) > 495:
        raise ValueError(f"public_key too long (max 495): length={len(public_key)}")

    import re

    if not re.fullmatch(r"[A-Za-z0-9_]+", getattr(container, "NAME", "") or ""):
        raise ValueError(f"invalid container name: '{getattr(container, 'NAME', '')}'. Allowed characters: A-Z a-z 0-9 _")


def check_duplicate_container_name(container_name: str, machine_id: int, *, session: Session) -> None:
    existing_id = get_id_by_name_machine(
        container_name=container_name,
        machine_id=machine_id,
        session=session,
    )
    if existing_id:
        message = f"container name '{container_name}' already exists on machine {machine_id} (id={existing_id})"
        raise IntegrityError(message, params=None, orig=message)


def validate_create_params(
    machine_id: int,
    container: Container_info,
    public_key: str | None = None,
    *,
    session: Session,
) -> None:
    """创建容器前的参数校验序列。"""

    machine = ensure_machine_exists(machine_id, session=session)
    validate_gpu_request(machine, container, session=session)
    validate_shared_request(machine, container, session=session)
    validate_cpu_request(machine, container, session=session)
    validate_names_and_lengths(container, public_key)
    check_duplicate_container_name(
        container_name=container.NAME,
        machine_id=machine_id,
        session=session,
    )


#####################
# 视图辅助


def derive_port_mappings(port: int | None, port_mappings: list | None) -> list | None:
    """出参层补齐结构化端口映射（22→port 派生）+ 去重；不修 DB 历史数据。"""

    def _int_or_none(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    mappings = []
    seen = set()
    for item in port_mappings or []:
        if not isinstance(item, dict):
            continue
        key = (
            _int_or_none(item.get("container_port")),
            _int_or_none(item.get("host_port")),
            str(item.get("protocol") or "tcp"),
        )
        if key in seen:
            continue
        seen.add(key)
        mappings.append(item)
    if port:
        has_ssh_mapping = any(
            _int_or_none(item.get("container_port")) == 22
            and _int_or_none(item.get("host_port")) == int(port)
            for item in mappings
        )
        if not has_ssh_mapping:
            mappings.insert(0, {
                "container_port": 22,
                "host_port": int(port),
                "protocol": "tcp",
            })
    return mappings or None


def get_container_root_owner_emails(container_id: int, *, session: Session) -> list[str]:
    bindings = usercontainer_repo.get_container_bindings(container_id, session=session) or []
    emails = []
    seen = set()
    for binding in bindings:
        if _binding_role_value(binding).upper() != ROLE.ROOT.value:
            continue
        user_id = binding.get("user_id")
        if user_id is None:
            continue
        user = user_repo.get_by_id(int(user_id), session=session)
        email = getattr(user, "email", None)
        if email and email not in seen:
            emails.append(email)
            seen.add(email)
    return emails


def _binding_role_value(binding: dict) -> str:
    role = binding.get("role") if isinstance(binding, dict) else None
    return role.value if isinstance(role, ROLE) else str(role or "")


def _root_user_ids_from_bindings(bindings: list | None) -> set[int]:
    return {
        int(binding["user_id"])
        for binding in (bindings or [])
        if isinstance(binding, dict)
        and binding.get("user_id") is not None
        and _binding_role_value(binding).upper() == ROLE.ROOT.value
    }
