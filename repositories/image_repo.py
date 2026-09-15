"""镜像模板仓储。

repo 只接收显式 session，负责 query/write/flush；事务由 service 统一控制。

**停用过滤的分层（2026-09 决策，务必区分）**：

- `get_by_id` / `get_by_name` 是**原语**，被业务读与管理写共用，**不过滤停用**。
  在原语上加过滤会让 `Update_image`、重新启用、seed 收敛一并失明——"停用"就变成了
  事实上的单向门，连改都改不了。
- `list_images` / `count_images` / `find_active_by_name` 是**业务读**，过滤停用。
- `update_image` / `disable_image` 是**管理写**，不过滤（否则停用行再也操作不了）。
"""

from typing import Sequence

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from ..constant import ImageStatus
from ..models.image import Image


def get_by_id(image_id: int, *, session: Session) -> Image | None:
    """按标识取行——**原语，不过滤停用**（理由见模块 docstring）。"""
    return session.get(Image, int(image_id))


def get_by_name(name: str, *, session: Session) -> Image | None:
    """按名取行——**原语，不过滤停用**。seed 收敛需要看见被停用的系统行。"""
    return session.scalars(select(Image).where(Image.name == name)).first()


def find_active_by_name(name: str, *, session: Session) -> Image | None:
    """在**未停用**的模板里按名查重。

    模板名唯一性由应用层承担（DB 已无唯一约束，见 models/image.py）：停用的模板继续
    占用名字，但不应阻止同名新建。改名路径也要用它排除"还是自己"的情形。
    """
    return session.scalars(
        select(Image).where(Image.name == name, Image.status != ImageStatus.DISABLED)
    ).first()


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
    """查询镜像概要（业务读，不含已停用）。

    - visible_image_ids=None 且 include_public=False：不过滤（资源通配者看全部）
    - 否则：可见 = 已授权 user_images 并集 + 系统内置镜像（created_by IS NULL）
    """
    stmt = (
        select(Image)
        .where(Image.status != ImageStatus.DISABLED)
        .order_by(Image.id.desc())
        .offset(offset)
        .limit(limit)
    )
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
    """统计镜像总数（业务读，不含已停用）——口径必须与 list_images 一致，
    否则会出现"总数 5、列表只有 3 条"的分页错乱。"""
    stmt = select(func.count()).select_from(Image).where(Image.status != ImageStatus.DISABLED)
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
    status: ImageStatus = ImageStatus.DRAFT,
    created_by_user_id: int | None,
    session: Session,
) -> Image:
    image = Image(
        name=name,
        description=description,
        base_image=base_image,
        dockerfile_body=dockerfile_body,
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
    allowed = {"name", "description", "base_image", "dockerfile_body", "status"}
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


def disable_image(image_id: int, *, session: Session) -> Image | None:
    """把模板置为停用（**管理写，不过滤停用**）。

    这是"移除模板"的落地方式——**不做物理删除**：容器对模板的引用必须保持完整，
    "这个容器当初构建自哪个模板"是一个事实，不因模板被撤下而消失。行保留也让
    `base_image` / `dockerfile_body` 仍可查，容器的运行基底因此不会变空。

    与 `update_image` 的关系：停用只是把 `status` 改为停用，`update_image` 本就能改
    这个字段（它在可更新白名单里），所以**重新启用**走 `update_image` 即可，无需另开接口。
    """
    image = get_by_id(image_id, session=session)
    if image is None:
        return None
    if image.status != ImageStatus.DISABLED:
        image.status = ImageStatus.DISABLED
        session.flush()
    return image
