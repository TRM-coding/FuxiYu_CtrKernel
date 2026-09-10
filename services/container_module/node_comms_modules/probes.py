from __future__ import annotations

import logging

from ....constant import MachineStatus
from ....extensions import session_scope
from ....repositories import containers_repo, machine_repo
from ...machine_tasks import Update_machine

logger = logging.getLogger(__name__)
CONNECTIVITY_PROBE_ATTEMPTS = 2


def _decode_container_probe_response(response):
    if isinstance(response, dict):
        if response.get("error") and response.get("status_code") != 404:
            return response, response["error"]
        if response.get("status_code") == 404:
            response.setdefault("error", "not found")
    return response, None


def _load_connectivity_probe_target(machine_id: int):
    try:
        with session_scope(commit=False) as session:
            machine = machine_repo.get_by_id(machine_id, session=session)
    except Exception:
        machine = None
    machine_ip = getattr(machine, "machine_ip", None)
    if not machine_ip:
        return None, None
    probe_name = None
    try:
        with session_scope(commit=False) as session:
            containers = containers_repo.list_containers(limit=1, offset=0, machine_id=machine_id, session=session)
        if containers:
            probe_name = getattr(containers[0], "name", None)
    except Exception:
        pass
    return machine_ip, probe_name


def _list_online_probe_targets() -> list:
    try:
        with session_scope(commit=False) as session:
            return machine_repo.list_machines_by_status(MachineStatus.ONLINE, session=session)
    except Exception as exc:
        logger.warning("probe_machines_online_once: list online machines failed: %s", exc)
        return []


def _mark_probe_target_offline(machine) -> bool:
    try:
        Update_machine(machine.id, machine_status=MachineStatus.OFFLINE)
        logger.warning(
            "probe_machines_online_once: machine %s (%s) offline (ghost online cleared)",
            machine.id, machine.machine_ip,
        )
        return True
    except Exception as exc:
        logger.warning("probe_machines_online_once: failed to set OFFLINE for machine %s: %s", machine.id, exc)
        return False
