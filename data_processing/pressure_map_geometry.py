"""Shared immutable physical geometry for Pressure Map generation."""

from __future__ import annotations

from dataclasses import dataclass
from functools import reduce
import math

from constants.pressure_map import (
    DEFAULT_PRESSURE_PEAK_POSITION_OUTER_OFFSET_MM,
    DEFAULT_PRESSURE_OUTER_BOUNDARY_REACH_MM,
    DEFAULT_PRESSURE_PACKAGE_CENTER_SPACING_MM,
    DEFAULT_PRESSURE_PIXELS_PER_MM,
    DEFAULT_PRESSURE_SENSOR_SPACING_MM,
)


@dataclass(frozen=True, slots=True, init=False)
class PressureMapGeometry:
    """Validated physical layout shared by local and array pressure fields."""

    sensor_spacing_mm: float = DEFAULT_PRESSURE_SENSOR_SPACING_MM
    package_center_spacing_mm: float = DEFAULT_PRESSURE_PACKAGE_CENTER_SPACING_MM
    outer_boundary_reach_mm: float = DEFAULT_PRESSURE_OUTER_BOUNDARY_REACH_MM
    peak_position_outer_offset_mm: float = DEFAULT_PRESSURE_PEAK_POSITION_OUTER_OFFSET_MM
    pixels_per_mm: float = DEFAULT_PRESSURE_PIXELS_PER_MM

    def __init__(
        self,
        sensor_spacing_mm: float = DEFAULT_PRESSURE_SENSOR_SPACING_MM,
        package_center_spacing_mm: float = DEFAULT_PRESSURE_PACKAGE_CENTER_SPACING_MM,
        outer_boundary_reach_mm: float = DEFAULT_PRESSURE_OUTER_BOUNDARY_REACH_MM,
        peak_position_outer_offset_mm: float = DEFAULT_PRESSURE_PEAK_POSITION_OUTER_OFFSET_MM,
        pixels_per_mm: float = DEFAULT_PRESSURE_PIXELS_PER_MM,
        *,
        near_outer_peak_offset_mm: float | None = None,
    ) -> None:
        """Create physical geometry, accepting the retired offset name on input."""

        if near_outer_peak_offset_mm is not None:
            if (
                peak_position_outer_offset_mm != DEFAULT_PRESSURE_PEAK_POSITION_OUTER_OFFSET_MM
                and not math.isclose(
                    peak_position_outer_offset_mm, near_outer_peak_offset_mm
                )
            ):
                raise ValueError("conflicting outer peak-position offsets")
            peak_position_outer_offset_mm = near_outer_peak_offset_mm
        object.__setattr__(self, "sensor_spacing_mm", float(sensor_spacing_mm))
        object.__setattr__(self, "package_center_spacing_mm", float(package_center_spacing_mm))
        object.__setattr__(self, "outer_boundary_reach_mm", float(outer_boundary_reach_mm))
        object.__setattr__(self, "peak_position_outer_offset_mm", float(peak_position_outer_offset_mm))
        object.__setattr__(self, "pixels_per_mm", float(pixels_per_mm))
        self.__post_init__()

    @property
    def near_outer_peak_offset_mm(self) -> float:
        """Deprecated compatibility alias for the renamed offset."""

        return self.peak_position_outer_offset_mm

    def __post_init__(self) -> None:
        values = (
            self.sensor_spacing_mm,
            self.package_center_spacing_mm,
            self.outer_boundary_reach_mm,
            self.peak_position_outer_offset_mm,
            self.pixels_per_mm,
        )
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("pressure-map geometry values must be finite")
        if self.sensor_spacing_mm <= 0 or self.pixels_per_mm <= 0:
            raise ValueError("sensor_spacing_mm and pixels_per_mm must be positive")
        if self.package_center_spacing_mm <= 2 * self.sensor_spacing_mm:
            raise ValueError("package_center_spacing_mm must exceed twice sensor_spacing_mm")
        if self.outer_boundary_reach_mm <= 0 or self.peak_position_outer_offset_mm < 0:
            raise ValueError("outer boundary reach must be positive and peak-position offset non-negative")
        if self.near_outer_circle_radius_mm >= self.outer_boundary_half_width_mm:
            raise ValueError("peak_position_outer_offset_mm must remain inside the outer boundary")

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
        return self.virtual_outer_spacing_mm

    @property
    def virtual_outer_spacing_mm(self) -> float:
        """Outer virtual position used only for inferred peak locations."""

        return self.sensor_spacing_mm + self.peak_position_outer_offset_mm

    @property
    def support_bounds_mm(self) -> tuple[float, float, float, float]:
        half = self.outer_boundary_half_width_mm
        return (-half, half, -half, half)

    @property
    def core_bounds_mm(self) -> tuple[float, float, float, float]:
        """The physical sensor-square core before outward field extension."""

        half = self.sensor_spacing_mm
        return (-half, half, -half, half)

    @property
    def geometry_quantum_mm(self) -> float:
        """Smallest stable physical increment represented by this geometry.

        Values are first rounded to micrometres so configured decimal geometry
        remains reproducible across platforms.  Zero-valued optional offsets
        are excluded: zero must not collapse the GCD to a one-micrometre grid.
        """

        values_mm = (
            self.sensor_spacing_mm,
            self.package_center_spacing_mm,
            self.outer_boundary_reach_mm,
            self.peak_position_outer_offset_mm,
            self.mid_boundary_half_width_mm,
            self.outer_boundary_half_width_mm,
        )
        micrometres = [
            abs(int(round(float(value) * 1000.0)))
            for value in values_mm
            if abs(float(value)) > 0.0
        ]
        if not micrometres:
            return 0.001
        return reduce(math.gcd, micrometres) / 1000.0

    @property
    def requested_cell_size_mm(self) -> float:
        """Cell size requested by the caller before geometry alignment."""

        return 1.0 / self.pixels_per_mm

    @property
    def aligned_subdivisions(self) -> int:
        """Integer subdivisions needed to meet the requested raster density."""

        return max(1, int(math.ceil(self.geometry_quantum_mm / self.requested_cell_size_mm)))

    @property
    def aligned_cell_size_mm(self) -> float:
        """Geometry-aligned cell size at least as dense as requested."""

        return self.geometry_quantum_mm / self.aligned_subdivisions

    @property
    def actual_pixels_per_mm(self) -> float:
        """Actual raster density after aligning physical landmarks to samples."""

        return 1.0 / self.aligned_cell_size_mm
