from __future__ import annotations

import logging
import math

from ...constant import ROLE
from ...repositories.containers_repo import derive_port_mappings
from . import node_comms
from .pydantic_models import container_bref_information, _derive_effective_status
from .utils import container_image_dockerfile, derive_allocated_limits

logger = logging.getLogger(__name__)

####################################################
# 出参组装工具族（纯拼装，不查库、不打 Node）
# 门户见 services/container_tasks.py：详情 / 列表项 / 分页结构都在这里成型。
# 口径约定：磁盘上限以 machine.max_disk_size_gb 现算派生（<=0 视为未设限）；
# 磁盘用量一律读 WSS 落库列，实时运行指标读 node_comms 的内存缓存。
####################################################

def _build_disk_usage_response(container) -> dict:
    """裸磁盘用量接口的出参（字节原值，不做单位换算）。"""
    return {
        "success": 1,
        "container": {
            "overlay_rw_bytes": getattr(container, "disk_overlay_rw_bytes", None),
            "bind_mount_bytes": getattr(container, "disk_bind_mount_bytes", None),
            "total_bytes": getattr(container, "disk_total_bytes", None),
            "bind_mount_path": getattr(container, "bind_mount_path", None),
        },
    }


def _disk_limit_bytes(machine) -> int:
    """磁盘上限统一口径：machine.max_disk_size_gb 现算；未配置（<=0）视为未设限返回 0。"""
    maximum = getattr(machine, "max_disk_size_gb", None) or 0
    return int(maximum * 1024**3) if maximum > 0 else 0


def _build_detail_disk_usage(container, machine) -> dict | None:
    """详情页磁盘用量（GB 换算 + 使用率）；无快照（total 为 None/负）返回 None。"""
    try:
        total = getattr(container, "disk_total_bytes", None)
        if total is None or total < 0:
            return None
        limit = _disk_limit_bytes(machine)
        return {
            "overlay_rw_gb": round((getattr(container, "disk_overlay_rw_bytes", None) or 0) / 1024**3, 1),
            "bind_mount_gb": round((getattr(container, "disk_bind_mount_bytes", None) or 0) / 1024**3, 1),
            "total_gb": round(total / 1024**3, 1),
            "limit_gb": round(limit / 1024**3, 1) if limit else 0.0,
            "usage_percent": round(total / limit * 100, 1) if limit > 0 else 0.0,
        }
    except Exception as exc:
        logger.warning("failed to read DB disk snapshot for container %s: %s", container.id, exc)
        return None


def _build_brief_disk_usage(container, machine) -> dict:
    """列表项磁盘用量：扁平三字段（total/limit/percent），无快照时为 None/0。"""
    total = getattr(container, "disk_total_bytes", None)
    limit = _disk_limit_bytes(machine)
    return {
        "disk_total_gb": round(total / 1024**3, 1) if total is not None else None,
        "disk_limit_gb": round(limit / 1024**3, 1) if limit else None,
        "disk_usage_percent": round(total / limit * 100, 1) if total is not None and limit > 0 else 0,
    }


def _build_container_common_fields(container, machine, bindings) -> dict:
    """详情与列表共用的字段骨架（身份 / 配额派生 / 有效状态 / 绑定 / 实时运行指标）。"""
    return {
        "container_id": container.id,
        "container_name": container.name,
        "container_image": container.image,
        "created_at": container.created_at.isoformat() if container.created_at else None,
        "machine_id": container.machine_id,
        "machine_ip": machine.machine_ip if machine else "",
        "port": container.port,
        **derive_allocated_limits(container, machine),
        "gpu_chosen_list": container.gpu_chosen_list,
        "port_mappings": derive_port_mappings(container.port, container.port_mappings),
        "effective_status": _derive_effective_status(
            container.container_status, container.machine_id, container=container,
        ),
        "failed_reason": getattr(container, "failed_reason", None),
        "failed_detail": getattr(container, "failed_detail", None),
        "accounts": [
            {
                "user_id": binding.get("user_id"), "username": binding.get("username"),
                "role": ROLE(binding.get("role")).value if binding.get("role") is not None else None,
            }
            for binding in bindings
        ],
        "runtime_metrics": node_comms.get_cached_container_runtime_metrics(container.machine_id, container.name),
    }


def _build_container_detail(container, machine, bindings, long_term, cleanup, freeze, disk_usage, owners) -> dict:
    """详情出参：公共骨架 + 镜像 Dockerfile / 规格 / 长期态 / 清理倒计时 / 冻结态 / owners。"""
    return {
        **_build_container_common_fields(container, machine, bindings),
        "image_dockerfile": container_image_dockerfile(container),
        "memory_gb": container.memory_gb,
        "shared_gb": container.shared_gb,
        "gpu_number": container.gpu_number,
        "cpu_number": container.cpu_number,
        **long_term,
        **cleanup,
        "disk_usage": disk_usage,
        "freeze_state": freeze,
        "owners": owners,
    }


def _build_container_brief(container, machine, bindings, long_term, cleanup, freeze) -> container_bref_information:
    """列表项出参：与详情同骨架，磁盘与冻结态压成扁平字段（无冻结则不显示天数）。"""
    freeze = freeze or {}
    return container_bref_information(
        **_build_container_common_fields(container, machine, bindings),
        **long_term,
        **cleanup,
        **_build_brief_disk_usage(container, machine),
        freeze_first_frozen_at=freeze.get("first_frozen_at"),
        freeze_grace_until=freeze.get("grace_until"),
        freeze_days_frozen=freeze.get("days_frozen") if freeze.get("first_frozen_at") else None,
        freeze_escalation_days=freeze.get("escalation_days"),
    )


def _build_container_page(containers: list, total_count: int, page_size: int) -> dict:
    """分页结构：总页数按总数与页长算（至少 1 页）；异常兜底为 1 页。"""
    try:
        total_page = max(1, math.ceil(total_count / page_size))
    except Exception:
        total_page = 1
    return {"containers": containers, "total_page": total_page, "total_number": total_count}
