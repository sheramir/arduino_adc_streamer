"""
ADC Configuration State
=======================
Typed configuration model for the live ADC/555 settings owned by the GUI.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

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
    repeat: int = 1
    ground_pin: int = -1
    use_ground: bool = False
    osr: int = 2
    gain: int = 1
    reference: str = "vdd"
    conv_speed: str = "med"
    samp_speed: str = "med"
    sample_rate: int = 0
    rb_ohms: float = ANALYZER555_DEFAULT_RB_OHMS
    rk_ohms: float = ANALYZER555_DEFAULT_RK_OHMS
    cf_farads: float = ANALYZER555_DEFAULT_CF_FARADS
    rxmax_ohms: float = ANALYZER555_DEFAULT_RXMAX_OHMS

    def copy(self) -> "ADCConfigurationState":
        return replace(
            self,
            channels=list(self.channels),
            selected_array_sensors=list(self.selected_array_sensors),
        )

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        return default

    def __getitem__(self, key: str) -> Any:
        if not hasattr(self, key):
            raise KeyError(key)
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        if not hasattr(self, key):
            raise KeyError(key)
        setattr(self, key, value)

    def update(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            self[key] = value


def build_default_adc_config_state() -> ADCConfigurationState:
    return ADCConfigurationState()
