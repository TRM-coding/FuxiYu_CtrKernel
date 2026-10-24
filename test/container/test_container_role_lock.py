"""容器角色锁的文件边界与 fork 继承回归。"""
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from ...utils import container_lock


def test_thread_lock_fallback_works_without_fcntl(monkeypatch):
    monkeypatch.setattr(container_lock, "CROSS_PROCESS_LOCK_SUPPORTED", False)
    monkeypatch.setattr(container_lock, "fcntl", None)
    started, acquired = threading.Event(), threading.Event()

    def contender():
        started.set()
        with container_lock.container_role_lock(11804):
            acquired.set()

    with container_lock.container_role_lock(11804):
        with container_lock.container_role_lock(11804):
            worker = threading.Thread(target=contender)
            worker.start()
            assert started.wait(5)
            assert not acquired.wait(0.1)
    worker.join(5)
    assert not worker.is_alive()
    assert acquired.is_set()


@pytest.mark.skipif(os.name != "posix", reason="POSIX 文件锁边界")
def test_role_lock_rejects_symlink_directory_without_chmod(tmp_path, monkeypatch):
    monkeypatch.setattr(container_lock.tempfile, "gettempdir", lambda: str(tmp_path))
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o755)
    before = outside.stat().st_mode
    (tmp_path / "fuxi-ctrl-role-locks").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        with container_lock.container_role_lock(11801):
            pytest.fail("symlink lock directory accepted")
    assert outside.stat().st_mode == before
    assert not list(outside.iterdir())


@pytest.mark.skipif(not container_lock.CROSS_PROCESS_LOCK_SUPPORTED, reason="POSIX 文件锁边界")
def test_role_lock_closes_descriptor_even_when_unlock_raises(tmp_path, monkeypatch):
    marker = (tmp_path / "marker").open("w+b")
    monkeypatch.setattr(container_lock, "_open_lock_file", lambda _cid: marker)

    def fail_unlock(_fd, operation):
        if operation == container_lock.fcntl.LOCK_UN:
            raise OSError("simulated unlock failure")

    monkeypatch.setattr(container_lock.fcntl, "flock", fail_unlock)
    with pytest.raises(OSError, match="simulated unlock failure"):
        with container_lock.container_role_lock(11802):
            pass
    assert marker.closed


@pytest.mark.skipif(not hasattr(os, "fork"), reason="POSIX fork 继承边界")
def test_forked_child_does_not_inherit_parent_reentrancy_or_lock_descriptor():
    # 独立解释器内 fork，避免在 pytest 进程复制线程/数据库夹具。
    script = r'''
import os, select, sys
from FuxiYu_CtrKernel.utils.container_lock import container_role_lock
read_fd, write_fd = os.pipe()
child = None
try:
    with container_role_lock(11803):
        child = os.fork()
        if child == 0:
            os.close(read_fd)
            try:
                with container_role_lock(11803):
                    os.write(write_fd, b"acquired")
            finally:
                os._exit(0)
        os.close(write_fd)
        assert not select.select([read_fd], [], [], 0.25)[0], "child bypassed parent's lock"
    assert select.select([read_fd], [], [], 5)[0], "child did not acquire after release"
    assert os.read(read_fd, 20) == b"acquired"
finally:
    os.close(read_fd)
    if child:
        os.waitpid(child, 0)
'''
    env = {**os.environ, "PYTHON_DOTENV_DISABLED": "1"}
    project_parent = str(Path(__file__).resolve().parents[3])
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [project_parent, env.get("PYTHONPATH")]))
    completed = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=15,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
