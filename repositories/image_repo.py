"""镜像模板仓储。

repo 只接收显式 session，负责 query/write/flush；事务由 service 统一控制。
"""

from typing import Sequence

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from ..constant import ImageStatus
from ..models.image import Image


def get_by_id(image_id: int, *, session: Session) -> Image | None:
    return session.get(Image, int(image_id))


def get_by_name(name: str, *, session: Session) -> Image | None:
    return session.scalars(select(Image).where(Image.name == name)).first()


def _search_filter(search: str | None):
    if not search:
        return None
    keyword = f"%{search.strip()}%"
    return or_(
        cast(Image.id, String).like(keyword),
        Image.name.like(keyword),
        Image.description.like(keyword),
        Image.base_image.like(keyword),
        cast(Image.status, String).like(keyword),
    )


def list_images(
    *,
    limit: int = 20,
    offset: int = 0,
    image_search: str | None = None,
    visible_image_ids: set[int] | None = None,
    include_public: bool = False,
    session: Session,
) -> Sequence[Image]:
    """查询镜像概要。

    - visible_image_ids=None 且 include_public=False：不过滤（资源通配者看全部）
    - 否则：可见 = 已授权 user_images 并集 + 系统内置镜像（created_by IS NULL）
    """
    stmt = select(Image).order_by(Image.id.desc()).offset(offset).limit(limit)
    search_filter = _search_filter(image_search)
    if search_filter is not None:
        stmt = stmt.where(search_filter)
    if visible_image_ids is not None or include_public:
        conds = []
        if visible_image_ids:
            conds.append(Image.id.in_(visible_image_ids))
        if include_public:
            conds.append(Image.created_by_user_id.is_(None))
        if not conds:
            return []
        stmt = stmt.where(or_(*conds))
    return list(session.scalars(stmt).all())


def count_images(
    *,
    image_search: str | None = None,
    visible_image_ids: set[int] | None = None,
    include_public: bool = False,
    session: Session,
) -> int:
    stmt = select(func.count()).select_from(Image)
    search_filter = _search_filter(image_search)
    if search_filter is not None:
        stmt = stmt.where(search_filter)
    if visible_image_ids is not None or include_public:
        conds = []
        if visible_image_ids:
            conds.append(Image.id.in_(visible_image_ids))
        if include_public:
            conds.append(Image.created_by_user_id.is_(None))
        if not conds:
            return 0
        stmt = stmt.where(or_(*conds))
    return int(session.scalar(stmt) or 0)


def create_image(
    *,
    name: str,
    description: str | None,
    base_image: str,
    dockerfile_body: str,
    pre_build: str | None,
    status: ImageStatus = ImageStatus.DRAFT,
    created_by_user_id: int | None,
    session: Session,
) -> Image:
    image = Image(
        name=name,
        description=description,
        base_image=base_image,
        dockerfile_body=dockerfile_body,
        pre_build=pre_build,
        status=status,
        created_by_user_id=created_by_user_id,
    )
    session.add(image)
    session.flush()
    return image


def update_image(image_id: int, *, session: Session, **fields) -> bool:
    image = get_by_id(image_id, session=session)
    if image is None:
        return False
    allowed = {"name", "description", "base_image", "dockerfile_body", "pre_build", "status"}
    dirty = False
    for key, value in fields.items():
        if key not in allowed or value is None:
            continue
        if getattr(image, key, None) != value:
            setattr(image, key, value)
            dirty = True
    if dirty:
        session.flush()
    return True


def delete_image(image_id: int, *, session: Session) -> Image | None:
    image = get_by_id(image_id, session=session)
    if image is None:
        return None
    session.delete(image)
    session.flush()
    return image
