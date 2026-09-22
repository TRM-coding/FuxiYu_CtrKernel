"""镜像模板仓储。

repo 只接收显式 session，负责 query/write/flush；事务由 service 统一控制。

**停用过滤的分层（2026-09 决策，务必区分）**：

- `get_by_id` / `get_by_name` 是**原语**，被业务读与管理写共用，**不过滤停用**。
  在原语上加过滤会让 `Update_image`、重新启用、seed 收敛一并失明——"停用"就变成了
  事实上的单向门，连改都改不了。
- `list_images` / `count_images` / `find_active_by_name` 是**业务读**，过滤停用。
- `update_image` / `disable_image` 是**管理写**，不过滤（否则停用行再也操作不了）。
"""

from typing import NamedTuple, Sequence

from sqlalchemy import String, and_, cast, false, func, or_, select
from sqlalchemy.orm import Session

from ..constant import ImageStatus, ImageValidRange
from ..models.image import Image
from ..models.userimage import UserImage


class ImageScope(NamedTuple):
    """镜像列表的可见性口径（由 services.image_tasks._visible_scope 造出）。

    - `unrestricted`：资源通配者（image:manage / bypass_resource）→ 不过滤，看全部
    - `mine_only`   ：编辑页"只看我的" → 只认 user_images 授权行，**不走三态**
    - 其余          ：走三态可见性（见 image_visibility_condition）
    """
    unrestricted: bool
    viewer_user_id: int | None
    granted_ids: frozenset[int]
    mine_only: bool = False


#####################
# 可见性：**一条规则，两个消费者**（SQL 谓词 + 点判定）
#
# ★ 两处必须逐字同构：列表/总数走 SQL 谓词，Can_use_image_for_container 与资源门
#   user_has_resource 走点判定。任何一处单独改都会造出"列表看得见、用不了"或反过来的
#   裂缝，而这类裂缝在页面上表现为随机 403——所以测试里锁了"两者对同一组样本结论一致"。


def image_visibility_condition(scope: ImageScope):
    """列表可见性的 SQL 谓词。unrestricted → None（调用方不加过滤）。"""
    if scope.unrestricted:
        return None
    if scope.mine_only:
        return Image.id.in_(sorted(scope.granted_ids)) if scope.granted_ids else false()
    conds = [Image.valid_range == ImageValidRange.EVERYONE]
    if scope.viewer_user_id is not None:
        # 自己建的一律看得见（PRIVATE 靠这一条，CUSTOM 下也成立——名单把人删掉也不该
        # 让人看不见自己建的东西）
        conds.append(Image.created_by_user_id == scope.viewer_user_id)
    if scope.granted_ids:
        conds.append(and_(
            Image.valid_range == ImageValidRange.CUSTOM,
            Image.id.in_(sorted(scope.granted_ids)),
        ))
    return or_(*conds)


def image_is_visible_to(image: Image | None, *, viewer_user_id: int | None, granted: bool) -> bool:
    """点判定——与 image_visibility_condition 是同一条规则（改一处必须改另一处）。"""
    if image is None:
        return False
    if image.valid_range == ImageValidRange.EVERYONE:
        return True
    if viewer_user_id is not None and image.created_by_user_id == viewer_user_id:
        return True
    return image.valid_range == ImageValidRange.CUSTOM and granted


def get_by_id(image_id: int, *, session: Session) -> Image | None:
    """按标识取行——**原语，不过滤停用**（理由见模块 docstring）。"""
    return session.get(Image, int(image_id))


def get_name_by_id(image_id: int | None, *, session: Session) -> str | None:
    """只取名字——容器出参要显示"这个容器用的是哪个模板"（原语，不过滤停用）。

    出参里**必须**由服务端解析这个名字：容器的可见性与模板的可见性是两套判据，
    用户完全可能看得见容器、却看不见它所属的模板。让前端拿着 image_id 去查模板详情
    会把"看不到模板"变成"这一栏空白甚至报错"。停用同理——历史容器该照常显示它当年用的
    模板名，停用只挡"用于新建"。
    """
    if image_id is None:
        return None
    return session.scalars(
        select(Image.name).where(Image.id == int(image_id))
    ).first()


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
    scope: ImageScope,
    session: Session,
) -> Sequence[Image]:
    """查询镜像概要（业务读，不含已停用）。可见性口径见 ImageScope。"""
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
    visibility = image_visibility_condition(scope)
    if visibility is not None:
        stmt = stmt.where(visibility)
    return list(session.scalars(stmt).all())


