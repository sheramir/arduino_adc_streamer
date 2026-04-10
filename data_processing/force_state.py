"""
Force Runtime State
===================
Typed force-sensor runtime state plus a compatibility adapter for legacy mixins.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field

from config_constants import MAX_FORCE_SAMPLES


@dataclass(slots=True)
class ForceRuntimeState:
    data: collections.deque = field(
        default_factory=lambda: collections.deque(maxlen=MAX_FORCE_SAMPLES)
    )
    start_time: float | None = None
    calibration_offset: dict[str, float] = field(
        default_factory=lambda: {"x": 0.0, "z": 0.0}
    )
    calibrating: bool = False
    calibration_samples: dict[str, list[float]] = field(
        default_factory=lambda: {"x": [], "z": []}
    )
    disconnect_in_progress: bool = False
    raw_samples_seen: int = 0
    selected_port_text: str | None = None


def build_default_force_runtime_state() -> ForceRuntimeState:
    return ForceRuntimeState()


class LegacyForceRuntimeStateAdapter:
    """Map legacy scattered force attributes onto the new runtime-state shape."""

    def __init__(self, owner):
        self.owner = owner

    @property
    def data(self):
        return self.owner.force_data

    @data.setter
    def data(self, value):
        self.owner.force_data = value

    @property
    def start_time(self):
        return self.owner.force_start_time

    @start_time.setter
    def start_time(self, value):
        self.owner.force_start_time = value

    @property
    def calibration_offset(self):
        return self.owner.force_calibration_offset

    @calibration_offset.setter
    def calibration_offset(self, value):
        self.owner.force_calibration_offset = value

    @property
    def calibrating(self):
        return self.owner.force_calibrating

    @calibrating.setter
    def calibrating(self, value):
        self.owner.force_calibrating = bool(value)

    @property
    def calibration_samples(self):
        return self.owner.calibration_samples

    @calibration_samples.setter
    def calibration_samples(self, value):
        self.owner.calibration_samples = value

    @property
    def disconnect_in_progress(self):
        return self.owner._force_disconnect_in_progress

    @disconnect_in_progress.setter
    def disconnect_in_progress(self, value):
        self.owner._force_disconnect_in_progress = bool(value)

    @property
    def raw_samples_seen(self):
        return int(getattr(self.owner, "_force_raw_samples_seen", 0) or 0)

    @raw_samples_seen.setter
    def raw_samples_seen(self, value):
        self.owner._force_raw_samples_seen = int(value)

    @property
    def selected_port_text(self):
        return getattr(self.owner, "_force_selected_port_text", None)

    @selected_port_text.setter
    def selected_port_text(self, value):
        self.owner._force_selected_port_text = value


def get_force_runtime_state(owner) -> ForceRuntimeState | LegacyForceRuntimeStateAdapter:
    state = getattr(owner, "force_state", None)
    if state is not None:
        return state
    return LegacyForceRuntimeStateAdapter(owner)
