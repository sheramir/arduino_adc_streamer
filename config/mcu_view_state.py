"""
MCU View State Helpers
======================
Translate resolved MCU profiles into plain GUI presentation state.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MCUViewState:
    show_ground_controls: bool
    show_555_controls: bool
    show_reference_control: bool
    show_gain_control: bool
    show_teensy_controls: bool
    yaxis_units_locked: bool
    yaxis_units_value: str | None
    buffer_size_max: int
    show_charge_discharge_labels: bool
    osr_visible: bool
    osr_label_text: str
    osr_options: tuple[str, ...]
    osr_default: str
    osr_tooltip: str
    device_mode_log_label: str


def build_mcu_view_state(profile) -> MCUViewState:
    return MCUViewState(
        show_ground_controls=profile.show_ground_controls,
        show_555_controls=profile.show_555_controls,
        show_reference_control=profile.show_reference_control,
        show_gain_control=profile.show_gain_control,
        show_teensy_controls=profile.show_teensy_controls,
        yaxis_units_locked=profile.yaxis_units_locked,
        yaxis_units_value=profile.yaxis_units_value,
        buffer_size_max=profile.buffer_size_max,
        show_charge_discharge_labels=profile.show_charge_discharge_labels,
        osr_visible=not profile.show_555_controls,
        osr_label_text=profile.osr_label_text,
        osr_options=tuple(profile.osr_options),
        osr_default=profile.osr_default,
        osr_tooltip=profile.osr_tooltip,
        device_mode_log_label=profile.device_mode_log_label,
    )
