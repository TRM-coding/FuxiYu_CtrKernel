"""WSS 接收进程看护测试（数据通路对账契约 C9：主进程对 WSS 存活负责）。"""

import subprocess
import sys
import threading
import time

from FuxiYu_CtrKernel.schedulers import wss_supervisor


class _FakeProc:
    def __init__(self, polls, exit_code=3):
        self._polls = list(polls)
        self.returncode = exit_code

    def poll(self):
        return self._polls.pop(0) if self._polls else self.returncode


def test_watch_wss_process_respawns_on_unexpected_exit(monkeypatch):
    spawned = []

    def _spawn():
        proc = _FakeProc([None, None, None])  # 新进程先存活 3 轮
        spawned.append(proc)
        return proc

    monkeypatch.setattr(wss_supervisor, "WATCH_POLL_SECONDS", 0.05)

    stop_event = threading.Event()
    process_ref = [_FakeProc([None, None])]  # 初始进程存活 2 轮后退出
    thread = threading.Thread(
        target=wss_supervisor.watch_wss_process,
        args=(process_ref, stop_event, _spawn),
        daemon=True,
    )
    thread.start()

    deadline = time.time() + 5
    while len(spawned) == 0 and time.time() < deadline:
        time.sleep(0.05)
    stop_event.set()
    thread.join(timeout=2)

    assert len(spawned) == 1
    assert process_ref[0] is spawned[0]  # ref 已指向新进程


def test_watch_wss_process_does_not_restart_when_stopped(monkeypatch):
    calls = []

    def _spawn():
        calls.append("spawn")
        return _FakeProc([None])

    monkeypatch.setattr(wss_supervisor, "WATCH_POLL_SECONDS", 0.05)

    stop_event = threading.Event()
    process_ref = [None]  # 未启用（CTRL_WSS_ENABLED=0 时）
    thread = threading.Thread(
        target=wss_supervisor.watch_wss_process,
        args=(process_ref, stop_event, _spawn),
        daemon=True,
    )
    thread.start()

    time.sleep(0.2)
    stop_event.set()
    thread.join(timeout=2)

    assert calls == []  # 未启用 → 永不 spawn


def test_watch_wss_process_real_subprocess_respawn(monkeypatch):
    """真实子进程验证（契约 C9）：杀死子进程 → supervisor 自动重启；stop_event 停止看护。

    用真实 Popen 而非 fake——验证的是 OS 级进程生命周期，不是 mock 语义。
    """
    monkeypatch.setattr(wss_supervisor, "WATCH_POLL_SECONDS", 0.05)

    spawned = []

    def _spawn():
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1000)"])
        spawned.append(proc)
        return proc

    stop_event = threading.Event()
    process_ref = [_spawn()]
    thread = threading.Thread(
        target=wss_supervisor.watch_wss_process,
        args=(process_ref, stop_event, _spawn),
        daemon=True,
    )
    thread.start()

    try:
        # 等看护就绪后杀死第一个子进程 → 应被重启
        time.sleep(0.3)
        spawned[0].kill()
        deadline = time.time() + 5
        while len(spawned) < 2 and time.time() < deadline:
            time.sleep(0.05)
        assert len(spawned) == 2, f"首次重启未发生: spawned={len(spawned)}"
        assert process_ref[0] is spawned[1]
        assert spawned[0].poll() is not None  # 旧进程已死
        assert spawned[1].poll() is None      # 新进程存活

        # 再杀一次 → 再重启（循环重启契约）
        spawned[1].kill()
        deadline = time.time() + 5
        while len(spawned) < 3 and time.time() < deadline:
            time.sleep(0.05)
        assert len(spawned) == 3, f"二次重启未发生: spawned={len(spawned)}"
        assert process_ref[0] is spawned[2]
        assert spawned[2].poll() is None
    finally:
        stop_event.set()
        thread.join(timeout=2)
        for proc in spawned:
            if proc.poll() is None:
                proc.kill()
