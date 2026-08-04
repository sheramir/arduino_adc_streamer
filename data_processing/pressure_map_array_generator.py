"""World-space package-candidate generation and overlap blending.

Each package keeps its own signed candidate field until every contributing
support has been evaluated.  This replaces the historic synthetic gap bridge
and absolute-value dominant pasting, which created artificial seams and peaks.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import count

import numpy as np

from constants.pressure_map import (
    ACTIVE_BOTTOM,
    ACTIVE_CENTER,
    ACTIVE_LEFT,
    ACTIVE_RIGHT,
    ACTIVE_TOP,
    DEFAULT_PRESSURE_OUTER_BOUNDARY_REACH_MM,
    DEFAULT_PRESSURE_PACKAGE_CENTER_SPACING_MM,
    DEFAULT_PRESSURE_PIXELS_PER_MM,
    DEFAULT_PRESSURE_SENSOR_SPACING_MM,
)
from constants.shear import SHEAR_ZERO_VALUE
from data_processing.normal_force_calculator import NormalForceResult
from data_processing.pressure_map_generator import (
    PRESSURE_QUADRANT_MODE_ISOLATED_OUTER_PEAKED,
    PressureMapResult,
    evaluate_pressure_map_result_at,
)
from data_processing.pressure_map_geometry import PressureMapGeometry


PRESSURE_ARRAY_GEOMETRY_EPSILON = 1e-9
PRESSURE_ARRAY_BLEND_EPSILON = 1e-12
PRESSURE_DIAGONAL_REGULARIZATION_SCALE = 0.05
_FRAME_IDS = count(1)


def overlap_bounds_to_slice(
    overlap: tuple[float, float, float, float],
    x_coordinates_mm: np.ndarray,
    y_coordinates_mm: np.ndarray,
) -> tuple[slice, slice]:
    """Convert world overlap bounds to the minimally enclosing raster slice."""

    x0, x1, y0, y1 = overlap
    x_start = int(np.searchsorted(x_coordinates_mm, x0, side="left"))
    x_end = int(np.searchsorted(x_coordinates_mm, x1, side="right"))
    y_start = int(np.searchsorted(y_coordinates_mm, y0, side="left"))
    y_end = int(np.searchsorted(y_coordinates_mm, y1, side="right"))
    return slice(y_start, y_end), slice(x_start, x_end)


@dataclass(frozen=True, slots=True)
class PressureMapArrayPackage:
    """One complete package positioned in the physical array layout."""

    sensor_id: str
    grid_position: tuple[int, int]
    normal_force_result: NormalForceResult
    pressure_result: PressureMapResult


@dataclass(frozen=True, slots=True)
class PressureMapArrayResult:
    """Combined array field plus its source-package geometry."""

    pressure_grid: np.ndarray
    magnitude_pressure_grid: np.ndarray
    x_coordinates_mm: np.ndarray
    y_coordinates_mm: np.ndarray
    x_grid_mm: np.ndarray
    y_grid_mm: np.ndarray
    package_centers: dict[str, tuple[float, float]]
    package_results: dict[str, PressureMapResult]
    structural_pairs: tuple[tuple[str, str], ...]
    active_overlap_pairs: tuple[tuple[str, str], ...]
    cell_size_x_mm: float
    cell_size_y_mm: float
    cell_size_mm: float
    total_extent_mm: float
    candidate_support_bounds_mm: dict[str, tuple[float, float, float, float]]
    package_center_spacing_mm: float
    outer_boundary_reach_mm: float
    actual_pixels_per_mm: float
    facing_sensor_gap_mm: float
    mid_boundary_half_width_mm: float
    outer_boundary_half_width_mm: float
    frame_id: int
    diagnostics: dict[str, object] | None = None

    @property
    def adjacent_pairs(self) -> tuple[tuple[str, str], ...]:
        """Compatibility alias for stable direct/diagonal grid adjacency."""
        return self.structural_pairs

    @property
    def overlap_pairs(self) -> tuple[tuple[str, str], ...]:
        """Compatibility alias for signal-dependent active overlap pairs."""
        return self.active_overlap_pairs


@dataclass(frozen=True, slots=True)
class _PackageCandidate:
    package: PressureMapArrayPackage
    center: tuple[float, float]
    support_bounds_mm: tuple[float, float, float, float]
    values: np.ndarray
    support_mask: np.ndarray
    support_confidence: np.ndarray
    activity_confidence: float
    local_present: np.ndarray


class PressureMapArrayGenerator:
    """Blend fixed-support package candidates in a shared world coordinate system."""

    def __init__(
        self,
        *,
        sensor_spacing_mm: float = DEFAULT_PRESSURE_SENSOR_SPACING_MM,
        package_center_spacing_mm: float = DEFAULT_PRESSURE_PACKAGE_CENTER_SPACING_MM,
        outer_boundary_reach_mm: float = DEFAULT_PRESSURE_OUTER_BOUNDARY_REACH_MM,
        pixels_per_mm: float = DEFAULT_PRESSURE_PIXELS_PER_MM,
        geometry: PressureMapGeometry | None = None,
        debug: bool = False,
    ) -> None:
        if geometry is not None:
            conflicting_scalars = (
                (sensor_spacing_mm, DEFAULT_PRESSURE_SENSOR_SPACING_MM, geometry.sensor_spacing_mm),
                (package_center_spacing_mm, DEFAULT_PRESSURE_PACKAGE_CENTER_SPACING_MM, geometry.package_center_spacing_mm),
                (outer_boundary_reach_mm, DEFAULT_PRESSURE_OUTER_BOUNDARY_REACH_MM, geometry.outer_boundary_reach_mm),
                (pixels_per_mm, DEFAULT_PRESSURE_PIXELS_PER_MM, geometry.pixels_per_mm),
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
            pixels_per_mm=float(pixels_per_mm),
        )
        self.sensor_spacing_mm = self.geometry.sensor_spacing_mm
        self.package_center_spacing_mm = self.geometry.package_center_spacing_mm
        self.outer_boundary_reach_mm = self.geometry.outer_boundary_reach_mm
        self.pixels_per_mm = self.geometry.pixels_per_mm
        self.actual_pixels_per_mm = self.geometry.actual_pixels_per_mm
        self.cell_size_mm = self.geometry.aligned_cell_size_mm
        self.facing_sensor_gap_mm = self.geometry.facing_sensor_gap_mm
        self.mid_boundary_half_width_mm = self.geometry.mid_boundary_half_width_mm
        self.outer_boundary_half_width_mm = self.geometry.outer_boundary_half_width_mm
        self.debug = bool(debug)
        if self.sensor_spacing_mm <= SHEAR_ZERO_VALUE:
            raise ValueError("sensor_spacing_mm must be positive")
        if self.package_center_spacing_mm <= 2.0 * self.sensor_spacing_mm:
            raise ValueError("package_center_spacing_mm must exceed twice sensor_spacing_mm")
        if self.outer_boundary_reach_mm <= SHEAR_ZERO_VALUE:
            raise ValueError("outer_boundary_reach_mm must be positive")

    def generate(self, packages: Sequence[PressureMapArrayPackage]) -> PressureMapArrayResult:
        """Evaluate all package candidates first, then blend shared supports."""

        complete_packages = sorted(
            (package for package in packages if package.grid_position is not None and package.pressure_result is not None),
            key=lambda package: (package.grid_position[0], package.grid_position[1], str(package.sensor_id)),
        )
        if not complete_packages:
            raise ValueError("at least one positioned package is required")
        sensor_ids = [str(package.sensor_id) for package in complete_packages]
        positions = [package.grid_position for package in complete_packages]
        if len(sensor_ids) != len(set(sensor_ids)):
            raise ValueError("duplicate sensor_id values are not permitted")
        if len(positions) != len(set(positions)):
            raise ValueError("duplicate grid_position values are not permitted")
        for package in complete_packages:
            if not np.isfinite(package.pressure_result.pressure_grid).all():
                raise ValueError("package pressure data must be finite")
            if not self._geometry_matches(package.pressure_result):
                raise ValueError("package pressure results use incompatible geometry")

        centers = self._package_centers(complete_packages)
        support_bounds = self._candidate_support_bounds(complete_packages, centers)
        x_coordinates, y_coordinates = self._array_coordinates(complete_packages, centers, support_bounds)
        x_grid, y_grid = np.meshgrid(x_coordinates, y_coordinates)
        candidates = tuple(
            self._evaluate_candidate(package, centers[package.sensor_id], support_bounds[package.sensor_id], x_grid, y_grid)
            for package in complete_packages
        )
        structural_candidate_pairs = self._eligible_neighbor_pairs(candidates)
        structural_pairs = tuple(
            (first.package.sensor_id, second.package.sensor_id)
            for first, second in structural_candidate_pairs
        )
        (
            pressure_grid,
            magnitude_pressure_grid,
            active_overlap_pairs,
            pair_denominator,
            candidate_denominator,
            pair_effective_weights,
        ) = self._blend_candidates(
            candidates,
            structural_candidate_pairs,
            x_grid,
            y_grid,
            x_coordinates,
            y_coordinates,
        )
        array_support_mask = np.logical_or.reduce(
            tuple(candidate.support_mask for candidate in candidates)
        )
        # Preserve the local support contract after every blend mode too.
        pressure_grid[~array_support_mask] = 0.0
        magnitude_pressure_grid[~array_support_mask] = 0.0
        diagnostics = None
        if self.debug:
            diagnostics = {
                "support_confidence": {
                    candidate.package.sensor_id: candidate.support_confidence.copy()
                    for candidate in candidates
                },
                "local_presence": {
                    candidate.package.sensor_id: candidate.local_present.copy()
                    for candidate in candidates
                },
                "structural_pairs": structural_pairs,
                "active_overlap_pairs": active_overlap_pairs,
                # Compatibility diagnostic name; these are structural,
                # signal-independent neighbor pairs.
                "eligible_neighbor_pairs": structural_pairs,
                "pair_confidence_denominator": pair_denominator,
                "candidate_fallback_denominator": candidate_denominator,
                "effective_pair_weights": pair_effective_weights,
                "array_support_mask": array_support_mask.copy(),
                "final_array_field": pressure_grid.copy(),
                "final_magnitude_array_field": magnitude_pressure_grid.copy(),
            }

        return PressureMapArrayResult(
            pressure_grid=pressure_grid,
            magnitude_pressure_grid=magnitude_pressure_grid,
            x_coordinates_mm=x_coordinates,
            y_coordinates_mm=y_coordinates,
            x_grid_mm=x_grid,
            y_grid_mm=y_grid,
            package_centers=dict(centers),
            package_results={package.sensor_id: package.pressure_result for package in complete_packages},
            structural_pairs=structural_pairs,
            active_overlap_pairs=active_overlap_pairs,
            cell_size_x_mm=float(x_coordinates[1] - x_coordinates[0]),
            cell_size_y_mm=float(y_coordinates[1] - y_coordinates[0]),
            # Compatibility scalar; callers that need physical integration
            # must use the exact per-axis metadata above.
            cell_size_mm=float(min(x_coordinates[1] - x_coordinates[0], y_coordinates[1] - y_coordinates[0])),
            total_extent_mm=float(max(x_coordinates[-1] - x_coordinates[0], y_coordinates[-1] - y_coordinates[0])),
            candidate_support_bounds_mm=dict(support_bounds),
            package_center_spacing_mm=self.package_center_spacing_mm,
            outer_boundary_reach_mm=self.outer_boundary_reach_mm,
            actual_pixels_per_mm=self.actual_pixels_per_mm,
            facing_sensor_gap_mm=self.facing_sensor_gap_mm,
            mid_boundary_half_width_mm=self.mid_boundary_half_width_mm,
            outer_boundary_half_width_mm=self.outer_boundary_half_width_mm,
            frame_id=next(_FRAME_IDS),
            diagnostics=diagnostics,
        )

    def _package_centers(self, packages: Sequence[PressureMapArrayPackage]) -> dict[str, tuple[float, float]]:
        rows = [package.grid_position[0] for package in packages]
        cols = [package.grid_position[1] for package in packages]
        row_midpoint = (min(rows) + max(rows)) / 2.0
        col_midpoint = (min(cols) + max(cols)) / 2.0
        return {
            package.sensor_id: (
                (float(package.grid_position[1]) - col_midpoint) * self.package_center_spacing_mm,
                (row_midpoint - float(package.grid_position[0])) * self.package_center_spacing_mm,
            )
            for package in packages
        }

    def _geometry_matches(self, result: PressureMapResult) -> bool:
        return all(
            np.isclose(actual, expected, rtol=0.0, atol=PRESSURE_ARRAY_GEOMETRY_EPSILON)
            for actual, expected in (
                (result.sensor_spacing_mm, self.geometry.sensor_spacing_mm),
                (result.package_center_spacing_mm, self.geometry.package_center_spacing_mm),
                (result.outer_boundary_reach_mm, self.geometry.outer_boundary_reach_mm),
                (result.near_outer_peak_offset_mm, self.geometry.near_outer_peak_offset_mm),
                (result.pixels_per_mm, self.geometry.pixels_per_mm),
            )
        )

    def _candidate_support_bounds(self, packages: Sequence[PressureMapArrayPackage], centers: Mapping[str, tuple[float, float]]) -> dict[str, tuple[float, float, float, float]]:
        """Return the same local Outer-Boundary support square for every package."""

        _ = centers
        half_width = self.outer_boundary_half_width_mm
        bounds = (-half_width, half_width, -half_width, half_width)
        result: dict[str, tuple[float, float, float, float]] = {}
        for package in packages:
            self._validate_peak_inside_support(package.pressure_result, bounds)
            result[package.sensor_id] = bounds
        return result

    def _validate_peak_inside_support(self, pressure_result: PressureMapResult, bounds: tuple[float, float, float, float]) -> None:
        """Reject a geometry that would put an inferred outer peak past support."""

        for plane in pressure_result.quadrant_planes:
            if plane.mode != PRESSURE_QUADRANT_MODE_ISOLATED_OUTER_PEAKED or plane.peak_point is None:
                continue
            peak_x, peak_y = plane.peak_point
            if peak_x > 0.0:
                available = bounds[1]
                required = peak_x
            elif peak_x < 0.0:
                available = -bounds[0]
                required = -peak_x
            elif peak_y > 0.0:
                available = bounds[3]
                required = peak_y
            else:
                available = -bounds[2]
                required = -peak_y
            if required >= available - PRESSURE_ARRAY_GEOMETRY_EPSILON:
                raise ValueError("near_outer_peak_offset_mm must remain inside the applicable outer support")

    def _array_coordinates(self, packages: Sequence[PressureMapArrayPackage], centers: Mapping[str, tuple[float, float]], support_bounds: Mapping[str, tuple[float, float, float, float]]) -> tuple[np.ndarray, np.ndarray]:
        min_x = min(centers[package.sensor_id][0] + support_bounds[package.sensor_id][0] for package in packages)
        max_x = max(centers[package.sensor_id][0] + support_bounds[package.sensor_id][1] for package in packages)
        min_y = min(centers[package.sensor_id][1] + support_bounds[package.sensor_id][2] for package in packages)
        max_y = max(centers[package.sensor_id][1] + support_bounds[package.sensor_id][3] for package in packages)
        cell_size = self.cell_size_mm
        x_start, x_end = int(round(min_x / cell_size)), int(round(max_x / cell_size))
        y_start, y_end = int(round(min_y / cell_size)), int(round(max_y / cell_size))
        x_count, y_count = x_end - x_start + 1, y_end - y_start + 1
        max_side = 4097
        if x_count > max_side or y_count > max_side or x_count * y_count > 16_000_000:
            raise ValueError("geometry-aligned pressure-map array grid exceeds the safety cap")
        return (
            np.arange(x_start, x_end + 1, dtype=np.float64) * cell_size,
            np.arange(y_start, y_end + 1, dtype=np.float64) * cell_size,
        )

    def _evaluate_candidate(self, package: PressureMapArrayPackage, center: tuple[float, float], support_bounds_mm: tuple[float, float, float, float], x_grid_mm: np.ndarray, y_grid_mm: np.ndarray) -> _PackageCandidate:
        local_x = x_grid_mm - center[0]
        local_y = y_grid_mm - center[1]
        left, right, bottom, top = support_bounds_mm
        support_mask = (local_x > left) & (local_x < right) & (local_y > bottom) & (local_y < top)
        values = np.zeros_like(x_grid_mm, dtype=np.float64)
        if np.any(support_mask):
            values[support_mask] = evaluate_pressure_map_result_at(
                package.pressure_result,
                local_x[support_mask],
                local_y[support_mask],
                support_bounds_mm=support_bounds_mm,
            )
        support_confidence = self._support_confidence(local_x, local_y)
        support_confidence[~support_mask] = 0.0
        values[~support_mask] = 0.0
        local_present = support_mask & (np.abs(values) > PRESSURE_ARRAY_BLEND_EPSILON)
        return _PackageCandidate(
            package,
            center,
            support_bounds_mm,
            values,
            support_mask,
            support_confidence,
            package.pressure_result.package_activity_confidence,
            local_present,
        )

    def _support_confidence(self, local_x: np.ndarray, local_y: np.ndarray) -> np.ndarray:
        """Continuous support participation, independent of pressure values."""

        radius = np.maximum(np.abs(local_x), np.abs(local_y))
        mid = self.mid_boundary_half_width_mm
        outer = self.outer_boundary_half_width_mm
        confidence = np.zeros_like(radius, dtype=np.float64)
        inside_mid = radius <= mid
        transition = (radius > mid) & (radius < outer)
        confidence[inside_mid] = 1.0
        if np.any(transition):
            t = (radius[transition] - mid) / (outer - mid)
            confidence[transition] = 1.0 - (3.0 * t ** 2) + (2.0 * t ** 3)
        return confidence

    def _blend_candidates(
        self,
        candidates: Sequence[_PackageCandidate],
        structural_candidate_pairs: Sequence[tuple[_PackageCandidate, _PackageCandidate]],
        x_grid_mm: np.ndarray,
        y_grid_mm: np.ndarray,
        x_coordinates_mm: np.ndarray,
        y_coordinates_mm: np.ndarray,
    ) -> tuple[
        np.ndarray,
        np.ndarray,
        tuple[tuple[str, str], ...],
        np.ndarray,
        np.ndarray,
        dict[tuple[str, str], tuple[np.ndarray, np.ndarray]],
    ]:
        """Blend local candidates using only present neighboring overlap regions."""

        candidate_numerator = np.zeros_like(x_grid_mm, dtype=np.float64)
        candidate_magnitude_numerator = np.zeros_like(x_grid_mm, dtype=np.float64)
        candidate_denominator = np.zeros_like(x_grid_mm, dtype=np.float64)
        for candidate in candidates:
            candidate_weight = (
                candidate.support_confidence
                * candidate.activity_confidence
                * candidate.local_present
            )
            candidate_numerator += candidate_weight * candidate.values
            candidate_magnitude_numerator += candidate_weight * np.abs(candidate.values)
            candidate_denominator += candidate_weight

        pair_numerator = np.zeros_like(x_grid_mm, dtype=np.float64)
        pair_magnitude_numerator = np.zeros_like(x_grid_mm, dtype=np.float64)
        pair_denominator = np.zeros_like(x_grid_mm, dtype=np.float64)
        active_overlap_pairs: list[tuple[str, str]] = []
        pair_effective_weights: dict[tuple[str, str], tuple[np.ndarray, np.ndarray]] = {}
        for first, second in structural_candidate_pairs:
            if not self._pair_is_sensor_relevant(first, second):
                continue
            overlap = self._support_overlap(first, second)
            if overlap is None:
                continue
            y_slice, x_slice = overlap_bounds_to_slice(
                overlap, x_coordinates_mm, y_coordinates_mm
            )
            region = np.s_[y_slice, x_slice]
            if x_grid_mm[region].size == 0:
                continue
            pair_values, magnitude_pair_values, pair_present, effective_weights = self._pair_blend(
                first,
                second,
                overlap,
                x_grid_mm[region],
                y_grid_mm[region],
                region,
                include_effective_weights=self.debug,
            )
            if not np.any(pair_present):
                continue
            pair_key = (first.package.sensor_id, second.package.sensor_id)
            active_overlap_pairs.append(pair_key)
            if effective_weights is not None:
                pair_effective_weights[pair_key] = effective_weights
            pair_confidence = (
                first.support_confidence[region]
                * second.support_confidence[region]
                * min(first.activity_confidence, second.activity_confidence)
                * pair_present
            )
            pair_numerator[region] += pair_confidence * pair_values
            pair_magnitude_numerator[region] += pair_confidence * magnitude_pair_values
            pair_denominator[region] += pair_confidence

        pressure_grid = np.zeros_like(x_grid_mm, dtype=np.float64)
        magnitude_pressure_grid = np.zeros_like(x_grid_mm, dtype=np.float64)
        pair_valid = pair_denominator > PRESSURE_ARRAY_BLEND_EPSILON
        pressure_grid[pair_valid] = pair_numerator[pair_valid] / pair_denominator[pair_valid]
        magnitude_pressure_grid[pair_valid] = (
            pair_magnitude_numerator[pair_valid] / pair_denominator[pair_valid]
        )
        candidate_valid = ~pair_valid & (candidate_denominator > PRESSURE_ARRAY_BLEND_EPSILON)
        pressure_grid[candidate_valid] = (
            candidate_numerator[candidate_valid] / candidate_denominator[candidate_valid]
        )
        magnitude_pressure_grid[candidate_valid] = (
            candidate_magnitude_numerator[candidate_valid] / candidate_denominator[candidate_valid]
        )
        return (
            pressure_grid,
            magnitude_pressure_grid,
            tuple(active_overlap_pairs),
            pair_denominator,
            candidate_denominator,
            pair_effective_weights,
        )

    def _eligible_neighbor_pairs(
        self, candidates: Sequence[_PackageCandidate]
    ) -> tuple[tuple[_PackageCandidate, _PackageCandidate], ...]:
        """Enumerate only direct/diagonal grid neighbors in linear time."""

        by_position = {candidate.package.grid_position: candidate for candidate in candidates}
        pairs: list[tuple[_PackageCandidate, _PackageCandidate]] = []
        # These four offsets cover each undirected eight-neighbor pair once.
        for first in candidates:
            row, col = first.package.grid_position
            for row_delta, col_delta in ((0, 1), (1, -1), (1, 0), (1, 1)):
                second = by_position.get((row + row_delta, col + col_delta))
                if second is not None:
                    pairs.append((first, second))
        return tuple(pairs)

    def _pair_is_sensor_relevant(
        self, first: _PackageCandidate, second: _PackageCandidate
    ) -> bool:
        """Cheap bitmask prefilter before evaluating an overlap slice."""

        first_row, first_col = first.package.grid_position
        second_row, second_col = second.package.grid_position
        row_delta = second_row - first_row
        col_delta = second_col - first_col
        first_facing = 0
        second_facing = 0
        if col_delta > 0:
            first_facing |= ACTIVE_RIGHT
            second_facing |= ACTIVE_LEFT
        elif col_delta < 0:
            first_facing |= ACTIVE_LEFT
            second_facing |= ACTIVE_RIGHT
        if row_delta > 0:
            first_facing |= ACTIVE_BOTTOM
            second_facing |= ACTIVE_TOP
        elif row_delta < 0:
            first_facing |= ACTIVE_TOP
            second_facing |= ACTIVE_BOTTOM
        first_mask = first.package.pressure_result.active_sensor_mask
        second_mask = second.package.pressure_result.active_sensor_mask
        return bool(
            (first_mask & (ACTIVE_CENTER | first_facing))
            or (second_mask & (ACTIVE_CENTER | second_facing))
        )

    def _support_overlap(self, first: _PackageCandidate, second: _PackageCandidate) -> tuple[float, float, float, float] | None:
        first_center_x, first_center_y = first.center
        second_center_x, second_center_y = second.center
        first_left, first_right, first_bottom, first_top = first.support_bounds_mm
        second_left, second_right, second_bottom, second_top = second.support_bounds_mm
        x0 = max(first_center_x + first_left, second_center_x + second_left)
        x1 = min(first_center_x + first_right, second_center_x + second_right)
        y0 = max(first_center_y + first_bottom, second_center_y + second_bottom)
        y1 = min(first_center_y + first_top, second_center_y + second_top)
        if x1 - x0 <= PRESSURE_ARRAY_GEOMETRY_EPSILON or y1 - y0 <= PRESSURE_ARRAY_GEOMETRY_EPSILON:
            return None
        return (x0, x1, y0, y1)

    def _pair_blend(
        self,
        first: _PackageCandidate,
        second: _PackageCandidate,
        overlap: tuple[float, float, float, float],
        x_grid_mm: np.ndarray,
        y_grid_mm: np.ndarray,
        region: tuple[slice, slice],
        *,
        include_effective_weights: bool,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[np.ndarray, np.ndarray] | None]:
        x0, x1, y0, y1 = overlap
        first_center_x, first_center_y = first.center
        second_center_x, second_center_y = second.center
        if abs(first_center_y - second_center_y) <= PRESSURE_ARRAY_GEOMETRY_EPSILON:
            u = np.clip((x_grid_mm - x0) / (x1 - x0), 0.0, 1.0)
            if first_center_x <= second_center_x:
                first_weight, second_weight = 1.0 - u, u
            else:
                first_weight, second_weight = u, 1.0 - u
        elif abs(first_center_x - second_center_x) <= PRESSURE_ARRAY_GEOMETRY_EPSILON:
            v = np.clip((y_grid_mm - y0) / (y1 - y0), 0.0, 1.0)
            if first_center_y <= second_center_y:
                first_weight, second_weight = 1.0 - v, v
            else:
                first_weight, second_weight = v, 1.0 - v
        else:
            u = np.clip((x_grid_mm - x0) / (x1 - x0), 0.0, 1.0)
            v = np.clip((y_grid_mm - y0) / (y1 - y0), 0.0, 1.0)
            first_is_left = first_center_x < second_center_x
            first_is_bottom = first_center_y < second_center_y
            if first_is_left == first_is_bottom:  # Bottom-left / Top-right
                first_raw = (1.0 - u) * (1.0 - v) if first_is_left else u * v
                second_raw = u * v if first_is_left else (1.0 - u) * (1.0 - v)
            else:  # Top-left / Bottom-right
                first_raw = (1.0 - u) * v if first_is_left else u * (1.0 - v)
                second_raw = u * (1.0 - v) if first_is_left else (1.0 - u) * v
            area_sum = first_raw + second_raw
            normalized_area = np.full_like(area_sum, 0.5, dtype=np.float64)
            np.divide(first_raw, area_sum, out=normalized_area, where=area_sum > PRESSURE_ARRAY_BLEND_EPSILON)
            first_distance = np.hypot(x_grid_mm - first_center_x, y_grid_mm - first_center_y)
            second_distance = np.hypot(x_grid_mm - second_center_x, y_grid_mm - second_center_y)
            first_inverse_distance = 1.0 / np.maximum(first_distance, PRESSURE_ARRAY_BLEND_EPSILON)
            second_inverse_distance = 1.0 / np.maximum(second_distance, PRESSURE_ARRAY_BLEND_EPSILON)
            distance_weight = first_inverse_distance / (first_inverse_distance + second_inverse_distance)
            normalized_sum = np.clip(area_sum / PRESSURE_DIAGONAL_REGULARIZATION_SCALE, 0.0, 1.0)
            area_blend = 3.0 * normalized_sum ** 2 - 2.0 * normalized_sum ** 3
            first_weight = area_blend * normalized_area + (1.0 - area_blend) * distance_weight
            second_weight = 1.0 - first_weight
        first_values = first.values[region]
        second_values = second.values[region]
        first_present = first.local_present[region]
        second_present = second.local_present[region]
        only_first = first_present & ~second_present
        only_second = second_present & ~first_present
        both_present = first_present & second_present
        pair_present = first_present | second_present
        pair_values = np.zeros_like(first_values, dtype=np.float64)
        magnitude_pair_values = np.zeros_like(first_values, dtype=np.float64)
        pair_values[only_first] = first_values[only_first]
        pair_values[only_second] = second_values[only_second]
        magnitude_pair_values[only_first] = np.abs(first_values[only_first])
        magnitude_pair_values[only_second] = np.abs(second_values[only_second])
        pair_values[both_present] = (
            first_weight[both_present] * first_values[both_present]
            + second_weight[both_present] * second_values[both_present]
        )
        magnitude_pair_values[both_present] = (
            first_weight[both_present] * np.abs(first_values[both_present])
            + second_weight[both_present] * np.abs(second_values[both_present])
        )
        if not include_effective_weights:
            return pair_values, magnitude_pair_values, pair_present, None
        applied_first = np.zeros_like(first_values, dtype=np.float64)
        applied_second = np.zeros_like(first_values, dtype=np.float64)
        applied_first[only_first] = 1.0
        applied_second[only_second] = 1.0
        applied_first[both_present] = first_weight[both_present]
        applied_second[both_present] = second_weight[both_present]
        return pair_values, magnitude_pair_values, pair_present, (applied_first, applied_second)
