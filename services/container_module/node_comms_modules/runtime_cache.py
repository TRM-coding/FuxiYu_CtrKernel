from __future__ import annotations

import copy
import threading

_RUNTIME_BUFFER_LOCK = threading.RLock()
_CONTAINER_RUNTIME_BUFFER: dict[str, dict[str, dict]] = {}
_MACHINE_RUNTIME_BUFFER: dict[str, dict] = {}


def _split_container_runtime_snapshot(snapshot: dict) -> tuple[dict, list[str]]:
    updates = {}
    clears = []
    for name, entry in snapshot.items():
        if not isinstance(entry, dict):
            continue
        runtime = entry.get("runtime_metrics")
        if runtime is not None:
            updates[str(name)] = copy.deepcopy(runtime)
        else:
            clears.append(str(name))
    return updates, clears


def _update_container_runtime_cache(machine_id: int, updates: dict, clears: list[str]) -> None:
    with _RUNTIME_BUFFER_LOCK:
        machine_buffer = _CONTAINER_RUNTIME_BUFFER.setdefault(str(machine_id), {})
        for name in clears:
            machine_buffer.pop(name, None)
        machine_buffer.update(updates)


def _write_machine_runtime_cache(machine_id: int, snapshot: dict) -> None:
    with _RUNTIME_BUFFER_LOCK:
        _MACHINE_RUNTIME_BUFFER[str(machine_id)] = copy.deepcopy(snapshot)


def _read_container_runtime_cache(machine_id: int, container_name: str) -> dict | None:
    with _RUNTIME_BUFFER_LOCK:
        value = (_CONTAINER_RUNTIME_BUFFER.get(str(machine_id)) or {}).get(container_name)
        return copy.deepcopy(value) if isinstance(value, dict) else None


def _read_machine_runtime_cache(machine_id: int) -> dict | None:
    with _RUNTIME_BUFFER_LOCK:
        value = _MACHINE_RUNTIME_BUFFER.get(str(machine_id))
        return copy.deepcopy(value) if isinstance(value, dict) else None
