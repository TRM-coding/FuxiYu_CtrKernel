"""MachineImage 仓储层：某台机器上、某份模板的制品是哪一版。

repo 只接收显式 session，负责查询、写入和 flush；事务边界由 service/tasks
的 session_scope 决定。

**检索一律按 `(machine_id, image_id)` 复合键。** `image_tag` 只作**值**读出，
MUST NOT 进任何查询谓词、MUST NOT 参与身份判定。

**本模块只有一个写入口，且是"有行即返回"**：一行就是"这台机器上那个制品"，就地改写它
等于凭空换版本、把宿主机上已有的制品变成孤儿。要换代只有一条路——
`services/image_tasks.Update_image` 在模板变更时**删掉整行**，让下次派发重新插入。
"""

import datetime as dt
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.machine_image import MachineImage


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
    *,
    session: Session,
) -> MachineImage:
    """把"这台机器上这份模板该用哪条标签"写进缓存；**已存在则原样返回，不做任何改写**。

    两列一起写：`image_tag` 是缓存的值本身，`created_at` 是它的版本戳。它们必须来自
    同一次解析（`services/image_tasks.resolve_image_build_tag` 的返回值），不能在写点
    另取一次 now()——版本戳要成为下一次读取时的权威值，差一微秒就会让下次算出的东西
    与库里那条对不上。

    已存在时**不改写**：那一行就是"这台机器上那个制品"，改写它等于悄悄换版本，而宿主机上
    那个制品还挂在旧标签下——它成了孤儿，且没有任何地方记得它。要换代只有一条路：
    `services/image_tasks.Update_image` 在模板变更时**整行删掉**（`delete_by_image`）。
    """
    existing = get_by_machine_image(machine_id, image_id, session=session)
    if existing is not None:
        return existing

    row = MachineImage(
        machine_id=int(machine_id),
        image_id=int(image_id),
        image_tag=image_tag,
        created_at=created_at,
    )
    session.add(row)
    session.flush()
    return row


def delete_by_image(image_id: int, *, session: Session) -> int:
    """清掉某份模板在**所有机器**上的版本记录；返回删掉的行数。

    这是本表唯一合法的删除入口，由 `services/image_tasks.Update_image` 在模板变更的同一
    事务里调用。语义是"这台机器上那份制品已经不是这一版了"——下次派发重新插入、拿到新的
    `created_at`、算出新的标签，宿主机因此必然重建。

    刻意"宁可多删"：模板改名、改描述这类不动配方的编辑也会触发重建。代价是几台机器各重建
    一次；换来的是**不可能漏删**——漏删会让模板改了而机器不重建，那是静默的、事后无从发现
    的错。
    """
    rows = list(session.scalars(
        select(MachineImage).where(MachineImage.image_id == int(image_id))
    ).all())
    for row in rows:
        session.delete(row)
    session.flush()
    return len(rows)


def list_by_machine(machine_id: int, *, session: Session) -> Sequence[MachineImage]:
    """某台机器上全部有记录的 (模板, 版本)（观测用，不参与任何决策）。"""
    return list(
        session.scalars(
            select(MachineImage)
            .where(MachineImage.machine_id == int(machine_id))
            .order_by(MachineImage.id)
        ).all()
    )
