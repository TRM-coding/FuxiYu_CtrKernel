import threading
import time

from ..repositories.containers_repo import update_container, list_containers as repo_list_containers
from ..repositories.machine_repo import get_by_id as get_machine_by_id, update_machine
from ..constant import ContainerStatus, MachineStatus, OperationType
from ..services.operation_log_tasks import write_operation_log
from flask import current_app


def _log_machine_status_transition(mid: int, new_status: MachineStatus) -> None:
    """机器状态真正变化时记一条系统日志（前→后），未变化不记。"""
    try:
        old = get_machine_by_id(mid)
        if old is None:
            return  # 机器已不存在（如过渡期间被删除），跳过记录
        old_val = getattr(old, 'machine_status', None)
        old_str = old_val.value if hasattr(old_val, 'value') else str(old_val) if old_val is not None else None
    except Exception:
        return
    new_str = new_status.value if hasattr(new_status, 'value') else str(new_status)
    if old_str is not None and str(old_str).lower() == str(new_str).lower():
        return
    write_operation_log(success=True, operator_user_id=None, operation=OperationType.MACHINE_STATUS_TRANSITION,
                        target_type="machine", target_id=mid,
                        detail={"before": {"machine_status": old_str}, "after": {"machine_status": new_str}})


def send(machine_ip: str, endpoint: str, payload: dict, timeout: float = 5.0):
    """HTTPS 明文 POST（check_keys 已退役，TLS 承载身份）。"""
    from ..services.container_module.node_comms import get_full_url, send as node_comms_send
    url = get_full_url(machine_ip, endpoint)
    try:
        return node_comms_send(url, payload, timeout=timeout)
    except Exception as e:
        return {"error": str(e)}


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
                    _log_machine_status_transition(mid, status)
                    update_machine(mid, machine_status=status)
            else:
                _log_machine_status_transition(mid, status)
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
