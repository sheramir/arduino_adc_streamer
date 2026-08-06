"""
Force Connection State Helpers
==============================
Plain helpers for force connection view-state snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class ForceConnectionState(Enum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()


@dataclass(frozen=True, slots=True)
class ForceConnectionViewState:
    connect_button_text: str
    port_selection_enabled: bool
    reset_button_enabled: bool


def build_force_connected_view_state() -> ForceConnectionViewState:
    return ForceConnectionViewState(
        connect_button_text="Disconnect Force",
        port_selection_enabled=False,
        reset_button_enabled=True,
    )


def build_force_disconnected_view_state() -> ForceConnectionViewState:
    return ForceConnectionViewState(
        connect_button_text="Auto-connect Force",
        port_selection_enabled=True,
        reset_button_enabled=False,
    )
