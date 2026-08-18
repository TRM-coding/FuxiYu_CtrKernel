import json
import logging
import time
import base64
import requests
import traceback

from ...config import CommsConfig
from ...repositories import machine_repo
from ..machine_tasks import is_machine_online_remote
from ...utils.CheckKeys import signature, encryption
from ...utils.parallel import parallel_node_calls
from .exceptions import NodeServiceError


####################################################

def get_full_url(machine_ip:str, endpoint:str)->str:
    return f"http://{machine_ip}{CommsConfig.NODE_URL_MIDDLE}{endpoint}"

####################################################
#发送指令到集群实体机

def send(ciphertext:bytes,signature:bytes,mechine_ip:str, timeout:float=5.0)->dict:
    """
    发送 POST 并返回解析后的响应（优先 JSON），出现错误时返回包含 error 字段的 dict。
    """
    try:
        resp = requests.post(mechine_ip, json={
            "message": base64.b64encode(ciphertext).decode('utf-8'),
            "signature": base64.b64encode(signature).decode('utf-8')
        }, timeout=timeout)

        # 尝试解析为 JSON（即使是 4xx/5xx，也优先解析 body 中的 JSON，以保留 Node 返回的 error_reason）
        try:
            j = resp.json()
            if isinstance(j, dict):
                j.setdefault('status_code', resp.status_code)
            return j
        except ValueError:
            return {"status_code": resp.status_code, "text": resp.text}

    except requests.RequestException as e:
        # 网络/超时/连接等错误
        logger.error("Request error: %s", e)
        return {"error": str(e)}


def _ensure_machine_online_for_operation(machine_id: int, operation: str = ''):
    """
    这里检查机器在线状态的主要目的是为了在执行诸如创建/删除/修改容器等操作之前，先验证目标机器是否在线，以避免不必要的远程调用和更快地反馈给用户。虽然最终的远程调用也会有类似的检查，但这个预检查可以节省资源并提供更即时的错误响应。
    """
    try:
        m = machine_repo.get_by_id(machine_id)
    except Exception:
        m = None
    if not m:
        raise NodeServiceError(f"MACHINE {operation} failed: machine {machine_id} not found", reason="machine_not_found")
    try:
        machine_status = m.machine_status.value.lower() if hasattr(m.machine_status, 'value') else str(m.machine_status).lower()
    except Exception:
        machine_status = str(getattr(m, 'machine_status', '')).lower()
    if machine_status == 'maintenance':
        raise NodeServiceError(f"MACHINE {operation} aborted: machine is maintenance", reason="machine_maintenance")
    ok = is_machine_online_remote(machine_id)
    if not ok:
        raise NodeServiceError(f"MACHINE {operation} aborted: remote node not reachable or not online", reason="machine_offline")


#返回一页容器的概要信息
def _node_probe_container(container, machine_ip: str, _app=None) -> dict | None:
    """封装单次 NodeKernel /container_status 查询。

    等同于原 for 循环内 ``get_container_status(machine_ip, container.name)``，
    抽取为独立函数以适配 ``parallel_node_calls``。

    *_app* 可选传入 Flask app 实例，用于线程池内推送 app context。
    """
    try:
        if _app is not None:
            with _app.app_context():
                return get_container_status(machine_ip, container.name)
        return get_container_status(machine_ip, container.name)
    except Exception:
        return None


####

def get_container_status(machine_ip: str, container_name: str, timeout: float = 5.0) -> dict:
    """
    这个方法主要是为了在服务端调用 Node 的 /container_status API 来验证容器状态的。但是这个方法不被heartbeat使用。
    """
    url = get_full_url(machine_ip, "/container_status")
    payload = json.dumps({"config": {"container_name": container_name}})
    sig = signature(payload)
    enc = encryption(payload)

    last_exc = None
    for attempt in range(2):
        try:
            res = send(enc, sig, url, timeout=timeout)
            # send 不抛网络异常（以 {"error": ...} 返回），按原语义对网络级失败重试
            if isinstance(res, dict) and res.get('error') and res.get('status_code') != 404:
                last_exc = res.get('error')
                logger.warning("get_container_status request error (attempt %s): %s", attempt + 1, last_exc)
                # short backoff before retrying
                if attempt == 0:
                    time.sleep(0.5)
                continue
            # 保留原 404 语义（下游以 status_code == 404 判断容器不存在）
            if isinstance(res, dict) and res.get('status_code') == 404:
                res.setdefault('error', 'not found')
            return res
        except Exception as e:
            last_exc = e
            logger.warning("get_container_status request error (attempt %s): %s", attempt + 1, e)
            # short backoff before retrying
            if attempt == 0:
                time.sleep(0.5)
            continue

    # both attempts failed due to network/request errors
    return {"error": str(last_exc) if last_exc is not None else "unknown error"}


