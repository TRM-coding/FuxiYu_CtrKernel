"""restore._resolve_restore_container_name 的单元测试。

恢复时原名可能已被新容器占用（软删即释放名字，同名可再建），此处决定复活后的容器叫什么：
原名可用则沿用，否则改名 {原名}_{YYYYMMDD}_{原 id}，再冲突则追加 _2、_3……；容器名列宽 115。
"""

from datetime import datetime

import pytest

from ..factories import create_container, create_machine
from ...services.container_module.exceptions import NodeServiceError
from ...services.container_module.restore import _resolve_restore_container_name

REMOVED_AT = datetime(2026, 9, 10, 12, 0, 0)


def test_keeps_original_name_when_free(db_session):
    machine = create_machine()
    db_session.commit()

    name, renamed = _resolve_restore_container_name("ghost_c", machine.id, 42, REMOVED_AT)

    assert (name, renamed) == ("ghost_c", False)


def test_keeps_original_name_when_held_by_its_own_record(db_session):
    """同名行就是待恢复的那一条（原 id 相同）→ 不算冲突，沿用原名。"""
    machine = create_machine()
    container = create_container(machine=machine, name="self_c")
    db_session.commit()

    name, renamed = _resolve_restore_container_name("self_c", machine.id, container.id, REMOVED_AT)

    assert (name, renamed) == ("self_c", False)


def test_renames_with_removed_date_and_original_id_when_taken(db_session):
    """名字被别的容器占用 → 改成 {原名}_20260910_{原 id}，并回报 renamed=True 供审计。"""
    machine = create_machine()
    create_container(machine=machine, name="taken_c")
    db_session.commit()

    name, renamed = _resolve_restore_container_name("taken_c", machine.id, 42, REMOVED_AT)

    assert renamed is True
    assert name == "taken_c_20260910_42"


def test_uses_current_date_when_removed_at_missing(db_session):
    machine = create_machine()
    create_container(machine=machine, name="taken_c")
    db_session.commit()

    name, renamed = _resolve_restore_container_name("taken_c", machine.id, 42, None)

    assert renamed is True
    assert name == f"taken_c_{datetime.utcnow().strftime('%Y%m%d')}_42"


def test_retries_with_counter_when_renamed_name_is_also_taken(db_session):
    """改名后的候选名也被占 → 追加递增计数，直到找到空位。"""
    machine = create_machine()
    create_container(machine=machine, name="taken_c")
    create_container(machine=machine, name="taken_c_20260910_42")
    db_session.commit()

    name, renamed = _resolve_restore_container_name("taken_c", machine.id, 42, REMOVED_AT)

    assert (name, renamed) == ("taken_c_20260910_42_2", True)


def test_long_name_is_truncated_to_column_width(db_session):
    """超长原名按后缀长度截断，结果不超过 115（容器名列宽）。"""
    machine = create_machine()
    long_name = "c" * 120
    create_container(machine=machine, name=long_name)
    db_session.commit()

    name, renamed = _resolve_restore_container_name(long_name, machine.id, 42, REMOVED_AT)

    assert renamed is True
    assert len(name) <= 115
    assert name.endswith("_20260910_42")


def test_raises_when_original_name_is_free_but_other_machine_holds_it(db_session):
    """机器维度的名字空间：别的机器占用同名不影响本机恢复。"""
    machine = create_machine()
    other_machine = create_machine()
    create_container(machine=other_machine, name="shared_c")
    db_session.commit()

    name, renamed = _resolve_restore_container_name("shared_c", machine.id, 42, REMOVED_AT)

    assert (name, renamed) == ("shared_c", False)


def test_raises_after_exhausting_candidates(db_session, monkeypatch):
    """候选位全被占满（99 次）→ 抛 container_exists，不静默改名成第 100 个。"""
    machine = create_machine()
    db_session.commit()

    import FuxiYu_CtrKernel.services.container_module.restore as restore_mod

    monkeypatch.setattr(
        restore_mod.containers_repo, "get_id_by_name_machine",
        lambda container_name, machine_id, session: 999,
    )

    with pytest.raises(NodeServiceError) as excinfo:
        _resolve_restore_container_name("taken_c", machine.id, 42, REMOVED_AT)

    assert excinfo.value.reason == "container_exists"
