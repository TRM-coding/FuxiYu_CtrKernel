"""alloc 派生规格核实（2026-09）：alloc = 上层许可/真值收缩后给到下层显示的值。

设计初衷：
- 机器真值降级 → 必要时 trim 机器分配上限（sys 漂移落库，见 machine 侧 drift 测试）；
- 机器分配上限降级 → 必要时 trim 容器侧 alloc 显示（utils.derive_allocated_limits）。

本文件按规格给纯函数投喂精确输入，逐条锁定行为：
(2) container 申请 5、machine 分配上限 4 → 容器显示 4 + degraded
(3) container 申请 4、machine 分配上限 5（真值后续降为 3，DB trim 后上限 3）
    → 递进降级后容器显示 3 + degraded
(1) 机器真值降级 trim 上限：见 machine/test_machine_tasks_status.py 的 drift 测试
    （本文件以 (3) 的链式用例衔接两层）。
"""

from types import SimpleNamespace

from ...services.container_module.utils import derive_allocated_limits


def _container(*, cpu_number=0, memory_gb=0, gpu_number=0, gpu_chosen_list=None):
    return SimpleNamespace(
        cpu_number=cpu_number,
        memory_gb=memory_gb,
        gpu_number=gpu_number,
        gpu_chosen_list=gpu_chosen_list or [],
    )


def _machine(*, max_cpu=None, max_memory=None, gpu_allow_list=None, gpu_number=0):
    return SimpleNamespace(
        max_cpu_core_number=max_cpu,
        max_memory_gb=max_memory,
        gpu_allow_list=gpu_allow_list,
        gpu_number=gpu_number,
    )


def test_spec_2_alloc_above_machine_cap_trimmed_per_resource():
    """规格(2)：container 申请 5 / machine 上限 4 → 显示 4 + degraded（逐资源）。"""
    # CPU
    alloc = derive_allocated_limits(
        _container(cpu_number=5),
        _machine(max_cpu=4, max_memory=16, gpu_allow_list=[0, 1]),
    )
    assert alloc["alloc_cpu_number"] == 4
    assert alloc["alloc_degraded"] is True
    # 内存
    alloc = derive_allocated_limits(
        _container(memory_gb=5),
        _machine(max_cpu=16, max_memory=4, gpu_allow_list=[0, 1]),
    )
    assert alloc["alloc_memory_gb"] == 4
    assert alloc["alloc_degraded"] is True
    # GPU：allow 许可 4 张，申请 5 张 → 显示 4 + degraded
    alloc = derive_allocated_limits(
        _container(gpu_number=5, gpu_chosen_list=[0, 1, 2, 3]),
        _machine(max_cpu=16, max_memory=16, gpu_allow_list=[0, 1, 2, 3]),
    )
    assert alloc["alloc_gpu_number"] == 4
    assert alloc["alloc_degraded"] is True


def test_spec_2_within_cap_not_trimmed():
    """规格(2) 对照：申请未超上限 → 原值 + 不 degraded。"""
    alloc = derive_allocated_limits(
        _container(cpu_number=4, memory_gb=4, gpu_number=2, gpu_chosen_list=[0, 1]),
        _machine(max_cpu=8, max_memory=8, gpu_allow_list=[0, 1, 2, 3]),
    )
    assert alloc == {
        "alloc_cpu_number": 4,
        "alloc_memory_gb": 4,
        "alloc_gpu_number": 2,
        "alloc_degraded": False,
    }


def test_spec_3_cascade_trim_after_machine_cap_shrink():
    """规格(3) 链式：容器申请 4、机器上限 5；机器真值降为 3 → DB trim 上限 3
    → 容器 alloc 沿新上限再 trim → 显示 3 + degraded（两层递进降级）。"""
    # 第一步：机器侧真值降级后，上限被 trim 到真值（对应 drift 落库结果 3）
    machine_after_drift = _machine(max_cpu=3, max_memory=3, gpu_allow_list=[0])
    # 第二步：容器申请 4，沿已 trim 的新上限派生
    alloc = derive_allocated_limits(
        _container(cpu_number=4, memory_gb=4, gpu_number=1, gpu_chosen_list=[0]),
        machine_after_drift,
    )
    assert alloc["alloc_cpu_number"] == 3
    assert alloc["alloc_memory_gb"] == 3
    assert alloc["alloc_gpu_number"] == 1          # 真值 3 但许可 1 张卡 → 卡不超
    assert alloc["alloc_degraded"] is True


def test_spec_1_machine_cap_trim_is_drift_side_contract():
    """规格(1) 锚点说明：机器"真值 3 vs 上限 5"的 trim 发生在 sys 漂移落库侧
    （node_comms.apply_sys_snapshot：max_* trim 到新真值），由 machine 侧 drift
    测试覆盖；本文件的 (3) 用例从"trim 完成后"的机器状态继续验证容器层。"""
    # 纯函数侧不重复实现漂移；此处仅为文档占位，断言 derive 在一致状态下的不变量：
    alloc = derive_allocated_limits(
        _container(cpu_number=3, memory_gb=3),
        _machine(max_cpu=3, max_memory=3, gpu_allow_list=[0]),
    )
    assert alloc["alloc_degraded"] is False  # 已收敛到真值，无二次降级
