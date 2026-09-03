from datetime import datetime, timedelta
from itertools import count

from werkzeug.security import generate_password_hash

from ..constant import ContainerStatus, MachineStatus, MachineTypes, ROLE
from ..extensions import SessionRegistry, session_scope
from ..models.authentications import Authentication
from ..models.containers import Container
from ..models.machine import Machine
from ..models.user import User
from ..models.usercontainer import UserContainer
from ..repositories import auth_repo, machine_permission_repo

DEFAULT_TEST_USERNAME = "test_user"
DEFAULT_TEST_OPERATOR = "test_operator"
DEFAULT_TEST_MACHINE_NAME = "test_machine"
DEFAULT_TEST_CONTAINER_NAME = "test_container"


_ids = count(1)


def _next(prefix: str) -> str:
    return f"{prefix}_{next(_ids)}"


def create_user(
    *,
    username: str | None = None,
    email: str | None = None,
    password: str = "Password_123",
    graduation_year: str = "2026",
    operator: bool = False,
) -> User:
    username = username or _next("user")
    email = email or f"{username}@bjtu.edu.cn"
    user = User(
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
        graduation_year=str(graduation_year),
    )
    SessionRegistry.add(user)
    SessionRegistry.commit()
    if operator:
        # 取代旧 permission 单字段：operator 语义 = 绑定 operator 组（通配权限点）
        with session_scope() as session:
            group = auth_repo.ensure_group("operator", "运维组：通配权限", session=session)
            auth_repo.ensure_group_entity(group.id, "bypass_resource", session=session)
            auth_repo.ensure_group_entity(group.id, "bypass_auth_entity", session=session)
            auth_repo.ensure_user_group(user.id, group.id, session=session)
    return user


def create_auth(user: User, *, token: str | None = None, expires_at: datetime | None = None) -> Authentication:
    auth = Authentication(
        token=token or _next("token"),
        user_id=user.id,
        expires_at=expires_at or (datetime.utcnow() + timedelta(hours=1)),
    )
    SessionRegistry.add(auth)
    SessionRegistry.commit()
    return auth


def create_machine(
    *,
    machine_name: str | None = None,
    machine_ip: str | None = None,
    machine_type: MachineTypes = MachineTypes.GPU,
    machine_status: MachineStatus = MachineStatus.ONLINE,
    is_maintenance: bool = False,
    cpu_core_number: int = 32,
    gpu_number: int = 4,
    gpu_type: str = "A100",
    gpu_list: list | None = None,
    gpu_allow_list: list | None = None,
    memory_size_gb: int = 256,
    max_shared_gb: int = 8,
    max_cpu_core_number: int = 32,
    max_gpu_number: int = 4,
    max_memory_gb: int = 256,
    disk_size_gb: int = 1024,
    max_disk_size_gb: int | None = None,
    machine_description: str = "test machine",
) -> Machine:
    idx = next(_ids)
    machine = Machine(
        machine_name=machine_name or f"machine_{idx}",
        machine_ip=machine_ip or f"127.0.0.{idx}",
        machine_type=machine_type,
        machine_status=machine_status,
        is_maintenance=is_maintenance,
        cpu_core_number=cpu_core_number,
        gpu_number=gpu_number,
        gpu_type=gpu_type,
        gpu_list=gpu_list,
        gpu_allow_list=gpu_allow_list,
        memory_size_gb=memory_size_gb,
        max_shared_gb=max_shared_gb,
        max_cpu_core_number=max_cpu_core_number,
        max_gpu_number=max_gpu_number,
        max_memory_gb=max_memory_gb,
        # 上限默认延续 disk_size_gb（与迁移回填语义一致）
        max_disk_size_gb=max_disk_size_gb if max_disk_size_gb is not None else disk_size_gb,
        disk_size_gb=disk_size_gb,
        machine_description=machine_description,
    )
    SessionRegistry.add(machine)
    SessionRegistry.commit()
    return machine


def create_container(
    *,
    machine: Machine | None = None,
    name: str | None = None,
    image: str = "ubuntu:22.04",
    status: ContainerStatus = ContainerStatus.ONLINE,
    port: int | None = None,
    memory_gb: int = 8,
    shared_gb: int = 2,
    gpu_number: int = 0,
    cpu_number: int = 2,
) -> Container:
    machine = machine or create_machine()
    idx = next(_ids)
    container = Container(
        name=name or f"container_{idx}",
        image=image,
        machine_id=machine.id,
        container_status=status,
        port=port or (20000 + idx),
        memory_gb=memory_gb,
        shared_gb=shared_gb,
        gpu_number=gpu_number,
        cpu_number=cpu_number,
    )
    SessionRegistry.add(container)
    SessionRegistry.commit()
    return container


def create_container_graph(
    *,
    root_user: User | None = None,
    collaborator_user: User | None = None,
    machine: Machine | None = None,
    container: Container | None = None,
    root_username: str = "root",
    collaborator_username: str | None = None,
) -> tuple[User, Machine, Container]:
    root_user = root_user or create_user()
    machine = machine or create_machine()
    container = container or create_container(machine=machine)
    machine_permission_repo.add_permission(machine.id, root_user.id, session=SessionRegistry)
    SessionRegistry.commit()
    bind_user_container(root_user, container, role=ROLE.ROOT, username=root_username)
    if collaborator_user is not None:
        bind_user_container(
            collaborator_user,
            container,
            role=ROLE.COLLABORATOR,
            username=collaborator_username or collaborator_user.username,
        )
    return root_user, machine, container


def bind_user_container(
    user: User,
    container: Container,
    *,
    role: ROLE = ROLE.ROOT,
    username: str | None = None,
    public_key: str | None = None,
) -> UserContainer:
    binding = UserContainer(
        user_id=user.id,
        container_id=container.id,
        role=role,
        username=username or ("root" if role == ROLE.ROOT else user.username),
        public_key=public_key,
    )
    SessionRegistry.add(binding)
    SessionRegistry.commit()
    return binding
