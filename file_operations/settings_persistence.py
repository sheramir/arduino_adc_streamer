"""
Settings Persistence Helpers
============================
Shared JSON settings save/load helpers used by GUI panels.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable


def save_settings_payload(
    file_path,
    payload: dict,
    *,
    log_callback: Callable[[str], None] | None = None,
    success_message: str | None = None,
) -> Path:
    """Persist a settings payload to disk and optionally log success."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    if log_callback is not None and success_message:
        log_callback(success_message.format(path=path))
    return path


def load_settings_payload(
    file_path,
    *,
    payload_key: str | None = None,
) -> tuple[Path, dict]:
    """Load a JSON settings payload and optionally unwrap its nested settings block."""
    path = Path(file_path)
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if payload_key:
        payload = payload.get(payload_key, payload)
    return path, payload
