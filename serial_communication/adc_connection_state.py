"""
ADC Connection State Helpers
============================
Plain helpers for ADC runtime defaults and connection view-state snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ADCConnectionViewState:
    connect_button_text: str
    configure_enabled: bool
    configure_style: str | None
    start_enabled: bool
    stop_enabled: bool
    status_message: str
    port_selection_enabled: bool


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


def build_default_arduino_status() -> dict:
    return {
        "channels": None,
        "repeat": None,
        "ground_pin": None,
        "use_ground": None,
        "osr": None,
        "gain": None,
        "reference": None,
        "buffer": None,
        "rb": None,
        "rk": None,
        "cf": None,
        "rxmax": None,
    }


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
