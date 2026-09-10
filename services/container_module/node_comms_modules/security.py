from __future__ import annotations

import datetime
import json
import logging
import os
from pathlib import Path

from .transport import PINNED_CERTS_DIR

logger = logging.getLogger(__name__)

WSS_RELOAD_MARKER = os.getenv(
    "CTRL_WSS_RELOAD_MARKER",
    str(Path(PINNED_CERTS_DIR) / "_wss_reload_requested"),
)

def _write_wss_restart_marker(marker: Path, chain: Path | None, reason: str) -> None:
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "reason": reason,
                "requested_at": datetime.datetime.utcnow().isoformat(),
                "pin_bundle": str(chain) if chain else None,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _read_pin_bundle(pem_files: list[Path]) -> bytes:
    return b"\n".join(path.read_bytes() for path in pem_files if path.name != "_chain_bundle.pem")
