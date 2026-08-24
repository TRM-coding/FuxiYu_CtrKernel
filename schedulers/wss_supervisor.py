"""WSS 接收进程看护（数据通路对账契约 C9）：主进程对 WSS 存活负责。

run.py 拉起 run_wss.py 子进程后由本模块看护：意外退出即重启（连续 spawn 异常指数退避），
主进程退出（stop_event）时停止重启并交还由调用方收尾子进程。
"""

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

# 看护轮询间隔（秒）
WATCH_POLL_SECONDS = float(os.getenv("CTRL_WSS_WATCH_POLL_SECONDS", "1"))
# 连续 spawn 异常的指数退避上限（秒）
RESPAWN_BACKOFF_MAX = 10.0


def watch_wss_process(process_ref: list, stop_event: threading.Event, spawn_fn) -> None:
    """看护 WSS 接收子进程：意外退出（poll() 非 None）→ 重启。

    process_ref 是单元素 list 持有当前 Popen，main 线程与看护线程共享（start 时写入、
    重启时更新）；spawn_fn() 返回新 Popen（返回 None 表示未启用，停止看护）。
    """
    backoff = 1.0
    while not stop_event.is_set():
        time.sleep(WATCH_POLL_SECONDS)
        proc = process_ref[0]
        if proc is None or proc.poll() is None:
            continue  # 未启用或存活
        if stop_event.is_set():
            break
        logger.warning("WSS receiver exited (code=%s); respawning", proc.returncode)
        try:
            new_proc = spawn_fn()
            if new_proc is None:
                logger.warning("WSS receiver respawn returned None (disabled?); stop watching")
                return
            process_ref[0] = new_proc
            backoff = 1.0
        except Exception as e:
            logger.warning("WSS receiver respawn failed: %s (retry in %.0fs)", e, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, RESPAWN_BACKOFF_MAX)
