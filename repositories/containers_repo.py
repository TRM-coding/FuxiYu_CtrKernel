"""Container 仓储层: 提供容器 CRUD 与用户绑定操作"""
from typing import Sequence, Any
from ..extensions import db
from ..models.containers import Container
from ..models.user import User
from ..models.machine import Machine
from ..utils.Container import Container_info
from ..constant import ROLE
from sqlalchemy.exc import IntegrityError
from . import machine_repo
from .machine_repo import get_max_gpu_number, get_max_swap_gb, get_max_cpu_core_number, get_max_memory_gb


def get_by_id(container_id: int) -> Container | None:
	return Container.query.get(container_id)

def get_id_by_name_machine(container_name: str, machine_id: int) -> int | None:
	container = Container.query.filter_by(name=container_name, machine_id=machine_id).first()
	return container.id if container else None

def get_machine_id_by_container_id(container_id: int) -> int | None:
	container = get_by_id(container_id)
	return container.machine_id if container else None

def list_containers(limit: int = 50, offset: int = 0, machine_id: int | None = None, user_id: int | None = None) -> Sequence[Container]:
	q = Container.query
	if machine_id is not None:
		q = q.filter_by(machine_id=machine_id)

	if user_id is not None:
		q = q.join(Container.users).filter(User.id == user_id)
	return q.order_by(Container.id).offset(offset).limit(limit).all()

# 增加主要目的是为了增加可读性
def count_containers(machine_id: int | None = None) -> int:
    q = Container.query
    if machine_id is not None:
        q = q.filter_by(machine_id=machine_id)
    return q.count()


def create_container(name: str, image: str, machine_id: int, port:int,status=None) -> Container:
	container = Container(name=name, image=image, machine_id=machine_id, port=port)
	if status is not None:
		container.container_status = status
	db.session.add(container)
	db.session.commit()
	return container


def update_container(container_id: int, *, commit: bool = True, **fields) -> Container | None:
	container = get_by_id(container_id)
	if not container:
		return None
	allowed = {"name", "image", "machine_id", "container_status"}
	dirty = False
	for k, v in fields.items():
		if k not in allowed or v is None:
			continue
		if getattr(container, k) != v:
			setattr(container, k, v)
			dirty = True
	if dirty:
		if commit:
			db.session.commit()
		else:
			db.session.flush()
	return container


def delete_container(container_id: int) -> bool:
	container = get_by_id(container_id)
	if not container:
		return False
	db.session.delete(container)
	db.session.commit()
	return True


def attach_user(container_id: int, user_id: int, commit: bool = True) -> bool:
	container = get_by_id(container_id)
	if not container:
		return False
	user = User.query.get(user_id)
	if not user:
		return False
	if user in container.users:
		return True
	container.users.append(user)
	if commit:
		db.session.commit()
	return True


def detach_user(container_id: int, user_id: int, commit: bool = True) -> bool:
	container = get_by_id(container_id)
	if not container:
		return False
	user = User.query.get(user_id)
	if not user:
		return False
	if user in container.users:
		container.users.remove(user)
		if commit:
			db.session.commit()
	return True


def list_users_in_container(container_id: int) -> Sequence[User]:
	container = get_by_id(container_id)
	if not container:
		return []
	return list(container.users)


# 用于检测各项指标 判定容器是否可以创建
def ensure_machine_exists(machine_id: int) -> Any:
	"""Return machine object or raise ValueError with error_reason."""
	try:
		m = machine_repo.get_by_id(machine_id) # machine object or None
	except Exception:
		m = None
	if not m:
		e = ValueError(f"Target machine {machine_id} not found")
		setattr(e, 'error_reason', 'invalid_payload')
		raise e
	return m


def validate_gpu_request(machine: Machine, container: Container_info) -> None:
	print(f"DEBUG: validating GPU request for machine {machine.id} and container {container.NAME}")
	
	max_gpu = int(get_max_gpu_number(machine.id) or 0)
	try:
		gl = getattr(container, 'GPU_LIST', []) or []
	except Exception:
		gl = []
	mtype = None
	try:
		mtype = machine.machine_type.value if hasattr(machine.machine_type, 'value') else str(getattr(machine, 'machine_type', '')).upper()
	except Exception:
		mtype = str(getattr(machine, 'machine_type', '')).upper()
	if str(mtype).upper() != 'GPU':
		try:
			container.GPU_LIST = []
		except Exception:
			pass
		return

	if len(gl) > max_gpu:
		e = ValueError(f"Requested GPU count {len(gl)} exceeds machine GPU count {max_gpu}")
		setattr(e, 'error_reason', 'invalid_config')
		raise e
	for gid in gl:
		try:
			gi = int(gid)
		except Exception:
			err = ValueError(f"Invalid GPU id in GPU_LIST: {gid}")
			setattr(err, 'error_reason', 'invalid_config')
			raise err
		if gi < 0 or gi >= max_gpu:
			err = ValueError(f"GPU id {gi} out of range for machine with {max_gpu} GPUs")
			setattr(err, 'error_reason', 'invalid_config')
			raise err


