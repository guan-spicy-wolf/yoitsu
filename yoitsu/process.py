"""Process lifecycle management: PID files, liveness, start/stop."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
_PASLOE_LOG = ROOT / "pasloe.log"
_TRENNI_LOG = ROOT / "trenni.log"
_PASLOE_DIR = ROOT / "pasloe"
_TRENNI_DIR = ROOT / "trenni"
_DEFAULT_CONFIG = ROOT / "config" / "trenni.yaml"


# ---------------------------------------------------------------------------
# Liveness
# ---------------------------------------------------------------------------

def is_alive(pid: int) -> bool:
    """Return True if process pid is running (or owned by another user)."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists, we just can't signal it


# ---------------------------------------------------------------------------
# PID file
# ---------------------------------------------------------------------------

def read_pids() -> dict[str, Any] | None:
    """Return parsed .pids.json or None if it doesn't exist / is corrupt."""
    pids_file = ROOT / ".pids.json"
    try:
        return json.loads(pids_file.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def write_pids(*, pasloe_pid: int, trenni_pid: int) -> None:
    pids_file = ROOT / ".pids.json"
    now = datetime.now(timezone.utc).isoformat()
    pids_file.write_text(json.dumps({
        "pasloe": {"pid": pasloe_pid, "started_at": now},
        "trenni": {"pid": trenni_pid, "started_at": now},
    }, indent=2))


def clear_pids() -> None:
    """Remove .pids.json; no-op if already absent."""
    pids_file = ROOT / ".pids.json"
    try:
        pids_file.unlink()
    except FileNotFoundError:
        pass
