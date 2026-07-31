"""Shared immutable physical geometry for Pressure Map generation."""

from __future__ import annotations

from dataclasses import dataclass
import math

from constants.pressure_map import (
    DEFAULT_PRESSURE_NEAR_OUTER_PEAK_OFFSET_MM,
    DEFAULT_PRESSURE_OUTER_BOUNDARY_REACH_MM,
    DEFAULT_PRESSURE_PACKAGE_CENTER_SPACING_MM,
    DEFAULT_PRESSURE_PIXELS_PER_MM,
    DEFAULT_PRESSURE_SENSOR_SPACING_MM,
)


@dataclass(frozen=True, slots=True)
class PressureMapGeometry:
    """Validated physical layout shared by local and array pressure fields."""

    sensor_spacing_mm: float = DEFAULT_PRESSURE_SENSOR_SPACING_MM
    package_center_spacing_mm: float = DEFAULT_PRESSURE_PACKAGE_CENTER_SPACING_MM
    outer_boundary_reach_mm: float = DEFAULT_PRESSURE_OUTER_BOUNDARY_REACH_MM
    near_outer_peak_offset_mm: float = DEFAULT_PRESSURE_NEAR_OUTER_PEAK_OFFSET_MM
    pixels_per_mm: float = DEFAULT_PRESSURE_PIXELS_PER_MM

    def __post_init__(self) -> None:
        values = (
            self.sensor_spacing_mm,
            self.package_center_spacing_mm,
            self.outer_boundary_reach_mm,
            self.near_outer_peak_offset_mm,
            self.pixels_per_mm,
        )
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("pressure-map geometry values must be finite")
        if self.sensor_spacing_mm <= 0 or self.pixels_per_mm <= 0:
            raise ValueError("sensor_spacing_mm and pixels_per_mm must be positive")
        if self.package_center_spacing_mm <= 2 * self.sensor_spacing_mm:
            raise ValueError("package_center_spacing_mm must exceed twice sensor_spacing_mm")
        if self.outer_boundary_reach_mm <= 0 or self.near_outer_peak_offset_mm < 0:
            raise ValueError("outer boundary reach must be positive and near-outer offset non-negative")
        if self.near_outer_circle_radius_mm >= self.outer_boundary_half_width_mm:
            raise ValueError("near_outer_peak_offset_mm must remain inside the outer boundary")

    @property
    def facing_sensor_gap_mm(self) -> float:
        return self.package_center_spacing_mm - (2 * self.sensor_spacing_mm)

    @property
    def mid_boundary_half_width_mm(self) -> float:
        return self.package_center_spacing_mm / 2.0

    @property
    def outer_boundary_half_width_mm(self) -> float:
        return self.mid_boundary_half_width_mm + self.outer_boundary_reach_mm

    @property
    def near_outer_circle_radius_mm(self) -> float:
        return self.sensor_spacing_mm + self.near_outer_peak_offset_mm

    @property
    def support_bounds_mm(self) -> tuple[float, float, float, float]:
        half = self.outer_boundary_half_width_mm
        return (-half, half, -half, half)
