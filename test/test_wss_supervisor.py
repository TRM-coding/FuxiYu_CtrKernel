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


def test_arm_parent_death_signal_requires_supervision_marker(monkeypatch):
    """孤儿防护只在受 run.py 看护时启用：无标记时连 prctl 都不碰。"""
    import ctypes as ctypes_module

    from FuxiYu_CtrKernel import run_node_links

    loaded = []
    monkeypatch.setattr(ctypes_module, "CDLL", lambda name: loaded.append(name) or _FakeLibc())
    monkeypatch.delenv("FUXI_CTRL_SUPERVISED", raising=False)
    run_node_links._arm_parent_death_signal()
    assert loaded == []


def test_arm_parent_death_signal_arms_prctl_and_stays(monkeypatch):
    """受看护且父进程存活：注册 PDEATHSIG（SIGTERM），不退出。"""
    import ctypes as ctypes_module

    from FuxiYu_CtrKernel import run_node_links

    calls = []
    monkeypatch.setattr(ctypes_module, "CDLL", lambda name: _FakeLibc(calls))
    monkeypatch.setenv("FUXI_CTRL_SUPERVISED", "1")
    monkeypatch.setattr(run_node_links.os, "getppid", lambda: 4242)
    exited = []
    monkeypatch.setattr(run_node_links.os, "_exit", lambda code: exited.append(code))
    run_node_links._arm_parent_death_signal()
    assert calls and calls[0][0] == 1  # PR_SET_PDEATHSIG
    assert exited == []


def test_arm_parent_death_signal_exits_when_already_orphaned(monkeypatch):
    """父进程在 prctl 注册与核对之间死亡（竞态）：PPID 已归 init 时直接退出。"""
    import ctypes as ctypes_module

    from FuxiYu_CtrKernel import run_node_links

    monkeypatch.setattr(ctypes_module, "CDLL", lambda name: _FakeLibc())
    monkeypatch.setenv("FUXI_CTRL_SUPERVISED", "1")
    monkeypatch.setattr(run_node_links.os, "getppid", lambda: 1)
    exited = []
    monkeypatch.setattr(run_node_links.os, "_exit", lambda code: exited.append(code))
    run_node_links._arm_parent_death_signal()
    assert exited == [0]


class _FakeLibc:
    def __init__(self, calls=None):
        self.calls = calls

    def prctl(self, *args):
        if self.calls is not None:
            self.calls.append(args)
        return 0


def test_pump_child_output_copies_lines_verbatim():
    """链路子进程的输出**原样**进主日志：不改写、不筛选，stdout/stderr 保持行序。

    回归锁：这里曾经是"两个进程各持一个 TimedRotatingFileHandler 写同一个 ctrl.log"——
    谁先轮转就把公共文件改名，另一个进程的 fd 跟着 inode 走，于是访问日志从 ctrl.log
    消失、文件名与内容还错位一天。输出必须只走这一条路（主进程唯一的 handler）。

    子进程用 `flush=True`：走管道时 Python 的 stdout 是**块缓冲**，不刷就看不到（真实
    链路进程的日志全在 stderr 上，行缓冲，不存在这个问题）。
    """
    import logging

    from FuxiYu_CtrKernel.utils.logging_config import pump_child_output

    captured = []

    class _Capture(logging.Handler):
        def emit(self, record):
            captured.append(record.getMessage())

    logger = logging.getLogger("FuxiYu_CtrKernel.run.wss")
    handler = _Capture()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False  # 不惊动其它测试挂在 root 上的 handler
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import sys;"
                "print('out-1', flush=True);"
                "print('err-1', file=sys.stderr, flush=True);"
                "print('out-2', flush=True)",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        pump_child_output(process)  # 读到 EOF 自然返回
    finally:
        logger.removeHandler(handler)
        logger.propagate = True

    assert captured == ["out-1", "err-1", "out-2"]
