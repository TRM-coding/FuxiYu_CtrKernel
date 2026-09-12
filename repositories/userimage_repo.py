"""用户-镜像授权仓储。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.userimage import UserImage


def grant_image(user_id: int, image_id: int, *, session: Session) -> UserImage:
    """给用户授予镜像资源访问权，已存在时保持幂等。"""

    existing = session.scalars(
        select(UserImage).where(
            UserImage.user_id == int(user_id),
            UserImage.image_id == int(image_id),
        )
    ).first()
    if existing is not None:
        return existing
    binding = UserImage(user_id=int(user_id), image_id=int(image_id))
    session.add(binding)
    session.flush()
    return binding


def revoke_image(user_id: int, image_id: int, *, session: Session) -> bool:
    binding = session.scalars(
        select(UserImage).where(
            UserImage.user_id == int(user_id),
            UserImage.image_id == int(image_id),
        )
    ).first()
    if binding is None:
        return False
    session.delete(binding)
    session.flush()
    return True


def list_image_ids_by_user(user_id: int, *, session: Session) -> list[int]:
    rows = session.scalars(
        select(UserImage.image_id).where(UserImage.user_id == int(user_id)).order_by(UserImage.image_id)
    ).all()
    return [int(v) for v in rows]
