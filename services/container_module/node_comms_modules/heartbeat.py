from __future__ import annotations

import logging
import time

_ANOMALY_REPEAT_SECONDS = 60.0
_last_anomaly_log_at: dict[str, float] = {}
_last_container_summary: dict[str, tuple] = {}
logger = logging.getLogger(__name__)

def _log_heartbeat(key: str, level: int, message: str, *args, anomaly: bool = False) -> None:
    """按需降噪记录心跳摘要。*anomaly* 为真时受 60s 复述节流（稳态不加节流）。"""
    if not anomaly:
        logger.log(level, message, *args)
        return
    now = time.time()
    last = _last_anomaly_log_at.get(key, 0.0)
    if now - last >= _ANOMALY_REPEAT_SECONDS:
        logger.log(level, message, *args)
        _last_anomaly_log_at[key] = now

