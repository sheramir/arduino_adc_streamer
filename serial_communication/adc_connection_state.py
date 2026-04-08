"""
ADC Connection State Helpers
============================
Plain helpers for ADC runtime defaults and connection view-state snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class ADCConnectionViewState:
    connect_button_text: str
    configure_enabled: bool
    configure_style: str | None
    start_enabled: bool
    stop_enabled: bool
    status_message: str
    port_selection_enabled: bool


@dataclass(slots=True)
class ArduinoStatus:
    channels: list[int] | None = None
    repeat: int | None = None
    ground_pin: int | None = None
    use_ground: bool | None = None
    osr: int | None = None
    gain: int | None = None
    reference: str | None = None
    buffer: int | None = None
    rb: float | None = None
    rk: float | None = None
    cf: float | None = None
    rxmax: float | None = None

    def copy(self) -> "ArduinoStatus":
        return replace(self)

    def apply(self, other: "ArduinoStatus") -> None:
        self.channels = None if other.channels is None else list(other.channels)
        self.repeat = other.repeat
        self.ground_pin = other.ground_pin
        self.use_ground = other.use_ground
        self.osr = other.osr
        self.gain = other.gain
        self.reference = other.reference
        self.buffer = other.buffer
        self.rb = other.rb
        self.rk = other.rk
        self.cf = other.cf
        self.rxmax = other.rxmax


def build_default_last_sent_config() -> dict:
    return {
        "channels": None,
        "repeat": None,
        "ground_pin": None,
        "use_ground": None,
        "osr": None,
        "gain": None,
        "reference": None,
    }


def build_default_arduino_status() -> ArduinoStatus:
    return ArduinoStatus()


def build_connected_view_state() -> ADCConnectionViewState:
    return ADCConnectionViewState(
        connect_button_text="Disconnect",
        configure_enabled=True,
        configure_style="QPushButton { background-color: #2196F3; color: white; font-weight: bold; }",
        start_enabled=False,
        stop_enabled=False,
        status_message="Connected - Please configure",
        port_selection_enabled=False,
    )


def build_disconnected_view_state() -> ADCConnectionViewState:
    return ADCConnectionViewState(
        connect_button_text="Connect",
        configure_enabled=False,
        configure_style=None,
        start_enabled=False,
        stop_enabled=False,
        status_message="Disconnected",
        port_selection_enabled=True,
    )
