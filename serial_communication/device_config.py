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


def find_device_port(device_list: list[dict]) -> tuple[str | None, dict | None]:
    """Scan *device_list* entries against live COM ports.

    Matches on VID + PID. If a device entry has a non-null ``serial_number``
    it must match exactly. Returns ``(port_device, matched_entry)`` for the
    first hit, or ``(None, None)`` if nothing found.
    """
    for dev in device_list:
        try:
            want_vid = int(dev["vid"], 16)
            want_pid = int(dev["pid"], 16)
        except (ValueError, TypeError, KeyError):
            continue
        want_sn = dev.get("serial_number")
        for p in serial.tools.list_ports.comports():
            if p.vid != want_vid or p.pid != want_pid:
                continue
            if want_sn is not None and p.serial_number != want_sn:
                continue
            return p.device, dev
    return None, None


def find_adc_port() -> tuple[str | None, dict | None]:
    """Return the first matching ADC device port from config."""
    cfg = load_device_config()
    return find_device_port(cfg.get("adc_devices", []))


def find_force_port() -> tuple[str | None, dict | None]:
    """Return the first matching Force device port from config."""
    cfg = load_device_config()
    return find_device_port(cfg.get("force_devices", []))
