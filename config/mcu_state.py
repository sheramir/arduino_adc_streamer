"""
MCU State Helpers
=================
Plain MCU detection/reset state used by ADC-side GUI adapters.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MCUState:
    current_mcu: str | None
    label_text: str
    log_message: str | None
    device_mode: str | None = None


def build_detected_mcu_state(mcu_name: str) -> MCUState:
    name = (mcu_name or "").strip()
    return MCUState(
        current_mcu=name or None,
        label_text=f"MCU: {name}" if name else "MCU: Unknown",
        log_message=f"Detected MCU: {name}" if name else "MCU detection timeout - using generic behavior",
    )


def build_unknown_mcu_state() -> MCUState:
    return MCUState(
        current_mcu=None,
        label_text="MCU: Unknown",
        log_message="MCU detection timeout - using generic behavior",
    )


def build_disconnected_mcu_state() -> MCUState:
    return MCUState(
        current_mcu=None,
        label_text="MCU: -",
        log_message=None,
        device_mode="adc",
    )
