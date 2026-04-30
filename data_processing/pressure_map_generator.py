"""
Pressure-grid generation from normalized five-sensor piezo signals.

This module builds a piecewise-linear 2D pressure surface for one sensor
package arranged as a cross. Each active quadrant is either a simple plane
through its three sensors, or a four-triangle fan through the center sensor,
two outer sensors, and a computed pressure point.

Dependencies:
    dataclasses, numpy, and constants.shear.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from constants.pressure_map import (
    DEFAULT_PRESSURE_DECAY_RATE,
    DEFAULT_PRESSURE_DECAY_REF_DISTANCE_MM,
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
)
from constants.shear import (
    DEFAULT_CIRCLE_DIAMETER_MM,
    SHEAR_POSITION_BOTTOM,
    SHEAR_POSITION_CENTER,
    SHEAR_POSITION_LEFT,
    SHEAR_POSITION_RIGHT,
    SHEAR_POSITION_TOP,
    SHEAR_SENSOR_POSITIONS,
    SHEAR_ZERO_VALUE,
)

DEFAULT_PRESSURE_SHOW_NEGATIVE = False
PRESSURE_GEOMETRY_EPSILON = 0.001
PRESSURE_QUADRANT_MODE_PEAKLESS = "peakless"
PRESSURE_QUADRANT_MODE_PEAKED = "peaked"


@dataclass(frozen=True, slots=True)
class PressureTrianglePlane:
    """Plane coefficients and vertices for one peaked-quadrant sub-triangle."""

    name: str
    a: float
    b: float
    c: float
    vertices: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]


@dataclass(frozen=True, slots=True)
class PressureQuadrantPlane:
    """Pressure surface metadata for one active pressure-map quadrant.

    The legacy ``a``, ``b`` and ``c`` fields remain available. For peakless
    quadrants they are the plane evaluated across the quadrant. For peaked
    quadrants they hold the 3-sensor base plane, while ``triangles`` contains
    the actual sub-triangle planes used for grid evaluation.
    """

    label: str
    a: float
    b: float
    c: float
    sign: float
    sensors: tuple[str, ...]
    mode: str = PRESSURE_QUADRANT_MODE_PEAKLESS
    peak_point: tuple[float, float] | None = None
    peak_height: float | None = None
    corner_value: float | None = None
    triangles: tuple[PressureTrianglePlane, ...] = ()
    single_outer_decay_sensor: str | None = None


@dataclass(frozen=True, slots=True)
class PressureMapResult:
    """Pressure-map output for one normalized five-sensor sample."""

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
    """Generate piecewise-linear pressure maps from normalized signals."""

    def __init__(
        self,
        *,
        circle_diameter_mm: float = DEFAULT_CIRCLE_DIAMETER_MM,
        sensor_spacing_mm: float = DEFAULT_PRESSURE_SENSOR_SPACING_MM,
        grid_margin: int = DEFAULT_PRESSURE_GRID_MARGIN,
        grid_resolution: int = DEFAULT_PRESSURE_GRID_RESOLUTION,
        decay_rate: float = DEFAULT_PRESSURE_DECAY_RATE,
        decay_ref_distance_mm: float = DEFAULT_PRESSURE_DECAY_REF_DISTANCE_MM,
        geometry_epsilon: float = PRESSURE_GEOMETRY_EPSILON,
        show_negative: bool = DEFAULT_PRESSURE_SHOW_NEGATIVE,
    ) -> None:
        self.circle_diameter_mm = float(circle_diameter_mm)
        self.sensor_spacing_mm = float(sensor_spacing_mm)
        self.grid_margin = int(grid_margin)
        self.grid_resolution = int(grid_resolution)
        self.decay_rate = float(decay_rate)
        self.decay_ref_distance_mm = float(decay_ref_distance_mm)
        self.geometry_epsilon = float(geometry_epsilon)
        self.show_negative = bool(show_negative)

        self._validate_parameters()
        self.sensor_positions = self._build_sensor_positions()
        self.quadrants = self._build_quadrant_definitions()
        self._quadrant_by_label = {quadrant.label: quadrant for quadrant in self.quadrants}
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
        """Generate a pressure map from one normalized five-sensor sample."""

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
        if self.decay_ref_distance_mm <= SHEAR_ZERO_VALUE:
            raise ValueError("decay_ref_distance_mm must be positive")
        if self.geometry_epsilon <= SHEAR_ZERO_VALUE:
            raise ValueError("geometry_epsilon must be positive")

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
            if self._quadrant_is_active(signals, quadrant):
                planes.append(self._build_quadrant_plane(signals, quadrant))
        return tuple(planes)

    def _quadrant_is_active(self, signals: Mapping[str, float], quadrant: _QuadrantDefinition) -> bool:
        values = [signals[sensor] for sensor in quadrant.sensors]
        nonzero_values = [value for value in values if value != SHEAR_ZERO_VALUE]
        if not nonzero_values:
            return False
        reference_sign = self._value_sign(nonzero_values[0])
        return all(self._value_sign(value) == reference_sign for value in nonzero_values[1:])

    def _build_quadrant_plane(
        self,
        signals: Mapping[str, float],
        quadrant: _QuadrantDefinition,
    ) -> PressureQuadrantPlane:
        base_a, base_b, base_c = self._three_sensor_plane_coefficients(signals, quadrant)
        sign = self._quadrant_sign(*(signals[sensor] for sensor in quadrant.sensors))
        single_outer_decay_sensor = self._single_outer_decay_sensor(signals, quadrant)
        peak_x, peak_y = self._pressure_point(signals, quadrant)
        if not self._is_peaked_pressure_point(peak_x, peak_y, quadrant):
            return PressureQuadrantPlane(
                label=quadrant.label,
                a=base_a,
                b=base_b,
                c=base_c,
                sign=sign,
                sensors=quadrant.sensors,
                single_outer_decay_sensor=single_outer_decay_sensor,
            )

        peak_height = self._pressure_point_height(signals, quadrant, peak_x, peak_y)
        triangles, corner_value = self._build_triangle_planes(
            signals,
            quadrant,
            peak_x,
            peak_y,
            peak_height,
        )
        if not triangles:
            return PressureQuadrantPlane(
                label=quadrant.label,
                a=base_a,
                b=base_b,
                c=base_c,
                sign=sign,
                sensors=quadrant.sensors,
                single_outer_decay_sensor=single_outer_decay_sensor,
            )
        return PressureQuadrantPlane(
            label=quadrant.label,
            a=base_a,
            b=base_b,
            c=base_c,
            sign=sign,
            sensors=quadrant.sensors,
            mode=PRESSURE_QUADRANT_MODE_PEAKED,
            peak_point=(peak_x, peak_y),
            peak_height=peak_height,
            corner_value=corner_value,
            triangles=triangles,
            single_outer_decay_sensor=single_outer_decay_sensor,
        )

    def _single_outer_decay_sensor(
        self,
        signals: Mapping[str, float],
        quadrant: _QuadrantDefinition,
    ) -> str | None:
        center_value = signals[SHEAR_POSITION_CENTER]
        horizontal_value = signals[quadrant.horizontal_sensor]
        vertical_value = signals[quadrant.vertical_sensor]
        center_is_zero = abs(center_value) <= self.geometry_epsilon
        horizontal_nonzero = abs(horizontal_value) > self.geometry_epsilon
        vertical_nonzero = abs(vertical_value) > self.geometry_epsilon
        if not center_is_zero:
            return None
        if horizontal_nonzero and not vertical_nonzero:
            return quadrant.horizontal_sensor
        if vertical_nonzero and not horizontal_nonzero:
            return quadrant.vertical_sensor
        return None

    def _three_sensor_plane_coefficients(
        self,
        signals: Mapping[str, float],
        quadrant: _QuadrantDefinition,
    ) -> tuple[float, float, float]:
        center_value = signals[SHEAR_POSITION_CENTER]
        horizontal_value = signals[quadrant.horizontal_sensor]
        vertical_value = signals[quadrant.vertical_sensor]
        spacing = self.sensor_spacing_mm
        a = quadrant.horizontal_sign * (horizontal_value - center_value) / spacing
        b = quadrant.vertical_sign * (vertical_value - center_value) / spacing
        return (float(a), float(b), float(center_value))

    def _pressure_point(
        self,
        signals: Mapping[str, float],
        quadrant: _QuadrantDefinition,
    ) -> tuple[float, float]:
        center_magnitude = self._pressure_magnitude(signals[SHEAR_POSITION_CENTER])
        horizontal_magnitude = self._pressure_magnitude(signals[quadrant.horizontal_sensor])
        vertical_magnitude = self._pressure_magnitude(signals[quadrant.vertical_sensor])
        x_denominator = horizontal_magnitude + center_magnitude
        y_denominator = vertical_magnitude + center_magnitude
        x_peak = (
            quadrant.horizontal_sign * self.sensor_spacing_mm * horizontal_magnitude / x_denominator
            if x_denominator != SHEAR_ZERO_VALUE
            else SHEAR_ZERO_VALUE
        )
        y_peak = (
            quadrant.vertical_sign * self.sensor_spacing_mm * vertical_magnitude / y_denominator
            if y_denominator != SHEAR_ZERO_VALUE
            else SHEAR_ZERO_VALUE
        )
        return (float(x_peak), float(y_peak))

    def _pressure_magnitude(self, value: float) -> float:
        if self.show_negative:
            return abs(value)
        return max(SHEAR_ZERO_VALUE, value)

    def _is_peaked_pressure_point(
        self,
        peak_x: float,
        peak_y: float,
        quadrant: _QuadrantDefinition,
    ) -> bool:
        local_x = peak_x * quadrant.horizontal_sign
        local_y = peak_y * quadrant.vertical_sign
        return local_x > self.geometry_epsilon and local_y > self.geometry_epsilon

    def _pressure_point_height(
        self,
        signals: Mapping[str, float],
        quadrant: _QuadrantDefinition,
        peak_x: float,
        peak_y: float,
    ) -> float:
        weighted_estimate_sum = 0.0
        weight_sum = 0.0
        for sensor in quadrant.sensors:
            sensor_x, sensor_y = self.sensor_positions[sensor]
            distance = float(np.hypot(sensor_x - peak_x, sensor_y - peak_y))
            estimate = signals[sensor] * (
                1.0 + self.decay_rate * distance / self.decay_ref_distance_mm
            )
            weight = 1.0 / max(self.geometry_epsilon, distance) ** 2
            weighted_estimate_sum += estimate * weight
            weight_sum += weight
        if weight_sum == SHEAR_ZERO_VALUE:
            return SHEAR_ZERO_VALUE
        return float(weighted_estimate_sum / weight_sum)

    def _build_triangle_planes(
        self,
        signals: Mapping[str, float],
        quadrant: _QuadrantDefinition,
        peak_x: float,
        peak_y: float,
        peak_height: float,
    ) -> tuple[tuple[PressureTrianglePlane, ...], float]:
        spacing = self.sensor_spacing_mm
        center = (SHEAR_ZERO_VALUE, SHEAR_ZERO_VALUE, signals[SHEAR_POSITION_CENTER])
        horizontal = (
            quadrant.horizontal_sign * spacing,
            SHEAR_ZERO_VALUE,
            signals[quadrant.horizontal_sensor],
        )
        vertical = (
            SHEAR_ZERO_VALUE,
            quadrant.vertical_sign * spacing,
            signals[quadrant.vertical_sensor],
        )
        peak = (peak_x, peak_y, peak_height)
        # Anchor outer corners at the margin boundary and force them to zero.
        # The square corners are outside the visible circular mask but still
        # shape the outer planes near the circle edge.
        half_extent = self.total_extent_mm / PRESSURE_GRID_MARGIN_SIDE_COUNT
        corner_xy = (
            quadrant.horizontal_sign * half_extent,
            quadrant.vertical_sign * half_extent,
        )
        corner_value = SHEAR_ZERO_VALUE
        corner = (corner_xy[0], corner_xy[1], corner_value)

        triangle_specs = (
            ("inner-x", center, horizontal, peak),
            ("inner-y", center, vertical, peak),
            ("outer-x", horizontal, corner, peak),
            ("outer-y", vertical, corner, peak),
        )
        triangles: list[PressureTrianglePlane] = []
        for name, first, second, third in triangle_specs:
            plane = self._solve_triangle_plane(name, first, second, third)
            if plane is not None:
                triangles.append(plane)
        return (tuple(triangles), corner_value)

    def _corner_value(
        self,
        horizontal: tuple[float, float, float],
        vertical: tuple[float, float, float],
        peak: tuple[float, float, float],
        corner_xy: tuple[float, float],
    ) -> float:
        plane = self._solve_triangle_plane("corner-source", horizontal, vertical, peak)
        if plane is None:
            return float((horizontal[2] + vertical[2]) / 2.0)
        return float((plane.a * corner_xy[0]) + (plane.b * corner_xy[1]) + plane.c)

    def _solve_triangle_plane(
        self,
        name: str,
        first: tuple[float, float, float],
        second: tuple[float, float, float],
        third: tuple[float, float, float],
    ) -> PressureTrianglePlane | None:
        matrix = np.array(
            [
                [first[0], first[1], 1.0],
                [second[0], second[1], 1.0],
                [third[0], third[1], 1.0],
            ],
            dtype=np.float64,
        )
        if abs(float(np.linalg.det(matrix))) < self.geometry_epsilon:
            return None
        values = np.array([first[2], second[2], third[2]], dtype=np.float64)
        a, b, c = np.linalg.solve(matrix, values)
        return PressureTrianglePlane(
            name=name,
            a=float(a),
            b=float(b),
            c=float(c),
            vertices=((first[0], first[1]), (second[0], second[1]), (third[0], third[1])),
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
            pressure_grid[region_mask] = self._evaluate_quadrant_for_region(
                plane,
                self.x_grid_mm[region_mask],
                self.y_grid_mm[region_mask],
            )
            filled_mask[region_mask] = True

        return pressure_grid

    def _evaluate_quadrant_for_region(
        self,
        plane: PressureQuadrantPlane,
        x_values_mm: np.ndarray,
        y_values_mm: np.ndarray,
    ) -> np.ndarray:
        if plane.mode == PRESSURE_QUADRANT_MODE_PEAKED and plane.triangles:
            values = self._evaluate_peaked_quadrant(plane, x_values_mm, y_values_mm)
        else:
            values = self._evaluate_plane(plane.a, plane.b, plane.c, x_values_mm, y_values_mm)
        values = self._apply_margin_decay(plane, x_values_mm, y_values_mm, values)
        return self._clamp_values(values, plane.sign)

    def _apply_margin_decay(
        self,
        plane: PressureQuadrantPlane,
        x_values_mm: np.ndarray,
        y_values_mm: np.ndarray,
        values: np.ndarray,
    ) -> np.ndarray:
        quadrant = self._quadrant_by_label.get(plane.label)
        if quadrant is None:
            return values

        half_extent = self.total_extent_mm / PRESSURE_GRID_MARGIN_SIDE_COUNT
        spacing = self.sensor_spacing_mm
        if half_extent <= spacing + self.geometry_epsilon:
            return values

        local_x = x_values_mm * quadrant.horizontal_sign
        local_y = y_values_mm * quadrant.vertical_sign
        decay_x = np.ones_like(values, dtype=np.float64)
        decay_y = np.ones_like(values, dtype=np.float64)
        denominator = max(self.geometry_epsilon, half_extent - spacing)

        x_mask = local_x > spacing
        y_mask = local_y > spacing
        decay_x[x_mask] = (half_extent - local_x[x_mask]) / denominator
        decay_y[y_mask] = (half_extent - local_y[y_mask]) / denominator
        decay = np.clip(decay_x, 0.0, 1.0) * np.clip(decay_y, 0.0, 1.0)

        if plane.single_outer_decay_sensor is not None:
            sensor_x, sensor_y = self.sensor_positions[plane.single_outer_decay_sensor]
            radial_distance = np.hypot(x_values_mm - sensor_x, y_values_mm - sensor_y)
            radial_range = max(self.geometry_epsilon, half_extent - spacing)
            side_decay = np.clip(1.0 - (radial_distance / radial_range), 0.0, 1.0)
            decay *= side_decay

        return values * decay

    def _evaluate_peaked_quadrant(
        self,
        plane: PressureQuadrantPlane,
        x_values_mm: np.ndarray,
        y_values_mm: np.ndarray,
    ) -> np.ndarray:
        values = np.empty_like(x_values_mm, dtype=np.float64)
        matched_mask = np.zeros_like(x_values_mm, dtype=bool)
        for triangle in plane.triangles:
            triangle_mask = (
                self._points_in_triangle(x_values_mm, y_values_mm, triangle.vertices)
                & ~matched_mask
            )
            if not np.any(triangle_mask):
                continue
            values[triangle_mask] = self._evaluate_plane(
                triangle.a,
                triangle.b,
                triangle.c,
                x_values_mm[triangle_mask],
                y_values_mm[triangle_mask],
            )
            matched_mask[triangle_mask] = True

        unmatched_indices = np.flatnonzero(~matched_mask)
        if unmatched_indices.size:
            self._evaluate_unmatched_peak_points(
                plane,
                x_values_mm,
                y_values_mm,
                values,
                unmatched_indices,
            )
        return values

    def _points_in_triangle(
        self,
        x_values_mm: np.ndarray,
        y_values_mm: np.ndarray,
        vertices: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
    ) -> np.ndarray:
        first, second, third = vertices
        s1 = self._cross(second, first, x_values_mm, y_values_mm)
        s2 = self._cross(third, second, x_values_mm, y_values_mm)
        s3 = self._cross(first, third, x_values_mm, y_values_mm)
        has_negative = (
            (s1 < -self.geometry_epsilon)
            | (s2 < -self.geometry_epsilon)
            | (s3 < -self.geometry_epsilon)
        )
        has_positive = (
            (s1 > self.geometry_epsilon)
            | (s2 > self.geometry_epsilon)
            | (s3 > self.geometry_epsilon)
        )
        return ~(has_negative & has_positive)

    def _cross(
        self,
        edge_end: tuple[float, float],
        edge_start: tuple[float, float],
        x_values_mm: np.ndarray,
        y_values_mm: np.ndarray,
    ) -> np.ndarray:
        return (
            (edge_end[0] - edge_start[0]) * (y_values_mm - edge_start[1])
            - (edge_end[1] - edge_start[1]) * (x_values_mm - edge_start[0])
        )

    def _evaluate_unmatched_peak_points(
        self,
        plane: PressureQuadrantPlane,
        x_values_mm: np.ndarray,
        y_values_mm: np.ndarray,
        values: np.ndarray,
        unmatched_indices: np.ndarray,
    ) -> None:
        outer_triangles = [triangle for triangle in plane.triangles if triangle.name.startswith("outer")]
        fallback_triangles = outer_triangles or list(plane.triangles)
        for index in unmatched_indices:
            triangle = self._nearest_triangle(
                fallback_triangles,
                float(x_values_mm[index]),
                float(y_values_mm[index]),
            )
            values[index] = self._evaluate_plane(
                triangle.a,
                triangle.b,
                triangle.c,
                x_values_mm[index],
                y_values_mm[index],
            )

    def _nearest_triangle(
        self,
        triangles: list[PressureTrianglePlane],
        x_value: float,
        y_value: float,
    ) -> PressureTrianglePlane:
        point = np.array([x_value, y_value], dtype=np.float64)
        distances = [
            float(np.linalg.norm(point - np.mean(np.array(triangle.vertices, dtype=np.float64), axis=0)))
            for triangle in triangles
        ]
        return triangles[int(np.argmin(distances))]

    def _evaluate_plane(
        self,
        a: float,
        b: float,
        c: float,
        x_values_mm: np.ndarray | float,
        y_values_mm: np.ndarray | float,
    ) -> np.ndarray | float:
        return (a * x_values_mm) + (b * y_values_mm) + c

    def _clamp_values(self, values: np.ndarray, sign: float) -> np.ndarray:
        if sign < SHEAR_ZERO_VALUE:
            return np.minimum(SHEAR_ZERO_VALUE, values)
        return np.maximum(SHEAR_ZERO_VALUE, values)
