"""Signed, continuous pressure fields for one five-sensor package.

The numerical field is intentionally independent from presentation.  A
``PressureFieldModel`` retains the thresholded anchors and evaluates the same
mathematical field on the local raster and on an array's world-space raster.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from itertools import count

import numpy as np

from constants.pressure_map import (
    ACTIVE_BOTTOM,
    ACTIVE_CENTER,
    ACTIVE_LEFT,
    ACTIVE_RIGHT,
    ACTIVE_TOP,
    DEFAULT_PRESSURE_DECAY_AMPLITUDE_REFERENCE,
    DEFAULT_PRESSURE_DECAY_RATE,
    DEFAULT_PRESSURE_DECAY_REF_DISTANCE_MM,
    DEFAULT_PRESSURE_MAXIMUM_DECAY_REACH_MM,
    DEFAULT_PRESSURE_MAXIMUM_PEAK_GAIN,
    DEFAULT_PRESSURE_MINIMUM_DECAY_REACH_MM,
    DEFAULT_PRESSURE_NATURAL_DECAY_REFERENCE_DISTANCE_MM,
    DEFAULT_PRESSURE_NEAR_OUTER_PEAK_OFFSET_MM,
    DEFAULT_PRESSURE_OUTER_BOUNDARY_REACH_MM,
    DEFAULT_PRESSURE_PACKAGE_CENTER_SPACING_MM,
    DEFAULT_PRESSURE_PEAK_GAIN_SLOPE_PER_MM,
    DEFAULT_PRESSURE_PIXELS_PER_MM,
    DEFAULT_PRESSURE_SENSOR_SPACING_MM,
    DEFAULT_PRESSURE_SHOW_NEGATIVE,
    DEFAULT_PRESSURE_SIGNAL_ACTIVITY_THRESHOLD,
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
from data_processing.pressure_map_geometry import PressureMapGeometry


PRESSURE_GEOMETRY_EPSILON = 0.001
PRESSURE_NUMERIC_EPSILON = 1e-14
PRESSURE_RADIUS_SEARCH_TOLERANCE_FRACTION = 0.1
PRESSURE_RADIUS_SEARCH_TOLERANCE_MIN_MM = 0.005
PRESSURE_RADIUS_SEARCH_TOLERANCE_MAX_MM = 0.05
PRESSURE_MAX_RADIUS_SEARCH_ITERATIONS = 32

PRESSURE_PACKAGE_MODE_ALL_INACTIVE = "all-inactive"
PRESSURE_PACKAGE_MODE_CENTER_ONLY = "center-only"
PRESSURE_PACKAGE_MODE_ISOLATED_OUTER = "isolated-outer"
PRESSURE_PACKAGE_MODE_CENTER_PLUS_ONE_OUTER = "center-plus-one-outer"
PRESSURE_PACKAGE_MODE_GENERAL_MULTI_SENSOR = "general-multi-sensor"

PRESSURE_QUADRANT_MODE_PEAKLESS = "peakless"
PRESSURE_QUADRANT_MODE_PEAKED = "peaked"
PRESSURE_QUADRANT_MODE_SIGNED_TRANSITION = "signed-transition"
# These public names are retained for settings/tests written against the first
# pressure-map implementation.  They now describe package-level models.
PRESSURE_QUADRANT_MODE_SINGLE_AXIS_PEAKED = "single-axis-peaked"
PRESSURE_QUADRANT_MODE_ISOLATED_OUTER_PEAKED = "isolated-outer-peaked"

_FRAME_IDS = count(1)


def _peak_position_weight(value: float) -> float:
    """Return the square-root magnitude weight used for inferred positions."""

    return float(np.sqrt(abs(float(value))))


def _center_outer_peak_axis(center: float, outer: float, spacing: float) -> float:
    """Return the canonical center-to-outer peak position."""

    center_weight = _peak_position_weight(center)
    outer_weight = _peak_position_weight(outer)
    return float(
        spacing
        * outer_weight
        / max(PRESSURE_NUMERIC_EPSILON, center_weight + outer_weight)
    )
_OUTER_SENSORS = (
    SHEAR_POSITION_LEFT,
    SHEAR_POSITION_RIGHT,
    SHEAR_POSITION_TOP,
    SHEAR_POSITION_BOTTOM,
)


def build_active_sensor_mask(sensor_values: Mapping[str, float]) -> int:
    """Return a compact bitmask for already-thresholded package anchors."""

    mask = 0
    if float(sensor_values[SHEAR_POSITION_CENTER]) != 0.0:
        mask |= ACTIVE_CENTER
    if float(sensor_values[SHEAR_POSITION_LEFT]) != 0.0:
        mask |= ACTIVE_LEFT
    if float(sensor_values[SHEAR_POSITION_RIGHT]) != 0.0:
        mask |= ACTIVE_RIGHT
    if float(sensor_values[SHEAR_POSITION_TOP]) != 0.0:
        mask |= ACTIVE_TOP
    if float(sensor_values[SHEAR_POSITION_BOTTOM]) != 0.0:
        mask |= ACTIVE_BOTTOM
    return mask


def smoothstep_fade(distance: np.ndarray | float, reach: np.ndarray | float) -> np.ndarray:
    """Return a compact-support cubic fade, with no NaN at zero reach.

    The value is one at distance zero, approaches zero with a zero derivative,
    and is exactly zero on and outside the supplied reach.
    """

    distance_array, reach_array = np.broadcast_arrays(
        np.asarray(distance, dtype=np.float64), np.asarray(reach, dtype=np.float64)
    )
    result = np.zeros_like(distance_array, dtype=np.float64)
    valid = reach_array > PRESSURE_NUMERIC_EPSILON
    if not np.any(valid):
        return result
    t = np.zeros_like(distance_array, dtype=np.float64)
    t[valid] = np.clip(distance_array[valid] / reach_array[valid], 0.0, 1.0)
    # The factored form avoids cancellation in ``1 - 3t² + 2t³`` when the
    # sample is immediately inside the compact-support endpoint.
    one_minus_t = 1.0 - t[valid]
    result[valid] = one_minus_t ** 2 * (1.0 + 2.0 * t[valid])
    result[distance_array >= reach_array] = 0.0
    return result


def _smoothstep_fade_scalar(distance: float, reach: float) -> float:
    """Return the scalar equivalent of :func:`smoothstep_fade`."""

    distance = float(distance)
    reach = float(reach)
    if np.isnan(distance) or np.isnan(reach):
        return 0.0
    if reach <= PRESSURE_NUMERIC_EPSILON or distance >= reach:
        return 0.0
    t = min(1.0, max(0.0, distance / reach))
    result = (1.0 - t) ** 2 * (1.0 + 2.0 * t)
    return float(result) if np.isfinite(result) and result >= 0.0 else 0.0


def ray_square_exit_distance(
    origin_x: float,
    origin_y: float,
    direction_x: float,
    direction_y: float,
    square_bounds: tuple[float, float, float, float],
) -> float:
    """Return physical distance from an in-square origin to its ray exit.

    A zero direction and an origin already on the exit edge return zero.  The
    helper is scalar by design so geometry tests can cover degenerate rays
    without relying on raster resolution.
    """

    length = float(np.hypot(direction_x, direction_y))
    if length <= PRESSURE_NUMERIC_EPSILON:
        return 0.0
    unit_x = float(direction_x) / length
    unit_y = float(direction_y) / length
    left, right, bottom, top = (float(value) for value in square_bounds)
    candidates: list[float] = []
    if unit_x > PRESSURE_NUMERIC_EPSILON:
        candidates.append((right - origin_x) / unit_x)
    elif unit_x < -PRESSURE_NUMERIC_EPSILON:
        candidates.append((left - origin_x) / unit_x)
    if unit_y > PRESSURE_NUMERIC_EPSILON:
        candidates.append((top - origin_y) / unit_y)
    elif unit_y < -PRESSURE_NUMERIC_EPSILON:
        candidates.append((bottom - origin_y) / unit_y)
    non_negative = [candidate for candidate in candidates if candidate >= 0.0]
    return float(min(non_negative)) if non_negative else 0.0


def ray_square_intersection_point(
    origin: tuple[float, float],
    target: tuple[float, float],
    square_bounds: tuple[float, float, float, float],
) -> tuple[float, float]:
    """Return the outward square-boundary intersection of ``origin -> target``."""

    direction_x = float(target[0]) - float(origin[0])
    direction_y = float(target[1]) - float(origin[1])
    distance = ray_square_exit_distance(
        float(origin[0]), float(origin[1]), direction_x, direction_y, square_bounds
    )
    length = float(np.hypot(direction_x, direction_y))
    if length <= PRESSURE_NUMERIC_EPSILON:
        return (float(origin[0]), float(origin[1]))
    return (
        float(origin[0]) + (direction_x / length) * distance,
        float(origin[1]) + (direction_y / length) * distance,
    )


@dataclass(frozen=True, slots=True)
class PressureTrianglePlane:
    """A linear triangle used only inside the sensor-square core."""

    name: str
    a: float
    b: float
    c: float
    vertices: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]


@dataclass(frozen=True, slots=True)
class PressureQuadrantPlane:
    """Diagnostic metadata for one complete core quadrant or lobe."""

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
    decay_origin: tuple[float, float] = (0.0, 0.0)


@dataclass(frozen=True, slots=True)
class PressureFieldModel:
    """Immutable signed field model shared by local and array evaluation."""

    geometry: PressureMapGeometry
    package_mode: str
    raw_sensor_values: tuple[tuple[str, float], ...]
    sensor_values: tuple[tuple[str, float], ...]
    active_sensor_mask: int
    package_activity_confidence: float
    quadrant_planes: tuple[PressureQuadrantPlane, ...]
    support_bounds_mm: tuple[float, float, float, float]
    decay_origin: tuple[float, float]
    model_strength: float
    decay_rate: float
    decay_ref_distance_mm: float
    peak_gain_slope_per_mm: float
    maximum_peak_gain: float
    natural_decay_reference_distance_mm: float
    decay_amplitude_reference: float
    minimum_decay_reach_mm: float
    maximum_decay_reach_mm: float
    geometry_epsilon: float
    minimum_lateral_width_mm: float
    active_axis_sensor: str | None = None
    peak_point: tuple[float, float] | None = None
    peak_height: float | None = None
    isolated_circular_radius_mm: float | None = None
    isolated_measured_sensor_value: float | None = None
    isolated_actual_peak_gain: float | None = None
    isolated_gain_cap_satisfied: bool | None = None
    isolated_gain_cap_search_iterations: int | None = None
    center_outer_circular_radius_mm: float | None = None
    center_outer_center_scale: float | None = None
    center_outer_outer_scale: float | None = None
    center_outer_actual_peak_gain: float | None = None
    center_outer_gain_cap_satisfied: bool | None = None
    center_outer_natural_radius_mm: float | None = None
    center_outer_fade_safe_minimum_radius_mm: float | None = None
    center_outer_geometric_maximum_radius_mm: float | None = None
    center_outer_center_factor: float | None = None
    center_outer_outer_factor: float | None = None
    center_outer_fade_safe_search_iterations: int | None = None
    center_outer_gain_cap_search_iterations: int | None = None
    center_outer_used_fallback: bool = False

    def signal(self, sensor: str) -> float:
        return dict(self.sensor_values)[sensor]

    def evaluate(
        self,
        x_mm: np.ndarray | float,
        y_mm: np.ndarray | float,
        support_bounds: tuple[float, float, float, float] | None = None,
    ) -> np.ndarray:
        """Evaluate the signed model without display transforms or resampling."""

        return _evaluate_pressure_field_model(
            self,
            np.asarray(x_mm, dtype=np.float64),
            np.asarray(y_mm, dtype=np.float64),
            self.support_bounds_mm if support_bounds is None else support_bounds,
        )


@dataclass(frozen=True, slots=True)
class PressureMapResult:
    """Raster output and its reusable immutable mathematical model."""

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
    actual_pixels_per_mm: float
    facing_sensor_gap_mm: float
    mid_boundary_half_width_mm: float
    outer_boundary_half_width_mm: float
    decay_rate: float
    decay_ref_distance_mm: float
    peak_gain_slope_per_mm: float
    maximum_peak_gain: float
    natural_decay_reference_distance_mm: float
    decay_amplitude_reference: float
    minimum_decay_reach_mm: float
    maximum_decay_reach_mm: float
    signal_activity_threshold: float
    raw_sensor_values: tuple[tuple[str, float], ...]
    active_sensor_mask: int
    package_activity_confidence: float
    geometry_epsilon: float
    show_negative: bool
    near_outer_peak_offset_mm: float
    field_model: PressureFieldModel
    package_mode: str
    frame_id: int
    diagnostics: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class _QuadrantDefinition:
    label: str
    horizontal_sensor: str
    vertical_sensor: str
    horizontal_sign: float
    vertical_sign: float
    sensors: tuple[str, ...]


class PressureMapGenerator:
    """Build immutable package fields and evaluate them on a local raster."""

    def __init__(
        self,
        *,
        sensor_spacing_mm: float = DEFAULT_PRESSURE_SENSOR_SPACING_MM,
        package_center_spacing_mm: float = DEFAULT_PRESSURE_PACKAGE_CENTER_SPACING_MM,
        outer_boundary_reach_mm: float = DEFAULT_PRESSURE_OUTER_BOUNDARY_REACH_MM,
        pixels_per_mm: float = DEFAULT_PRESSURE_PIXELS_PER_MM,
        decay_rate: float = DEFAULT_PRESSURE_DECAY_RATE,
        decay_ref_distance_mm: float = DEFAULT_PRESSURE_DECAY_REF_DISTANCE_MM,
        peak_gain_slope_per_mm: float = DEFAULT_PRESSURE_PEAK_GAIN_SLOPE_PER_MM,
        maximum_peak_gain: float = DEFAULT_PRESSURE_MAXIMUM_PEAK_GAIN,
        natural_decay_reference_distance_mm: float | None = None,
        decay_amplitude_reference: float = DEFAULT_PRESSURE_DECAY_AMPLITUDE_REFERENCE,
        minimum_decay_reach_mm: float = DEFAULT_PRESSURE_MINIMUM_DECAY_REACH_MM,
        maximum_decay_reach_mm: float = DEFAULT_PRESSURE_MAXIMUM_DECAY_REACH_MM,
        signal_activity_threshold: float = DEFAULT_PRESSURE_SIGNAL_ACTIVITY_THRESHOLD,
        geometry: PressureMapGeometry | None = None,
        near_outer_peak_offset_mm: float = DEFAULT_PRESSURE_NEAR_OUTER_PEAK_OFFSET_MM,
        geometry_epsilon: float = PRESSURE_GEOMETRY_EPSILON,
        show_negative: bool = DEFAULT_PRESSURE_SHOW_NEGATIVE,
        debug: bool = False,
    ) -> None:
        # Geometry wins when supplied.  This keeps legacy scalar callers
        # compatible while preventing stale scalar members from diverging.
        if geometry is not None:
            conflicting_scalars = (
                (sensor_spacing_mm, DEFAULT_PRESSURE_SENSOR_SPACING_MM, geometry.sensor_spacing_mm),
                (package_center_spacing_mm, DEFAULT_PRESSURE_PACKAGE_CENTER_SPACING_MM, geometry.package_center_spacing_mm),
                (outer_boundary_reach_mm, DEFAULT_PRESSURE_OUTER_BOUNDARY_REACH_MM, geometry.outer_boundary_reach_mm),
                (pixels_per_mm, DEFAULT_PRESSURE_PIXELS_PER_MM, geometry.pixels_per_mm),
                (near_outer_peak_offset_mm, DEFAULT_PRESSURE_NEAR_OUTER_PEAK_OFFSET_MM, geometry.near_outer_peak_offset_mm),
            )
            if any(
                not np.isclose(value, default) and not np.isclose(value, geometry_value)
                for value, default, geometry_value in conflicting_scalars
            ):
                raise ValueError("scalar pressure-map geometry conflicts with supplied geometry")
        self.geometry = geometry or PressureMapGeometry(
            sensor_spacing_mm=float(sensor_spacing_mm),
            package_center_spacing_mm=float(package_center_spacing_mm),
            outer_boundary_reach_mm=float(outer_boundary_reach_mm),
            near_outer_peak_offset_mm=float(near_outer_peak_offset_mm),
            pixels_per_mm=float(pixels_per_mm),
        )
        self.sensor_spacing_mm = self.geometry.sensor_spacing_mm
        self.package_center_spacing_mm = self.geometry.package_center_spacing_mm
        self.outer_boundary_reach_mm = self.geometry.outer_boundary_reach_mm
        self.near_outer_peak_offset_mm = self.geometry.near_outer_peak_offset_mm
        self.pixels_per_mm = self.geometry.pixels_per_mm
        self.decay_rate = float(decay_rate)
        self.decay_ref_distance_mm = float(decay_ref_distance_mm)
        self.peak_gain_slope_per_mm = float(peak_gain_slope_per_mm)
        self.maximum_peak_gain = float(maximum_peak_gain)
        self.natural_decay_reference_distance_mm = float(
            decay_ref_distance_mm
            if natural_decay_reference_distance_mm is None
            else natural_decay_reference_distance_mm
        )
        self.decay_amplitude_reference = float(decay_amplitude_reference)
        self.minimum_decay_reach_mm = float(minimum_decay_reach_mm)
        self.maximum_decay_reach_mm = float(maximum_decay_reach_mm)
        self.signal_activity_threshold = float(signal_activity_threshold)
        self.geometry_epsilon = float(geometry_epsilon)
        # Retained only as a legacy settings input.  It never affects the
        # signed backend; magnitude belongs in PressureMapWidget.
        self.show_negative = bool(show_negative)
        self.debug = bool(debug)
        self._validate_parameters()
        self.sensor_positions = self._build_sensor_positions()
        self.quadrants = self._build_quadrant_definitions()
        self._quadrant_by_label = {quadrant.label: quadrant for quadrant in self.quadrants}
        self.facing_sensor_gap_mm = self.geometry.facing_sensor_gap_mm
        self.mid_boundary_half_width_mm = self.geometry.mid_boundary_half_width_mm
        self.outer_boundary_half_width_mm = self.geometry.outer_boundary_half_width_mm
        self.visual_boundary_radius_mm = self.geometry.near_outer_circle_radius_mm
        self.actual_pixels_per_mm = self.geometry.actual_pixels_per_mm
        self.cell_size_mm = self.geometry.aligned_cell_size_mm
        self.half_intervals = int(round(self.outer_boundary_half_width_mm / self.cell_size_mm))
        self.total_grid_side = (2 * self.half_intervals) + 1
        if self.total_grid_side > 4097:
            raise ValueError("geometry-aligned pressure-map grid exceeds the 4097-pixel safety cap")
        self.total_extent_mm = self.outer_boundary_half_width_mm * 2.0
        self.support_bounds_mm = self.geometry.support_bounds_mm
        self.x_coordinates_mm = (
            np.arange(-self.half_intervals, self.half_intervals + 1, dtype=np.float64)
            * self.cell_size_mm
        )
        self.y_coordinates_mm = self.x_coordinates_mm.copy()
        self.x_grid_mm, self.y_grid_mm = np.meshgrid(self.x_coordinates_mm, self.y_coordinates_mm)
        # A visual overlay compatibility mask only; it never clips the field.
        self.circle_mask = np.hypot(self.x_grid_mm, self.y_grid_mm) <= self.visual_boundary_radius_mm

    def generate(self, normalized_signals: Mapping[str, float]) -> PressureMapResult:
        """Threshold input signals, then build and rasterize one signed model."""

        raw_signals = self._raw_signals(normalized_signals)
        signals = self._normalize_signals(raw_signals)
        model = self._build_package_field_model(signals, raw_signals)
        pressure_grid = model.evaluate(self.x_grid_mm, self.y_grid_mm)
        if not np.isfinite(pressure_grid).all():
            # The circular profile is optional enhancement only.  Preserve a
            # bounded field for live input even if an unexpected numeric edge
            # case escapes its construction-time validation.
            if (
                model.package_mode == PRESSURE_PACKAGE_MODE_CENTER_PLUS_ONE_OUTER
                and model.peak_height is not None
                and model.quadrant_planes
            ):
                fallback_plane = replace(model.quadrant_planes[0], peak_height=None)
                model = replace(
                    model,
                    quadrant_planes=(fallback_plane,),
                    peak_height=None,
                    center_outer_circular_radius_mm=None,
                    center_outer_center_scale=None,
                    center_outer_outer_scale=None,
                    center_outer_actual_peak_gain=None,
                    center_outer_gain_cap_satisfied=None,
                    center_outer_center_factor=None,
                    center_outer_outer_factor=None,
                    center_outer_used_fallback=True,
                )
                pressure_grid = model.evaluate(self.x_grid_mm, self.y_grid_mm)
            if not np.isfinite(pressure_grid).all():
                raise ValueError("pressure-map evaluation produced non-finite values")
        diagnostics = self._build_diagnostics(model, pressure_grid) if self.debug else None
        return PressureMapResult(
            pressure_grid=pressure_grid,
            circle_mask=self.circle_mask.copy(),
            active_quadrants=tuple(plane.label for plane in model.quadrant_planes),
            quadrant_planes=model.quadrant_planes,
            x_coordinates_mm=self.x_coordinates_mm.copy(),
            y_coordinates_mm=self.y_coordinates_mm.copy(),
            x_grid_mm=self.x_grid_mm.copy(), y_grid_mm=self.y_grid_mm.copy(),
            sensor_positions=dict(self.sensor_positions),
            cell_size_mm=self.cell_size_mm, total_extent_mm=self.total_extent_mm,
            visual_boundary_radius_mm=self.visual_boundary_radius_mm,
            support_bounds_mm=self.support_bounds_mm,
            sensor_spacing_mm=self.sensor_spacing_mm,
            package_center_spacing_mm=self.package_center_spacing_mm,
            outer_boundary_reach_mm=self.outer_boundary_reach_mm,
            pixels_per_mm=self.pixels_per_mm,
            actual_pixels_per_mm=self.actual_pixels_per_mm,
            facing_sensor_gap_mm=self.facing_sensor_gap_mm,
            mid_boundary_half_width_mm=self.mid_boundary_half_width_mm,
            outer_boundary_half_width_mm=self.outer_boundary_half_width_mm,
            decay_rate=self.decay_rate, decay_ref_distance_mm=self.decay_ref_distance_mm,
            peak_gain_slope_per_mm=self.peak_gain_slope_per_mm,
            maximum_peak_gain=self.maximum_peak_gain,
            natural_decay_reference_distance_mm=self.natural_decay_reference_distance_mm,
            decay_amplitude_reference=self.decay_amplitude_reference,
            minimum_decay_reach_mm=self.minimum_decay_reach_mm,
            maximum_decay_reach_mm=self.maximum_decay_reach_mm,
            signal_activity_threshold=self.signal_activity_threshold,
            raw_sensor_values=model.raw_sensor_values,
            active_sensor_mask=model.active_sensor_mask,
            package_activity_confidence=model.package_activity_confidence,
            geometry_epsilon=self.geometry_epsilon, show_negative=self.show_negative,
            near_outer_peak_offset_mm=self.near_outer_peak_offset_mm,
            field_model=model, package_mode=model.package_mode, frame_id=next(_FRAME_IDS),
            diagnostics=diagnostics,
        )

    def _build_diagnostics(
        self, model: PressureFieldModel, pressure_grid: np.ndarray
    ) -> dict[str, object]:
        """Return opt-in diagnostic data without touching the live fast path."""

        spacing = self.geometry.sensor_spacing_mm
        core_mask = (np.abs(self.x_grid_mm) <= spacing) & (np.abs(self.y_grid_mm) <= spacing)
        core_surface = np.zeros_like(pressure_grid)
        if np.any(core_mask) and model.package_mode != PRESSURE_PACKAGE_MODE_ALL_INACTIVE:
            if model.package_mode == PRESSURE_PACKAGE_MODE_CENTER_ONLY:
                core_surface[core_mask] = _evaluate_center_only_model(
                    model, self.x_grid_mm[core_mask], self.y_grid_mm[core_mask]
                )
            elif model.package_mode == PRESSURE_PACKAGE_MODE_ISOLATED_OUTER:
                core_surface[core_mask] = _evaluate_isolated_model(
                    model,
                    self.x_grid_mm[core_mask],
                    self.y_grid_mm[core_mask],
                    model.support_bounds_mm,
                    core_mask[core_mask],
                )
            elif (
                model.package_mode == PRESSURE_PACKAGE_MODE_CENTER_PLUS_ONE_OUTER
                and model.peak_height is not None
            ):
                core_surface[core_mask] = _evaluate_center_outer_circular_model(
                    model,
                    self.x_grid_mm[core_mask],
                    self.y_grid_mm[core_mask],
                    model.support_bounds_mm,
                    core_mask[core_mask],
                )
            else:
                core_surface[core_mask] = _evaluate_core(
                    model, self.x_grid_mm[core_mask], self.y_grid_mm[core_mask]
                )
        diagnostics = {
            "raw_sensor_values": dict(model.raw_sensor_values),
            "thresholded_sensor_values": dict(model.sensor_values),
            "active_sensor_mask": model.active_sensor_mask,
            "package_mode": model.package_mode,
            "package_activity_confidence": model.package_activity_confidence,
            "quadrant_modes": {plane.label: plane.mode for plane in model.quadrant_planes},
            "quadrant_corner_values": {
                plane.label: plane.corner_value for plane in model.quadrant_planes
            },
            "quadrant_decay_origins": {
                plane.label: plane.decay_origin for plane in model.quadrant_planes
            },
            "peaks": tuple(
                (plane.label, plane.peak_point, plane.peak_height)
                for plane in model.quadrant_planes if plane.peak_point is not None
            ),
            "core_surface": core_surface,
            # These arrays identify the two separate support mechanisms.  The
            # detailed extension factors are intentionally diagnostic-only;
            # normal evaluation remains the single vectorized field path.
            "natural_decay_factor": self._diagnostic_decay_factor(model, natural=True),
            "boundary_guard_factor": self._diagnostic_decay_factor(model, natural=False),
            "final_package_candidate": pressure_grid.copy(),
            "support_bounds_mm": model.support_bounds_mm,
        }
        if model.package_mode == PRESSURE_PACKAGE_MODE_ISOLATED_OUTER:
            diagnostics.update(
                {
                    "isolated_circular_radius_mm": model.isolated_circular_radius_mm,
                    "isolated_measured_sensor_value": model.isolated_measured_sensor_value,
                    "isolated_actual_peak_value": model.peak_height,
                    "isolated_actual_peak_gain": model.isolated_actual_peak_gain,
                    "isolated_gain_cap_satisfied": model.isolated_gain_cap_satisfied,
                    "isolated_gain_cap_search_iterations": model.isolated_gain_cap_search_iterations,
                }
            )
        if (
            model.package_mode == PRESSURE_PACKAGE_MODE_CENTER_PLUS_ONE_OUTER
            and model.active_axis_sensor is not None
        ):
            peak_axis = (
                _axis_distance_from_peak_point(model.active_axis_sensor, model.peak_point)
                if model.peak_point is not None
                else None
            )
            diagnostics.update(
                {
                    "center_outer_peak_axis_mm": peak_axis,
                    "center_outer_circular_radius_mm": model.center_outer_circular_radius_mm,
                    "center_outer_measured_center_value": model.signal(SHEAR_POSITION_CENTER),
                    "center_outer_measured_outer_value": model.signal(model.active_axis_sensor),
                    "center_outer_actual_peak_value": model.peak_height,
                    "center_outer_actual_peak_gain": model.center_outer_actual_peak_gain,
                    "center_outer_center_scale": model.center_outer_center_scale,
                    "center_outer_outer_scale": model.center_outer_outer_scale,
                    "center_outer_gain_cap_satisfied": model.center_outer_gain_cap_satisfied,
                    "center_outer_natural_radius_mm": model.center_outer_natural_radius_mm,
                    "center_outer_fade_safe_minimum_radius_mm": model.center_outer_fade_safe_minimum_radius_mm,
                    "center_outer_geometric_maximum_radius_mm": model.center_outer_geometric_maximum_radius_mm,
                    "center_outer_center_factor": model.center_outer_center_factor,
                    "center_outer_outer_factor": model.center_outer_outer_factor,
                    "center_outer_fade_safe_search_iterations": model.center_outer_fade_safe_search_iterations,
                    "center_outer_gain_cap_search_iterations": model.center_outer_gain_cap_search_iterations,
                    "center_outer_used_fallback": model.center_outer_used_fallback,
                    "center_outer_extension_decay_factors_applicable": False,
                }
            )
        return diagnostics

    def _diagnostic_decay_factor(self, model: PressureFieldModel, *, natural: bool) -> np.ndarray:
        factors = np.zeros_like(self.x_grid_mm, dtype=np.float64)
        inside = _strict_support_mask(self.x_grid_mm, self.y_grid_mm, model.support_bounds_mm)
        if model.package_mode == PRESSURE_PACKAGE_MODE_ALL_INACTIVE:
            return factors
        factors[inside] = 1.0
        if model.package_mode == PRESSURE_PACKAGE_MODE_ISOLATED_OUTER:
            return factors
        if (
            model.package_mode == PRESSURE_PACKAGE_MODE_CENTER_PLUS_ONE_OUTER
            and model.peak_height is not None
        ):
            # Circular center-plus-one fields have no core/extension decay
            # split.  The retained generic factors are explicitly marked as
            # not applicable in the diagnostics payload.
            return np.zeros_like(factors)
        spacing = self.geometry.sensor_spacing_mm
        extension = inside & ((np.abs(self.x_grid_mm) > spacing) | (np.abs(self.y_grid_mm) > spacing))
        if model.package_mode == PRESSURE_PACKAGE_MODE_CENTER_PLUS_ONE_OUTER:
            _, natural_factor, boundary_factor = _extension_decay_components(
                model,
                self.x_grid_mm[extension],
                self.y_grid_mm[extension],
                model.support_bounds_mm,
                model.decay_origin,
            )
            factors[extension] = natural_factor if natural else boundary_factor
            return factors
        by_label = {plane.label: plane for plane in model.quadrant_planes}
        regions = {
            PRESSURE_QUADRANT_TOP_RIGHT: extension & (self.x_grid_mm > 0.0) & (self.y_grid_mm > 0.0),
            PRESSURE_QUADRANT_TOP_LEFT: extension & (self.x_grid_mm < 0.0) & (self.y_grid_mm > 0.0),
            PRESSURE_QUADRANT_BOTTOM_LEFT: extension & (self.x_grid_mm < 0.0) & (self.y_grid_mm < 0.0),
            PRESSURE_QUADRANT_BOTTOM_RIGHT: extension & (self.x_grid_mm > 0.0) & (self.y_grid_mm < 0.0),
        }
        for label, mask in regions.items():
            plane = by_label.get(label)
            if plane is None or not np.any(mask):
                factors[mask] = 0.0
                continue
            _, natural_factor, boundary_factor = _extension_decay_components(
                model,
                self.x_grid_mm[mask],
                self.y_grid_mm[mask],
                model.support_bounds_mm,
                plane.decay_origin,
            )
            factors[mask] = natural_factor if natural else boundary_factor
        return factors

    def _build_package_field_model(
        self,
        signals: Mapping[str, float],
        raw_signals: Mapping[str, float] | None = None,
    ) -> PressureFieldModel:
        raw_signals = signals if raw_signals is None else raw_signals
        package_mode, active_outer = self._classify_package(signals)
        if package_mode == PRESSURE_PACKAGE_MODE_ALL_INACTIVE:
            planes: tuple[PressureQuadrantPlane, ...] = ()
            axis_sensor = None
            peak_point = None
            peak_height = None
        elif package_mode == PRESSURE_PACKAGE_MODE_CENTER_ONLY:
            planes = ()
            axis_sensor = None
            peak_point = None
            peak_height = None
        elif package_mode == PRESSURE_PACKAGE_MODE_ISOLATED_OUTER:
            axis_sensor = active_outer[0]
            plane = self._build_isolated_outer_plane(signals, axis_sensor)
            planes = (plane,)
            peak_point, peak_height = plane.peak_point, plane.peak_height
        elif package_mode == PRESSURE_PACKAGE_MODE_CENTER_PLUS_ONE_OUTER:
            axis_sensor = active_outer[0]
            plane = self._build_center_plus_one_plane(signals, axis_sensor)
            planes = (plane,)
            peak_point, peak_height = plane.peak_point, plane.peak_height
        else:
            axis_sensor = None
            planes = tuple(
                self._build_quadrant_plane(signals, quadrant)
                for quadrant in self.quadrants
                if self._quadrant_is_active(signals, quadrant)
            )
            peak_point = None
            peak_height = None

        strength_candidates = [abs(value) for value in signals.values()]
        strength_candidates.extend(
            abs(float(plane.peak_height))
            for plane in planes
            if plane.peak_height is not None
        )
        model_strength = max(strength_candidates, default=0.0)
        # General fields select local quadrant origins at evaluation time;
        # single-axis packages retain their one explicit axis origin here.
        decay_origin = (
            planes[0].decay_origin
            if package_mode in (
                PRESSURE_PACKAGE_MODE_ISOLATED_OUTER,
                PRESSURE_PACKAGE_MODE_CENTER_PLUS_ONE_OUTER,
            ) and planes
            else (0.0, 0.0)
        )
        model = PressureFieldModel(
            geometry=self.geometry, package_mode=package_mode,
            raw_sensor_values=tuple(
                (sensor, float(raw_signals[sensor])) for sensor in SHEAR_SENSOR_POSITIONS
            ),
            sensor_values=tuple((sensor, float(signals[sensor])) for sensor in SHEAR_SENSOR_POSITIONS),
            active_sensor_mask=build_active_sensor_mask(signals),
            package_activity_confidence=self._package_activity_confidence(raw_signals),
            quadrant_planes=planes, support_bounds_mm=self.support_bounds_mm,
            decay_origin=(float(decay_origin[0]), float(decay_origin[1])),
            model_strength=float(model_strength), decay_rate=self.decay_rate,
            decay_ref_distance_mm=self.decay_ref_distance_mm,
            peak_gain_slope_per_mm=self.peak_gain_slope_per_mm,
            maximum_peak_gain=self.maximum_peak_gain,
            natural_decay_reference_distance_mm=self.natural_decay_reference_distance_mm,
            decay_amplitude_reference=self.decay_amplitude_reference,
            minimum_decay_reach_mm=self.minimum_decay_reach_mm,
            maximum_decay_reach_mm=self.maximum_decay_reach_mm,
            geometry_epsilon=self.geometry_epsilon,
            minimum_lateral_width_mm=max(3.0 * self.cell_size_mm, self.geometry_epsilon),
            active_axis_sensor=axis_sensor, peak_point=peak_point, peak_height=peak_height,
        )
        if package_mode == PRESSURE_PACKAGE_MODE_ISOLATED_OUTER:
            (
                radius,
                measured_value,
                inferred_peak_value,
                actual_gain,
                cap_satisfied,
                gain_cap_search_iterations,
            ) = (
                _isolated_circular_profile(model, self.support_bounds_mm)
            )
            plane = replace(
                model.quadrant_planes[0],
                peak_height=inferred_peak_value,
            )
            model = replace(
                model,
                quadrant_planes=(plane,),
                model_strength=max(model.model_strength, abs(inferred_peak_value)),
                peak_height=inferred_peak_value,
                isolated_circular_radius_mm=radius,
                isolated_measured_sensor_value=measured_value,
                isolated_actual_peak_gain=actual_gain,
                isolated_gain_cap_satisfied=cap_satisfied,
                isolated_gain_cap_search_iterations=gain_cap_search_iterations,
            )
        elif (
            package_mode == PRESSURE_PACKAGE_MODE_CENTER_PLUS_ONE_OUTER
            and model.peak_point is not None
            and model.signal(SHEAR_POSITION_CENTER) * model.signal(axis_sensor) > 0.0
        ):
            profile = _center_outer_circular_profile(model, self.support_bounds_mm)
            if profile is None:
                # Keep the pre-circular bounded axis interpolation as a
                # deterministic live-data fallback when no circular radius is
                # geometrically/numerically feasible.
                model = replace(model, center_outer_used_fallback=True)
            else:
                plane = replace(
                    model.quadrant_planes[0],
                    peak_height=profile.actual_peak_value,
                )
                model = replace(
                    model,
                    quadrant_planes=(plane,),
                    model_strength=max(model.model_strength, abs(profile.actual_peak_value)),
                    peak_height=profile.actual_peak_value,
                    center_outer_circular_radius_mm=profile.radius,
                    center_outer_center_scale=profile.center_scale,
                    center_outer_outer_scale=profile.outer_scale,
                    center_outer_actual_peak_gain=profile.actual_peak_gain,
                    center_outer_gain_cap_satisfied=profile.gain_cap_satisfied,
                    center_outer_natural_radius_mm=profile.natural_radius,
                    center_outer_fade_safe_minimum_radius_mm=profile.fade_safe_minimum_radius,
                    center_outer_geometric_maximum_radius_mm=profile.geometric_maximum_radius,
                    center_outer_center_factor=profile.center_factor,
                    center_outer_outer_factor=profile.outer_factor,
                    center_outer_fade_safe_search_iterations=profile.fade_safe_search_iterations,
                    center_outer_gain_cap_search_iterations=profile.gain_cap_search_iterations,
                )
        return model

    def _classify_package(self, signals: Mapping[str, float]) -> tuple[str, list[str]]:
        active_outer = [sensor for sensor in _OUTER_SENSORS if self.is_signal_active(signals[sensor])]
        center_active = self.is_signal_active(signals[SHEAR_POSITION_CENTER])
        if not center_active and not active_outer:
            return PRESSURE_PACKAGE_MODE_ALL_INACTIVE, active_outer
        if center_active and not active_outer:
            return PRESSURE_PACKAGE_MODE_CENTER_ONLY, active_outer
        if not center_active and len(active_outer) == 1:
            return PRESSURE_PACKAGE_MODE_ISOLATED_OUTER, active_outer
        if center_active and len(active_outer) == 1:
            return PRESSURE_PACKAGE_MODE_CENTER_PLUS_ONE_OUTER, active_outer
        return PRESSURE_PACKAGE_MODE_GENERAL_MULTI_SENSOR, active_outer

    def _validate_parameters(self) -> None:
        if self.decay_ref_distance_mm <= 0.0:
            raise ValueError("decay_ref_distance_mm must be positive")
        if self.peak_gain_slope_per_mm < 0.0 or self.maximum_peak_gain < 1.0:
            raise ValueError("peak-height shaping parameters are invalid")
        if self.natural_decay_reference_distance_mm <= 0.0 or self.decay_amplitude_reference <= 0.0:
            raise ValueError("natural decay parameters must be positive")
        if not 0.0 <= self.minimum_decay_reach_mm <= self.maximum_decay_reach_mm:
            raise ValueError("decay reach limits are invalid")
        if self.signal_activity_threshold < 0.0:
            raise ValueError("signal_activity_threshold must be non-negative")
        if self.geometry_epsilon <= 0.0:
            raise ValueError("geometry_epsilon must be positive")

    def _build_sensor_positions(self) -> dict[str, tuple[float, float]]:
        spacing = self.sensor_spacing_mm
        return {
            SHEAR_POSITION_CENTER: (0.0, 0.0), SHEAR_POSITION_LEFT: (-spacing, 0.0),
            SHEAR_POSITION_RIGHT: (spacing, 0.0), SHEAR_POSITION_TOP: (0.0, spacing),
            SHEAR_POSITION_BOTTOM: (0.0, -spacing),
        }

    def _build_quadrant_definitions(self) -> tuple[_QuadrantDefinition, ...]:
        return (
            _QuadrantDefinition(PRESSURE_QUADRANT_TOP_RIGHT, SHEAR_POSITION_RIGHT, SHEAR_POSITION_TOP, 1.0, 1.0, (SHEAR_POSITION_CENTER, SHEAR_POSITION_RIGHT, SHEAR_POSITION_TOP)),
            _QuadrantDefinition(PRESSURE_QUADRANT_TOP_LEFT, SHEAR_POSITION_LEFT, SHEAR_POSITION_TOP, -1.0, 1.0, (SHEAR_POSITION_CENTER, SHEAR_POSITION_LEFT, SHEAR_POSITION_TOP)),
            _QuadrantDefinition(PRESSURE_QUADRANT_BOTTOM_LEFT, SHEAR_POSITION_LEFT, SHEAR_POSITION_BOTTOM, -1.0, -1.0, (SHEAR_POSITION_CENTER, SHEAR_POSITION_LEFT, SHEAR_POSITION_BOTTOM)),
            _QuadrantDefinition(PRESSURE_QUADRANT_BOTTOM_RIGHT, SHEAR_POSITION_RIGHT, SHEAR_POSITION_BOTTOM, 1.0, -1.0, (SHEAR_POSITION_CENTER, SHEAR_POSITION_RIGHT, SHEAR_POSITION_BOTTOM)),
        )

    def _raw_signals(self, normalized_signals: Mapping[str, float]) -> dict[str, float]:
        signals: dict[str, float] = {}
        for sensor in SHEAR_SENSOR_POSITIONS:
            value = float(normalized_signals.get(sensor, SHEAR_ZERO_VALUE))
            if not np.isfinite(value):
                raise ValueError(f"pressure signal {sensor} must be finite")
            signals[sensor] = value
        return signals

    def _normalize_signals(self, raw_signals: Mapping[str, float]) -> dict[str, float]:
        """Remove exact and sub-threshold input after finite validation."""

        return {
            sensor: float(raw_signals[sensor]) if self.is_signal_active(raw_signals[sensor]) else 0.0
            for sensor in SHEAR_SENSOR_POSITIONS
        }

    def is_signal_active(self, value: float) -> bool:
        effective_threshold = max(self.signal_activity_threshold, PRESSURE_NUMERIC_EPSILON)
        return abs(float(value)) > effective_threshold

    def _package_activity_confidence(self, raw_signals: Mapping[str, float]) -> float:
        raw_strength = max(abs(float(raw_signals[sensor])) for sensor in SHEAR_SENSOR_POSITIONS)
        activity_low = max(self.signal_activity_threshold, PRESSURE_NUMERIC_EPSILON)
        activity_high = max(
            activity_low * 2.0,
            activity_low + 0.02 * self.decay_amplitude_reference,
        )
        if raw_strength <= activity_low:
            return 0.0
        if raw_strength >= activity_high:
            return 1.0
        t = (raw_strength - activity_low) / (activity_high - activity_low)
        return float(3.0 * t ** 2 - 2.0 * t ** 3)

    def _quadrant_is_active(self, signals: Mapping[str, float], quadrant: _QuadrantDefinition) -> bool:
        return any(self.is_signal_active(signals[sensor]) for sensor in quadrant.sensors)

    def _build_center_plus_one_plane(self, signals: Mapping[str, float], sensor: str) -> PressureQuadrantPlane:
        center = float(signals[SHEAR_POSITION_CENTER])
        outer = float(signals[sensor])
        sign = self._value_sign(center if center else outer)
        same_sign = center * outer > 0.0
        peak_point: tuple[float, float] | None = None
        peak_height: float | None = None
        mode = PRESSURE_QUADRANT_MODE_SIGNED_TRANSITION
        if same_sign:
            peak_axis = _center_outer_peak_axis(
                center,
                outer,
                self.sensor_spacing_mm,
            )
            peak_point = self._point_on_sensor_axis(sensor, peak_axis)
            mode = PRESSURE_QUADRANT_MODE_SINGLE_AXIS_PEAKED
        a, b = self._axis_plane_coefficients(sensor, center, outer)
        return PressureQuadrantPlane(
            label=sensor, a=a, b=b, c=center, sign=sign,
            sensors=(SHEAR_POSITION_CENTER, sensor), mode=mode,
            peak_point=peak_point, peak_height=peak_height,
            single_axis_peak_sensor=sensor, single_axis_center_value=center,
            single_axis_outer_value=outer,
            decay_origin=peak_point or self._axis_decay_origin(signals, sensor),
        )

    def _build_isolated_outer_plane(self, signals: Mapping[str, float], sensor: str) -> PressureQuadrantPlane:
        value = float(signals[sensor])
        peak_axis = self.sensor_spacing_mm + self.near_outer_peak_offset_mm
        peak_point = self._point_on_sensor_axis(sensor, peak_axis)
        a, b = self._axis_plane_coefficients(sensor, 0.0, value)
        return PressureQuadrantPlane(
            label=sensor, a=a, b=b, c=0.0, sign=self._value_sign(value),
            sensors=(SHEAR_POSITION_CENTER, sensor),
            mode=PRESSURE_QUADRANT_MODE_ISOLATED_OUTER_PEAKED,
            peak_point=peak_point, peak_height=None,
            single_outer_decay_sensor=sensor, single_axis_peak_sensor=sensor,
            single_axis_center_value=0.0, single_axis_outer_value=value,
            decay_origin=peak_point,
        )

    def _build_quadrant_plane(self, signals: Mapping[str, float], quadrant: _QuadrantDefinition) -> PressureQuadrantPlane:
        a, b, c = self._three_sensor_plane_coefficients(signals, quadrant)
        values = tuple(float(signals[sensor]) for sensor in quadrant.sensors)
        active = tuple(value for value in values if self.is_signal_active(value))
        sign = self._value_sign(active[0]) if active else 0.0
        mixed_sign = any(value > 0.0 for value in active) and any(value < 0.0 for value in active)
        corner_value = (values[1] + values[2] + (0.5 * values[0])) / 2.5
        weighted_origin = self._quadrant_decay_origin(signals, quadrant)
        if mixed_sign:
            return PressureQuadrantPlane(
                label=quadrant.label, a=a, b=b, c=c, sign=sign, sensors=quadrant.sensors,
                mode=PRESSURE_QUADRANT_MODE_SIGNED_TRANSITION, corner_value=corner_value,
                triangles=self._build_peakless_triangles(signals, quadrant, corner_value),
                decay_origin=weighted_origin,
            )
        peak_x, peak_y = self._pressure_point(signals, quadrant)
        if not self._is_peaked_pressure_point(peak_x, peak_y, quadrant):
            return PressureQuadrantPlane(
                label=quadrant.label, a=a, b=b, c=c, sign=sign, sensors=quadrant.sensors,
                mode=PRESSURE_QUADRANT_MODE_PEAKLESS, corner_value=corner_value,
                triangles=self._build_peakless_triangles(signals, quadrant, corner_value),
                decay_origin=weighted_origin,
            )
        peak_height = self._pressure_point_height(signals, quadrant, peak_x, peak_y)
        triangles = self._build_peaked_triangles(signals, quadrant, peak_x, peak_y, peak_height, corner_value)
        if not triangles:
            return PressureQuadrantPlane(
                label=quadrant.label, a=a, b=b, c=c, sign=sign, sensors=quadrant.sensors,
                mode=PRESSURE_QUADRANT_MODE_PEAKLESS, corner_value=corner_value,
                triangles=self._build_peakless_triangles(signals, quadrant, corner_value),
                decay_origin=weighted_origin,
            )
        return PressureQuadrantPlane(
            label=quadrant.label, a=a, b=b, c=c, sign=sign, sensors=quadrant.sensors,
            mode=PRESSURE_QUADRANT_MODE_PEAKED, peak_point=(peak_x, peak_y),
            peak_height=peak_height, corner_value=corner_value, triangles=triangles,
            decay_origin=(peak_x, peak_y),
        )

    def _axis_decay_origin(
        self, signals: Mapping[str, float], sensor: str
    ) -> tuple[float, float]:
        center_weight = abs(float(signals[SHEAR_POSITION_CENTER]))
        outer_weight = abs(float(signals[sensor]))
        total_weight = center_weight + outer_weight
        if total_weight <= PRESSURE_NUMERIC_EPSILON:
            return (0.0, 0.0)
        outer_x, outer_y = self.sensor_positions[sensor]
        return (
            outer_weight * outer_x / total_weight,
            outer_weight * outer_y / total_weight,
        )

    def _quadrant_decay_origin(
        self, signals: Mapping[str, float], quadrant: _QuadrantDefinition
    ) -> tuple[float, float]:
        weights = np.asarray(
            [abs(float(signals[sensor])) for sensor in quadrant.sensors], dtype=np.float64
        )
        total_weight = float(weights.sum())
        if total_weight <= PRESSURE_NUMERIC_EPSILON:
            return (0.0, 0.0)
        positions = np.asarray(
            [self.sensor_positions[sensor] for sensor in quadrant.sensors], dtype=np.float64
        )
        origin = (weights[:, np.newaxis] * positions).sum(axis=0) / total_weight
        spacing = self.sensor_spacing_mm
        low_x, high_x = sorted((0.0, quadrant.horizontal_sign * spacing))
        low_y, high_y = sorted((0.0, quadrant.vertical_sign * spacing))
        return (
            float(np.clip(origin[0], low_x, high_x)),
            float(np.clip(origin[1], low_y, high_y)),
        )

    def _three_sensor_plane_coefficients(self, signals: Mapping[str, float], quadrant: _QuadrantDefinition) -> tuple[float, float, float]:
        center = float(signals[SHEAR_POSITION_CENTER])
        horizontal = float(signals[quadrant.horizontal_sensor])
        vertical = float(signals[quadrant.vertical_sensor])
        return (
            quadrant.horizontal_sign * (horizontal - center) / self.sensor_spacing_mm,
            quadrant.vertical_sign * (vertical - center) / self.sensor_spacing_mm,
            center,
        )

    def _pressure_point(self, signals: Mapping[str, float], quadrant: _QuadrantDefinition) -> tuple[float, float]:
        center = _peak_position_weight(signals[SHEAR_POSITION_CENTER])
        horizontal = _peak_position_weight(signals[quadrant.horizontal_sensor])
        vertical = _peak_position_weight(signals[quadrant.vertical_sensor])
        return (
            quadrant.horizontal_sign * self.sensor_spacing_mm * horizontal / (horizontal + center) if horizontal + center else 0.0,
            quadrant.vertical_sign * self.sensor_spacing_mm * vertical / (vertical + center) if vertical + center else 0.0,
        )

    def _is_peaked_pressure_point(self, peak_x: float, peak_y: float, quadrant: _QuadrantDefinition) -> bool:
        spacing = self.sensor_spacing_mm
        return (
            self.geometry_epsilon < peak_x * quadrant.horizontal_sign < spacing - self.geometry_epsilon
            and self.geometry_epsilon < peak_y * quadrant.vertical_sign < spacing - self.geometry_epsilon
        )

    def _pressure_point_height(self, signals: Mapping[str, float], quadrant: _QuadrantDefinition, peak_x: float, peak_y: float) -> float:
        estimate_sum = 0.0
        weight_sum = 0.0
        for sensor in quadrant.sensors:
            sensor_x, sensor_y = self.sensor_positions[sensor]
            distance = float(np.hypot(sensor_x - peak_x, sensor_y - peak_y))
            gain = min(
                self.maximum_peak_gain,
                1.0 + distance * self.peak_gain_slope_per_mm,
            )
            weight = 1.0 / max(self.geometry_epsilon, distance) ** 2
            estimate_sum += float(signals[sensor]) * gain * weight
            weight_sum += weight
        return estimate_sum / weight_sum if weight_sum else 0.0

    def _build_peakless_triangles(self, signals: Mapping[str, float], quadrant: _QuadrantDefinition, corner_value: float) -> tuple[PressureTrianglePlane, ...]:
        spacing = self.sensor_spacing_mm
        center = (0.0, 0.0, float(signals[SHEAR_POSITION_CENTER]))
        horizontal = (quadrant.horizontal_sign * spacing, 0.0, float(signals[quadrant.horizontal_sensor]))
        vertical = (0.0, quadrant.vertical_sign * spacing, float(signals[quadrant.vertical_sensor]))
        corner = (quadrant.horizontal_sign * spacing, quadrant.vertical_sign * spacing, corner_value)
        return tuple(
            plane for plane in (
                self._solve_triangle_plane("core-horizontal", center, horizontal, corner),
                self._solve_triangle_plane("core-vertical", center, corner, vertical),
            ) if plane is not None
        )

    def _build_peaked_triangles(self, signals: Mapping[str, float], quadrant: _QuadrantDefinition, peak_x: float, peak_y: float, peak_height: float, corner_value: float) -> tuple[PressureTrianglePlane, ...]:
        spacing = self.sensor_spacing_mm
        center = (0.0, 0.0, float(signals[SHEAR_POSITION_CENTER]))
        horizontal = (quadrant.horizontal_sign * spacing, 0.0, float(signals[quadrant.horizontal_sensor]))
        vertical = (0.0, quadrant.vertical_sign * spacing, float(signals[quadrant.vertical_sensor]))
        corner = (quadrant.horizontal_sign * spacing, quadrant.vertical_sign * spacing, corner_value)
        peak = (peak_x, peak_y, peak_height)
        triangles = (
            self._solve_triangle_plane("peak-center-horizontal", peak, center, horizontal),
            self._solve_triangle_plane("peak-horizontal-corner", peak, horizontal, corner),
            self._solve_triangle_plane("peak-corner-vertical", peak, corner, vertical),
            self._solve_triangle_plane("peak-vertical-center", peak, vertical, center),
        )
        return tuple(triangle for triangle in triangles if triangle is not None) if all(triangles) else ()

    def _solve_triangle_plane(self, name: str, first: tuple[float, float, float], second: tuple[float, float, float], third: tuple[float, float, float]) -> PressureTrianglePlane | None:
        matrix = np.asarray(((first[0], first[1], 1.0), (second[0], second[1], 1.0), (third[0], third[1], 1.0)), dtype=np.float64)
        if abs(float(np.linalg.det(matrix))) <= self.geometry_epsilon:
            return None
        a, b, c = np.linalg.solve(matrix, np.asarray((first[2], second[2], third[2]), dtype=np.float64))
        return PressureTrianglePlane(name, float(a), float(b), float(c), ((first[0], first[1]), (second[0], second[1]), (third[0], third[1])))

    def _point_on_sensor_axis(self, sensor: str, distance: float) -> tuple[float, float]:
        if sensor == SHEAR_POSITION_LEFT:
            return (-distance, 0.0)
        if sensor == SHEAR_POSITION_RIGHT:
            return (distance, 0.0)
        if sensor == SHEAR_POSITION_TOP:
            return (0.0, distance)
        return (0.0, -distance)

    def _axis_plane_coefficients(self, sensor: str, center: float, outer: float) -> tuple[float, float]:
        delta = (outer - center) / self.sensor_spacing_mm
        if sensor == SHEAR_POSITION_LEFT:
            return (-delta, 0.0)
        if sensor == SHEAR_POSITION_RIGHT:
            return (delta, 0.0)
        if sensor == SHEAR_POSITION_TOP:
            return (0.0, delta)
        return (0.0, -delta)

    def _value_sign(self, value: float) -> float:
        return PRESSURE_AXIS_POSITIVE_DIRECTION if value > 0.0 else PRESSURE_AXIS_NEGATIVE_DIRECTION if value < 0.0 else 0.0

    # Compatibility helpers retained for older focused callers.  New code uses
    # the immutable model retained on PressureMapResult.
    def _build_pressure_grid(self, quadrant_planes: tuple[PressureQuadrantPlane, ...]) -> np.ndarray:
        return self._evaluate_planes_at(quadrant_planes, self.x_grid_mm, self.y_grid_mm, support_bounds_mm=self.support_bounds_mm)

    def _evaluate_planes_at(self, quadrant_planes: tuple[PressureQuadrantPlane, ...], x_values_mm: np.ndarray, y_values_mm: np.ndarray, *, support_bounds_mm: tuple[float, float, float, float]) -> np.ndarray:
        signals = {sensor: 0.0 for sensor in SHEAR_SENSOR_POSITIONS}
        for plane in quadrant_planes:
            for sensor in plane.sensors:
                if sensor == SHEAR_POSITION_CENTER:
                    signals[sensor] = plane.c
        model = self._build_package_field_model(signals)
        return model.evaluate(x_values_mm, y_values_mm, support_bounds_mm)

    def _evaluate_quadrant_for_region(self, plane: PressureQuadrantPlane, x_values_mm: np.ndarray, y_values_mm: np.ndarray, *, support_bounds_mm: tuple[float, float, float, float] | None = None) -> np.ndarray:
        if plane.triangles:
            return _evaluate_triangles(plane, np.asarray(x_values_mm), np.asarray(y_values_mm), self.geometry_epsilon)
        return (plane.a * np.asarray(x_values_mm)) + (plane.b * np.asarray(y_values_mm)) + plane.c

    def _natural_decay_reach(self, strength: float) -> float:
        return float(_natural_decay_reach(np.asarray(strength), self))


def _natural_decay_reach(strength: np.ndarray, model: PressureFieldModel | PressureMapGenerator) -> np.ndarray:
    normalized = np.abs(np.asarray(strength, dtype=np.float64)) / float(
        model.decay_amplitude_reference
    )
    minimum = float(model.minimum_decay_reach_mm)
    natural = float(model.natural_decay_reference_distance_mm)
    maximum = float(model.maximum_decay_reach_mm)
    low_reach = minimum + normalized * (natural - minimum)
    high_t = np.clip(normalized - 1.0, 0.0, 1.0)
    high_reach = natural + high_t * (maximum - natural)
    return np.clip(np.where(normalized <= 1.0, low_reach, high_reach), minimum, maximum)


def _radius_search_tolerance_mm(model: PressureFieldModel | PressureMapGenerator) -> float:
    """Return the resolution-aware scalar radius-search tolerance."""

    return float(np.clip(
        PRESSURE_RADIUS_SEARCH_TOLERANCE_FRACTION * model.geometry.aligned_cell_size_mm,
        PRESSURE_RADIUS_SEARCH_TOLERANCE_MIN_MM,
        PRESSURE_RADIUS_SEARCH_TOLERANCE_MAX_MM,
    ))


def _minimum_radius_for_gain_cap(
    model: PressureFieldModel,
    offset: float,
    maximum_peak_gain: float,
    maximum_radius: float,
) -> tuple[float, int]:
    """Find the smallest circular radius that satisfies the peak-gain cap."""

    epsilon = PRESSURE_NUMERIC_EPSILON
    if maximum_radius <= offset + epsilon or maximum_peak_gain <= 1.0 + epsilon:
        return maximum_radius, 0
    target_factor = 1.0 / float(maximum_peak_gain)
    high_factor = _smoothstep_fade_scalar(offset, maximum_radius)
    if high_factor < target_factor:
        return maximum_radius, 0

    low = offset + epsilon
    high = maximum_radius
    tolerance = _radius_search_tolerance_mm(model)
    iterations = 0
    while (
        high - low > tolerance
        and iterations < PRESSURE_MAX_RADIUS_SEARCH_ITERATIONS
    ):
        midpoint = (low + high) / 2.0
        midpoint_factor = _smoothstep_fade_scalar(offset, midpoint)
        if midpoint_factor >= target_factor:
            high = midpoint
        else:
            low = midpoint
        iterations += 1
    return high, iterations


def _isolated_circular_radius(
    model: PressureFieldModel,
    support_bounds: tuple[float, float, float, float],
) -> tuple[float, bool, int]:
    """Return the support-limited circular radius and gain-cap status."""

    sensor = model.active_axis_sensor
    if sensor is None or model.peak_point is None:
        raise ValueError("isolated circular lobe requires an active outer sensor and peak point")
    measured_value = abs(float(model.signal(sensor)))
    offset = float(model.geometry.near_outer_peak_offset_mm)
    peak_x, peak_y = model.peak_point
    left, right, bottom, top = (float(value) for value in support_bounds)
    boundary_radius = min(
        peak_x - left,
        right - peak_x,
        peak_y - bottom,
        top - peak_y,
    )
    if boundary_radius <= offset + PRESSURE_NUMERIC_EPSILON:
        raise ValueError(
            "isolated circular lobe requires the inferred peak to have more "
            "than one offset of support before the Outer Boundary"
        )
    natural_radius = float(
        _natural_decay_reach(np.asarray(measured_value, dtype=np.float64), model)
    )
    radius = min(max(natural_radius, np.nextafter(offset, np.inf)), boundary_radius)
    sensor_factor = _smoothstep_fade_scalar(offset, radius)
    target_factor = 1.0 / float(model.maximum_peak_gain)
    gain_cap_search_iterations = 0
    if sensor_factor < target_factor:
        radius, gain_cap_search_iterations = _minimum_radius_for_gain_cap(
            model,
            offset,
            float(model.maximum_peak_gain),
            boundary_radius,
        )
        sensor_factor = _smoothstep_fade_scalar(offset, radius)
    if sensor_factor <= PRESSURE_NUMERIC_EPSILON:
        raise ValueError(
            "isolated circular lobe cannot preserve the active sensor value "
            "with the configured peak offset and support"
        )
    actual_gain = 1.0 / sensor_factor
    cap_satisfied = actual_gain <= float(model.maximum_peak_gain) + 1e-10
    return radius, cap_satisfied, gain_cap_search_iterations


def _isolated_circular_profile(
    model: PressureFieldModel,
    support_bounds: tuple[float, float, float, float],
) -> tuple[float, float, float, float, bool, int]:
    """Return radius, measured value, inferred peak, gain, and cap status."""

    radius, cap_satisfied, gain_cap_search_iterations = _isolated_circular_radius(
        model, support_bounds
    )
    sensor = model.active_axis_sensor
    if sensor is None:
        raise ValueError("isolated circular lobe requires an active outer sensor")
    measured_value = float(model.signal(sensor))
    offset = float(model.geometry.near_outer_peak_offset_mm)
    sensor_factor = _smoothstep_fade_scalar(offset, radius)
    if sensor_factor <= PRESSURE_NUMERIC_EPSILON:
        raise ValueError(
            "isolated circular lobe cannot preserve the active sensor value "
            "with the configured peak offset and support"
        )
    inferred_peak_value = measured_value / sensor_factor
    actual_gain = abs(inferred_peak_value / measured_value) if measured_value else 0.0
    return (
        radius,
        measured_value,
        inferred_peak_value,
        actual_gain,
        cap_satisfied,
        gain_cap_search_iterations,
    )


def _axis_distance_from_peak_point(
    sensor: str,
    peak_point: tuple[float, float],
) -> float:
    """Return the positive canonical-axis coordinate of a retained peak."""

    peak_x, peak_y = peak_point
    if sensor == SHEAR_POSITION_RIGHT:
        return float(peak_x)
    if sensor == SHEAR_POSITION_LEFT:
        return float(-peak_x)
    if sensor == SHEAR_POSITION_TOP:
        return float(peak_y)
    return float(-peak_y)


@dataclass(frozen=True, slots=True)
class _CenterOuterCircularProfile:
    """One validated, retained circular center-plus-one profile."""

    radius: float
    actual_peak_value: float
    center_scale: float
    outer_scale: float
    actual_peak_gain: float
    gain_cap_satisfied: bool
    natural_radius: float
    fade_safe_minimum_radius: float
    geometric_maximum_radius: float
    center_factor: float
    outer_factor: float
    fade_safe_search_iterations: int
    gain_cap_search_iterations: int


def _center_outer_circular_profile(
    model: PressureFieldModel,
    support_bounds: tuple[float, float, float, float],
) -> _CenterOuterCircularProfile | None:
    """Build a feasible retained circular center-plus-one profile.

    ``None`` deliberately selects the established bounded axis interpolation
    fallback.  Transient live data must not become a generator exception.
    """

    sensor = model.active_axis_sensor
    if sensor is None or model.peak_point is None:
        return None
    center = float(model.signal(SHEAR_POSITION_CENTER))
    outer = float(model.signal(sensor))
    spacing = float(model.geometry.sensor_spacing_mm)
    peak_axis = _axis_distance_from_peak_point(sensor, model.peak_point)
    distance_to_center = peak_axis
    distance_to_outer = spacing - peak_axis
    farthest_anchor_distance = max(distance_to_center, distance_to_outer)
    inactive_sensor_limit = min(
        spacing + peak_axis,
        float(np.hypot(peak_axis, spacing)),
    )
    peak_x, peak_y = model.peak_point
    left, right, bottom, top = (float(value) for value in support_bounds)
    boundary_limit = min(
        peak_x - left,
        right - peak_x,
        peak_y - bottom,
        top - peak_y,
    )
    maximum_radius = min(inactive_sensor_limit, boundary_limit)
    if not np.isfinite(maximum_radius) or maximum_radius <= farthest_anchor_distance:
        return None

    def anchor_factors(candidate_radius: float) -> tuple[float, float]:
        return (
            _smoothstep_fade_scalar(distance_to_center, candidate_radius),
            _smoothstep_fade_scalar(distance_to_outer, candidate_radius),
        )

    maximum_center_factor, maximum_outer_factor = anchor_factors(maximum_radius)
    if min(maximum_center_factor, maximum_outer_factor) <= PRESSURE_NUMERIC_EPSILON:
        return None

    anchor_strength = max(abs(center), abs(outer))
    natural_radius = float(
        _natural_decay_reach(np.asarray(anchor_strength, dtype=np.float64), model)
    )
    natural_candidate = float(np.clip(
        natural_radius,
        farthest_anchor_distance,
        maximum_radius,
    ))
    natural_center_factor, natural_outer_factor = anchor_factors(natural_candidate)
    fade_safe_search_iterations = 0
    if min(natural_center_factor, natural_outer_factor) > PRESSURE_NUMERIC_EPSILON:
        fade_safe_minimum_radius = natural_candidate
    else:
        # Search only when the natural candidate is too close to the compact
        # support endpoint, returning the known-valid high side.
        low = farthest_anchor_distance
        high = maximum_radius
        tolerance = _radius_search_tolerance_mm(model)
        iterations = 0
        while (
            high - low > tolerance
            and iterations < PRESSURE_MAX_RADIUS_SEARCH_ITERATIONS
        ):
            midpoint = (low + high) / 2.0
            if min(anchor_factors(midpoint)) > PRESSURE_NUMERIC_EPSILON:
                high = midpoint
            else:
                low = midpoint
            iterations += 1
        fade_safe_minimum_radius = high
        fade_safe_search_iterations = iterations
    radius = max(natural_candidate, fade_safe_minimum_radius)
    if not np.isfinite(radius):
        return None

    def profile_at(
        candidate_radius: float,
    ) -> tuple[float, float, float, float, float, float] | None:
        center_factor, outer_factor = anchor_factors(candidate_radius)
        if min(center_factor, outer_factor) <= PRESSURE_NUMERIC_EPSILON:
            return None
        required_peak_magnitude = max(
            abs(center) / center_factor,
            abs(outer) / outer_factor,
        )
        field_sign = 1.0 if center > 0.0 else -1.0
        actual_peak_value = field_sign * required_peak_magnitude
        center_scale = center / (actual_peak_value * center_factor)
        outer_scale = outer / (actual_peak_value * outer_factor)
        reference_magnitude = max(abs(center), abs(outer))
        actual_peak_gain = abs(actual_peak_value) / reference_magnitude
        values = (
            center_factor,
            outer_factor,
            actual_peak_value,
            center_scale,
            outer_scale,
            actual_peak_gain,
        )
        return values if all(np.isfinite(value) for value in values) else None

    initial_profile = profile_at(radius)
    if initial_profile is None:
        return None
    gain_cap_search_iterations = 0
    if initial_profile[-1] > model.maximum_peak_gain + 1e-10:
        maximum_profile = profile_at(maximum_radius)
        if maximum_profile is not None and maximum_profile[-1] <= model.maximum_peak_gain + 1e-10:
            low = radius
            high = maximum_radius
            tolerance = _radius_search_tolerance_mm(model)
            iterations = 0
            while (
                high - low > tolerance
                and iterations < PRESSURE_MAX_RADIUS_SEARCH_ITERATIONS
            ):
                midpoint = (low + high) / 2.0
                midpoint_profile = profile_at(midpoint)
                if midpoint_profile is not None and midpoint_profile[-1] <= model.maximum_peak_gain:
                    high = midpoint
                else:
                    low = midpoint
                iterations += 1
            radius = high
            gain_cap_search_iterations = iterations
        else:
            radius = maximum_radius

    final_profile = profile_at(radius)
    if final_profile is None:
        return None
    center_factor, outer_factor, actual_peak_value, center_scale, outer_scale, actual_peak_gain = final_profile
    if not (
        0.0 < center_scale <= 1.0 + 1e-10
        and 0.0 < outer_scale <= 1.0 + 1e-10
    ):
        return None
    return _CenterOuterCircularProfile(
        radius=radius,
        actual_peak_value=actual_peak_value,
        center_scale=center_scale,
        outer_scale=outer_scale,
        actual_peak_gain=actual_peak_gain,
        gain_cap_satisfied=actual_peak_gain <= model.maximum_peak_gain + 1e-10,
        natural_radius=natural_radius,
        fade_safe_minimum_radius=fade_safe_minimum_radius,
        geometric_maximum_radius=maximum_radius,
        center_factor=center_factor,
        outer_factor=outer_factor,
        fade_safe_search_iterations=fade_safe_search_iterations,
        gain_cap_search_iterations=gain_cap_search_iterations,
    )


def _evaluate_pressure_field_model(model: PressureFieldModel, x_values: np.ndarray, y_values: np.ndarray, support_bounds: tuple[float, float, float, float]) -> np.ndarray:
    x_values, y_values = np.broadcast_arrays(x_values, y_values)
    values = np.zeros_like(x_values, dtype=np.float64)
    if model.package_mode == PRESSURE_PACKAGE_MODE_ALL_INACTIVE:
        return values
    # The strict mask is the terminal support contract: samples at or beyond
    # an Outer Boundary are identically zero, regardless of interpolation.
    inside = _strict_support_mask(x_values, y_values, support_bounds)
    if not np.any(inside):
        return values
    if model.package_mode == PRESSURE_PACKAGE_MODE_CENTER_ONLY:
        values[inside] = _evaluate_center_only_model(
            model, x_values[inside], y_values[inside]
        )
        values[~inside] = 0.0
        return _numeric_cleanup(values)
    if model.package_mode == PRESSURE_PACKAGE_MODE_ISOLATED_OUTER:
        values = _evaluate_isolated_model(model, x_values, y_values, support_bounds, inside)
        values[~inside] = 0.0
        return _numeric_cleanup(values)
    if (
        model.package_mode == PRESSURE_PACKAGE_MODE_CENTER_PLUS_ONE_OUTER
        and model.peak_point is not None
        and model.peak_height is not None
    ):
        values = _evaluate_center_outer_circular_model(
            model,
            x_values,
            y_values,
            support_bounds,
            inside,
        )
        values[~inside] = 0.0
        return _numeric_cleanup(values)
    spacing = model.geometry.sensor_spacing_mm
    core_mask = inside & (np.abs(x_values) <= spacing) & (np.abs(y_values) <= spacing)
    if np.any(core_mask):
        values[core_mask] = _evaluate_core(model, x_values[core_mask], y_values[core_mask])
    extension_mask = inside & ~core_mask
    if np.any(extension_mask):
        if model.package_mode == PRESSURE_PACKAGE_MODE_CENTER_PLUS_ONE_OUTER:
            values[extension_mask] = _evaluate_core_extension(
                model,
                x_values[extension_mask],
                y_values[extension_mask],
                support_bounds,
                model.decay_origin,
            )
            values[~inside] = 0.0
            return _numeric_cleanup(values)
        by_label = {plane.label: plane for plane in model.quadrant_planes}
        quadrant_masks = {
            PRESSURE_QUADRANT_TOP_RIGHT: extension_mask & (x_values > 0.0) & (y_values > 0.0),
            PRESSURE_QUADRANT_TOP_LEFT: extension_mask & (x_values < 0.0) & (y_values > 0.0),
            PRESSURE_QUADRANT_BOTTOM_LEFT: extension_mask & (x_values < 0.0) & (y_values < 0.0),
            PRESSURE_QUADRANT_BOTTOM_RIGHT: extension_mask & (x_values > 0.0) & (y_values < 0.0),
        }
        for label, mask in quadrant_masks.items():
            plane = by_label.get(label)
            if plane is not None and np.any(mask):
                values[mask] = _evaluate_core_extension(
                    model, x_values[mask], y_values[mask], support_bounds, plane.decay_origin
                )
        axis_tolerance = max(PRESSURE_NUMERIC_EPSILON, model.geometry_epsilon * 1e-6)
        axis_masks = (
            (extension_mask & (np.abs(y_values) <= axis_tolerance) & (x_values > 0.0), SHEAR_POSITION_RIGHT),
            (extension_mask & (np.abs(y_values) <= axis_tolerance) & (x_values < 0.0), SHEAR_POSITION_LEFT),
            (extension_mask & (np.abs(x_values) <= axis_tolerance) & (y_values > 0.0), SHEAR_POSITION_TOP),
            (extension_mask & (np.abs(x_values) <= axis_tolerance) & (y_values < 0.0), SHEAR_POSITION_BOTTOM),
        )
        for mask, sensor in axis_masks:
            if np.any(mask):
                values[mask] = _evaluate_core_extension(
                    model,
                    x_values[mask],
                    y_values[mask],
                    support_bounds,
                    _model_axis_decay_origin(model, sensor),
                )
    values[~inside] = 0.0
    return _numeric_cleanup(values)


def _evaluate_core(model: PressureFieldModel, x_values: np.ndarray, y_values: np.ndarray) -> np.ndarray:
    if model.package_mode == PRESSURE_PACKAGE_MODE_CENTER_ONLY:
        return _evaluate_center_only_model(model, x_values, y_values)
    if model.package_mode == PRESSURE_PACKAGE_MODE_CENTER_PLUS_ONE_OUTER:
        return _evaluate_axis_lobe(model, x_values, y_values)
    return _evaluate_general_core(model, x_values, y_values)


def _evaluate_center_only_model(
    model: PressureFieldModel, x_values: np.ndarray, y_values: np.ndarray
) -> np.ndarray:
    """Rotationally symmetric center-only field with no outer extension."""

    center = dict(model.sensor_values)[SHEAR_POSITION_CENTER]
    radius = np.hypot(x_values, y_values)
    return center * smoothstep_fade(radius, model.geometry.sensor_spacing_mm)


def _evaluate_general_core(model: PressureFieldModel, x_values: np.ndarray, y_values: np.ndarray) -> np.ndarray:
    values = np.zeros_like(x_values, dtype=np.float64)
    by_label = {plane.label: plane for plane in model.quadrant_planes}
    regions = {
        PRESSURE_QUADRANT_TOP_RIGHT: (x_values > 0.0) & (y_values > 0.0),
        PRESSURE_QUADRANT_TOP_LEFT: (x_values < 0.0) & (y_values > 0.0),
        PRESSURE_QUADRANT_BOTTOM_LEFT: (x_values < 0.0) & (y_values < 0.0),
        PRESSURE_QUADRANT_BOTTOM_RIGHT: (x_values > 0.0) & (y_values < 0.0),
    }
    for label in PRESSURE_ACTIVE_QUADRANTS:
        mask = regions[label]
        plane = by_label.get(label)
        if plane is not None and np.any(mask):
            values[mask] = _evaluate_triangles(plane, x_values[mask], y_values[mask], model.geometry_epsilon)
    signal = dict(model.sensor_values)
    spacing = model.geometry.sensor_spacing_mm
    axis_tolerance = max(PRESSURE_NUMERIC_EPSILON, model.geometry_epsilon * 1e-6)
    x_axis = np.abs(y_values) <= axis_tolerance
    y_axis = np.abs(x_values) <= axis_tolerance
    positive_x = x_axis & (x_values > 0.0)
    negative_x = x_axis & (x_values < 0.0)
    positive_y = y_axis & (y_values > 0.0)
    negative_y = y_axis & (y_values < 0.0)
    values[positive_x] = signal[SHEAR_POSITION_CENTER] + (signal[SHEAR_POSITION_RIGHT] - signal[SHEAR_POSITION_CENTER]) * x_values[positive_x] / spacing
    values[negative_x] = signal[SHEAR_POSITION_CENTER] + (signal[SHEAR_POSITION_LEFT] - signal[SHEAR_POSITION_CENTER]) * (-x_values[negative_x]) / spacing
    values[positive_y] = signal[SHEAR_POSITION_CENTER] + (signal[SHEAR_POSITION_TOP] - signal[SHEAR_POSITION_CENTER]) * y_values[positive_y] / spacing
    values[negative_y] = signal[SHEAR_POSITION_CENTER] + (signal[SHEAR_POSITION_BOTTOM] - signal[SHEAR_POSITION_CENTER]) * (-y_values[negative_y]) / spacing
    values[x_axis & y_axis] = signal[SHEAR_POSITION_CENTER]
    return values


def _evaluate_triangles(plane: PressureQuadrantPlane, x_values: np.ndarray, y_values: np.ndarray, epsilon: float) -> np.ndarray:
    values = np.zeros_like(x_values, dtype=np.float64)
    matched = np.zeros_like(x_values, dtype=bool)
    for triangle in plane.triangles:
        mask = _points_in_triangle(x_values, y_values, triangle.vertices, epsilon) & ~matched
        if np.any(mask):
            values[mask] = triangle.a * x_values[mask] + triangle.b * y_values[mask] + triangle.c
            matched[mask] = True
    if not np.all(matched):
        raise AssertionError(f"core triangulation for {plane.label} did not cover its assigned region")
    return values


def _points_in_triangle(x_values: np.ndarray, y_values: np.ndarray, vertices: tuple[tuple[float, float], tuple[float, float], tuple[float, float]], epsilon: float) -> np.ndarray:
    first, second, third = vertices
    def cross(end: tuple[float, float], start: tuple[float, float]) -> np.ndarray:
        return (end[0] - start[0]) * (y_values - start[1]) - (end[1] - start[1]) * (x_values - start[0])
    signs = (cross(second, first), cross(third, second), cross(first, third))
    has_negative = np.logical_or.reduce(tuple(value < -epsilon for value in signs))
    has_positive = np.logical_or.reduce(tuple(value > epsilon for value in signs))
    return ~(has_negative & has_positive)


def _axis_coordinates(sensor: str, x_values: np.ndarray, y_values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if sensor == SHEAR_POSITION_RIGHT:
        return x_values, y_values
    if sensor == SHEAR_POSITION_LEFT:
        return -x_values, y_values
    if sensor == SHEAR_POSITION_TOP:
        return y_values, x_values
    return -y_values, x_values


def _smooth_interpolate(start: float, end: float, t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)
    curve = 3.0 * t ** 2 - 2.0 * t ** 3
    return start + (end - start) * curve


def _piecewise_width(model: PressureFieldModel, u: np.ndarray, peak_axis: float) -> np.ndarray:
    spacing = model.geometry.sensor_spacing_mm
    minimum = min(spacing, max(model.minimum_lateral_width_mm, spacing * 0.4))
    peak_width = min(spacing, max(model.minimum_lateral_width_mm, spacing * 0.7))
    width = np.empty_like(u, dtype=np.float64)
    negative = u < 0.0
    before_peak = (u >= 0.0) & (u <= peak_axis)
    after_peak = u > peak_axis
    width[negative] = _smooth_interpolate(minimum, spacing, (u[negative] + spacing) / spacing)
    width[before_peak] = _smooth_interpolate(spacing, peak_width, u[before_peak] / max(PRESSURE_NUMERIC_EPSILON, peak_axis))
    denominator = max(PRESSURE_NUMERIC_EPSILON, spacing - peak_axis)
    width[after_peak] = _smooth_interpolate(peak_width, minimum, (u[after_peak] - peak_axis) / denominator)
    return np.maximum(model.minimum_lateral_width_mm, width)


def _evaluate_axis_lobe(model: PressureFieldModel, x_values: np.ndarray, y_values: np.ndarray) -> np.ndarray:
    sensor = model.active_axis_sensor
    if sensor is None:
        return np.zeros_like(x_values, dtype=np.float64)
    signal = dict(model.sensor_values)
    center = signal[SHEAR_POSITION_CENTER]
    outer = signal[sensor]
    u, v = _axis_coordinates(sensor, x_values, y_values)
    spacing = model.geometry.sensor_spacing_mm
    peak_axis = (
        _axis_distance_from_peak_point(sensor, model.peak_point)
        if model.peak_point is not None
        else spacing
    )
    peak_value = model.peak_height if model.peak_height is not None else outer
    if model.peak_height is None:
        longitudinal = np.empty_like(u, dtype=np.float64)
        negative = u < 0.0
        positive = ~negative
        longitudinal[negative] = _smooth_interpolate(0.0, center, (u[negative] + spacing) / spacing)
        longitudinal[positive] = _smooth_interpolate(center, outer, u[positive] / spacing)
    else:
        longitudinal = np.empty_like(u, dtype=np.float64)
        negative = u < 0.0
        rising = (u >= 0.0) & (u <= peak_axis)
        falling = u > peak_axis
        longitudinal[negative] = _smooth_interpolate(0.0, center, (u[negative] + spacing) / spacing)
        longitudinal[rising] = _smooth_interpolate(center, peak_value, u[rising] / max(PRESSURE_NUMERIC_EPSILON, peak_axis))
        longitudinal[falling] = _smooth_interpolate(peak_value, outer, (u[falling] - peak_axis) / max(PRESSURE_NUMERIC_EPSILON, spacing - peak_axis))
    width = _piecewise_width(model, u, peak_axis)
    lateral = smoothstep_fade(np.abs(v), width)
    return longitudinal * lateral


def _evaluate_core_extension(
    model: PressureFieldModel,
    x_values: np.ndarray,
    y_values: np.ndarray,
    support_bounds: tuple[float, float, float, float],
    origin: tuple[float, float],
) -> np.ndarray:
    anchor, natural_factor, boundary_factor = _extension_decay_components(
        model, x_values, y_values, support_bounds, origin
    )
    return anchor * natural_factor * boundary_factor


def _extension_decay_components(
    model: PressureFieldModel,
    x_values: np.ndarray,
    y_values: np.ndarray,
    support_bounds: tuple[float, float, float, float],
    origin: tuple[float, float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    origin_x, origin_y = origin
    dx = x_values - origin_x
    dy = y_values - origin_y
    distance = np.hypot(dx, dy)
    core_bounds = model.geometry.core_bounds_mm
    t_core = _ray_exit_parameter(origin_x, origin_y, dx, dy, core_bounds)
    t_outer = _ray_exit_parameter(origin_x, origin_y, dx, dy, support_bounds)
    anchor_x = origin_x + t_core * dx
    anchor_y = origin_y + t_core * dy
    anchor = _evaluate_core(model, anchor_x, anchor_y)
    outward_distance = distance * np.maximum(0.0, 1.0 - t_core)
    available_distance = distance * np.maximum(0.0, t_outer - t_core)
    strength = np.where(np.abs(anchor) > PRESSURE_NUMERIC_EPSILON, np.abs(anchor), model.model_strength)
    natural_factor = smoothstep_fade(outward_distance, _natural_decay_reach(strength, model))
    guard_width = np.minimum(
        available_distance,
        np.maximum(0.20 * available_distance, model.geometry_epsilon),
    )
    guard_start = available_distance - guard_width
    boundary_factor = smoothstep_fade(
        np.maximum(0.0, outward_distance - guard_start),
        np.maximum(guard_width, PRESSURE_NUMERIC_EPSILON),
    )
    return anchor, natural_factor, boundary_factor


def _strict_support_mask(
    x_values: np.ndarray,
    y_values: np.ndarray,
    support_bounds: tuple[float, float, float, float],
) -> np.ndarray:
    left, right, bottom, top = (float(value) for value in support_bounds)
    return (x_values > left) & (x_values < right) & (y_values > bottom) & (y_values < top)


def _model_axis_decay_origin(model: PressureFieldModel, sensor: str) -> tuple[float, float]:
    signal = dict(model.sensor_values)
    center_weight = abs(signal[SHEAR_POSITION_CENTER])
    outer_weight = abs(signal[sensor])
    weight_sum = center_weight + outer_weight
    if weight_sum <= PRESSURE_NUMERIC_EPSILON:
        return (0.0, 0.0)
    spacing = model.geometry.sensor_spacing_mm
    if sensor == SHEAR_POSITION_RIGHT:
        return (spacing * outer_weight / weight_sum, 0.0)
    if sensor == SHEAR_POSITION_LEFT:
        return (-spacing * outer_weight / weight_sum, 0.0)
    if sensor == SHEAR_POSITION_TOP:
        return (0.0, spacing * outer_weight / weight_sum)
    return (0.0, -spacing * outer_weight / weight_sum)


def _ray_exit_parameter(origin_x: float, origin_y: float, dx: np.ndarray, dy: np.ndarray, bounds: tuple[float, float, float, float]) -> np.ndarray:
    left, right, bottom, top = (float(value) for value in bounds)
    x_parameter = np.full_like(dx, np.inf, dtype=np.float64)
    y_parameter = np.full_like(dy, np.inf, dtype=np.float64)
    positive_x = dx > PRESSURE_NUMERIC_EPSILON
    negative_x = dx < -PRESSURE_NUMERIC_EPSILON
    positive_y = dy > PRESSURE_NUMERIC_EPSILON
    negative_y = dy < -PRESSURE_NUMERIC_EPSILON
    x_parameter[positive_x] = (right - origin_x) / dx[positive_x]
    x_parameter[negative_x] = (left - origin_x) / dx[negative_x]
    y_parameter[positive_y] = (top - origin_y) / dy[positive_y]
    y_parameter[negative_y] = (bottom - origin_y) / dy[negative_y]
    parameter = np.minimum(x_parameter, y_parameter)
    return np.maximum(0.0, parameter)


def _evaluate_isolated_model(model: PressureFieldModel, x_values: np.ndarray, y_values: np.ndarray, support_bounds: tuple[float, float, float, float], inside: np.ndarray) -> np.ndarray:
    values = np.zeros_like(x_values, dtype=np.float64)
    sensor = model.active_axis_sensor
    if sensor is None or model.peak_point is None:
        return values
    radius = model.isolated_circular_radius_mm
    inferred_peak_value = model.peak_height
    if radius is None or inferred_peak_value is None:
        radius, _measured, inferred_peak_value, _gain, _cap, _iterations = _isolated_circular_profile(
            model, support_bounds
        )
    u, v = _axis_coordinates(sensor, x_values, y_values)
    peak_axis = model.geometry.sensor_spacing_mm + model.geometry.near_outer_peak_offset_mm
    radial_distance = np.hypot(u - peak_axis, v)
    radial_factor = smoothstep_fade(
        radial_distance,
        np.asarray(radius, dtype=np.float64),
    )
    q = np.clip(
        u / max(model.geometry.sensor_spacing_mm, PRESSURE_NUMERIC_EPSILON),
        0.0,
        1.0,
    )
    axial_gate = 3.0 * q**2 - 2.0 * q**3
    values[inside] = inferred_peak_value * radial_factor[inside] * axial_gate[inside]
    values[~inside] = 0.0
    return _numeric_cleanup(values)


def _evaluate_center_outer_circular_model(
    model: PressureFieldModel,
    x_values: np.ndarray,
    y_values: np.ndarray,
    support_bounds: tuple[float, float, float, float],
    inside: np.ndarray,
) -> np.ndarray:
    """Evaluate the retained same-sign center-plus-one circular profile."""

    values = np.zeros_like(x_values, dtype=np.float64)
    sensor = model.active_axis_sensor
    if sensor is None or model.peak_point is None or model.peak_height is None:
        return values
    radius = model.center_outer_circular_radius_mm
    center_scale = model.center_outer_center_scale
    outer_scale = model.center_outer_outer_scale
    if radius is None or center_scale is None or outer_scale is None:
        profile = _center_outer_circular_profile(model, support_bounds)
        if profile is None:
            return values
        radius = profile.radius
        center_scale = profile.center_scale
        outer_scale = profile.outer_scale
    u, v = _axis_coordinates(sensor, x_values, y_values)
    peak_axis = _axis_distance_from_peak_point(sensor, model.peak_point)
    spacing = model.geometry.sensor_spacing_mm
    radial_distance = np.hypot(u - peak_axis, v)
    radial_factor = smoothstep_fade(
        radial_distance,
        np.asarray(radius, dtype=np.float64),
    )
    before_t = np.clip(
        u / max(peak_axis, PRESSURE_NUMERIC_EPSILON),
        0.0,
        1.0,
    )
    before_scale = _smooth_interpolate(
        float(center_scale),
        1.0,
        before_t,
    )
    after_t = np.clip(
        (u - peak_axis) / max(spacing - peak_axis, PRESSURE_NUMERIC_EPSILON),
        0.0,
        1.0,
    )
    after_scale = _smooth_interpolate(
        1.0,
        float(outer_scale),
        after_t,
    )
    axial_scale = np.where(
        u <= 0.0,
        float(center_scale),
        np.where(
            u < peak_axis,
            before_scale,
            np.where(u < spacing, after_scale, float(outer_scale)),
        ),
    )
    values[inside] = (
        float(model.peak_height)
        * radial_factor[inside]
        * axial_scale[inside]
    )
    values[~inside] = 0.0
    return _numeric_cleanup(values)


def _numeric_cleanup(values: np.ndarray) -> np.ndarray:
    result = np.asarray(values, dtype=np.float64)
    result[np.abs(result) < PRESSURE_NUMERIC_EPSILON] = 0.0
    return result


def evaluate_pressure_map_result_at(
    result: PressureMapResult,
    local_x_mm: np.ndarray,
    local_y_mm: np.ndarray,
    *,
    support_bounds_mm: tuple[float, float, float, float] | None = None,
) -> np.ndarray:
    """Evaluate a retained result with its own immutable field evaluator."""

    return result.field_model.evaluate(local_x_mm, local_y_mm, support_bounds_mm)
