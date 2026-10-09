"""
ADC Configuration State
=======================
Typed configuration model for the live ADC/555 settings owned by the GUI.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any
from config.boards import get_board_registry
from config.legacy_array_api import legacy_array_default


def _default(profile, parameter):
    return get_board_registry().profiles[profile].mode().parameters[parameter].default

from constants.defaults_555 import (
    ANALYZER555_DEFAULT_CF_FARADS,
    ANALYZER555_DEFAULT_RB_OHMS,
    ANALYZER555_DEFAULT_RK_OHMS,
    ANALYZER555_DEFAULT_RXMAX_OHMS,
)


@dataclass(slots=True)
class ADCConfigurationState:
    channels: list[int] = field(default_factory=list)
    channel_selection_source: str = "none"
    selected_array_sensors: list[str] = field(default_factory=list)
    array_operation_mode: str = "PZT"
    testboard_array_selection: str = field(default_factory=lambda: legacy_array_default("array_selection"))
    testboard_scan_order: str = field(default_factory=lambda: legacy_array_default("scan_order"))
    testboard_spi_clock_hz: int = field(default_factory=lambda: legacy_array_default("spi_clock_hz"))
    testboard_channel_repeat: int = field(default_factory=lambda: legacy_array_default("settling_conversions"))
    testboard_sequence: str = field(default_factory=lambda: legacy_array_default("sequence"))
    repeat: int = field(default_factory=lambda: _default("generic_adc", "samples_per_channel"))
    ground_pin: int = -1
    use_ground: bool = False
    osr: int = field(default_factory=lambda: _default("generic_adc", "osr"))
    gain: int = field(default_factory=lambda: _default("generic_adc", "gain"))
    reference: str = field(default_factory=lambda: _default("generic_adc", "reference"))
    conv_speed: str = "med"
    samp_speed: str = "med"
    sample_rate: int = 0
    rb_ohms: float = ANALYZER555_DEFAULT_RB_OHMS
    rk_ohms: float = ANALYZER555_DEFAULT_RK_OHMS
    cf_farads: float = ANALYZER555_DEFAULT_CF_FARADS
    rxmax_ohms: float = ANALYZER555_DEFAULT_RXMAX_OHMS

    parameters: dict[str, Any] = field(default_factory=dict)

    def register_parameters(self, mode):
        self.parameters = {p.legacy_key: self.parameters.get(p.legacy_key, p.default)
                           for p in mode.parameters.values() if not hasattr(self, p.legacy_key)}

    def copy(self) -> "ADCConfigurationState":
        return replace(
            self,
            parameters=dict(self.parameters),
            channels=list(self.channels),
            selected_array_sensors=list(self.selected_array_sensors),
        )

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        return self.parameters.get(key, default)

    def __getitem__(self, key: str) -> Any:
        if not hasattr(self, key):
            return self.parameters[key]
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        if not hasattr(self, key):
            if key not in self.parameters:
                raise KeyError(key)
            self.parameters[key] = value
        else:
            setattr(self, key, value)

    def update(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            self[key] = value


def build_default_adc_config_state() -> ADCConfigurationState:
    return ADCConfigurationState()
