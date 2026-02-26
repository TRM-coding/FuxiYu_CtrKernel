import threading
import time
import json
import base64
import requests

from ..config import CommsConfig
from ..utils.CheckKeys import signature, encryption
from ..repositories.containers_repo import update_container, list_containers as repo_list_containers
from ..repositories.machine_repo import get_by_id as get_machine_by_id, update_machine
from ..constant import ContainerStatus, MachineStatus
from flask import current_app


def send(machine_ip: str, endpoint: str, payload: dict, timeout: float = 5.0):
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
    以background thread的方式定期向远程机器发送请求查询容器状态，直到收到容器在线或失败的状态，或者超时。
    当状态变为RUNNING时，更新数据库中的容器记录（如果提供了container_id）并停止。
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
            res = send(machine_ip, "/container_status", payload, timeout=5.0)
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


def container_stopping_status_heartbeat(machine_ip: str, container_name: str, container_id: int | None = None,
                                      timeout: int = 180, interval: int = 3):
    """
    Heartbeat for stop action: initial state 'stoping', terminal state 'offline'.
    """
    app = None
    try:
        app = current_app._get_current_object()
    except RuntimeError:
        app = None

    def _worker():
        start = time.time()
        while time.time() - start < timeout:
            print(f"Stop-heartbeat check for '{container_name}' at {machine_ip}...")
            payload = {"config": {"container_name": container_name}}
            res = send(machine_ip, "/container_status", payload, timeout=5.0)
            if isinstance(res, dict) and 'container_status' in res:
                st = res.get('container_status')
                print(f"Received container_status (stop): {st}")
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
                if isinstance(st, str) and st.lower() == 'offline':
                    if container_id is not None:
                        try:
                            if app is not None:
                                with app.app_context():
                                    update_container(container_id, container_status=ContainerStatus.OFFLINE)
                            else:
                                update_container(container_id, container_status=ContainerStatus.OFFLINE)
                        except Exception as e:
                            print(f"Error updating container status: {e}")
                    return
            time.sleep(interval)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t


def container_restart_status_heartbeat(machine_ip: str, container_name: str, container_id: int | None = None,
                                       timeout: int = 180, interval: int = 3):
    """
    Heartbeat for restart action: initial 'stoping' then terminal 'online'.
    """
    app = None
    try:
        app = current_app._get_current_object()
    except RuntimeError:
        app = None

    def _worker():
        start = time.time()
        while time.time() - start < timeout:
            print(f"Restart-heartbeat check for '{container_name}' at {machine_ip}...")
            payload = {"config": {"container_name": container_name}}
            res = send(machine_ip, "/container_status", payload, timeout=5.0)
            if isinstance(res, dict) and 'container_status' in res:
                st = res.get('container_status')
                print(f"Received container_status (restart): {st}")
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


def start_machine_maintenance_transition_heartbeat(machine_id: int, timeout: int = 180, interval: int = 3):
    """
    Ctrl-side transition worker for ONLINE -> MAINTENANCE.
    1) Send stop requests to containers on the machine.
    2) Poll each container status and update DB until all OFFLINE (or FAILED).
    3) Set machine status to MAINTENANCE when converged; if node unreachable, mark OFFLINE.
    """
    app = None
    try:
        app = current_app._get_current_object()
    except RuntimeError:
        app = None

    def _db_update_machine(mid: int, status: MachineStatus):
        try:
            if app is not None:
                with app.app_context():
                    update_machine(mid, machine_status=status)
            else:
                update_machine(mid, machine_status=status)
        except Exception:
            pass

    def _db_update_container(cid: int, status: ContainerStatus):
        try:
            if app is not None:
                with app.app_context():
                    update_container(cid, container_status=status)
            else:
                update_container(cid, container_status=status)
        except Exception:
            pass

    def _worker():
        start_ts = time.time()
        while True:
            if time.time() - start_ts > timeout:
                break

            try:
                if app is not None:
                    with app.app_context():
                        m = get_machine_by_id(machine_id)
                else:
                    m = get_machine_by_id(machine_id)
            except Exception:
                m = None
            if not m:
                return

            machine_ip = getattr(m, 'machine_ip', None)
            if not machine_ip:
                _db_update_machine(machine_id, MachineStatus.OFFLINE)
                return

            try:
                if app is not None:
                    with app.app_context():
                        containers = repo_list_containers(limit=10000, offset=0, machine_id=machine_id)
                else:
                    containers = repo_list_containers(limit=10000, offset=0, machine_id=machine_id)
            except Exception:
                containers = []

            if not containers:
                _db_update_machine(machine_id, MachineStatus.MAINTENANCE)
                return

            # send stop command best-effort to non-offline containers
            for c in containers:
                c_status = c.container_status.value if hasattr(c.container_status, 'value') else str(c.container_status)
                if str(c_status).lower() == ContainerStatus.OFFLINE.value:
                    continue
                send(machine_ip, "/stop_container", {"config": {"container_name": c.name}}, timeout=3.0)
                _db_update_container(c.id, ContainerStatus.STOPPING)

            # poll statuses
            all_done = True
            for c in containers:
                res = send(machine_ip, "/container_status", {"config": {"container_name": c.name}}, timeout=3.0)
                if isinstance(res, dict) and res.get('status_code') == 404:
                    _db_update_container(c.id, ContainerStatus.OFFLINE)
                    continue
                if isinstance(res, dict) and res.get('error'):
                    all_done = False
                    continue
                st = (res.get('container_status') if isinstance(res, dict) else None) or ''
                st = str(st).lower()
                if st == ContainerStatus.OFFLINE.value:
                    _db_update_container(c.id, ContainerStatus.OFFLINE)
                elif st == ContainerStatus.FAILED.value:
                    _db_update_container(c.id, ContainerStatus.FAILED)
                else:
                    all_done = False

            if all_done:
                _db_update_machine(machine_id, MachineStatus.MAINTENANCE)
                return

            time.sleep(interval)

        # timeout fallback
        m2 = None
        try:
            if app is not None:
                with app.app_context():
                    m2 = get_machine_by_id(machine_id)
            else:
                m2 = get_machine_by_id(machine_id)
        except Exception:
            m2 = None

        machine_ip = getattr(m2, 'machine_ip', None) if m2 else None
        if not machine_ip:
            _db_update_machine(machine_id, MachineStatus.OFFLINE)
            return
        check = send(machine_ip, "/machine_status", {"config": {}}, timeout=2.0)
        ms = (check.get('machine_status') if isinstance(check, dict) else '') or ''
        ok = isinstance(check, dict) and check.get('success') in (1, True) and str(ms).lower() == MachineStatus.ONLINE.value
        _db_update_machine(machine_id, MachineStatus.MAINTENANCE if ok else MachineStatus.OFFLINE)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t
