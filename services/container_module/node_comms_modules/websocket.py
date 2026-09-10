from __future__ import annotations

import asyncio
import json
import logging
from urllib.parse import parse_qs

from ....config import CommsConfig
from ....constant import MachineStatus
from ....extensions import session_scope
from ....repositories import machine_repo
from ...machine_tasks import Update_machine
from .deletion import _handle_container_deleted
from .. import node_comms

logger = logging.getLogger(__name__)
FRAME_QUEUE_MAXSIZE = 8

def _enqueue_frame(queue: asyncio.Queue, frame: dict) -> None:
    """投递帧到处理队列；满时丢最旧（快照幂等覆盖，丢旧不丢新，删帧由下帧 vanish 兜底）。"""
    try:
        queue.put_nowait(frame)
    except asyncio.QueueFull:
        try:
            queue.get_nowait()
            queue.put_nowait(frame)
        except asyncio.QueueEmpty:  # pragma: no cover
            pass


async def _consume_frames(queue: asyncio.Queue, uid: str, machine_id: int) -> None:
    """串行消费帧（契约 C7）：快照/删除落库在独立线程执行——DB 慢不阻塞 receive 事件循环，
    C4 读超时只度量 socket 活性。单消费者保证帧序。

    machine_id 由连接 uid 归位（handle_node_ws）：delete 帧删除操作限定在发送机器内。
    """
    while True:
        frame = await queue.get()
        try:
            ftype = frame.get("type")
            if ftype == "snapshot_batch":
                await asyncio.to_thread(node_comms.apply_snapshot_batch, frame)
            elif ftype == "delete":
                container_name = frame.get("container_name")
                if container_name:
                    await asyncio.to_thread(_handle_container_deleted, container_name, machine_id)
            else:
                logger.warning("handle_node_ws: consumer unknown frame type %r", ftype)
        except Exception as e:
            logger.warning("handle_node_ws: frame processing error uid=%s: %s", uid, e)
        finally:
            queue.task_done()


async def _resolve_ws_identity(websocket):
    scope = getattr(websocket, "scope", {}) or {}
    query = parse_qs(scope.get("query_string", b"").decode("utf-8", errors="ignore"))
    uid = (query.get("uid") or [None])[0]
    if not uid:
        await websocket.close(code=4401)
        return None
    try:
        with session_scope(commit=False) as session:
            machine = machine_repo.get_by_uid(uid, session=session)
    except Exception as exc:
        logger.warning("handle_node_ws: get_by_uid failed: %s", exc)
        machine = None
    if machine is None:
        logger.warning("handle_node_ws: rejected connection with unknown uid %r", uid)
        await websocket.close(code=4403)
        return None
    return uid, machine


async def _accept_node_ws(websocket, uid, machine) -> bool:
    logger.info("node WSS connected: uid=%s machine=%s ip=%s", uid, machine.id, getattr(machine, "machine_ip", "?"))
    try:
        await websocket.accept()
    except Exception as exc:
        Update_machine(machine.id, machine_status=MachineStatus.OFFLINE)
        logger.warning("handle_node_ws: accept failed for uid=%s: %s", uid, exc)
        return False
    Update_machine(machine.id, machine_status=MachineStatus.ONLINE)
    return True


async def _receive_node_frame(websocket, uid):
    raw = await asyncio.wait_for(websocket.receive_text(), timeout=CommsConfig.WSS_READ_TIMEOUT)
    try:
        frame = json.loads(raw)
    except Exception as exc:
        logger.warning("handle_node_ws: malformed frame from %s: %s", uid, exc)
        return None
    if not isinstance(frame, dict):
        logger.warning("handle_node_ws: non-dict frame from %s", uid)
        return None
    return frame


def _route_node_frame(frame: dict, frame_queue: asyncio.Queue, uid: str) -> None:
    if frame.get("type") in ("snapshot_batch", "delete"):
        _enqueue_frame(frame_queue, frame)
    elif frame.get("type") == "event":
        logger.info(
            "handle_node_ws: container event uid=%s name=%s type=%s exit_code=%s",
            uid, frame.get("container_name"), frame.get("event_type"), frame.get("exit_code"),
        )
    else:
        logger.warning("handle_node_ws: unknown frame type %r (uid=%s)", frame.get("type"), uid)


async def _finish_node_ws(websocket, consumer_task, uid, machine_id, reachable_after_close, close_reason) -> None:
    # Reconnection provides a fresh snapshot; discard any queued work at disconnect.
    consumer_task.cancel()
    try:
        await consumer_task
    except (asyncio.CancelledError, Exception):
        pass
    if reachable_after_close is False:
        Update_machine(machine_id, machine_status=MachineStatus.OFFLINE)
    logger.info("handle_node_ws: connection closed for uid=%s: %s", uid, close_reason)
    try:
        await websocket.close()
    except Exception:
        pass
