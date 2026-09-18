"""MachineImage 仓储层：Ctrl 派发到各机器的构建记录。

repo 只接收显式 session，负责查询、写入和 flush；事务边界由 service/tasks
的 session_scope 决定。

**检索一律按 `(machine_id, image_id)` 复合键**：标签只作为值随行读回，MUST NOT 出现在
任何查询谓词里。标签是派生值（归属标识 + 版本戳），拿它检索等于让派生值承担身份——
格式一变即断，正是本变更一路在消灭的模式。

**本模块刻意没有删除函数。** 模板更新会让 `image_tag` 变化，写点按复合键改写同一行；
写一条删除路径只会引入一个将来容易被遗忘的维护入口，并销毁"这个 (机器, 模板) 被派发过"
这个事实。
"""

from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..extensions import db
from ..models.machine_image import MachineImage


def get_by_machine_image(
    machine_id: int, image_id: int, *, session: Session
) -> MachineImage | None:
    """按 `(machine_id, image_id)` 复合键取该机器上该模板的行。

    这是本表**唯一**的检索方式：标签是派生值，MUST NOT 进查询谓词。
    """
    stmt = select(MachineImage).where(
        MachineImage.machine_id == int(machine_id),
        MachineImage.image_id == int(image_id),
    )
    return session.scalars(stmt).first()


def record_dispatch(
    machine_id: int, image_id: int, image_tag: str, *, session: Session
) -> MachineImage:
    """登记/刷新一次构建派发；同一 (machine_id, image_id) 只保留一行。

    存在即改写 `image_tag` 与 `created_at`（模板更新后新标签要落到同一行，否则撞复合
    唯一键）。**`created_at` 因此是"最近一次派发的时刻"，不是首次**——它是
    `services/image_tasks.format_image_build_tag` 新鲜度预检查的判据：这一行晚于模板的
    最后一次修改，才说明行里的标签就是当前模板版本产出的。
    """
    existing = get_by_machine_image(machine_id, image_id, session=session)
    if existing is not None:
        existing.image_tag = image_tag
        existing.created_at = db.func.now()
        session.flush()
        return existing

    # created_at 显式给 db.func.now() 而不吃 Python 时钟：它与判新鲜时要对比的
    # `images.updated_at` 必须**同源**。两个时钟（app 与 DB 主机）若不同步，DB 时钟偏慢
    # 就会把一个早于本次模板修改的行判成新鲜——正是要杜绝的方向。
    row = MachineImage(
        machine_id=int(machine_id),
        image_id=int(image_id),
        image_tag=image_tag,
        created_at=db.func.now(),
    )
    session.add(row)
    session.flush()
    return row


def list_by_machine(machine_id: int, *, session: Session) -> Sequence[MachineImage]:
    """某台机器上派发过的全部构建（观测用，不参与任何决策）。"""
    return list(
        session.scalars(
            select(MachineImage)
            .where(MachineImage.machine_id == int(machine_id))
            .order_by(MachineImage.id)
        ).all()
    )