def validate_swap_request(machine: Machine, container: Container_info) -> int:
	try:
		requested_swap = int(getattr(container, 'SWAP_MEMORY', getattr(container, 'swap_memory', 0) or 0))
	except Exception:
		err = ValueError(f"swap_memory must be an integer: {getattr(container, 'SWAP_MEMORY', None)}")
		setattr(err, 'error_reason', 'invalid_config')
		raise err
	machine_max_swap = int(get_max_swap_gb(machine.id) or 0)
	if requested_swap < 0 or requested_swap > machine_max_swap:
		err = ValueError(f"Requested swap_memory {requested_swap}GB out of allowed range (0-{machine_max_swap} GB)")
		setattr(err, 'error_reason', 'invalid_config')
		raise err
	return requested_swap


def validate_cpu_request(machine: Machine, container: Container_info) -> int:
	try:
		requested_cpus = int(getattr(container, 'CPU_NUMBER', getattr(container, 'cpu_number', 0) or 0))
	except Exception:
		err = ValueError(f"cpu_number must be an integer: {getattr(container, 'CPU_NUMBER', None)}")
		setattr(err, 'error_reason', 'invalid_config')
		raise err

	machine_max_cpus = int(get_max_cpu_core_number(machine.id) or 0)

	if requested_cpus <= 0:
		err = ValueError(f"Requested cpu_number must be > 0: {requested_cpus}")
		setattr(err, 'error_reason', 'invalid_config')
		raise err
	if requested_cpus > machine_max_cpus:
		err = ValueError(f"Requested cpu_number {requested_cpus} exceeds machine cpu cores {machine_max_cpus}")
		setattr(err, 'error_reason', 'invalid_config')
		raise err
	return requested_cpus


def validate_memory_request(machine: Machine, container: Container_info) -> int:
	try:
		requested_memory = int(getattr(container, 'MEMORY', getattr(container, 'memory', 0) or 0))
	except Exception:
		err = ValueError(f"memory must be an integer (GB): {getattr(container, 'MEMORY', None)}")
		setattr(err, 'error_reason', 'invalid_config')
		raise err

	machine_memory_gb = int(get_max_memory_gb(machine.id) or 0)

	if requested_memory <= 0:
		err = ValueError(f"Requested memory must be > 0 GB: {requested_memory}")
		setattr(err, 'error_reason', 'invalid_config')
		raise err
	if requested_memory > machine_memory_gb:
		err = ValueError(f"Requested memory {requested_memory}GB exceeds machine memory {machine_memory_gb}GB")
		setattr(err, 'error_reason', 'invalid_config')
		raise err
	return requested_memory


def validate_names_and_lengths(container: Container_info, public_key: str | None = None) -> None:
	# length limits
	if getattr(container, 'NAME', None) and len(container.NAME) > 115:
		raise ValueError(f"container name too long (max 115): length={len(container.NAME)}")
	if getattr(container, 'image', None) and len(container.image) > 195:
		raise ValueError(f"container image name too long (max 195): length={len(container.image)}")
	if public_key and len(public_key) > 495:
		raise ValueError(f"public_key too long (max 495): length={len(public_key)}")
	# name pattern
	import re
	if not re.fullmatch(r'[A-Za-z0-9_]+', getattr(container, 'NAME', '') or ''):
		raise ValueError(f"invalid container name: '{getattr(container, 'NAME', '')}'. Allowed characters: A-Z a-z 0-9 _")


def check_duplicate_container_name(container_name: str, machine_id: int) -> None:
	try:
		existing_id = get_id_by_name_machine(container_name=container_name, machine_id=machine_id)
		if existing_id:
			orig_msg = f"container name '{container_name}' already exists on machine {machine_id} (id={existing_id})"
			raise IntegrityError(orig_msg, params=None, orig=orig_msg)
	except IntegrityError:
		raise
	except Exception:
		# Log and ignore DB lookup errors at validation level
		return

