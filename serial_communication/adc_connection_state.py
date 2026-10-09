"""
ADC Connection State Helpers
============================
Plain helpers for ADC runtime defaults and connection view-state snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass, replace, fields, field
from enum import Enum, auto


class ADCConnectionState(Enum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()


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
    parameters: dict = field(default_factory=dict)
    stream_diagnostics: dict = field(default_factory=dict)
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
    testboard_routes: list[tuple[int, int]] | None = None
    testboard_array: str | None = None
    testboard_scan_order: str | None = None
    testboard_sequence: str | None = None
    testboard_spi_clock_hz: int | None = None
    testboard_channel_repeat: int | None = None
    testboard_effective_repeat: int | None = None
    testboard_vmid: bool | None = None
    testboard_effective_vmid: bool | None = None
    testboard_engine: str | None = None
    testboard_route_count: int | None = None

    def copy(self) -> "ArduinoStatus":
        return replace(self)

    def apply(self, other: "ArduinoStatus") -> None:
        self.parameters = dict(other.parameters)
        self.stream_diagnostics = dict(other.stream_diagnostics)
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
        for item in fields(self):
            if item.name.startswith("testboard_"):
                value = getattr(other, item.name)
                setattr(self, item.name, list(value) if isinstance(value, list) else value)


@dataclass(slots=True)
class LastSentConfig:
    channels: list[int] | None = None
    repeat: int | None = None
    ground_pin: int | None = None
    use_ground: bool | None = None
    osr: int | None = None
    gain: int | None = None
    reference: str | None = None
    testboard_spi_clock_hz: int | None = None
    testboard_channel_repeat: int | None = None
    testboard_sequence: str | None = None
    testboard_array: str | None = None
    testboard_scan_order: str | None = None
    testboard_routes: list[tuple[int, int]] | None = None

    def copy(self) -> "LastSentConfig":
        return replace(self)


def build_default_last_sent_config() -> LastSentConfig:
    return LastSentConfig()


def build_default_arduino_status() -> ArduinoStatus:
    return ArduinoStatus()


def build_connected_view_state() -> ADCConnectionViewState:
    return ADCConnectionViewState(
        connect_button_text="Disconnect ADC",
        configure_enabled=True,
        configure_style="QPushButton { background-color: #2196F3; color: white; font-weight: bold; }",
        start_enabled=False,
        stop_enabled=False,
        status_message="Connected - Please configure",
        port_selection_enabled=False,
    )


def build_connecting_view_state() -> ADCConnectionViewState:
    return ADCConnectionViewState(
        connect_button_text="Connecting ADC...",
        configure_enabled=False,
        configure_style=None,
        start_enabled=False,
        stop_enabled=False,
        status_message="Connecting...",
        port_selection_enabled=False,
    )


def build_disconnected_view_state() -> ADCConnectionViewState:
    return ADCConnectionViewState(
        connect_button_text="Auto-connect ADC",
        configure_enabled=False,
        configure_style=None,
        start_enabled=False,
        stop_enabled=False,
        status_message="Disconnected",
        port_selection_enabled=True,
    )
