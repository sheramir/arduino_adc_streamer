"""
Device Configuration
====================
Loads adc_devices.json and matches configured devices against live COM ports.
"""

from __future__ import annotations

import json
import os

import serial.tools.list_ports

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "adc_devices.json")


def load_device_config() -> dict:
    """Load adc_devices.json; returns empty config on any error."""
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"auto_connect": True, "adc_devices": [], "force_devices": []}


def find_device_port(
    device_list: list[dict], *, exclude_port: str | None = None
) -> tuple[str | None, dict | None]:
    """Scan *device_list* entries against live COM ports.

    Matches on VID + PID. If a device entry has a non-null ``serial_number``
    it must match exactly. ``exclude_port`` skips a port already claimed by
    another live connection (e.g. the Force port, when auto-connecting ADC),
    so a VID/PID mismatch elsewhere never leaves ADC and Force sharing one
    physical port. Returns ``(port_device, matched_entry)`` for the first
    hit, or ``(None, None)`` if nothing found.
    """
    ports = list(serial.tools.list_ports.comports())
    for dev in device_list:
        try:
            want_vid = int(dev["vid"], 16)
            want_pid = int(dev["pid"], 16)
        except (ValueError, TypeError, KeyError):
            continue
        want_sn = dev.get("serial_number")
        for p in ports:
            if exclude_port is not None and p.device == exclude_port:
                continue
            if p.vid != want_vid or p.pid != want_pid:
                continue
            if want_sn is not None and p.serial_number != want_sn:
                continue
            return p.device, dev
    return None, None


def connected_port_name(serial_port) -> str | None:
    """Device name (e.g. "COM16") of a live serial.Serial-like port, or None if not open."""
    if serial_port is not None and getattr(serial_port, "is_open", False):
        return getattr(serial_port, "port", None) or getattr(serial_port, "name", None)
    return None


def find_adc_port(*, exclude_port: str | None = None) -> tuple[str | None, dict | None]:
    """Return the first matching ADC device port from config."""
    cfg = load_device_config()
    return find_device_port(cfg.get("adc_devices", []), exclude_port=exclude_port)


def find_force_port(*, exclude_port: str | None = None) -> tuple[str | None, dict | None]:
    """Return the first matching Force device port from config."""
    cfg = load_device_config()
    return find_device_port(cfg.get("force_devices", []), exclude_port=exclude_port)
