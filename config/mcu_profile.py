"""
MCU Profile Helpers
===================
Resolve MCU capability and GUI-mode decisions into plain data.
"""

from __future__ import annotations

from dataclasses import dataclass

from constants.defaults_555 import ANALYZER555_BUFFER_SIZE_MAX
from constants.serial import BUFFER_SIZE_MAX


@dataclass(frozen=True, slots=True)
class MCUProfile:
    mcu_name: str
    is_array_mcu: bool
    is_array_pzt1: bool
    is_array_dual: bool
    is_array_pzt_pzr17: bool
    supports_pzt_rs: bool
    is_pzt_rs_mode: bool
    array_operation_modes: tuple[str, ...]
    is_teensy: bool
    is_555_mode: bool
    device_mode: str
    show_ground_controls: bool
    show_555_controls: bool
    osr_visible: bool
    show_teensy_controls: bool
    show_reference_control: bool
    show_gain_control: bool
    yaxis_units_locked: bool
    yaxis_units_value: str | None
    buffer_size_max: int
    show_charge_discharge_labels: bool
    osr_label_text: str
    osr_options: tuple[str, ...]
    osr_default: str
    osr_tooltip: str
    device_mode_log_label: str


def resolve_mcu_profile(mcu_name: str | None, *, selected_array_mode: str = "PZT") -> MCUProfile:
    name = (mcu_name or "").strip()
    lower_name = name.lower()
    is_array_pzt_pzr17 = lower_name == "array_pzt_pzr1.7"
    supports_pzt_rs = lower_name in ("array_pzt_pzr1", "array_pzt_pzr1.7")
    array_operation_modes = ("PZT", "PZR", "PZT_RS") if supports_pzt_rs else ("PZT", "PZR")
    normalized_array_mode = (selected_array_mode or "PZT").strip().upper()
    if normalized_array_mode not in array_operation_modes:
        normalized_array_mode = "PZT"

    is_array_dual = lower_name.startswith("array_pzt_pzr")
    is_array_mcu = lower_name.startswith("array")
    is_pzt_rs_mode = is_array_dual and normalized_array_mode == "PZT_RS"
    is_array_pzt1 = lower_name == "array_pzt1" or (
        is_array_dual and normalized_array_mode in ("PZT", "PZT_RS")
    )
    is_teensy = "teensy" in lower_name
    is_555_mode = normalized_array_mode == "PZR" if is_array_dual else ("555" in lower_name)
    device_mode = "555" if is_555_mode else "adc"

    if is_555_mode:
        return MCUProfile(
            mcu_name=name,
            is_array_mcu=is_array_mcu,
            is_array_pzt1=is_array_pzt1,
            is_array_dual=is_array_dual,
            is_array_pzt_pzr17=is_array_pzt_pzr17,
            supports_pzt_rs=supports_pzt_rs,
            is_pzt_rs_mode=is_pzt_rs_mode,
            array_operation_modes=array_operation_modes,
            is_teensy=is_teensy,
            is_555_mode=True,
            device_mode=device_mode,
            show_ground_controls=False,
            show_555_controls=True,
            osr_visible=False,
            show_teensy_controls=False,
            show_reference_control=False,
            show_gain_control=False,
            yaxis_units_locked=True,
            yaxis_units_value="Values",
            buffer_size_max=ANALYZER555_BUFFER_SIZE_MAX,
            show_charge_discharge_labels=True,
            osr_label_text="OSR (Oversampling):",
            osr_options=("2", "4", "8"),
            osr_default="2",
            osr_tooltip="Oversampling ratio: higher = better SNR, lower sample rate",
            device_mode_log_label="PZR" if is_array_dual else "555 analyzer",
        )

    if is_teensy:
        return MCUProfile(
            mcu_name=name,
            is_array_mcu=is_array_mcu,
            is_array_pzt1=is_array_pzt1,
            is_array_dual=is_array_dual,
            is_array_pzt_pzr17=is_array_pzt_pzr17,
            supports_pzt_rs=supports_pzt_rs,
            is_pzt_rs_mode=is_pzt_rs_mode,
            array_operation_modes=array_operation_modes,
            is_teensy=True,
            is_555_mode=False,
            device_mode=device_mode,
            show_ground_controls=True,
            show_555_controls=is_pzt_rs_mode,
            osr_visible=True,
            show_teensy_controls=True,
            show_reference_control=False,
            show_gain_control=False,
            yaxis_units_locked=False,
            yaxis_units_value=None,
            buffer_size_max=BUFFER_SIZE_MAX,
            show_charge_discharge_labels=False,
            osr_label_text="Averaging:",
            osr_options=("0", "1", "4", "8", "16", "32"),
            osr_default="4",
            osr_tooltip="Hardware averaging: 0=disabled, higher = better SNR",
            device_mode_log_label="PZT" if is_array_dual else "ADC streamer",
        )

    return MCUProfile(
        mcu_name=name,
        is_array_mcu=is_array_mcu,
        is_array_pzt1=is_array_pzt1,
        is_array_dual=is_array_dual,
        is_array_pzt_pzr17=is_array_pzt_pzr17,
        supports_pzt_rs=supports_pzt_rs,
        is_pzt_rs_mode=is_pzt_rs_mode,
        array_operation_modes=array_operation_modes,
        is_teensy=False,
        is_555_mode=False,
        device_mode=device_mode,
        show_ground_controls=True,
        show_555_controls=is_pzt_rs_mode,
        osr_visible=True,
        show_teensy_controls=False,
        show_reference_control=not is_array_mcu,
        show_gain_control=True,
        yaxis_units_locked=False,
        yaxis_units_value=None,
        buffer_size_max=BUFFER_SIZE_MAX,
        show_charge_discharge_labels=False,
        osr_label_text="OSR (Oversampling):",
        osr_options=("2", "4", "8"),
        osr_default="4" if is_array_mcu else "2",
        osr_tooltip="Oversampling ratio: higher = better SNR, lower sample rate",
        device_mode_log_label="PZT" if is_array_dual else "ADC streamer",
    )
