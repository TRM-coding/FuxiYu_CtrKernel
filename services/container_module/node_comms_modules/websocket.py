from __future__ import annotations

import asyncio
import json
import logging

from ....config import CommsConfig
from .deletion import _handle_container_deleted
from .. import node_comms

logger = logging.getLogger(__name__)
FRAME_QUEUE_MAXSIZE = 8

############################################################
# Frame Queue and Serial Consumption
############################################################

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

    machine_id 由链路归属确定（Ctrl 拨的就是这台机器）：delete 帧删除操作限定在该机器内。
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
                logger.warning("node link: consumer unknown frame type %r", ftype)
        except Exception as e:
            logger.warning("node link: frame processing error uid=%s: %s", uid, e)
        finally:
            queue.task_done()


############################################################
# Link Receive Path
############################################################

async def _receive_node_frame(websocket, uid):
    # websockets >= 14 的 asyncio 客户端只提供 recv()（旧名 receive_text 已移除）
    raw = await asyncio.wait_for(websocket.recv(), timeout=CommsConfig.WSS_READ_TIMEOUT)
    try:
        frame = json.loads(raw)
    except Exception as exc:
        logger.warning("node link: malformed frame from %s: %s", uid, exc)
        return None
    if not isinstance(frame, dict):
        logger.warning("node link: non-dict frame from %s", uid)
        return None
    return frame


def _route_node_frame(frame: dict, frame_queue: asyncio.Queue, uid: str) -> None:
    if frame.get("type") in ("snapshot_batch", "delete"):
        _enqueue_frame(frame_queue, frame)
    elif frame.get("type") == "event":
        logger.info(
            "node link: container event uid=%s name=%s type=%s exit_code=%s",
            uid, frame.get("container_name"), frame.get("event_type"), frame.get("exit_code"),
        )
    else:
        logger.warning("node link: unknown frame type %r (uid=%s)", frame.get("type"), uid)


async def _consume_link(websocket, uid: str, machine_id: int) -> None:
    """读帧 → 路由 → 串行消费，直到连接断开。

    断线时丢弃队列中未处理的帧：重连后 Node 会给一份全新快照，它才是权威状态。
    """
    queue = asyncio.Queue(maxsize=FRAME_QUEUE_MAXSIZE)
    consumer = asyncio.create_task(_consume_frames(queue, uid, machine_id))
    try:
        while True:
            frame = await _receive_node_frame(websocket, uid)
            if frame is not None:
                _route_node_frame(frame, queue, uid)
    finally:
        consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)
