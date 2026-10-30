"""容器名唯一性的归属（2026-09 决策）。

软删要求「删掉即释放名字」，而 UNIQUE(name, machine_id) 会让已删行继续占名。
曾经为此引入派生列 active_name 做局部唯一，事后评估成本高于收益，整套卸除。
现在唯一性只由两层承担：

1. **Node 侧 docker daemon** —— 真正的守卫。容器名在单机 daemon 内唯一，且创建链路是
   「请求 Node → 成功才落库」，竞态被拒时失败发生在落库之前，不会留下重复行。
2. **`check_duplicate_container_name`** —— 只负责在活容器集合（name + machine_id + is_valid）
   内提前拦下并给出可读的 409。

DB 层不再建任何 name 唯一约束。本文件的第 3 个用例就是防止有人把约束加回去：
加回去不会报错，只会让「软删后同名重建」静默失效。
"""

import pytest
from sqlalchemy import UniqueConstraint
from sqlalchemy.exc import IntegrityError

from ...models.containers import Container
from ...repositories import containers_repo
from ..factories import create_container, create_machine


def test_name_reusable_after_soft_delete(app, db_session):
    """软删后同名可在同机器重建 —— 这是卸掉 DB 唯一约束的根本原因。"""
    machine = create_machine()
    gone = create_container(machine=machine, name="reusable_name")
    containers_repo.delete_container(gone.id, session=db_session, deleted_trigger="api")
    db_session.commit()

    revived = create_container(machine=machine, name="reusable_name")
    db_session.commit()

    assert revived.id != gone.id
    db_session.expire_all()
    assert containers_repo.get_id_by_name_machine(
        "reusable_name", machine.id, session=db_session,
    ) == revived.id


def test_live_duplicate_name_is_rejected_by_code_check(app, db_session):
    """活容器重名仍被代码那道拦下（并给出可读的 409 依据）。"""
    machine = create_machine()
    create_container(machine=machine, name="taken_name")
    db_session.commit()

    with pytest.raises(IntegrityError):
        containers_repo.check_duplicate_container_name("taken_name", machine.id, session=db_session)


def test_same_name_on_different_machines_is_allowed(app, db_session):
    """作用域是「每机器」，不是全局。"""
    first = create_container(machine=create_machine(), name="shared_name")
    second = create_container(machine=create_machine(), name="shared_name")
    db_session.commit()

    assert first.id != second.id


def test_model_declares_no_unique_name_constraint(app, db_session):
    """锁住决策：模型上不得出现任何覆盖 name 的唯一约束/唯一索引。

    加回去不会报错，只会让 test_name_reusable_after_soft_delete 静默失效——
    那条用例是唯一会拦住你的地方，所以这里再显式锁一道，让失败信息直指原因。
    """
    unique_constraints = [
        constraint
        for constraint in Container.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    ]
    assert unique_constraints == [], (
        "容器名唯一性由 Node 侧 docker 承担，DB 层不得再加唯一约束："
        "UNIQUE(name, ...) 会让软删行继续占名，破坏「删掉即释放名字」"
    )

    for index in Container.__table__.indexes:
        if not index.unique:
            continue
        column_names = {column.name for column in index.columns}
        assert "name" not in column_names, (
            f"唯一索引 {index.name} 覆盖了 name，同样会破坏软删后的名字重用"
        )
