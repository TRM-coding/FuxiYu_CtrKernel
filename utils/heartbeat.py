import threading
import time
import json
import base64
import requests

from ..config import CommsConfig
from ..utils.CheckKeys import signature, encryption
from ..repositories.containers_repo import update_container
from ..constant import ContainerStatus
from flask import current_app


def _send_encrypted(machine_ip: str, endpoint: str, payload: dict, timeout: float = 5.0):
    url = f"http://{machine_ip}{CommsConfig.NODE_URL_MIDDLE}{endpoint}"
    body = json.dumps(payload)
    sig = signature(body)
    enc = encryption(body)
    try:
        resp = requests.post(url, json={
            "message": base64.b64encode(enc).decode('utf-8'),
            "signature": base64.b64encode(sig).decode('utf-8')
        }, timeout=timeout)
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError:
            return {"text": resp.text, "status_code": resp.status_code}
    except Exception as e:
        return {"error": str(e)}


def container_starting_status_heartbeat(machine_ip: str, container_name: str, container_id: int | None = None,
                                     timeout: int = 180, interval: int = 3):
    """
    Start a background thread polling Node's /container_status for the given container_name.
    When status becomes RUNNING, update the DB container record (if container_id provided) and stop.
    """
    # capture Flask app if available so background thread can use its app_context
    app = None
    try:
        app = current_app._get_current_object()
    except RuntimeError:
        app = None

    def _worker():
        start = time.time()
        while time.time() - start < timeout:
            print(f"Heartbeat check for container '{container_name}' at {machine_ip}...")
            payload = {"config": {"container_name": container_name}}
            res = _send_encrypted(machine_ip, "/container_status", payload, timeout=5.0)
            if isinstance(res, dict) and 'container_status' in res:
                st = res.get('container_status')
                print(f"Received container_status: {st}")
                # if remote reports a creation failure, mark local container as FAILED and stop
                if res.get('container_status') == 'failed' or res.get('error_reason'):
                    try:
                        if container_id is not None:
                            if app is not None:
                                with app.app_context():
                                    update_container(container_id, container_status=ContainerStatus.FAILED)
                            else:
                                update_container(container_id, container_status=ContainerStatus.FAILED)
                    except Exception as e:
                        print(f"Error updating container status to FAILED: {e}")
                    return
                if isinstance(st, str) and st.lower() == 'online':
                    if container_id is not None:
                        try:
                            if app is not None:
                                with app.app_context():
                                    update_container(container_id, container_status=ContainerStatus.ONLINE)
                            else:
                                update_container(container_id, container_status=ContainerStatus.ONLINE)
                        except Exception as e:
                            print(f"Error updating container status: {e}")
                    return
            time.sleep(interval)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t
