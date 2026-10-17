"""select_gpu_allowance（allow_list 内最低占用选卡）纯单元测试。

不依赖真实 DB：替换 session_scope 与容器查询，按轮喂入既有占用，
观察算法随轮次的选择序列（等效轮转）。

- 机器 GPU 建模：allow_list 许可（空 = 按 gpu_number 全量回退）
- 算法：对 allow 内每张卡统计"现存容器占用数"，选占用最少、
  同占用按卡号升序的前 count 张（utils.select_gpu_allowance）。
"""

import contextlib
from types import SimpleNamespace

import pytest

from ...services.container_module import utils


def _machine(allow=None, gpu_number=0):
    return SimpleNamespace(id=1, gpu_allow_list=allow, gpu_number=gpu_number)


def _row(chosen):
    """构造一个"现存容器"假行。"""
    return SimpleNamespace(gpu_chosen_list=list(chosen))


@pytest.fixture()
def allocator(monkeypatch):
    """每轮从 existing 读取占用（模拟创建前读 DB），轮次内可追加占用。"""
    existing = []
    monkeypatch.setattr(utils, "session_scope", lambda **kw: contextlib.nullcontext())

    def _fake_list_containers(*args, **kwargs):
        return list(existing)

    monkeypatch.setattr(utils.containers_repo, "list_containers", _fake_list_containers)

    def _pick(machine, count):
        chosen = utils.select_gpu_allowance(machine, count)
        existing.append(_row(chosen))
        return list(chosen)

    return _pick


def test_single_gpu_always_picks_0(allocator):
    """单卡机器（dev 现状 gpu_number=1 allow=[0]）：无论几轮都选 [0]。"""
    machine = _machine(allow=[0], gpu_number=1)
    assert [allocator(machine, 1) for _ in range(5)] == [[0]] * 5


def test_round_robin_rotates_over_four_cards(allocator):
    """四卡空机连建 6 个单卡容器 → 0,1,2,3,0,1（轮转一圈回到起点）。"""
    machine = _machine(allow=[0, 1, 2, 3], gpu_number=4)
    picks = [allocator(machine, 1)[0] for _ in range(6)]
    assert picks == [0, 1, 2, 3, 0, 1]


def test_multi_count_rounds_rotate_in_groups(allocator):
    """每次申请 2 卡连建 3 轮 → [0,1],[2,3],[0,1]（组内同占用按卡号升序）。"""
    machine = _machine(allow=[0, 1, 2, 3], gpu_number=4)
    assert [allocator(machine, 2) for _ in range(3)] == [[0, 1], [2, 3], [0, 1]]


def test_rotates_over_noncontiguous_allow(allocator):
    """allow 非连续/乱序 [2,5,7]：按占用优先 + 卡号升序轮转。"""
    machine = _machine(allow=[2, 5, 7], gpu_number=8)
    picks = [allocator(machine, 1)[0] for _ in range(5)]
    assert picks == [2, 5, 7, 2, 5]


def test_picks_least_used_with_existing_pressure(monkeypatch):
    """预置占用压力：GPU0 已被 3 个容器占用，再申请 2 卡 → 避开 0 选 [1,2]。"""
    existing = [_row([0]), _row([0]), _row([0, 2])]
    monkeypatch.setattr(utils, "session_scope", lambda **kw: contextlib.nullcontext())
    monkeypatch.setattr(
        utils.containers_repo,
        "list_containers",
        lambda *a, **k: list(existing),
    )
    machine = _machine(allow=[0, 1, 2, 3], gpu_number=4)
    # 占用：g0=3, g1=0, g2=1, g3=0 → 最少的是 1、3
    assert utils.select_gpu_allowance(machine, 2) == [1, 3]


def test_zero_or_empty_request_returns_empty(allocator):
    machine = _machine(allow=[0, 1], gpu_number=2)
    assert allocator(machine, 0) == []
    machine_none = _machine(allow=None, gpu_number=0)
    assert allocator(machine_none, 1) == []


def test_allow_defaults_to_gpu_number_range(allocator):
    """allow 未配置（None）→ 回退 0..gpu_number-1。"""
    machine = _machine(allow=None, gpu_number=3)
    picks = [allocator(machine, 1)[0] for _ in range(4)]
    assert picks == [0, 1, 2, 0]


def test_skips_heavy_card_until_others_catch_up(monkeypatch):
    """allow=[1,2,4,6,9] 且卡 2 预置 3 个占用：先轮 1,4,6,9 三圈，
    等其余卡占用追平 3 后按卡号升序回到 1 → 2（纯创建无删除，不会提前回来）。"""
    existing = [_row([2]) for _ in range(3)]
    monkeypatch.setattr(utils, "session_scope", lambda **kw: contextlib.nullcontext())
    monkeypatch.setattr(
        utils.containers_repo,
        "list_containers",
        lambda *a, **k: list(existing),
    )
    machine = _machine(allow=[1, 2, 4, 6, 9], gpu_number=9)
    picks = []
    for _ in range(14):
        chosen = utils.select_gpu_allowance(machine, 1)
        picks.append(chosen[0])
        existing.append(_row(chosen))
    assert picks == [1, 4, 6, 9, 1, 4, 6, 9, 1, 4, 6, 9, 1, 2]


def test_corrupt_chosen_entries_are_ignored(monkeypatch):
    """历史脏数据（非数字 chosen）不参与占用统计，也不抛错。"""
    existing = [_row([0]), _row(["x", None])]
    monkeypatch.setattr(utils, "session_scope", lambda **kw: contextlib.nullcontext())
    monkeypatch.setattr(
        utils.containers_repo,
        "list_containers",
        lambda *a, **k: list(existing),
    )
    machine = _machine(allow=[0, 1], gpu_number=2)
    # g0 被占 1 次、g1 0 次（脏行不计）→ 应选 g1
    assert utils.select_gpu_allowance(machine, 1) == [1]
