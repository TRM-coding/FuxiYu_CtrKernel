from datetime import datetime, timedelta
from itertools import count

from werkzeug.security import generate_password_hash

from ..constant import ContainerStatus, MachineStatus, MachineTypes, PERMISSION, ROLE
from ..extensions import db
from ..models.authentications import Authentication
from ..models.containers import Container
from ..models.machine import Machine
from ..models.user import User
from ..models.usercontainer import UserContainer
from ..repositories import machine_permission_repo


_ids = count(1)


def _next(prefix: str) -> str:
    return f"{prefix}_{next(_ids)}"


def create_user(
    *,
    username: str | None = None,
    email: str | None = None,
    password: str = "Password_123",
    graduation_year: str = "2026",
    permission: PERMISSION = PERMISSION.USER,
) -> User:
    username = username or _next("user")
    email = email or f"{username}@bjtu.edu.cn"
    user = User(
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
        graduation_year=str(graduation_year),
        permission=permission,
    )
    db.session.add(user)
    db.session.commit()
    return user


def create_auth(user: User, *, token: str | None = None, expires_at: datetime | None = None) -> Authentication:
    auth = Authentication(
        token=token or _next("token"),
        user_id=user.id,
        expires_at=expires_at or (datetime.utcnow() + timedelta(hours=1)),
    )
    db.session.add(auth)
    db.session.commit()
    return auth


def create_machine(
    *,
    machine_name: str | None = None,
    machine_ip: str | None = None,
    machine_type: MachineTypes = MachineTypes.GPU,
    machine_status: MachineStatus = MachineStatus.ONLINE,
    cpu_core_number: int = 32,
    gpu_number: int = 4,
    gpu_type: str = "A100",
    memory_size_gb: int = 256,
    max_shared_gb: int = 8,
    max_cpu_core_number: int = 32,
    max_gpu_number: int = 4,
    max_memory_gb: int = 256,
    disk_size_gb: int = 1024,
    machine_description: str = "test machine",
) -> Machine:
    idx = next(_ids)
    machine = Machine(
        machine_name=machine_name or f"machine_{idx}",
        machine_ip=machine_ip or f"127.0.0.{idx}",
        machine_type=machine_type,
        machine_status=machine_status,
        cpu_core_number=cpu_core_number,
        gpu_number=gpu_number,
        gpu_type=gpu_type,
        memory_size_gb=memory_size_gb,
        max_shared_gb=max_shared_gb,
        max_cpu_core_number=max_cpu_core_number,
        max_gpu_number=max_gpu_number,
        max_memory_gb=max_memory_gb,
        disk_size_gb=disk_size_gb,
        machine_description=machine_description,
    )
    db.session.add(machine)
    db.session.commit()
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
    db.session.add(container)
    db.session.commit()
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
    machine_permission_repo.add_permission(machine.id, root_user.id)
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
    db.session.add(binding)
    db.session.commit()
    return binding
