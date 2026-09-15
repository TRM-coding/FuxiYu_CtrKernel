"""MachineImage 仓储层：Ctrl 向各机器派发过的构建记录。

repo 只接收显式 session，负责查询、写入和 flush；事务边界由 service/tasks
的 session_scope 决定。

**本模块刻意没有删除函数。** 记录表达的是派发历史——模板更新会让镜像标签本身变化，
从而自然产生新行，旧行作为历史保留。写一条删除路径只会引入一个将来容易被遗忘的
维护入口，并销毁审计线索（"我们请求了 5 次都没建成"正是最该看见的信号）。
"""

from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.machine_image import MachineImage


def record_dispatch(machine_id: int, image_tag: str, *, session: Session) -> MachineImage:
    """登记一次构建派发；同一 (machine_id, image_tag) 只保留一行。

    幂等：已存在则原样返回，不更新时间戳——它记的是"第一次请求"这件事。
    """
    stmt = select(MachineImage).where(
        MachineImage.machine_id == int(machine_id),
        MachineImage.image_tag == image_tag,
    )
    existing = session.scalars(stmt).first()
    if existing is not None:
        return existing

    row = MachineImage(machine_id=int(machine_id), image_tag=image_tag)
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
