"""同机容器级角色互斥。

锁文件只作为空标记放在私有临时目录，不保存密码、角色或任何业务状态。
Linux/POSIX 用标准库 ``fcntl.flock`` 覆盖同一主机上的多个 Ctrl 进程；线程层用
``threading.RLock`` 覆盖同进程并发并支持嵌套重入。Windows 没有 ``fcntl`` 时退化为
仅线程锁，跨进程边界必须由调用方如实标注。
"""

from __future__ import annotations

import contextlib
import os
import stat
import tempfile
import threading
from pathlib import Path

try:  # POSIX only
    import fcntl
except ImportError:  # pragma: no cover - Windows dev
    fcntl = None

CROSS_PROCESS_LOCK_SUPPORTED = fcntl is not None

_THREAD_LOCKS: dict[int, threading.RLock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()
_LOCAL = threading.local()
_OPEN_FILES = set()


def _after_fork_child():
    """子进程关闭继承的描述符，不能继承父线程的重入资格。"""
    global _THREAD_LOCKS, _THREAD_LOCKS_GUARD, _LOCAL
    for marker in tuple(_OPEN_FILES):
        marker.close()
    _OPEN_FILES.clear()
    _THREAD_LOCKS = {}
    _THREAD_LOCKS_GUARD = threading.Lock()
    _LOCAL = threading.local()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork_child)


def _thread_lock(container_id: int) -> threading.RLock:
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(int(container_id), threading.RLock())


def _lock_dir() -> Path:
    base = Path(tempfile.gettempdir()) / "fuxi-ctrl-role-locks"
    base.mkdir(mode=0o700, exist_ok=True)
    if os.name == "posix":
        metadata = base.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise PermissionError("role lock directory is not a private owned directory")
        os.chmod(base, 0o700)
    return base


def _lock_path(container_id: int) -> Path:
    return _lock_dir() / f"container-{int(container_id)}.lock"


def _open_lock_file(container_id: int):
    path = _lock_path(container_id)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(path, flags, 0o600)
    return os.fdopen(fd, "r+b", buffering=0)


@contextlib.contextmanager
def container_role_lock(container_id: int):
    """串行化同一容器的角色变更；同线程嵌套重入不重复加 OS 锁。"""

    cid = int(container_id)
    with _thread_lock(cid):
        depths = getattr(_LOCAL, "depths", None)
        if depths is None:
            depths = _LOCAL.depths = {}
        depth = depths.get(cid, 0)
        if depth:
            depths[cid] = depth + 1
            try:
                yield
            finally:
                depths[cid] = depth
            return

        lock_file = None
        depths[cid] = 1
        try:
            if CROSS_PROCESS_LOCK_SUPPORTED:
                lock_file = _open_lock_file(cid)
                _OPEN_FILES.add(lock_file)
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                if lock_file is not None and not lock_file.closed:
                    try:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    finally:
                        lock_file.close()
            finally:
                _OPEN_FILES.discard(lock_file)
                depths.pop(cid, None)
