"""
Pressure-grid generation from normalized five-sensor piezo signals.

This module implements Step 6 of the Shear & Pressure Map pipeline. It accepts
the normalized signals produced by ``NormalForceCalculator``, identifies active
quadrant peaks and isolated sensor fallback peaks, and renders an additive
decay-kernel pressure grid. The circular grid coordinates and mask are
precomputed at initialization so per-frame work stays small.

Dependencies:
    Python math utilities, dataclasses, numpy, and constants.shear.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math

import numpy as np

from constants.shear import (
    DEFAULT_CIRCLE_DIAMETER_MM,
    DEFAULT_PRESSURE_DECAY_RATE,
    DEFAULT_PRESSURE_DECAY_REF_DISTANCE_MM,
    DEFAULT_PRESSURE_GRID_MARGIN,
    DEFAULT_PRESSURE_GRID_RESOLUTION,
    DEFAULT_PRESSURE_IDW_POWER,
    DEFAULT_PRESSURE_SENSOR_SPACING_MM,
    PRESSURE_AXIS_NEGATIVE_DIRECTION,
    PRESSURE_AXIS_POSITIVE_DIRECTION,
    PRESSURE_DISTANCE_EPSILON_MM,
    PRESSURE_GRID_MARGIN_SIDE_COUNT,
    PRESSURE_GRID_MIN_MARGIN,
    PRESSURE_GRID_MIN_RESOLUTION,
    PRESSURE_KERNEL_CAP,
    PRESSURE_KERNEL_RADIUS_SENSOR_SPACING_DIVISOR,
    PRESSURE_OUTSIDE_MASK_VALUE,
    PRESSURE_PEAK_KIND_FALLBACK,
    PRESSURE_PEAK_KIND_QUADRANT,
    PRESSURE_QUADRANT_BOTTOM_LEFT,
    PRESSURE_QUADRANT_BOTTOM_RIGHT,
    PRESSURE_QUADRANT_TOP_LEFT,
    PRESSURE_QUADRANT_TOP_RIGHT,
    SHEAR_POSITION_BOTTOM,
    SHEAR_POSITION_CENTER,
    SHEAR_POSITION_LEFT,
    SHEAR_POSITION_RIGHT,
    SHEAR_POSITION_TOP,
    SHEAR_SENSOR_POSITIONS,
    SHEAR_ZERO_VALUE,
)


@dataclass(frozen=True, slots=True)
class PressurePeak:
    """Peak source used by the additive pressure-map kernel.

    Args:
        source: Quadrant label (``TR``, ``TL``, ``BL``, ``BR``) or sensor
            position label (``C``, ``L``, ``R``, ``T``, ``B``).
        kind: ``quadrant`` for ratio-estimated peaks or ``fallback`` for
            isolated single-sensor peaks.
        x_mm: Peak x coordinate in millimeters.
        y_mm: Peak y coordinate in millimeters.
        height: Signed peak height in force-like signal units.
        sensors: Sensor positions that contributed to this peak.

    Usage example:
        peak = PressurePeak("TR", "quadrant", 1.0, 1.0, 5.0, ("C", "R", "T"))
        assert peak.x_mm > 0.0
    """

    source: str
    kind: str
    x_mm: float
    y_mm: float
    height: float
    sensors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PressureMapResult:
    """Pressure-map output for one normalized five-sensor sample.

    Args:
        pressure_grid: 2D pressure values with shape
            ``(total_grid_side, total_grid_side)``.
        circle_mask: Boolean mask for cells inside the extended circular map.
        peaks: Active quadrant and fallback peaks used to build the grid.
        active_quadrants: Quadrant labels that were active before fallback
            peaks were added.
        x_coordinates_mm: 1D grid x coordinates in millimeters.
        y_coordinates_mm: 1D grid y coordinates in millimeters.
        x_grid_mm: 2D x-coordinate mesh in millimeters.
        y_grid_mm: 2D y-coordinate mesh in millimeters.
        sensor_positions: Physical sensor coordinates keyed by position label.
        cell_size_mm: Grid cell size in millimeters.
        total_extent_mm: Diameter of the extended circular grid.

    Usage example:
        result = PressureMapGenerator().generate({"C": 0, "R": 5, "T": 5, "L": 0, "B": 0})
        assert result.peaks
    """

    pressure_grid: np.ndarray
    circle_mask: np.ndarray
    peaks: tuple[PressurePeak, ...]
    active_quadrants: tuple[str, ...]
    x_coordinates_mm: np.ndarray
    y_coordinates_mm: np.ndarray
    x_grid_mm: np.ndarray
    y_grid_mm: np.ndarray
    sensor_positions: dict[str, tuple[float, float]]
    cell_size_mm: float
    total_extent_mm: float


@dataclass(frozen=True, slots=True)
class _QuadrantDefinition:
    label: str
    horizontal_sensor: str
    vertical_sensor: str
    horizontal_sign: float
    vertical_sign: float


class PressureMapGenerator:
    """Generate additive decay-kernel pressure maps from normalized signals.

    Args:
        circle_diameter_mm: Diameter of the sensor footprint circle.
        sensor_spacing_mm: Center-to-outer sensor spacing in millimeters.
        grid_margin: Extra cells beyond the sensor circle on each side.
        grid_resolution: Cells per side across the sensor circle diameter.
        idw_power: Exponent used for peak-height IDW and kernel decay.
        decay_rate: Signal decay factor used when extrapolating peak height.
        decay_ref_distance_mm: Reference distance for peak-height decay.
        peak_kernel_radius_mm: Kernel radius ``r0``. When ``None``, defaults to
            ``sensor_spacing_mm / 2``.

    Usage example:
        generator = PressureMapGenerator(grid_resolution=21, grid_margin=2)
        result = generator.generate({"C": 10, "R": 5, "T": 3, "L": 0, "B": 0})
    """

    def __init__(
        self,
        *,
        circle_diameter_mm: float = DEFAULT_CIRCLE_DIAMETER_MM,
        sensor_spacing_mm: float = DEFAULT_PRESSURE_SENSOR_SPACING_MM,
        grid_margin: int = DEFAULT_PRESSURE_GRID_MARGIN,
        grid_resolution: int = DEFAULT_PRESSURE_GRID_RESOLUTION,
        idw_power: float = DEFAULT_PRESSURE_IDW_POWER,
        decay_rate: float = DEFAULT_PRESSURE_DECAY_RATE,
        decay_ref_distance_mm: float = DEFAULT_PRESSURE_DECAY_REF_DISTANCE_MM,
        peak_kernel_radius_mm: float | None = None,
    ) -> None:
        self.circle_diameter_mm = float(circle_diameter_mm)
        self.sensor_spacing_mm = float(sensor_spacing_mm)
        self.grid_margin = int(grid_margin)
        self.grid_resolution = int(grid_resolution)
        self.idw_power = float(idw_power)
        self.decay_rate = float(decay_rate)
        self.decay_ref_distance_mm = float(decay_ref_distance_mm)
        self.peak_kernel_radius_mm = (
            float(peak_kernel_radius_mm)
            if peak_kernel_radius_mm is not None
            else self.sensor_spacing_mm / PRESSURE_KERNEL_RADIUS_SENSOR_SPACING_DIVISOR
        )

        self._validate_parameters()
        self.sensor_positions = self._build_sensor_positions()
        self.quadrants = self._build_quadrant_definitions()
        self.cell_size_mm = self.circle_diameter_mm / float(self.grid_resolution - 1)
        self.total_grid_side = self.grid_resolution + (
            PRESSURE_GRID_MARGIN_SIDE_COUNT * self.grid_margin
        )
        self.total_extent_mm = self.circle_diameter_mm + (
            PRESSURE_GRID_MARGIN_SIDE_COUNT * self.grid_margin * self.cell_size_mm
        )
        self.x_coordinates_mm = np.linspace(
            -self.total_extent_mm / PRESSURE_GRID_MARGIN_SIDE_COUNT,
            self.total_extent_mm / PRESSURE_GRID_MARGIN_SIDE_COUNT,
            self.total_grid_side,
            dtype=np.float64,
        )
        self.y_coordinates_mm = np.linspace(
            -self.total_extent_mm / PRESSURE_GRID_MARGIN_SIDE_COUNT,
            self.total_extent_mm / PRESSURE_GRID_MARGIN_SIDE_COUNT,
            self.total_grid_side,
            dtype=np.float64,
        )
        self.x_grid_mm, self.y_grid_mm = np.meshgrid(
            self.x_coordinates_mm,
            self.y_coordinates_mm,
        )
        self.circle_mask = (
            np.hypot(self.x_grid_mm, self.y_grid_mm)
            <= self.total_extent_mm / PRESSURE_GRID_MARGIN_SIDE_COUNT
        )

    def generate(self, normalized_signals: Mapping[str, float]) -> PressureMapResult:
        """Generate a pressure map from one normalized five-sensor sample.

        Args:
            normalized_signals: Mapping keyed by ``C``, ``L``, ``R``, ``T`` and
                ``B``. Missing positions are treated as zero.

        Returns:
            PressureMapResult containing the pressure grid, mask, active peaks,
            active quadrants, and grid coordinate metadata.

        Raises:
            TypeError: If a supplied signal value cannot be converted to float.
        """
        signals = self._normalize_signals(normalized_signals)
        quadrant_peaks, active_quadrants = self._build_quadrant_peaks(signals)
        peaks = tuple(quadrant_peaks + self._build_fallback_peaks(signals, active_quadrants))
        pressure_grid = self._build_pressure_grid(peaks)
        return PressureMapResult(
            pressure_grid=pressure_grid,
            circle_mask=self.circle_mask.copy(),
            peaks=peaks,
            active_quadrants=tuple(active_quadrants),
            x_coordinates_mm=self.x_coordinates_mm.copy(),
            y_coordinates_mm=self.y_coordinates_mm.copy(),
            x_grid_mm=self.x_grid_mm.copy(),
            y_grid_mm=self.y_grid_mm.copy(),
            sensor_positions=dict(self.sensor_positions),
            cell_size_mm=self.cell_size_mm,
            total_extent_mm=self.total_extent_mm,
        )

    def _validate_parameters(self) -> None:
        if self.grid_resolution < PRESSURE_GRID_MIN_RESOLUTION:
            raise ValueError("grid_resolution must be at least 2")
        if self.grid_margin < PRESSURE_GRID_MIN_MARGIN:
            raise ValueError("grid_margin must be non-negative")
        if self.circle_diameter_mm <= SHEAR_ZERO_VALUE:
            raise ValueError("circle_diameter_mm must be positive")
        if self.sensor_spacing_mm <= SHEAR_ZERO_VALUE:
            raise ValueError("sensor_spacing_mm must be positive")
        if self.idw_power <= SHEAR_ZERO_VALUE:
            raise ValueError("idw_power must be positive")
        if self.decay_ref_distance_mm <= SHEAR_ZERO_VALUE:
            raise ValueError("decay_ref_distance_mm must be positive")
        if self.peak_kernel_radius_mm <= SHEAR_ZERO_VALUE:
            raise ValueError("peak_kernel_radius_mm must be positive")

    def _build_sensor_positions(self) -> dict[str, tuple[float, float]]:
        spacing = self.sensor_spacing_mm
        return {
            SHEAR_POSITION_CENTER: (SHEAR_ZERO_VALUE, SHEAR_ZERO_VALUE),
            SHEAR_POSITION_LEFT: (-spacing, SHEAR_ZERO_VALUE),
            SHEAR_POSITION_RIGHT: (spacing, SHEAR_ZERO_VALUE),
            SHEAR_POSITION_TOP: (SHEAR_ZERO_VALUE, spacing),
            SHEAR_POSITION_BOTTOM: (SHEAR_ZERO_VALUE, -spacing),
        }

    def _build_quadrant_definitions(self) -> tuple[_QuadrantDefinition, ...]:
        return (
            _QuadrantDefinition(
                PRESSURE_QUADRANT_TOP_RIGHT,
                SHEAR_POSITION_RIGHT,
                SHEAR_POSITION_TOP,
                PRESSURE_AXIS_POSITIVE_DIRECTION,
                PRESSURE_AXIS_POSITIVE_DIRECTION,
            ),
            _QuadrantDefinition(
                PRESSURE_QUADRANT_TOP_LEFT,
                SHEAR_POSITION_LEFT,
                SHEAR_POSITION_TOP,
                PRESSURE_AXIS_NEGATIVE_DIRECTION,
                PRESSURE_AXIS_POSITIVE_DIRECTION,
            ),
            _QuadrantDefinition(
                PRESSURE_QUADRANT_BOTTOM_LEFT,
                SHEAR_POSITION_LEFT,
                SHEAR_POSITION_BOTTOM,
                PRESSURE_AXIS_NEGATIVE_DIRECTION,
                PRESSURE_AXIS_NEGATIVE_DIRECTION,
            ),
            _QuadrantDefinition(
                PRESSURE_QUADRANT_BOTTOM_RIGHT,
                SHEAR_POSITION_RIGHT,
                SHEAR_POSITION_BOTTOM,
                PRESSURE_AXIS_POSITIVE_DIRECTION,
                PRESSURE_AXIS_NEGATIVE_DIRECTION,
            ),
        )

    def _normalize_signals(self, normalized_signals: Mapping[str, float]) -> dict[str, float]:
        return {
            position: float(normalized_signals.get(position, SHEAR_ZERO_VALUE))
            for position in SHEAR_SENSOR_POSITIONS
        }

    def _build_quadrant_peaks(
        self,
        signals: Mapping[str, float],
    ) -> tuple[list[PressurePeak], list[str]]:
        peaks: list[PressurePeak] = []
        active_quadrants: list[str] = []
        for quadrant in self.quadrants:
            if not self._quadrant_is_active(signals, quadrant):
                continue
            peak = self._build_quadrant_peak(signals, quadrant)
            peaks.append(peak)
            active_quadrants.append(quadrant.label)
        return peaks, active_quadrants

    def _quadrant_is_active(self, signals: Mapping[str, float], quadrant: _QuadrantDefinition) -> bool:
        horizontal_value = signals[quadrant.horizontal_sensor]
        vertical_value = signals[quadrant.vertical_sensor]
        center_value = signals[SHEAR_POSITION_CENTER]
        if not self._same_nonzero_sign(horizontal_value, vertical_value):
            return False
        if center_value == SHEAR_ZERO_VALUE:
            return True
        return self._same_sign(center_value, horizontal_value)

    def _same_nonzero_sign(self, first_value: float, second_value: float) -> bool:
        return (
            first_value != SHEAR_ZERO_VALUE
            and second_value != SHEAR_ZERO_VALUE
            and self._same_sign(first_value, second_value)
        )

    def _same_sign(self, first_value: float, second_value: float) -> bool:
        return (
            (first_value > SHEAR_ZERO_VALUE and second_value > SHEAR_ZERO_VALUE)
            or (first_value < SHEAR_ZERO_VALUE and second_value < SHEAR_ZERO_VALUE)
        )

    def _build_quadrant_peak(
        self,
        signals: Mapping[str, float],
        quadrant: _QuadrantDefinition,
    ) -> PressurePeak:
        center_value = signals[SHEAR_POSITION_CENTER]
        horizontal_value = signals[quadrant.horizontal_sensor]
        vertical_value = signals[quadrant.vertical_sensor]
        x_peak = quadrant.horizontal_sign * self._axis_peak_offset(horizontal_value, center_value)
        y_peak = quadrant.vertical_sign * self._axis_peak_offset(vertical_value, center_value)
        contributing_sensors = (
            SHEAR_POSITION_CENTER,
            quadrant.horizontal_sensor,
            quadrant.vertical_sensor,
        )
        peak_height = self._estimate_peak_height(
            signals,
            contributing_sensors,
            x_peak,
            y_peak,
        )
        return PressurePeak(
            source=quadrant.label,
            kind=PRESSURE_PEAK_KIND_QUADRANT,
            x_mm=x_peak,
            y_mm=y_peak,
            height=peak_height,
            sensors=contributing_sensors,
        )

    def _axis_peak_offset(self, outer_value: float, center_value: float) -> float:
        denominator = outer_value + center_value
        if denominator == SHEAR_ZERO_VALUE:
            return SHEAR_ZERO_VALUE
        return self.sensor_spacing_mm * outer_value / denominator

    def _estimate_peak_height(
        self,
        signals: Mapping[str, float],
        sensors: tuple[str, ...],
        x_peak: float,
        y_peak: float,
    ) -> float:
        weighted_sum = SHEAR_ZERO_VALUE
        weight_total = SHEAR_ZERO_VALUE
        for sensor in sensors:
            sensor_x, sensor_y = self.sensor_positions[sensor]
            distance = math.hypot(x_peak - sensor_x, y_peak - sensor_y)
            estimate = signals[sensor] * (
                PRESSURE_KERNEL_CAP
                + (self.decay_rate * distance / self.decay_ref_distance_mm)
            )
            weight = PRESSURE_KERNEL_CAP / (
                max(PRESSURE_DISTANCE_EPSILON_MM, distance) ** self.idw_power
            )
            weighted_sum += estimate * weight
            weight_total += weight
        if weight_total == SHEAR_ZERO_VALUE:
            return SHEAR_ZERO_VALUE
        return weighted_sum / weight_total

    def _build_fallback_peaks(
        self,
        signals: Mapping[str, float],
        active_quadrants: list[str],
    ) -> list[PressurePeak]:
        covered_sensors = self._covered_sensors(active_quadrants)
        peaks: list[PressurePeak] = []
        for sensor in SHEAR_SENSOR_POSITIONS:
            sensor_value = signals[sensor]
            if sensor_value == SHEAR_ZERO_VALUE or sensor in covered_sensors:
                continue
            sensor_x, sensor_y = self.sensor_positions[sensor]
            peaks.append(
                PressurePeak(
                    source=sensor,
                    kind=PRESSURE_PEAK_KIND_FALLBACK,
                    x_mm=sensor_x,
                    y_mm=sensor_y,
                    height=sensor_value,
                    sensors=(sensor,),
                )
            )
        return peaks

    def _covered_sensors(self, active_quadrants: list[str]) -> set[str]:
        covered: set[str] = set()
        if active_quadrants:
            covered.add(SHEAR_POSITION_CENTER)
        if PRESSURE_QUADRANT_TOP_LEFT in active_quadrants or PRESSURE_QUADRANT_BOTTOM_LEFT in active_quadrants:
            covered.add(SHEAR_POSITION_LEFT)
        if PRESSURE_QUADRANT_TOP_RIGHT in active_quadrants or PRESSURE_QUADRANT_BOTTOM_RIGHT in active_quadrants:
            covered.add(SHEAR_POSITION_RIGHT)
        if PRESSURE_QUADRANT_TOP_RIGHT in active_quadrants or PRESSURE_QUADRANT_TOP_LEFT in active_quadrants:
            covered.add(SHEAR_POSITION_TOP)
        if PRESSURE_QUADRANT_BOTTOM_LEFT in active_quadrants or PRESSURE_QUADRANT_BOTTOM_RIGHT in active_quadrants:
            covered.add(SHEAR_POSITION_BOTTOM)
        return covered

    def _build_pressure_grid(self, peaks: tuple[PressurePeak, ...]) -> np.ndarray:
        pressure_grid = np.zeros_like(self.x_grid_mm, dtype=np.float64)
        for peak in peaks:
            distance = np.hypot(self.x_grid_mm - peak.x_mm, self.y_grid_mm - peak.y_mm)
            kernel = np.minimum(
                PRESSURE_KERNEL_CAP,
                (
                    self.peak_kernel_radius_mm
                    / np.maximum(PRESSURE_DISTANCE_EPSILON_MM, distance)
                ) ** self.idw_power,
            )
            pressure_grid += float(peak.height) * kernel
        return np.where(self.circle_mask, pressure_grid, PRESSURE_OUTSIDE_MASK_VALUE)
