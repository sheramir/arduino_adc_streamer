"""
Force Calibration State
=======================
Typed force-calibration state and persistence helpers.
Separate from force_state.py (which manages zero-offset load-cell calibration).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ForceCalibrationSignalSource = Literal["raw", "heatmap", "pressure_shear"]


@dataclass(slots=True)
class CalibrationRow:
    """One measured calibration entry: live 5-sensor readings and summary values."""
    
    sensor_family: Literal["PZT", "PZR", "Rosette"]
    sensor_number: int
    signal_source: ForceCalibrationSignalSource = "heatmap"
    sensor_top: float = 0.0
    sensor_bottom: float = 0.0
    sensor_left: float = 0.0
    sensor_right: float = 0.0
    sensor_center: float = 0.0
    sensor_total: float = 0.0
    max_force_x: float = 0.0  # Newtons
    max_force_z: float = 0.0  # Newtons
    max_sensor_value: float = 0.0  # integrated voltage (PZT), resistance (PZR/Rosette)
    min_sensor_value: float | None = None  # For PZR/Rosette: min resistance
    timestamp: float | None = None  # Unix timestamp when row was captured
    integration_samples: int = 0  # Snapshot of active integration window size
    array_number: int | None = None
    sensor_id: str | None = None


@dataclass(slots=True)
class ForceCalibrationState:
    """State for the Force Calibration tab."""
    
    # Persisted rows per sensor family
    pzt_calibration_rows: list[CalibrationRow] = field(default_factory=list)
    pzr_calibration_rows: list[CalibrationRow] = field(default_factory=list)
    rosette_calibration_rows: list[CalibrationRow] = field(default_factory=list)
    
    # Active measurement window state
    active_measurement_window: ActiveMeasurementWindow = field(default_factory=lambda: ActiveMeasurementWindow())
    active_row_index: int | None = None
    
    # UI state
    selected_sensor_family: Literal["PZT", "PZR", "Rosette"] = "PZT"
    selected_signal_source: ForceCalibrationSignalSource = "heatmap"
    selected_sensor_number: int = 1
    integration_samples: int = 10  # Number of samples to integrate for PZT
    is_capturing: bool = False
    
    # Autosave enable flag
    autosave_enabled: bool = True


@dataclass(slots=True)
class ActiveMeasurementWindow:
    """Tracks live sensor values during an active measurement window."""
    
    force_x_peaks: list[float] = field(default_factory=list)
    force_z_peaks: list[float] = field(default_factory=list)
    sensor_values: list[float] = field(default_factory=list)
    latest_sensor_values: list[float] = field(default_factory=list)
    latest_sensor_total: float = 0.0
    sample_count: int = 0

    def update_live_sensor_values(self, sensor_values: list[float], total_value: float | None = None) -> None:
        self.latest_sensor_values = [float(value) for value in sensor_values]
        self.latest_sensor_total = float(total_value if total_value is not None else sum(self.latest_sensor_values))
        self.sample_count += 1
    
    def get_max_force_x(self) -> float:
        return max(self.force_x_peaks) if self.force_x_peaks else 0.0
    
    def get_max_force_z(self) -> float:
        return max(self.force_z_peaks) if self.force_z_peaks else 0.0
    
    def get_max_sensor_value(self) -> float:
        return max(self.sensor_values) if self.sensor_values else 0.0
    
    def get_min_sensor_value(self) -> float | None:
        return min(self.sensor_values) if self.sensor_values else None
    
    def reset(self):
        """Clear all accumulated samples."""
        self.force_x_peaks.clear()
        self.force_z_peaks.clear()
        self.sensor_values.clear()
        self.latest_sensor_values.clear()
        self.latest_sensor_total = 0.0
        self.sample_count = 0


def build_default_force_calibration_state() -> ForceCalibrationState:
    """Build a fresh calibration state."""
    return ForceCalibrationState()


def get_calibration_rows_for_family(
    state: ForceCalibrationState, 
    family: Literal["PZT", "PZR", "Rosette"]
) -> list[CalibrationRow]:
    """Return the calibration rows for a given sensor family."""
    if family == "PZT":
        return state.pzt_calibration_rows
    elif family == "PZR":
        return state.pzr_calibration_rows
    else:  # Rosette
        return state.rosette_calibration_rows
