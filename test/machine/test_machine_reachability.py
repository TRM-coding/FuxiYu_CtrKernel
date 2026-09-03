"""机器可达性统一入口（TTL 缓存）测试。"""

from ...services import machine_tasks


def _reset_cache():
    machine_tasks._reach_cache.clear()


def test_get_machine_reachable_hits_cache(monkeypatch):
    _reset_cache()
    calls = {"n": 0}

    def _probe(mid, timeout=2.0):
        calls["n"] += 1
        return True

    monkeypatch.setattr(machine_tasks, "is_machine_online_remote", _probe)

    assert machine_tasks.get_machine_reachable(1) is True
    assert machine_tasks.get_machine_reachable(1) is True
    assert calls["n"] == 1  # 第二次命中缓存，不再探测
    _reset_cache()


def test_get_machine_reachable_expires_after_ttl(monkeypatch):
    _reset_cache()
    t = {"now": 0.0}
    monkeypatch.setattr(machine_tasks.time, "time", lambda: t["now"])
    calls = {"n": 0}

    def _probe(mid, timeout=2.0):
        calls["n"] += 1
        return False

    monkeypatch.setattr(machine_tasks, "is_machine_online_remote", _probe)

    assert machine_tasks.get_machine_reachable(1) is False
    assert machine_tasks.get_machine_reachable(1) is False
    assert calls["n"] == 1

    # 越过 TTL 后重新探测
    t["now"] = machine_tasks.REACH_CACHE_TTL_SEC + 1
    assert machine_tasks.get_machine_reachable(1) is False
    assert calls["n"] == 2
    _reset_cache()


def test_peek_returns_none_when_empty():
    _reset_cache()
    assert machine_tasks._peek_machine_reachable(999) is None


def test_set_and_peek_roundtrip(monkeypatch):
    _reset_cache()
    t = {"now": 100.0}
    monkeypatch.setattr(machine_tasks.time, "time", lambda: t["now"])
    machine_tasks._set_machine_reachable(7, True)
    assert machine_tasks._peek_machine_reachable(7) is True
    _reset_cache()
