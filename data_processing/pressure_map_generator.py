"""
Pressure-grid generation from normalized five-sensor piezo signals.

This module implements the revised Step 6 backend using one linear plane per
quadrant instead of point peaks with radial decay kernels. Each active
quadrant fits an exact plane through its three sensor values and evaluates that
plane only inside the quadrant's spatial region. The circular grid geometry
and quadrant masks are precomputed at initialization so per-frame work stays
small.

Dependencies:
    dataclasses, numpy, and constants.shear.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from constants.shear import (
    DEFAULT_CIRCLE_DIAMETER_MM,
    DEFAULT_PRESSURE_GRID_MARGIN,
    DEFAULT_PRESSURE_GRID_RESOLUTION,
    DEFAULT_PRESSURE_SENSOR_SPACING_MM,
    PRESSURE_ACTIVE_QUADRANTS,
    PRESSURE_AXIS_NEGATIVE_DIRECTION,
    PRESSURE_AXIS_POSITIVE_DIRECTION,
    PRESSURE_GRID_MARGIN_SIDE_COUNT,
    PRESSURE_GRID_MIN_MARGIN,
    PRESSURE_GRID_MIN_RESOLUTION,
    PRESSURE_OUTSIDE_MASK_VALUE,
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
class PressureQuadrantPlane:
    """Plane coefficients for one active pressure-map quadrant.

    Args:
        label: Quadrant label such as ``TR`` or ``BL``.
        a: Plane x coefficient in ``z = a*x + b*y + c``.
        b: Plane y coefficient in ``z = a*x + b*y + c``.
        c: Plane offset, equal to the center sensor value.
        sign: Dominant sign of the nonzero quadrant sensors. Positive means
            compression-like values should be clamped at zero from below;
            negative means tension-like values should be clamped at zero from
            above.
        sensors: The three sensor positions used to fit the plane.

    Usage example:
        plane = PressureQuadrantPlane("TR", 1.0, 2.0, 3.0, 1.0, ("C", "R", "T"))
        assert plane.c == 3.0
    """

    label: str
    a: float
    b: float
    c: float
    sign: float
    sensors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PressureMapResult:
    """Pressure-map output for one normalized five-sensor sample.

    Args:
        pressure_grid: 2D pressure values with shape
            ``(total_grid_side, total_grid_side)``.
        circle_mask: Boolean mask for cells inside the extended circular map.
        active_quadrants: Quadrant labels that were active for this sample.
        quadrant_planes: Plane coefficients for the active quadrants.
        x_coordinates_mm: 1D grid x coordinates in millimeters.
        y_coordinates_mm: 1D grid y coordinates in millimeters.
        x_grid_mm: 2D x-coordinate mesh in millimeters.
        y_grid_mm: 2D y-coordinate mesh in millimeters.
        sensor_positions: Physical sensor coordinates keyed by position label.
        cell_size_mm: Grid cell size in millimeters.
        total_extent_mm: Diameter of the extended circular grid.

    Usage example:
        result = PressureMapGenerator().generate({"C": 10, "R": 5, "T": 3, "L": 0, "B": 0})
        assert result.active_quadrants
    """

    pressure_grid: np.ndarray
    circle_mask: np.ndarray
    active_quadrants: tuple[str, ...]
    quadrant_planes: tuple[PressureQuadrantPlane, ...]
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
    sensors: tuple[str, ...]


class PressureMapGenerator:
    """Generate piecewise-linear pressure maps from normalized signals.

    Args:
        circle_diameter_mm: Diameter of the sensor footprint circle.
        sensor_spacing_mm: Center-to-outer sensor spacing in millimeters.
        grid_margin: Extra cells beyond the sensor circle on each side.
        grid_resolution: Cells per side across the sensor circle diameter.

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
    ) -> None:
        self.circle_diameter_mm = float(circle_diameter_mm)
        self.sensor_spacing_mm = float(sensor_spacing_mm)
        self.grid_margin = int(grid_margin)
        self.grid_resolution = int(grid_resolution)

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
        self.quadrant_region_masks = self._build_quadrant_region_masks()

    def generate(self, normalized_signals: Mapping[str, float]) -> PressureMapResult:
        """Generate a pressure map from one normalized five-sensor sample.

        Args:
            normalized_signals: Mapping keyed by ``C``, ``L``, ``R``, ``T`` and
                ``B``. Missing positions are treated as zero.

        Returns:
            PressureMapResult containing the pressure grid, mask, active
            quadrant labels, active plane coefficients, and grid metadata.

        Raises:
            TypeError: If a supplied signal value cannot be converted to float.
        """
        signals = self._normalize_signals(normalized_signals)
        quadrant_planes = self._build_active_quadrant_planes(signals)
        pressure_grid = self._build_pressure_grid(quadrant_planes)
        return PressureMapResult(
            pressure_grid=pressure_grid,
            circle_mask=self.circle_mask.copy(),
            active_quadrants=tuple(plane.label for plane in quadrant_planes),
            quadrant_planes=quadrant_planes,
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
                (SHEAR_POSITION_CENTER, SHEAR_POSITION_RIGHT, SHEAR_POSITION_TOP),
            ),
            _QuadrantDefinition(
                PRESSURE_QUADRANT_TOP_LEFT,
                SHEAR_POSITION_LEFT,
                SHEAR_POSITION_TOP,
                PRESSURE_AXIS_NEGATIVE_DIRECTION,
                PRESSURE_AXIS_POSITIVE_DIRECTION,
                (SHEAR_POSITION_CENTER, SHEAR_POSITION_LEFT, SHEAR_POSITION_TOP),
            ),
            _QuadrantDefinition(
                PRESSURE_QUADRANT_BOTTOM_LEFT,
                SHEAR_POSITION_LEFT,
                SHEAR_POSITION_BOTTOM,
                PRESSURE_AXIS_NEGATIVE_DIRECTION,
                PRESSURE_AXIS_NEGATIVE_DIRECTION,
                (SHEAR_POSITION_CENTER, SHEAR_POSITION_LEFT, SHEAR_POSITION_BOTTOM),
            ),
            _QuadrantDefinition(
                PRESSURE_QUADRANT_BOTTOM_RIGHT,
                SHEAR_POSITION_RIGHT,
                SHEAR_POSITION_BOTTOM,
                PRESSURE_AXIS_POSITIVE_DIRECTION,
                PRESSURE_AXIS_NEGATIVE_DIRECTION,
                (SHEAR_POSITION_CENTER, SHEAR_POSITION_RIGHT, SHEAR_POSITION_BOTTOM),
            ),
        )

    def _build_quadrant_region_masks(self) -> dict[str, np.ndarray]:
        # The axis lines are intentionally shared between adjacent quadrants.
        # When both adjacent planes are active they evaluate to the same value
        # on the boundary; when only one is active, the shared masks let that
        # surviving plane fill the axis instead of leaving a zero-valued seam.
        return {
            PRESSURE_QUADRANT_TOP_RIGHT: (
                self.circle_mask
                & (self.x_grid_mm >= SHEAR_ZERO_VALUE)
                & (self.y_grid_mm >= SHEAR_ZERO_VALUE)
            ),
            PRESSURE_QUADRANT_TOP_LEFT: (
                self.circle_mask
                & (self.x_grid_mm <= SHEAR_ZERO_VALUE)
                & (self.y_grid_mm >= SHEAR_ZERO_VALUE)
            ),
            PRESSURE_QUADRANT_BOTTOM_LEFT: (
                self.circle_mask
                & (self.x_grid_mm <= SHEAR_ZERO_VALUE)
                & (self.y_grid_mm <= SHEAR_ZERO_VALUE)
            ),
            PRESSURE_QUADRANT_BOTTOM_RIGHT: (
                self.circle_mask
                & (self.x_grid_mm >= SHEAR_ZERO_VALUE)
                & (self.y_grid_mm <= SHEAR_ZERO_VALUE)
            ),
        }

    def _normalize_signals(self, normalized_signals: Mapping[str, float]) -> dict[str, float]:
        return {
            position: float(normalized_signals.get(position, SHEAR_ZERO_VALUE))
            for position in SHEAR_SENSOR_POSITIONS
        }

    def _build_active_quadrant_planes(
        self,
        signals: Mapping[str, float],
    ) -> tuple[PressureQuadrantPlane, ...]:
        planes: list[PressureQuadrantPlane] = []
        for quadrant in self.quadrants:
            if not self._quadrant_is_active(signals, quadrant):
                continue
            planes.append(self._build_quadrant_plane(signals, quadrant))
        return tuple(planes)

    def _quadrant_is_active(self, signals: Mapping[str, float], quadrant: _QuadrantDefinition) -> bool:
        values = [signals[sensor] for sensor in quadrant.sensors]
        nonzero_values = [value for value in values if value != SHEAR_ZERO_VALUE]
        if not nonzero_values:
            return False
        # Zero means "no detected pressure here", so only nonzero sign conflicts
        # should suppress a plane fit for the quadrant.
        reference_sign = self._value_sign(nonzero_values[0])
        return all(self._value_sign(value) == reference_sign for value in nonzero_values[1:])

    def _build_quadrant_plane(
        self,
        signals: Mapping[str, float],
        quadrant: _QuadrantDefinition,
    ) -> PressureQuadrantPlane:
        center_value = signals[SHEAR_POSITION_CENTER]
        horizontal_value = signals[quadrant.horizontal_sensor]
        vertical_value = signals[quadrant.vertical_sensor]
        spacing = self.sensor_spacing_mm
        # Because the center sensor sits at the origin, the plane coefficients
        # reduce to simple sensor-to-center slopes along the x and y axes.
        a = quadrant.horizontal_sign * (horizontal_value - center_value) / spacing
        b = quadrant.vertical_sign * (vertical_value - center_value) / spacing
        sign = self._quadrant_sign(center_value, horizontal_value, vertical_value)
        return PressureQuadrantPlane(
            label=quadrant.label,
            a=float(a),
            b=float(b),
            c=float(center_value),
            sign=sign,
            sensors=quadrant.sensors,
        )

    def _quadrant_sign(self, *values: float) -> float:
        for value in values:
            sign = self._value_sign(value)
            if sign != SHEAR_ZERO_VALUE:
                return sign
        return SHEAR_ZERO_VALUE

    def _value_sign(self, value: float) -> float:
        if value > SHEAR_ZERO_VALUE:
            return PRESSURE_AXIS_POSITIVE_DIRECTION
        if value < SHEAR_ZERO_VALUE:
            return PRESSURE_AXIS_NEGATIVE_DIRECTION
        return SHEAR_ZERO_VALUE

    def _build_pressure_grid(
        self,
        quadrant_planes: tuple[PressureQuadrantPlane, ...],
    ) -> np.ndarray:
        pressure_grid = np.full_like(self.x_grid_mm, PRESSURE_OUTSIDE_MASK_VALUE, dtype=np.float64)
        if not quadrant_planes:
            return pressure_grid

        plane_by_label = {plane.label: plane for plane in quadrant_planes}
        filled_mask = np.zeros_like(self.circle_mask, dtype=bool)
        for quadrant_label in PRESSURE_ACTIVE_QUADRANTS:
            plane = plane_by_label.get(quadrant_label)
            if plane is None:
                continue
            region_mask = self.quadrant_region_masks[quadrant_label] & ~filled_mask
            if not np.any(region_mask):
                continue
            pressure_grid[region_mask] = self._evaluate_plane_for_region(
                plane,
                self.x_grid_mm[region_mask],
                self.y_grid_mm[region_mask],
            )
            filled_mask[region_mask] = True

        return pressure_grid

    def _evaluate_plane_for_region(
        self,
        plane: PressureQuadrantPlane,
        x_values_mm: np.ndarray,
        y_values_mm: np.ndarray,
    ) -> np.ndarray:
        plane_values = (plane.a * x_values_mm) + (plane.b * y_values_mm) + plane.c
        if plane.sign < SHEAR_ZERO_VALUE:
            return np.minimum(SHEAR_ZERO_VALUE, plane_values)
        return np.maximum(SHEAR_ZERO_VALUE, plane_values)
