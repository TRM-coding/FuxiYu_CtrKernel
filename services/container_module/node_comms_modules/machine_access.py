from __future__ import annotations

import logging

from ....constant import MachineStatus
from ....extensions import session_scope
from ....repositories import machine_repo
from ...machine_tasks import is_machine_in_maintenance
from ..exceptions import NodeServiceError

logger = logging.getLogger(__name__)

def _ensure_machine_online_for_operation(machine_id: int, operation: str = ''):
    """操作准入只读 Ctrl 侧状态机，不在普通操作前额外探活。"""
    try:
        with session_scope(commit=False) as session:
            m = machine_repo.get_by_id(machine_id, session=session)
    except Exception:
        m = None
    if not m:
        raise NodeServiceError(f"MACHINE {operation} failed: machine {machine_id} not found", reason="machine_not_found")
    if bool(getattr(m, "is_maintenance", False)) or is_machine_in_maintenance(machine_id):
        raise NodeServiceError(f"MACHINE {operation} aborted: machine is maintenance", reason="machine_maintenance")
    status = getattr(m, "machine_status", None)
    status_value = status.value if hasattr(status, "value") else str(status or "")
    if status_value != MachineStatus.ONLINE.value:
        raise NodeServiceError(f"MACHINE {operation} aborted: remote node not reachable or not online", reason="machine_offline")

