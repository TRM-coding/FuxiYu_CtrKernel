"""Container 仓储层: 提供容器 CRUD 与用户绑定操作"""
from typing import Sequence
from ..extensions import db
from ..models.containers import Container
from ..models.user import User


def get_by_id(container_id: int) -> Container | None:
	return Container.query.get(container_id)


def list_containers(limit: int = 50, offset: int = 0, machine_id: int | None = None) -> Sequence[Container]:
	q = Container.query
	if machine_id is not None:
		q = q.filter_by(machine_id=machine_id)
	return q.order_by(Container.id).offset(offset).limit(limit).all()


def create_container(name: str, image: str, machine_id: int, status=None) -> Container:
	container = Container(name=name, image=image, machine_id=machine_id)
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


def list_users(container_id: int) -> Sequence[User]:
	container = get_by_id(container_id)
	if not container:
		return []
	return list(container.users)

