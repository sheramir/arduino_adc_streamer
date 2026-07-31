"""Pressure-grid generation for one five-sensor pressure package.

The visible circle/square is deliberately separate from the numerical
pressure field.  A package field is evaluated over its whole local grid and
is only limited by a continuous support envelope.  Array generation can reuse
the retained plane data to evaluate the same package over larger world-space
supports before blending overlapping candidates.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from constants.pressure_map import (
    DEFAULT_PRESSURE_DECAY_RATE,
    DEFAULT_PRESSURE_DECAY_REF_DISTANCE_MM,
    DEFAULT_PRESSURE_NEAR_OUTER_PEAK_OFFSET_MM,
    DEFAULT_PRESSURE_OUTER_BOUNDARY_REACH_MM,
    DEFAULT_PRESSURE_PACKAGE_CENTER_SPACING_MM,
    DEFAULT_PRESSURE_PIXELS_PER_MM,
    DEFAULT_PRESSURE_SENSOR_SPACING_MM,
    DEFAULT_PRESSURE_SHOW_NEGATIVE,
    PRESSURE_ACTIVE_QUADRANTS,
    PRESSURE_AXIS_NEGATIVE_DIRECTION,
    PRESSURE_AXIS_POSITIVE_DIRECTION,
    PRESSURE_OUTSIDE_MASK_VALUE,
    PRESSURE_QUADRANT_BOTTOM_LEFT,
    PRESSURE_QUADRANT_BOTTOM_RIGHT,
    PRESSURE_QUADRANT_TOP_LEFT,
    PRESSURE_QUADRANT_TOP_RIGHT,
)
from constants.shear import (
    SHEAR_POSITION_BOTTOM,
    SHEAR_POSITION_CENTER,
    SHEAR_POSITION_LEFT,
    SHEAR_POSITION_RIGHT,
    SHEAR_POSITION_TOP,
    SHEAR_SENSOR_POSITIONS,
    SHEAR_ZERO_VALUE,
)


PRESSURE_GEOMETRY_EPSILON = 0.001
PRESSURE_QUADRANT_MODE_PEAKLESS = "peakless"
PRESSURE_QUADRANT_MODE_PEAKED = "peaked"
PRESSURE_QUADRANT_MODE_SINGLE_AXIS_PEAKED = "single-axis-peaked"
PRESSURE_QUADRANT_MODE_ISOLATED_OUTER_PEAKED = "isolated-outer-peaked"


@dataclass(frozen=True, slots=True)
class PressureTrianglePlane:
    """Plane coefficients and vertices for one peaked-quadrant triangle."""

    name: str
    a: float
    b: float
    c: float
    vertices: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]


@dataclass(frozen=True, slots=True)
class PressureQuadrantPlane:
    """Pressure surface metadata for one quadrant or isolated outer response."""

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
    single_axis_peak_sensor: str | None = None
    single_axis_center_value: float | None = None
    single_axis_outer_value: float | None = None


@dataclass(frozen=True, slots=True)
class PressureMapResult:
    """Pressure-map output and enough geometry to re-evaluate candidates."""

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
    visual_boundary_radius_mm: float
    support_bounds_mm: tuple[float, float, float, float]
    sensor_spacing_mm: float
    package_center_spacing_mm: float
    outer_boundary_reach_mm: float
    pixels_per_mm: float
    facing_sensor_gap_mm: float
    mid_boundary_half_width_mm: float
    outer_boundary_half_width_mm: float
    decay_rate: float
    decay_ref_distance_mm: float
    geometry_epsilon: float
    show_negative: bool
    near_outer_peak_offset_mm: float


@dataclass(frozen=True, slots=True)
class _QuadrantDefinition:
    label: str
    horizontal_sensor: str
    vertical_sensor: str
    horizontal_sign: float
    vertical_sign: float
    sensors: tuple[str, ...]


class PressureMapGenerator:
    """Generate a continuous, signed pressure candidate for one package."""

    def __init__(
        self,
        *,
        sensor_spacing_mm: float = DEFAULT_PRESSURE_SENSOR_SPACING_MM,
        package_center_spacing_mm: float = DEFAULT_PRESSURE_PACKAGE_CENTER_SPACING_MM,
        outer_boundary_reach_mm: float = DEFAULT_PRESSURE_OUTER_BOUNDARY_REACH_MM,
        pixels_per_mm: float = DEFAULT_PRESSURE_PIXELS_PER_MM,
        decay_rate: float = DEFAULT_PRESSURE_DECAY_RATE,
        decay_ref_distance_mm: float = DEFAULT_PRESSURE_DECAY_REF_DISTANCE_MM,
        near_outer_peak_offset_mm: float = DEFAULT_PRESSURE_NEAR_OUTER_PEAK_OFFSET_MM,
        geometry_epsilon: float = PRESSURE_GEOMETRY_EPSILON,
        show_negative: bool = DEFAULT_PRESSURE_SHOW_NEGATIVE,
    ) -> None:
        self.sensor_spacing_mm = float(sensor_spacing_mm)
        self.package_center_spacing_mm = float(package_center_spacing_mm)
        self.outer_boundary_reach_mm = float(outer_boundary_reach_mm)
        self.pixels_per_mm = float(pixels_per_mm)
        self.decay_rate = float(decay_rate)
        self.decay_ref_distance_mm = float(decay_ref_distance_mm)
        self.near_outer_peak_offset_mm = float(near_outer_peak_offset_mm)
        self.geometry_epsilon = float(geometry_epsilon)
        self.show_negative = bool(show_negative)

        self._validate_parameters()
        self.sensor_positions = self._build_sensor_positions()
        self.quadrants = self._build_quadrant_definitions()
        self._quadrant_by_label = {quadrant.label: quadrant for quadrant in self.quadrants}
        self.facing_sensor_gap_mm = self.package_center_spacing_mm - (2.0 * self.sensor_spacing_mm)
        self.mid_boundary_half_width_mm = self.package_center_spacing_mm / 2.0
        self.outer_boundary_half_width_mm = (
            self.mid_boundary_half_width_mm + self.outer_boundary_reach_mm
        )
        self.visual_boundary_radius_mm = (
            self.sensor_spacing_mm + self.near_outer_peak_offset_mm
        )
        self.half_intervals = int(np.ceil(self.outer_boundary_half_width_mm * self.pixels_per_mm))
        self.total_grid_side = (2 * self.half_intervals) + 1
        self.cell_size_mm = self.outer_boundary_half_width_mm / float(self.half_intervals)
        self.total_extent_mm = self.outer_boundary_half_width_mm * 2.0
        self.support_bounds_mm = (
            -self.outer_boundary_half_width_mm,
            self.outer_boundary_half_width_mm,
            -self.outer_boundary_half_width_mm,
            self.outer_boundary_half_width_mm,
        )
        self.x_coordinates_mm = np.linspace(
            -self.outer_boundary_half_width_mm,
            self.outer_boundary_half_width_mm,
            self.total_grid_side,
            dtype=np.float64,
        )
        self.y_coordinates_mm = np.linspace(
            -self.outer_boundary_half_width_mm,
            self.outer_boundary_half_width_mm,
            self.total_grid_side,
            dtype=np.float64,
        )
        self.x_grid_mm, self.y_grid_mm = np.meshgrid(self.x_coordinates_mm, self.y_coordinates_mm)
        # Retained as display metadata only; it never clips the pressure field.
        self.circle_mask = np.hypot(self.x_grid_mm, self.y_grid_mm) <= self.visual_boundary_radius_mm

    def generate(self, normalized_signals: Mapping[str, float]) -> PressureMapResult:
        """Generate one local package field from thresholded/calibrated signals."""

        signals = self._normalize_signals(normalized_signals)
        quadrant_planes = self._build_active_quadrant_planes(signals)
        pressure_grid = self._evaluate_planes_at(
            quadrant_planes,
            self.x_grid_mm,
            self.y_grid_mm,
            support_bounds_mm=self.support_bounds_mm,
        )
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
            # The near-outer overlay follows the inferred peak, not the
            # optional visual/package footprint diameter.
            visual_boundary_radius_mm=self.visual_boundary_radius_mm,
            support_bounds_mm=self.support_bounds_mm,
            sensor_spacing_mm=self.sensor_spacing_mm,
            package_center_spacing_mm=self.package_center_spacing_mm,
            outer_boundary_reach_mm=self.outer_boundary_reach_mm,
            pixels_per_mm=self.pixels_per_mm,
            facing_sensor_gap_mm=self.facing_sensor_gap_mm,
            mid_boundary_half_width_mm=self.mid_boundary_half_width_mm,
            outer_boundary_half_width_mm=self.outer_boundary_half_width_mm,
            decay_rate=self.decay_rate,
            decay_ref_distance_mm=self.decay_ref_distance_mm,
            geometry_epsilon=self.geometry_epsilon,
            show_negative=self.show_negative,
            near_outer_peak_offset_mm=self.near_outer_peak_offset_mm,
        )

    def _validate_parameters(self) -> None:
        if self.sensor_spacing_mm <= SHEAR_ZERO_VALUE:
            raise ValueError("sensor_spacing_mm must be positive")
        if self.package_center_spacing_mm <= 2.0 * self.sensor_spacing_mm:
            raise ValueError("package_center_spacing_mm must exceed twice sensor_spacing_mm")
        if self.outer_boundary_reach_mm <= SHEAR_ZERO_VALUE:
            raise ValueError("outer_boundary_reach_mm must be positive")
        if self.pixels_per_mm <= SHEAR_ZERO_VALUE:
            raise ValueError("pixels_per_mm must be positive")
        if self.decay_ref_distance_mm <= SHEAR_ZERO_VALUE:
            raise ValueError("decay_ref_distance_mm must be positive")
        if self.near_outer_peak_offset_mm < SHEAR_ZERO_VALUE:
            raise ValueError("near_outer_peak_offset_mm must be non-negative")
        if (
            self.sensor_spacing_mm + self.near_outer_peak_offset_mm
            >= (self.package_center_spacing_mm / 2.0) + self.outer_boundary_reach_mm
        ):
            raise ValueError("near_outer_peak_offset_mm must remain inside the outer boundary")
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
            _QuadrantDefinition(PRESSURE_QUADRANT_TOP_RIGHT, SHEAR_POSITION_RIGHT, SHEAR_POSITION_TOP, 1.0, 1.0, (SHEAR_POSITION_CENTER, SHEAR_POSITION_RIGHT, SHEAR_POSITION_TOP)),
            _QuadrantDefinition(PRESSURE_QUADRANT_TOP_LEFT, SHEAR_POSITION_LEFT, SHEAR_POSITION_TOP, -1.0, 1.0, (SHEAR_POSITION_CENTER, SHEAR_POSITION_LEFT, SHEAR_POSITION_TOP)),
            _QuadrantDefinition(PRESSURE_QUADRANT_BOTTOM_LEFT, SHEAR_POSITION_LEFT, SHEAR_POSITION_BOTTOM, -1.0, -1.0, (SHEAR_POSITION_CENTER, SHEAR_POSITION_LEFT, SHEAR_POSITION_BOTTOM)),
            _QuadrantDefinition(PRESSURE_QUADRANT_BOTTOM_RIGHT, SHEAR_POSITION_RIGHT, SHEAR_POSITION_BOTTOM, 1.0, -1.0, (SHEAR_POSITION_CENTER, SHEAR_POSITION_RIGHT, SHEAR_POSITION_BOTTOM)),
        )

    def _normalize_signals(self, normalized_signals: Mapping[str, float]) -> dict[str, float]:
        return {position: float(normalized_signals.get(position, SHEAR_ZERO_VALUE)) for position in SHEAR_SENSOR_POSITIONS}

    def _build_active_quadrant_planes(self, signals: Mapping[str, float]) -> tuple[PressureQuadrantPlane, ...]:
        isolated_sensor = self._isolated_outer_sensor(signals)
        if isolated_sensor is not None:
            return (self._build_isolated_outer_plane(signals, isolated_sensor),)

        planes: list[PressureQuadrantPlane] = []
        for quadrant in self.quadrants:
            if self._quadrant_is_active(signals, quadrant):
                planes.append(self._build_quadrant_plane(signals, quadrant))
        return tuple(planes)

    def _isolated_outer_sensor(self, signals: Mapping[str, float]) -> str | None:
        outer_sensors = (SHEAR_POSITION_LEFT, SHEAR_POSITION_RIGHT, SHEAR_POSITION_TOP, SHEAR_POSITION_BOTTOM)
        active = [sensor for sensor in outer_sensors if signals[sensor] != SHEAR_ZERO_VALUE]
        if signals[SHEAR_POSITION_CENTER] != SHEAR_ZERO_VALUE or len(active) != 1:
            return None
        return active[0]

    def _build_isolated_outer_plane(self, signals: Mapping[str, float], sensor: str) -> PressureQuadrantPlane:
        sensor_x, sensor_y = self.sensor_positions[sensor]
        if sensor == SHEAR_POSITION_RIGHT:
            peak_point = (sensor_x + self.near_outer_peak_offset_mm, sensor_y)
        elif sensor == SHEAR_POSITION_LEFT:
            peak_point = (sensor_x - self.near_outer_peak_offset_mm, sensor_y)
        elif sensor == SHEAR_POSITION_TOP:
            peak_point = (sensor_x, sensor_y + self.near_outer_peak_offset_mm)
        else:
            peak_point = (sensor_x, sensor_y - self.near_outer_peak_offset_mm)
        value = float(signals[sensor])
        return PressureQuadrantPlane(
            label=sensor,
            a=0.0,
            b=0.0,
            c=0.0,
            sign=self._value_sign(value),
            sensors=(SHEAR_POSITION_CENTER, sensor),
            mode=PRESSURE_QUADRANT_MODE_ISOLATED_OUTER_PEAKED,
            peak_point=peak_point,
            peak_height=value,
            single_axis_peak_sensor=sensor,
            single_axis_center_value=0.0,
            single_axis_outer_value=value,
        )

    def _quadrant_is_active(self, signals: Mapping[str, float], quadrant: _QuadrantDefinition) -> bool:
        values = [signals[sensor] for sensor in quadrant.sensors]
        nonzero_values = [value for value in values if value != SHEAR_ZERO_VALUE]
        if not nonzero_values:
            return False
        reference_sign = self._value_sign(nonzero_values[0])
        return all(self._value_sign(value) == reference_sign for value in nonzero_values[1:])

    def _build_quadrant_plane(self, signals: Mapping[str, float], quadrant: _QuadrantDefinition) -> PressureQuadrantPlane:
        base_a, base_b, base_c = self._three_sensor_plane_coefficients(signals, quadrant)
        sign = self._quadrant_sign(*(signals[sensor] for sensor in quadrant.sensors))
        single_axis_peak_sensor = self._single_axis_peak_sensor(signals, quadrant)
        peak_x, peak_y = self._pressure_point(signals, quadrant)
        if single_axis_peak_sensor is not None:
            peak_height = self._pressure_point_height(signals, quadrant, peak_x, peak_y)
            return PressureQuadrantPlane(
                label=quadrant.label, a=base_a, b=base_b, c=base_c, sign=sign, sensors=quadrant.sensors,
                mode=PRESSURE_QUADRANT_MODE_SINGLE_AXIS_PEAKED, peak_point=(peak_x, peak_y), peak_height=peak_height,
                single_axis_peak_sensor=single_axis_peak_sensor,
                single_axis_center_value=float(signals[SHEAR_POSITION_CENTER]),
                single_axis_outer_value=float(signals[single_axis_peak_sensor]),
            )
        if not self._is_peaked_pressure_point(peak_x, peak_y, quadrant):
            return PressureQuadrantPlane(label=quadrant.label, a=base_a, b=base_b, c=base_c, sign=sign, sensors=quadrant.sensors)

        peak_height = self._pressure_point_height(signals, quadrant, peak_x, peak_y)
        triangles, corner_value = self._build_triangle_planes(signals, quadrant, peak_x, peak_y, peak_height)
        if not triangles:
            return PressureQuadrantPlane(label=quadrant.label, a=base_a, b=base_b, c=base_c, sign=sign, sensors=quadrant.sensors)
        return PressureQuadrantPlane(
            label=quadrant.label, a=base_a, b=base_b, c=base_c, sign=sign, sensors=quadrant.sensors,
            mode=PRESSURE_QUADRANT_MODE_PEAKED, peak_point=(peak_x, peak_y), peak_height=peak_height,
            corner_value=corner_value, triangles=triangles,
        )

    def _single_axis_peak_sensor(self, signals: Mapping[str, float], quadrant: _QuadrantDefinition) -> str | None:
        center_nonzero = abs(signals[SHEAR_POSITION_CENTER]) > self.geometry_epsilon
        horizontal_nonzero = abs(signals[quadrant.horizontal_sensor]) > self.geometry_epsilon
        vertical_nonzero = abs(signals[quadrant.vertical_sensor]) > self.geometry_epsilon
        if not center_nonzero:
            return None
        if horizontal_nonzero and not vertical_nonzero:
            return quadrant.horizontal_sensor
        if vertical_nonzero and not horizontal_nonzero:
            return quadrant.vertical_sensor
        return None

    def _three_sensor_plane_coefficients(self, signals: Mapping[str, float], quadrant: _QuadrantDefinition) -> tuple[float, float, float]:
        center_value = signals[SHEAR_POSITION_CENTER]
        horizontal_value = signals[quadrant.horizontal_sensor]
        vertical_value = signals[quadrant.vertical_sensor]
        a = quadrant.horizontal_sign * (horizontal_value - center_value) / self.sensor_spacing_mm
        b = quadrant.vertical_sign * (vertical_value - center_value) / self.sensor_spacing_mm
        return (float(a), float(b), float(center_value))

    def _pressure_point(self, signals: Mapping[str, float], quadrant: _QuadrantDefinition) -> tuple[float, float]:
        center_magnitude = self._pressure_magnitude(signals[SHEAR_POSITION_CENTER])
        horizontal_magnitude = self._pressure_magnitude(signals[quadrant.horizontal_sensor])
        vertical_magnitude = self._pressure_magnitude(signals[quadrant.vertical_sensor])
        x_denominator = horizontal_magnitude + center_magnitude
        y_denominator = vertical_magnitude + center_magnitude
        x_peak = quadrant.horizontal_sign * self.sensor_spacing_mm * horizontal_magnitude / x_denominator if x_denominator else 0.0
        y_peak = quadrant.vertical_sign * self.sensor_spacing_mm * vertical_magnitude / y_denominator if y_denominator else 0.0
        return (float(x_peak), float(y_peak))

    def _pressure_magnitude(self, value: float) -> float:
        return abs(value) if self.show_negative else max(SHEAR_ZERO_VALUE, value)

    def _is_peaked_pressure_point(self, peak_x: float, peak_y: float, quadrant: _QuadrantDefinition) -> bool:
        return (
            peak_x * quadrant.horizontal_sign > self.geometry_epsilon
            and peak_y * quadrant.vertical_sign > self.geometry_epsilon
        )

    def _pressure_point_height(self, signals: Mapping[str, float], quadrant: _QuadrantDefinition, peak_x: float, peak_y: float) -> float:
        weighted_estimate_sum = 0.0
        weight_sum = 0.0
        for sensor in quadrant.sensors:
            sensor_x, sensor_y = self.sensor_positions[sensor]
            distance = float(np.hypot(sensor_x - peak_x, sensor_y - peak_y))
            estimate = signals[sensor] * (1.0 + self.decay_rate * distance / self.decay_ref_distance_mm)
            weight = 1.0 / max(self.geometry_epsilon, distance) ** 2
            weighted_estimate_sum += estimate * weight
            weight_sum += weight
        return float(weighted_estimate_sum / weight_sum) if weight_sum else 0.0

    def _build_triangle_planes(self, signals: Mapping[str, float], quadrant: _QuadrantDefinition, peak_x: float, peak_y: float, peak_height: float) -> tuple[tuple[PressureTrianglePlane, ...], float]:
        spacing = self.sensor_spacing_mm
        center = (0.0, 0.0, signals[SHEAR_POSITION_CENTER])
        horizontal = (quadrant.horizontal_sign * spacing, 0.0, signals[quadrant.horizontal_sensor])
        vertical = (0.0, quadrant.vertical_sign * spacing, signals[quadrant.vertical_sensor])
        peak = (peak_x, peak_y, peak_height)
        half_extent = self.outer_boundary_half_width_mm
        corner = (quadrant.horizontal_sign * half_extent, quadrant.vertical_sign * half_extent, 0.0)
        triangle_specs = (("inner-x", center, horizontal, peak), ("inner-y", center, vertical, peak), ("outer-x", horizontal, corner, peak), ("outer-y", vertical, corner, peak))
        triangles = [plane for name, first, second, third in triangle_specs if (plane := self._solve_triangle_plane(name, first, second, third)) is not None]
        return (tuple(triangles), 0.0)

    def _solve_triangle_plane(self, name: str, first: tuple[float, float, float], second: tuple[float, float, float], third: tuple[float, float, float]) -> PressureTrianglePlane | None:
        matrix = np.array(((first[0], first[1], 1.0), (second[0], second[1], 1.0), (third[0], third[1], 1.0)), dtype=np.float64)
        if abs(float(np.linalg.det(matrix))) < self.geometry_epsilon:
            return None
        a, b, c = np.linalg.solve(matrix, np.array((first[2], second[2], third[2]), dtype=np.float64))
        return PressureTrianglePlane(name=name, a=float(a), b=float(b), c=float(c), vertices=((first[0], first[1]), (second[0], second[1]), (third[0], third[1])))

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

    def _build_pressure_grid(self, quadrant_planes: tuple[PressureQuadrantPlane, ...]) -> np.ndarray:
        """Compatibility wrapper retained for callers/tests of the old helper."""
        return self._evaluate_planes_at(quadrant_planes, self.x_grid_mm, self.y_grid_mm, support_bounds_mm=self.support_bounds_mm)

    def _evaluate_planes_at(self, quadrant_planes: tuple[PressureQuadrantPlane, ...], x_values_mm: np.ndarray, y_values_mm: np.ndarray, *, support_bounds_mm: tuple[float, float, float, float]) -> np.ndarray:
        values = np.full_like(x_values_mm, PRESSURE_OUTSIDE_MASK_VALUE, dtype=np.float64)
        if not quadrant_planes:
            return values
        isolated_plane = next((plane for plane in quadrant_planes if plane.mode == PRESSURE_QUADRANT_MODE_ISOLATED_OUTER_PEAKED), None)
        if isolated_plane is not None:
            return self._evaluate_isolated_outer_plane(isolated_plane, x_values_mm, y_values_mm, support_bounds_mm)

        plane_by_label = {plane.label: plane for plane in quadrant_planes}
        filled_mask = np.zeros_like(values, dtype=bool)
        region_masks = {
            PRESSURE_QUADRANT_TOP_RIGHT: (x_values_mm >= 0.0) & (y_values_mm >= 0.0),
            PRESSURE_QUADRANT_TOP_LEFT: (x_values_mm <= 0.0) & (y_values_mm >= 0.0),
            PRESSURE_QUADRANT_BOTTOM_LEFT: (x_values_mm <= 0.0) & (y_values_mm <= 0.0),
            PRESSURE_QUADRANT_BOTTOM_RIGHT: (x_values_mm >= 0.0) & (y_values_mm <= 0.0),
        }
        for label in PRESSURE_ACTIVE_QUADRANTS:
            plane = plane_by_label.get(label)
            if plane is None:
                continue
            mask = region_masks[label] & ~filled_mask
            if not np.any(mask):
                continue
            values[mask] = self._evaluate_quadrant_for_region(plane, x_values_mm[mask], y_values_mm[mask], support_bounds_mm=support_bounds_mm)
            filled_mask[mask] = True
        return values

    def _evaluate_quadrant_for_region(self, plane: PressureQuadrantPlane, x_values_mm: np.ndarray, y_values_mm: np.ndarray, *, support_bounds_mm: tuple[float, float, float, float] | None = None) -> np.ndarray:
        if plane.mode == PRESSURE_QUADRANT_MODE_PEAKED and plane.triangles:
            values = self._evaluate_peaked_quadrant(plane, x_values_mm, y_values_mm)
        elif plane.mode == PRESSURE_QUADRANT_MODE_SINGLE_AXIS_PEAKED:
            values = self._evaluate_single_axis_peaked_quadrant(plane, x_values_mm, y_values_mm)
        else:
            values = self._evaluate_plane(plane.a, plane.b, plane.c, x_values_mm, y_values_mm)
        bounds = self.support_bounds_mm if support_bounds_mm is None else support_bounds_mm
        values = self._apply_support_decay(plane, x_values_mm, y_values_mm, values, bounds)
        return self._clamp_values(values, plane.sign)

    def _evaluate_isolated_outer_plane(self, plane: PressureQuadrantPlane, x_values_mm: np.ndarray, y_values_mm: np.ndarray, support_bounds_mm: tuple[float, float, float, float]) -> np.ndarray:
        sensor = plane.single_axis_peak_sensor
        if sensor is None or plane.peak_point is None or plane.peak_height is None:
            return np.zeros_like(x_values_mm, dtype=np.float64)
        if sensor in (SHEAR_POSITION_LEFT, SHEAR_POSITION_RIGHT):
            direction = 1.0 if sensor == SHEAR_POSITION_RIGHT else -1.0
            local_axis = x_values_mm * direction
            local_lateral = np.abs(y_values_mm)
            axis_bound = support_bounds_mm[1] if direction > 0 else -support_bounds_mm[0]
            lateral_bounds = np.where(y_values_mm >= 0.0, support_bounds_mm[3], -support_bounds_mm[2])
        else:
            direction = 1.0 if sensor == SHEAR_POSITION_TOP else -1.0
            local_axis = y_values_mm * direction
            local_lateral = np.abs(x_values_mm)
            axis_bound = support_bounds_mm[3] if direction > 0 else -support_bounds_mm[2]
            lateral_bounds = np.where(x_values_mm >= 0.0, support_bounds_mm[1], -support_bounds_mm[0])

        sensor_axis = self.sensor_spacing_mm
        peak_axis = sensor_axis + self.near_outer_peak_offset_mm
        outer_value = float(plane.single_axis_outer_value or 0.0)
        before_sensor = outer_value * np.clip(local_axis / sensor_axis, 0.0, 1.0)
        to_peak = np.full_like(local_axis, outer_value, dtype=np.float64)
        after_peak_distance = np.maximum(0.0, local_axis - peak_axis)
        natural = self._natural_decay_factor(after_peak_distance, abs(float(plane.peak_height)))
        after_peak = outer_value * natural
        axial = np.where(local_axis <= sensor_axis, before_sensor, np.where(local_axis <= peak_axis, to_peak, after_peak))
        axial = np.where(local_axis >= 0.0, axial, 0.0)

        lateral_width = max(self.geometry_epsilon, self.sensor_spacing_mm * 0.65)
        lateral_profile = np.exp(-((local_lateral / lateral_width) ** 2))
        terminal_axis = self._terminal_envelope(local_axis, peak_axis, axis_bound)
        terminal_lateral = np.clip(1.0 - (local_lateral / np.maximum(self.geometry_epsilon, lateral_bounds)), 0.0, 1.0)
        values = axial * lateral_profile * terminal_axis * terminal_lateral
        return self._clamp_values(values, plane.sign)

    def _evaluate_single_axis_peaked_quadrant(self, plane: PressureQuadrantPlane, x_values_mm: np.ndarray, y_values_mm: np.ndarray) -> np.ndarray:
        if plane.peak_point is None:
            return self._evaluate_plane(plane.a, plane.b, plane.c, x_values_mm, y_values_mm)
        quadrant = self._quadrant_by_label.get(plane.label)
        if quadrant is None or plane.single_axis_peak_sensor is None:
            return self._evaluate_plane(plane.a, plane.b, plane.c, x_values_mm, y_values_mm)
        peak_x, peak_y = plane.peak_point
        active_horizontal = plane.single_axis_peak_sensor == quadrant.horizontal_sensor
        if active_horizontal:
            local_axis, local_lateral, peak_axis = x_values_mm * quadrant.horizontal_sign, np.abs(y_values_mm), peak_x * quadrant.horizontal_sign
        else:
            local_axis, local_lateral, peak_axis = y_values_mm * quadrant.vertical_sign, np.abs(x_values_mm), peak_y * quadrant.vertical_sign
        peak_axis = float(np.clip(peak_axis, self.geometry_epsilon, self.sensor_spacing_mm - self.geometry_epsilon))
        before_peak = np.clip(local_axis / peak_axis, 0.0, 1.0)
        after_peak = np.clip((self.sensor_spacing_mm - local_axis) / (self.sensor_spacing_mm - peak_axis), 0.0, 1.0)
        axial_blend = np.where(local_axis <= peak_axis, before_peak, after_peak)
        center_value = float(plane.single_axis_center_value or 0.0)
        outer_value = float(plane.single_axis_outer_value or 0.0)
        edge_value = (center_value + outer_value) / 2.0
        peak_value = float(plane.peak_height if plane.peak_height is not None else plane.c)
        values = edge_value + (peak_value - edge_value) * axial_blend
        width_at_peak = max(self.geometry_epsilon, self.sensor_spacing_mm * 0.22)
        width_at_edges = max(self.geometry_epsilon, self.sensor_spacing_mm * 0.07)
        lateral_width = width_at_edges + (width_at_peak - width_at_edges) * axial_blend
        return values * np.exp(-((local_lateral / lateral_width) ** 2))

    def _apply_support_decay(self, plane: PressureQuadrantPlane, x_values_mm: np.ndarray, y_values_mm: np.ndarray, values: np.ndarray, bounds: tuple[float, float, float, float]) -> np.ndarray:
        quadrant = self._quadrant_by_label.get(plane.label)
        if quadrant is None:
            return values
        local_x = x_values_mm * quadrant.horizontal_sign
        local_y = y_values_mm * quadrant.vertical_sign
        x_bound = bounds[1] if quadrant.horizontal_sign > 0 else -bounds[0]
        y_bound = bounds[3] if quadrant.vertical_sign > 0 else -bounds[2]
        peak_x = abs(plane.peak_point[0]) if plane.peak_point is not None else 0.0
        peak_y = abs(plane.peak_point[1]) if plane.peak_point is not None else 0.0
        x_anchor = max(self.sensor_spacing_mm, peak_x)
        y_anchor = max(self.sensor_spacing_mm, peak_y)
        strength = self._plane_decay_strength(plane)
        natural = self._natural_decay_factor(np.maximum(0.0, local_x - x_anchor), strength)
        natural *= self._natural_decay_factor(np.maximum(0.0, local_y - y_anchor), strength)
        terminal = self._terminal_envelope(local_x, x_anchor, x_bound)
        terminal *= self._terminal_envelope(local_y, y_anchor, y_bound)
        return values * natural * terminal

    def _plane_decay_strength(self, plane: PressureQuadrantPlane) -> float:
        if plane.peak_height is not None:
            return abs(float(plane.peak_height))
        spacing = self.sensor_spacing_mm
        candidates = (plane.c, plane.c + plane.a * spacing, plane.c - plane.a * spacing, plane.c + plane.b * spacing, plane.c - plane.b * spacing)
        return max(abs(float(value)) for value in candidates)

    def _natural_decay_factor(self, distance_mm: np.ndarray, strength: float) -> np.ndarray:
        if self.decay_rate <= self.geometry_epsilon:
            return np.ones_like(distance_mm, dtype=np.float64)
        natural_reach = self.decay_ref_distance_mm * max(1.0, strength * self.decay_rate)
        return np.clip(1.0 - (distance_mm / max(self.geometry_epsilon, natural_reach)), 0.0, 1.0)

    def _terminal_envelope(self, coordinate_mm: np.ndarray, anchor_mm: float, boundary_mm: float) -> np.ndarray:
        if boundary_mm <= anchor_mm + self.geometry_epsilon:
            return np.where(coordinate_mm < boundary_mm, 1.0, 0.0)
        envelope = np.ones_like(coordinate_mm, dtype=np.float64)
        outward = coordinate_mm > anchor_mm
        envelope[outward] = np.clip((boundary_mm - coordinate_mm[outward]) / (boundary_mm - anchor_mm), 0.0, 1.0)
        return envelope

    def _evaluate_peaked_quadrant(self, plane: PressureQuadrantPlane, x_values_mm: np.ndarray, y_values_mm: np.ndarray) -> np.ndarray:
        values = np.empty_like(x_values_mm, dtype=np.float64)
        matched_mask = np.zeros_like(x_values_mm, dtype=bool)
        for triangle in plane.triangles:
            triangle_mask = self._points_in_triangle(x_values_mm, y_values_mm, triangle.vertices) & ~matched_mask
            if not np.any(triangle_mask):
                continue
            values[triangle_mask] = self._evaluate_plane(triangle.a, triangle.b, triangle.c, x_values_mm[triangle_mask], y_values_mm[triangle_mask])
            matched_mask[triangle_mask] = True
        unmatched = np.flatnonzero(~matched_mask)
        if unmatched.size:
            outer_triangles = [triangle for triangle in plane.triangles if triangle.name.startswith("outer")]
            fallbacks = outer_triangles or list(plane.triangles)
            for index in unmatched:
                triangle = self._nearest_triangle(fallbacks, float(x_values_mm[index]), float(y_values_mm[index]))
                values[index] = self._evaluate_plane(triangle.a, triangle.b, triangle.c, x_values_mm[index], y_values_mm[index])
        return values

    def _points_in_triangle(self, x_values_mm: np.ndarray, y_values_mm: np.ndarray, vertices: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]) -> np.ndarray:
        first, second, third = vertices
        s1 = self._cross(second, first, x_values_mm, y_values_mm)
        s2 = self._cross(third, second, x_values_mm, y_values_mm)
        s3 = self._cross(first, third, x_values_mm, y_values_mm)
        has_negative = (s1 < -self.geometry_epsilon) | (s2 < -self.geometry_epsilon) | (s3 < -self.geometry_epsilon)
        has_positive = (s1 > self.geometry_epsilon) | (s2 > self.geometry_epsilon) | (s3 > self.geometry_epsilon)
        return ~(has_negative & has_positive)

    def _cross(self, edge_end: tuple[float, float], edge_start: tuple[float, float], x_values_mm: np.ndarray, y_values_mm: np.ndarray) -> np.ndarray:
        return ((edge_end[0] - edge_start[0]) * (y_values_mm - edge_start[1]) - (edge_end[1] - edge_start[1]) * (x_values_mm - edge_start[0]))

    def _nearest_triangle(self, triangles: list[PressureTrianglePlane], x_value: float, y_value: float) -> PressureTrianglePlane:
        point = np.array((x_value, y_value), dtype=np.float64)
        distances = [float(np.linalg.norm(point - np.mean(np.array(triangle.vertices, dtype=np.float64), axis=0))) for triangle in triangles]
        return triangles[int(np.argmin(distances))]

    def _evaluate_plane(self, a: float, b: float, c: float, x_values_mm: np.ndarray | float, y_values_mm: np.ndarray | float) -> np.ndarray | float:
        return (a * x_values_mm) + (b * y_values_mm) + c

    def _clamp_values(self, values: np.ndarray, sign: float) -> np.ndarray:
        return np.minimum(0.0, values) if sign < 0.0 else np.maximum(0.0, values)


def evaluate_pressure_map_result_at(
    result: PressureMapResult,
    local_x_mm: np.ndarray,
    local_y_mm: np.ndarray,
    *,
    support_bounds_mm: tuple[float, float, float, float] | None = None,
) -> np.ndarray:
    """Evaluate a retained package result on arbitrary local coordinates.

    Array generation uses this rather than stretching or resampling a rendered
    local image.  The optional support bounds apply the terminal boundary
    envelope without changing the natural decay model.
    """

    # Avoid constructing a throwaway numerical grid for every package/world
    # candidate. Only the scalar geometry used by the evaluator is needed.
    evaluator = object.__new__(PressureMapGenerator)
    evaluator.sensor_spacing_mm = result.sensor_spacing_mm
    evaluator.package_center_spacing_mm = result.package_center_spacing_mm
    evaluator.outer_boundary_reach_mm = result.outer_boundary_reach_mm
    evaluator.pixels_per_mm = result.pixels_per_mm
    evaluator.facing_sensor_gap_mm = result.facing_sensor_gap_mm
    evaluator.mid_boundary_half_width_mm = result.mid_boundary_half_width_mm
    evaluator.outer_boundary_half_width_mm = result.outer_boundary_half_width_mm
    evaluator.decay_rate = result.decay_rate
    evaluator.decay_ref_distance_mm = result.decay_ref_distance_mm
    evaluator.near_outer_peak_offset_mm = result.near_outer_peak_offset_mm
    evaluator.geometry_epsilon = result.geometry_epsilon
    evaluator.show_negative = result.show_negative
    evaluator.support_bounds_mm = result.support_bounds_mm
    evaluator.sensor_positions = dict(result.sensor_positions)
    evaluator.quadrants = evaluator._build_quadrant_definitions()
    evaluator._quadrant_by_label = {
        quadrant.label: quadrant for quadrant in evaluator.quadrants
    }
    return evaluator._evaluate_planes_at(
        result.quadrant_planes,
        np.asarray(local_x_mm, dtype=np.float64),
        np.asarray(local_y_mm, dtype=np.float64),
        support_bounds_mm=result.support_bounds_mm if support_bounds_mm is None else support_bounds_mm,
    )
