"""World-space package-candidate generation and overlap blending.

Each package keeps its own signed candidate field until every contributing
support has been evaluated.  This replaces the historic synthetic gap bridge
and absolute-value dominant pasting, which created artificial seams and peaks.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import logging
import warnings

import numpy as np

from constants.pressure_map import (
    DEFAULT_PRESSURE_OUTER_BOUNDARY_REACH_MM,
    DEFAULT_PRESSURE_PACKAGE_CENTER_SPACING_MM,
    DEFAULT_PRESSURE_SENSOR_SPACING_MM,
)
from constants.shear import SHEAR_ZERO_VALUE
from data_processing.normal_force_calculator import NormalForceResult
from data_processing.pressure_map_generator import (
    PRESSURE_QUADRANT_MODE_ISOLATED_OUTER_PEAKED,
    PressureMapResult,
    evaluate_pressure_map_result_at,
)


PRESSURE_ARRAY_GEOMETRY_EPSILON = 1e-9
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PressureMapArrayPackage:
    """One complete package positioned in the physical array layout."""

    sensor_id: str
    grid_position: tuple[int, int]
    normal_force_result: NormalForceResult
    pressure_result: PressureMapResult
    calibrated_values: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class PressureMapArrayResult:
    """Combined array field plus its source-package geometry."""

    pressure_grid: np.ndarray
    x_coordinates_mm: np.ndarray
    y_coordinates_mm: np.ndarray
    x_grid_mm: np.ndarray
    y_grid_mm: np.ndarray
    package_centers: dict[str, tuple[float, float]]
    package_results: dict[str, PressureMapResult]
    adjacent_pairs: tuple[tuple[str, str], ...]
    cell_size_mm: float
    total_extent_mm: float
    candidate_support_bounds_mm: dict[str, tuple[float, float, float, float]]
    package_center_spacing_mm: float
    outer_boundary_reach_mm: float
    facing_sensor_gap_mm: float
    mid_boundary_half_width_mm: float
    outer_boundary_half_width_mm: float

    @property
    def overlap_pairs(self) -> tuple[tuple[str, str], ...]:
        """Explicit name for ``adjacent_pairs`` retained for widget compatibility."""
        return self.adjacent_pairs


@dataclass(frozen=True, slots=True)
class _PackageCandidate:
    package: PressureMapArrayPackage
    center: tuple[float, float]
    support_bounds_mm: tuple[float, float, float, float]
    values: np.ndarray
    support_mask: np.ndarray


class PressureMapArrayGenerator:
    """Blend fixed-support package candidates in a shared world coordinate system."""

    def __init__(
        self,
        *,
        sensor_spacing_mm: float = DEFAULT_PRESSURE_SENSOR_SPACING_MM,
        package_center_spacing_mm: float = DEFAULT_PRESSURE_PACKAGE_CENTER_SPACING_MM,
        outer_boundary_reach_mm: float = DEFAULT_PRESSURE_OUTER_BOUNDARY_REACH_MM,
        show_negative: bool = False,
    ) -> None:
        self.sensor_spacing_mm = float(sensor_spacing_mm)
        self.package_center_spacing_mm = float(package_center_spacing_mm)
        self.outer_boundary_reach_mm = float(outer_boundary_reach_mm)
        self.facing_sensor_gap_mm = self.package_center_spacing_mm - (2.0 * self.sensor_spacing_mm)
        self.mid_boundary_half_width_mm = self.package_center_spacing_mm / 2.0
        self.outer_boundary_half_width_mm = (
            self.mid_boundary_half_width_mm + self.outer_boundary_reach_mm
        )
        self.show_negative = bool(show_negative)
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

        centers = self._package_centers(complete_packages)
        cell_size_mm = self._cell_size_mm(complete_packages)
        support_bounds = self._candidate_support_bounds(complete_packages, centers)
        x_coordinates, y_coordinates = self._array_coordinates(complete_packages, centers, support_bounds, cell_size_mm)
        x_grid, y_grid = np.meshgrid(x_coordinates, y_coordinates)
        candidates = tuple(
            self._evaluate_candidate(package, centers[package.sensor_id], support_bounds[package.sensor_id], x_grid, y_grid)
            for package in complete_packages
        )
        pressure_grid, overlap_pairs = self._blend_candidates(candidates, x_grid, y_grid)

        return PressureMapArrayResult(
            pressure_grid=pressure_grid,
            x_coordinates_mm=x_coordinates,
            y_coordinates_mm=y_coordinates,
            x_grid_mm=x_grid,
            y_grid_mm=y_grid,
            package_centers=dict(centers),
            package_results={package.sensor_id: package.pressure_result for package in complete_packages},
            adjacent_pairs=overlap_pairs,
            cell_size_mm=cell_size_mm,
            total_extent_mm=float(max(x_coordinates[-1] - x_coordinates[0], y_coordinates[-1] - y_coordinates[0])),
            candidate_support_bounds_mm=dict(support_bounds),
            package_center_spacing_mm=self.package_center_spacing_mm,
            outer_boundary_reach_mm=self.outer_boundary_reach_mm,
            facing_sensor_gap_mm=self.facing_sensor_gap_mm,
            mid_boundary_half_width_mm=self.mid_boundary_half_width_mm,
            outer_boundary_half_width_mm=self.outer_boundary_half_width_mm,
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

    def _cell_size_mm(self, packages: Sequence[PressureMapArrayPackage]) -> float:
        cell_sizes = [float(package.pressure_result.cell_size_mm) for package in packages if float(package.pressure_result.cell_size_mm) > SHEAR_ZERO_VALUE]
        if not cell_sizes:
            raise ValueError("package pressure results must provide a positive cell size")
        return float(min(cell_sizes))

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

    def _array_coordinates(self, packages: Sequence[PressureMapArrayPackage], centers: Mapping[str, tuple[float, float]], support_bounds: Mapping[str, tuple[float, float, float, float]], cell_size_mm: float) -> tuple[np.ndarray, np.ndarray]:
        min_x = min(centers[package.sensor_id][0] + support_bounds[package.sensor_id][0] for package in packages)
        max_x = max(centers[package.sensor_id][0] + support_bounds[package.sensor_id][1] for package in packages)
        min_y = min(centers[package.sensor_id][1] + support_bounds[package.sensor_id][2] for package in packages)
        max_y = max(centers[package.sensor_id][1] + support_bounds[package.sensor_id][3] for package in packages)
        x_count = max(2, int(np.ceil((max_x - min_x) / cell_size_mm)) + 1)
        y_count = max(2, int(np.ceil((max_y - min_y) / cell_size_mm)) + 1)
        return (
            np.linspace(min_x, max_x, x_count, dtype=np.float64),
            np.linspace(min_y, max_y, y_count, dtype=np.float64),
        )

    def _evaluate_candidate(self, package: PressureMapArrayPackage, center: tuple[float, float], support_bounds_mm: tuple[float, float, float, float], x_grid_mm: np.ndarray, y_grid_mm: np.ndarray) -> _PackageCandidate:
        local_x = x_grid_mm - center[0]
        local_y = y_grid_mm - center[1]
        left, right, bottom, top = support_bounds_mm
        support_mask = (local_x >= left) & (local_x <= right) & (local_y >= bottom) & (local_y <= top)
        values = np.zeros_like(x_grid_mm, dtype=np.float64)
        if np.any(support_mask):
            values[support_mask] = evaluate_pressure_map_result_at(
                package.pressure_result,
                local_x[support_mask],
                local_y[support_mask],
                support_bounds_mm=support_bounds_mm,
            )
        return _PackageCandidate(package, center, support_bounds_mm, values, support_mask)

    def _blend_candidates(self, candidates: Sequence[_PackageCandidate], x_grid_mm: np.ndarray, y_grid_mm: np.ndarray) -> tuple[np.ndarray, tuple[tuple[str, str], ...]]:
        contributor_count = np.sum(np.stack([candidate.support_mask for candidate in candidates]), axis=0)
        pressure_grid = np.zeros_like(x_grid_mm, dtype=np.float64)
        for candidate in candidates:
            only_candidate = candidate.support_mask & (contributor_count == 1)
            pressure_grid[only_candidate] = candidate.values[only_candidate]

        pair_sum = np.zeros_like(x_grid_mm, dtype=np.float64)
        pair_count = np.zeros_like(x_grid_mm, dtype=np.int16)
        overlap_pairs: list[tuple[str, str]] = []
        for first_index, first in enumerate(candidates):
            for second in candidates[first_index + 1:]:
                overlap = self._support_overlap(first, second)
                if overlap is None:
                    continue
                overlap_pairs.append((first.package.sensor_id, second.package.sensor_id))
                pair_values = self._pair_blend(first, second, overlap, x_grid_mm, y_grid_mm)
                pair_mask = first.support_mask & second.support_mask
                pair_sum[pair_mask] += pair_values[pair_mask]
                pair_count[pair_mask] += 1

        shared = contributor_count >= 2
        if np.any(shared):
            expected_pairs = (contributor_count * (contributor_count - 1)) // 2
            valid = shared & (pair_count == expected_pairs)
            pressure_grid[valid] = pair_sum[valid] / expected_pairs[valid]
            if np.any(shared & ~valid):
                LOGGER.warning(
                    "Pressure Map overlap geometry has an incomplete pair set; using the available pair average."
                )
                warnings.warn(
                    "Pressure Map overlap geometry has an incomplete pair set; using the available pair average.",
                    RuntimeWarning,
                    stacklevel=2,
                )
                fallback = shared & ~valid & (pair_count > 0)
                pressure_grid[fallback] = pair_sum[fallback] / pair_count[fallback]
            if np.any(contributor_count >= 4):
                LOGGER.warning(
                    "Pressure Map four-or-more package overlap uses the documented all-pairs average fallback."
                )
                warnings.warn(
                    "Pressure Map four-or-more package overlap uses the documented all-pairs average fallback.",
                    RuntimeWarning,
                    stacklevel=2,
                )
        return pressure_grid, tuple(overlap_pairs)

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

    def _pair_blend(self, first: _PackageCandidate, second: _PackageCandidate, overlap: tuple[float, float, float, float], x_grid_mm: np.ndarray, y_grid_mm: np.ndarray) -> np.ndarray:
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
            denominator = first_raw + second_raw
            first_weight = np.full_like(denominator, 0.5, dtype=np.float64)
            second_weight = np.full_like(denominator, 0.5, dtype=np.float64)
            np.divide(first_raw, denominator, out=first_weight, where=denominator > PRESSURE_ARRAY_GEOMETRY_EPSILON)
            np.divide(second_raw, denominator, out=second_weight, where=denominator > PRESSURE_ARRAY_GEOMETRY_EPSILON)
        return first_weight * first.values + second_weight * second.values
