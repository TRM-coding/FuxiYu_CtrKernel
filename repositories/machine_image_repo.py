"""镜像缓存仓储；按机器与模板配对读写，事务由调用方管理。"""

import datetime as dt
import logging
from typing import Sequence

from sqlalchemy import and_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models.machine_image import MachineImage

logger = logging.getLogger(__name__)


def get_by_machine_image(
    machine_id: int, image_id: int, *, session: Session
) -> MachineImage | None:
    """按 `(machine_id, image_id)` 复合键取该机器上该模板的行。"""
    stmt = select(MachineImage).where(
        MachineImage.machine_id == int(machine_id),
        MachineImage.image_id == int(image_id),
    )
    return session.scalars(stmt).first()


def record_dispatch(
    machine_id: int,
    image_id: int,
    image_tag: str,
    created_at: dt.datetime,
    recipe_fingerprint: str | None = None,
    *,
    session: Session,
) -> MachineImage:
    """登记同次解析的版本与指纹；已有版本不回退，同标签不改配方。"""
    machine_id = int(machine_id)
    image_id = int(image_id)
    for _ in range(3):
        existing = get_by_machine_image(machine_id, image_id, session=session)
        if existing is None:
            row = MachineImage(
                machine_id=machine_id,
                image_id=image_id,
                image_tag=image_tag,
                created_at=created_at,
                recipe_fingerprint=recipe_fingerprint,
            )
            session.add(row)
            try:
                session.flush()
                return row
            except IntegrityError:
                session.rollback()
                if get_by_machine_image(machine_id, image_id, session=session) is not None:
                    # 并发首次插入：让位给对方，回滚后按既有行走 CAS。
                    continue
                # 行仍不存在 ⇒ 冲突来自外键（机器/模板不成立），不是并发插入，交给上层。
                raise

        conditions = [
            MachineImage.machine_id == machine_id,
            MachineImage.image_id == image_id,
            MachineImage.created_at < created_at,
        ]
        if recipe_fingerprint is None:
            conditions.append(
                ~and_(
                    MachineImage.image_tag == image_tag,
                    MachineImage.recipe_fingerprint.is_not(None),
                )
            )
        else:
            conditions.append(
                ~and_(
                    MachineImage.image_tag == image_tag,
                    MachineImage.recipe_fingerprint.is_not(None),
                    MachineImage.recipe_fingerprint != recipe_fingerprint,
                )
            )
        result = session.execute(
            update(MachineImage)
            .where(*conditions)
            .values(
                image_tag=image_tag,
                created_at=created_at,
                recipe_fingerprint=recipe_fingerprint,
            )
            .execution_options(synchronize_session=False)
        )
        # 丢弃会话里可能过期的副本；否则下面的回读会拿到同一个未刷新的 ORM 对象。
        if existing is not None:
            session.expire(existing)
        if result.rowcount:
            return get_by_machine_image(machine_id, image_id, session=session)

        current = get_by_machine_image(machine_id, image_id, session=session)
        if current is None:
            continue
        if (
            current.image_tag == image_tag
            and current.created_at == created_at
            and current.recipe_fingerprint == recipe_fingerprint
        ):
            return current
        logger.warning(
            "machine_image write not applied (newer version or tag taken by another recipe):"
            " machine=%s image=%s tag=%s",
            machine_id, image_id, image_tag,
        )
        return current
    raise RuntimeError(
        f"machine_image record_dispatch did not converge: machine={machine_id} image={image_id}"
    )


def list_by_machine(machine_id: int, *, session: Session) -> Sequence[MachineImage]:
    """某台机器上全部 (模板, 版本)（观测与诊断用）。"""
    return list(
        session.scalars(
            select(MachineImage)
            .where(MachineImage.machine_id == int(machine_id))
            .order_by(MachineImage.id)
        ).all()
    )
