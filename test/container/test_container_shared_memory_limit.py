"""创建容器的共享内存双重上限回归（2026-10 决策）。

后端契约（与 openspec/specs/backend--table-containers 主 SPEC 一致）：
- 共享内存 SHALL 受「机器共享上限 `max_shared_gb`」约束；
- 共享内存 SHALL 受「本次申请的 `MEMORY`」约束；
- 任一越界 → `invalid_config`，错误信息带上具体数值。

机器侧上限本身不再有固定 8GB 硬码（见 machine/test_machine_tasks_status.py），因此
本文件用 `max_shared_gb=16` 的机器证明「>8GB 的合法共享配置」在创建路径上真的可用，
同时锁住两条上限都仍然生效。
"""

import pytest

from ...repositories import containers_repo
from ...utils.Container import Container_info
from ..factories import create_machine


def _container(*, memory=24, shared_memory=16, cpu_number=2):
    return Container_info(
        gpu_list=[],
        cpu_number=cpu_number,
        memory=memory,
        shared_memory=shared_memory,
        name="shared_limit_container",
        image="ubuntu:22.04",
    )


def test_shared_above_8_accepted_when_within_machine_and_memory(db_session):
    """>8GB 但两条上限都没越 → 放行（机器共享 16 / 本次内存 24）。"""
    machine = create_machine(max_shared_gb=16, max_memory_gb=32)

    assert containers_repo.validate_shared_request(
        machine, _container(memory=24, shared_memory=16), session=db_session
    ) == 16


def test_shared_above_machine_limit_rejected(db_session):
    """机器共享上限 16、本次内存 32、申请 20 → 越机器上限，即使未超内存也拒绝。"""
    machine = create_machine(max_shared_gb=16, max_memory_gb=32)

    with pytest.raises(ValueError, match="out of allowed range") as excinfo:
        containers_repo.validate_shared_request(
            machine, _container(memory=32, shared_memory=20), session=db_session
        )

    assert getattr(excinfo.value, "error_reason") == "invalid_config"
    assert "20" in str(excinfo.value)
    assert "16" in str(excinfo.value)


def test_shared_above_requested_memory_rejected(db_session):
    """机器共享上限 32、申请内存 8、共享 16 → 越本次内存，即使未超机器上限也拒绝。"""
    machine = create_machine(max_shared_gb=32, max_memory_gb=64)

    with pytest.raises(ValueError, match="cannot exceed requested memory") as excinfo:
        containers_repo.validate_shared_request(
            machine, _container(memory=8, shared_memory=16), session=db_session
        )

    assert getattr(excinfo.value, "error_reason") == "invalid_config"
    assert "16" in str(excinfo.value)
    assert "8" in str(excinfo.value)


def test_create_params_sequence_enforces_machine_limit(db_session):
    """走完整创建校验序列（创建入口）同样成立：共享 24 > 机器上限 16 → invalid_config。"""
    machine = create_machine(max_shared_gb=16, max_memory_gb=64)

    with pytest.raises(ValueError) as excinfo:
        containers_repo.validate_create_params(
            machine.id, _container(memory=32, shared_memory=24), session=db_session
        )

    assert getattr(excinfo.value, "error_reason") == "invalid_config"