def count_images(
    *,
    image_search: str | None = None,
    scope: ImageScope,
    session: Session,
) -> int:
    """统计镜像总数（业务读，不含已停用）——口径必须与 list_images 一致，
    否则会出现"总数 5、列表只有 3 条"的分页错乱。

    两条查询共用 image_visibility_condition：口径一致由构造保证，不靠人记得同步。
    """
    stmt = select(func.count()).select_from(Image).where(Image.status != ImageStatus.DISABLED)
    search_filter = _search_filter(image_search)
    if search_filter is not None:
        stmt = stmt.where(search_filter)
    visibility = image_visibility_condition(scope)
    if visibility is not None:
        stmt = stmt.where(visibility)
    return int(session.scalar(stmt) or 0)


def create_image(
    *,
    name: str,
    description: str | None,
    base_image: str,
    dockerfile_body: str,
    status: ImageStatus = ImageStatus.DRAFT,
    created_by_user_id: int | None,
    entrypoint: str | None = None,
    valid_range: ImageValidRange = ImageValidRange.CUSTOM,
    session: Session,
) -> Image:
    image = Image(
        name=name,
        description=description,
        base_image=base_image,
        dockerfile_body=dockerfile_body,
        entrypoint=entrypoint,
        status=status,
        created_by_user_id=created_by_user_id,
        valid_range=valid_range,
    )
    session.add(image)
    session.flush()
    return image


def update_image(image_id: int, *, session: Session, **fields) -> bool:
    image = get_by_id(image_id, session=session)
    if image is None:
        return False
    allowed = {"name", "description", "base_image", "dockerfile_body", "entrypoint", "status"}
    # entrypoint 的 NULL 是**有意义的取值**（= 清除，回到平台默认），所以它不能走
    # 下面"None 即不提供"的通用跳过规则。其余字段照旧：None = 这次不动它。
    nullable = {"entrypoint"}
    dirty = False
    for key, value in fields.items():
        if key not in allowed:
            continue
        if value is None and key not in nullable:
            continue
        if getattr(image, key, None) != value:
            setattr(image, key, value)
            dirty = True
    if dirty:
        session.flush()
    return True


def set_valid_range(image_id: int, valid_range: ImageValidRange, *, session: Session) -> bool:
    """设置可见范围（**管理写**）。

    **不动 user_images**：切到 EVERYONE/PRIVATE 时名单原样留着，切回 CUSTOM 时它还在。
    删掉是破坏性的，而"曾经授权给谁"在切回来的那一刻就是用户期待看到的东西。
    """
    image = get_by_id(image_id, session=session)
    if image is None:
        return False
    if image.valid_range != valid_range:
        image.valid_range = valid_range
        session.flush()
    return True


def replace_image_visible_users(image_id: int, user_ids: list[int], *, session: Session) -> list[int]:
    """整组替换模板的授权名单（**set 语义**，与 auth_repo.replace_user_groups 同形）。

    返回落定的 user_id 列表（去重升序）。仅动 user_images 行，不碰 valid_range——
    "名单是什么"与"名单生不生效"是两件事，后者由 valid_range 决定。
    """
    wanted = sorted({int(uid) for uid in (user_ids or [])})
    existing = set(session.scalars(
        select(UserImage.user_id).where(UserImage.image_id == int(image_id))
    ).all())
    for user_id in wanted:
        if user_id not in existing:
            session.add(UserImage(user_id=user_id, image_id=int(image_id)))
    for user_id in existing - set(wanted):
        session.delete(session.scalars(
            select(UserImage).where(
                UserImage.image_id == int(image_id),
                UserImage.user_id == user_id,
            )
        ).first())
    session.flush()
    return wanted


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
