"""Array-level pressure-map generation for adjacent sensor packages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from constants.pressure_map import (
    DEFAULT_PRESSURE_GAP_CONTRAST_GAIN,
    DEFAULT_PRESSURE_GAP_FADE_WIDTH_FRACTION,
    DEFAULT_PRESSURE_PACKAGE_GAP_MM,
    PRESSURE_GRID_MARGIN_SIDE_COUNT,
)
from constants.shear import (
    DEFAULT_CIRCLE_DIAMETER_MM,
    SHEAR_POSITION_BOTTOM,
    SHEAR_POSITION_CENTER,
    SHEAR_POSITION_LEFT,
    SHEAR_POSITION_RIGHT,
    SHEAR_POSITION_TOP,
    SHEAR_ZERO_VALUE,
)
from data_processing.normal_force_calculator import NormalForceResult
from data_processing.pressure_map_generator import PressureMapResult


@dataclass(frozen=True, slots=True)
class PressureMapArrayPackage:
    """Package input for array-level pressure interpolation."""

    sensor_id: str
    grid_position: tuple[int, int]
    normal_force_result: NormalForceResult
    pressure_result: PressureMapResult
    calibrated_values: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class PressureMapArrayResult:
    """Single pressure image containing packages and adjacent gap pressure."""

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


@dataclass(frozen=True, slots=True)
class _AdjacentPair:
    first: PressureMapArrayPackage
    second: PressureMapArrayPackage
    first_facing_sensor: str
    second_facing_sensor: str
    axis: str


class PressureMapArrayGenerator:
    """Build one world-space pressure surface for adjacent package arrays."""

    def __init__(
        self,
        *,
        circle_diameter_mm: float = DEFAULT_CIRCLE_DIAMETER_MM,
        package_gap_mm: float = DEFAULT_PRESSURE_PACKAGE_GAP_MM,
        gap_contrast_gain: float = DEFAULT_PRESSURE_GAP_CONTRAST_GAIN,
        gap_fade_width_fraction: float = DEFAULT_PRESSURE_GAP_FADE_WIDTH_FRACTION,
        show_negative: bool = False,
    ) -> None:
        self.circle_diameter_mm = float(circle_diameter_mm)
        self.package_gap_mm = max(0.0, float(package_gap_mm))
        self.package_center_spacing_mm = self.circle_diameter_mm + self.package_gap_mm
        self.gap_contrast_gain = max(0.0, float(gap_contrast_gain))
        self.gap_fade_width_fraction = max(0.0, float(gap_fade_width_fraction))
        self.show_negative = bool(show_negative)
        if self.circle_diameter_mm <= SHEAR_ZERO_VALUE:
            raise ValueError("circle_diameter_mm must be positive")

    def generate(self, packages: Sequence[PressureMapArrayPackage]) -> PressureMapArrayResult:
        complete_packages = [
            package
            for package in packages
            if package.grid_position is not None and package.pressure_result is not None
        ]
        if not complete_packages:
            raise ValueError("at least one positioned package is required")

        centers = self._package_centers(complete_packages)
        cell_size_mm = self._cell_size_mm(complete_packages)
        x_coordinates, y_coordinates = self._array_coordinates(complete_packages, centers, cell_size_mm)
        x_grid, y_grid = np.meshgrid(x_coordinates, y_coordinates)
        pressure_grid = np.zeros_like(x_grid, dtype=np.float64)

        for package in complete_packages:
            self._paste_package_grid(pressure_grid, x_grid, y_grid, centers[package.sensor_id], package.pressure_result)

        adjacent_pairs = self._adjacent_pairs(complete_packages)
        for pair in adjacent_pairs:
            self._apply_pair_gap_pressure(pressure_grid, x_grid, y_grid, centers, pair)

        return PressureMapArrayResult(
            pressure_grid=pressure_grid,
            x_coordinates_mm=x_coordinates,
            y_coordinates_mm=y_coordinates,
            x_grid_mm=x_grid,
            y_grid_mm=y_grid,
            package_centers=dict(centers),
            package_results={package.sensor_id: package.pressure_result for package in complete_packages},
            adjacent_pairs=tuple((pair.first.sensor_id, pair.second.sensor_id) for pair in adjacent_pairs),
            cell_size_mm=cell_size_mm,
            total_extent_mm=float(max(x_coordinates[-1] - x_coordinates[0], y_coordinates[-1] - y_coordinates[0])),
        )

    def _package_centers(
        self,
        packages: Sequence[PressureMapArrayPackage],
    ) -> dict[str, tuple[float, float]]:
        rows = [package.grid_position[0] for package in packages]
        cols = [package.grid_position[1] for package in packages]
        row_midpoint = (min(rows) + max(rows)) / 2.0
        col_midpoint = (min(cols) + max(cols)) / 2.0
        centers: dict[str, tuple[float, float]] = {}
        for package in packages:
            row, col = package.grid_position
            centers[package.sensor_id] = (
                (float(col) - col_midpoint) * self.package_center_spacing_mm,
                (row_midpoint - float(row)) * self.package_center_spacing_mm,
            )
        return centers

    def _cell_size_mm(self, packages: Sequence[PressureMapArrayPackage]) -> float:
        cell_sizes = [
            float(package.pressure_result.cell_size_mm)
            for package in packages
            if float(package.pressure_result.cell_size_mm) > SHEAR_ZERO_VALUE
        ]
        if not cell_sizes:
            raise ValueError("package pressure results must provide a positive cell size")
        return float(min(cell_sizes))

    def _array_coordinates(
        self,
        packages: Sequence[PressureMapArrayPackage],
        centers: Mapping[str, tuple[float, float]],
        cell_size_mm: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        min_x = float("inf")
        max_x = float("-inf")
        min_y = float("inf")
        max_y = float("-inf")
        for package in packages:
            center_x, center_y = centers[package.sensor_id]
            half_extent = float(package.pressure_result.total_extent_mm) / PRESSURE_GRID_MARGIN_SIDE_COUNT
            min_x = min(min_x, center_x - half_extent)
            max_x = max(max_x, center_x + half_extent)
            min_y = min(min_y, center_y - half_extent)
            max_y = max(max_y, center_y + half_extent)

        padding = max(cell_size_mm, self.package_gap_mm) + cell_size_mm
        min_x -= padding
        max_x += padding
        min_y -= padding
        max_y += padding

        x_count = max(2, int(np.ceil((max_x - min_x) / cell_size_mm)) + 1)
        y_count = max(2, int(np.ceil((max_y - min_y) / cell_size_mm)) + 1)
        x_coordinates = min_x + (np.arange(x_count, dtype=np.float64) * cell_size_mm)
        y_coordinates = min_y + (np.arange(y_count, dtype=np.float64) * cell_size_mm)
        return x_coordinates, y_coordinates

    def _paste_package_grid(
        self,
        pressure_grid: np.ndarray,
        x_grid: np.ndarray,
        y_grid: np.ndarray,
        center: tuple[float, float],
        pressure_result: PressureMapResult,
    ) -> None:
        center_x, center_y = center
        local_x = x_grid - center_x
        local_y = y_grid - center_y
        x_coords = pressure_result.x_coordinates_mm
        y_coords = pressure_result.y_coordinates_mm
        mask = (
            (local_x >= float(x_coords[0]))
            & (local_x <= float(x_coords[-1]))
            & (local_y >= float(y_coords[0]))
            & (local_y <= float(y_coords[-1]))
        )
        if not np.any(mask):
            return

        x_indices = np.searchsorted(x_coords, local_x[mask], side="left")
        y_indices = np.searchsorted(y_coords, local_y[mask], side="left")
        x_indices = np.clip(x_indices, 0, len(x_coords) - 1)
        y_indices = np.clip(y_indices, 0, len(y_coords) - 1)
        package_values = pressure_result.pressure_grid[y_indices, x_indices]
        current_values = pressure_grid[mask]
        pressure_grid[mask] = self._dominant_values(current_values, package_values)

    def _adjacent_pairs(self, packages: Sequence[PressureMapArrayPackage]) -> tuple[_AdjacentPair, ...]:
        by_position = {package.grid_position: package for package in packages}
        pairs: list[_AdjacentPair] = []
        for package in packages:
            row, col = package.grid_position
            right = by_position.get((row, col + 1))
            if right is not None:
                pairs.append(_AdjacentPair(package, right, SHEAR_POSITION_RIGHT, SHEAR_POSITION_LEFT, "x"))
            lower = by_position.get((row + 1, col))
            if lower is not None:
                pairs.append(_AdjacentPair(package, lower, SHEAR_POSITION_BOTTOM, SHEAR_POSITION_TOP, "y"))
        return tuple(pairs)

    def _apply_pair_gap_pressure(
        self,
        pressure_grid: np.ndarray,
        x_grid: np.ndarray,
        y_grid: np.ndarray,
        centers: Mapping[str, tuple[float, float]],
        pair: _AdjacentPair,
    ) -> None:
        first_center = centers[pair.first.sensor_id]
        second_center = centers[pair.second.sensor_id]
        first_sensor = self._sensor_world_position(first_center, pair.first.pressure_result, pair.first_facing_sensor)
        second_sensor = self._sensor_world_position(second_center, pair.second.pressure_result, pair.second_facing_sensor)
        axis_values = x_grid if pair.axis == "x" else y_grid
        lateral_values = y_grid if pair.axis == "x" else x_grid
        start_axis = first_sensor[0] if pair.axis == "x" else first_sensor[1]
        end_axis = second_sensor[0] if pair.axis == "x" else second_sensor[1]
        start_lateral = first_sensor[1] if pair.axis == "x" else first_sensor[0]
        end_lateral = second_sensor[1] if pair.axis == "x" else second_sensor[0]
        axis_min = min(start_axis, end_axis)
        axis_max = max(start_axis, end_axis)
        if axis_max - axis_min <= SHEAR_ZERO_VALUE:
            return

        lateral_center = (start_lateral + end_lateral) / 2.0
        fade_half_width = max(
            float(pair.first.pressure_result.total_extent_mm) * 0.25,
            self.circle_diameter_mm * self.gap_fade_width_fraction,
        )
        mask = (axis_values >= axis_min) & (axis_values <= axis_max)
        lateral_fade = np.clip(1.0 - (np.abs(lateral_values - lateral_center) / fade_half_width), 0.0, 1.0)
        mask &= lateral_fade > 0.0
        if not np.any(mask):
            return

        first_value = float(pair.first.calibrated_values.get(pair.first_facing_sensor, 0.0))
        second_value = float(pair.second.calibrated_values.get(pair.second_facing_sensor, 0.0))
        first_center_value = float(pair.first.calibrated_values.get(SHEAR_POSITION_CENTER, 0.0))
        second_center_value = float(pair.second.calibrated_values.get(SHEAR_POSITION_CENTER, 0.0))
        axial_fraction = np.clip((axis_values[mask] - axis_min) / (axis_max - axis_min), 0.0, 1.0)
        if start_axis > end_axis:
            axial_fraction = 1.0 - axial_fraction

        axial_values = self._gap_axial_values(
            axial_fraction,
            first_value,
            second_value,
            first_center_value,
            second_center_value,
        )
        gap_values = self._apply_negative_policy(axial_values * lateral_fade[mask])
        current_values = pressure_grid[mask]
        pressure_grid[mask] = self._dominant_values(current_values, gap_values)

    def _sensor_world_position(
        self,
        center: tuple[float, float],
        pressure_result: PressureMapResult,
        sensor: str,
    ) -> tuple[float, float]:
        local_x, local_y = pressure_result.sensor_positions.get(sensor, (0.0, 0.0))
        return (center[0] + float(local_x), center[1] + float(local_y))

    def _gap_axial_values(
        self,
        fraction: np.ndarray,
        first_value: float,
        second_value: float,
        first_center_value: float,
        second_center_value: float,
    ) -> np.ndarray:
        first_mag = abs(first_value)
        second_mag = abs(second_value)
        first_center_mag = abs(first_center_value)
        second_center_mag = abs(second_center_value)
        if max(first_mag, second_mag, first_center_mag, second_center_mag) <= SHEAR_ZERO_VALUE:
            return np.zeros_like(fraction, dtype=np.float64)

        first_center_dominates = first_center_mag > first_mag and first_center_mag > second_mag
        second_center_dominates = second_center_mag > second_mag and second_center_mag > first_mag
        if first_center_dominates and first_center_mag >= second_center_mag:
            return self._monotonic_between(fraction, first_value, second_value)
        if second_center_dominates and second_center_mag > first_center_mag:
            return self._monotonic_between(fraction, first_value, second_value)

        if self._opposite_signs(first_value, second_value):
            return self._monotonic_between(fraction, first_value, second_value)

        denominator = first_mag + second_mag
        peak_fraction = 0.5 if denominator <= SHEAR_ZERO_VALUE else second_mag / denominator
        peak_value = self._gap_peak_value(first_value, second_value)
        if peak_fraction <= SHEAR_ZERO_VALUE:
            before_peak = np.full_like(fraction, peak_value, dtype=np.float64)
        else:
            before_peak = first_value + (
                (peak_value - first_value) * np.clip(fraction / peak_fraction, 0.0, 1.0)
            )

        if peak_fraction >= 1.0:
            after_peak = np.full_like(fraction, peak_value, dtype=np.float64)
        else:
            after_peak = peak_value + (
                (second_value - peak_value)
                * np.clip((fraction - peak_fraction) / (1.0 - peak_fraction), 0.0, 1.0)
            )
        return np.where(fraction <= peak_fraction, before_peak, after_peak)

    def _gap_peak_value(self, first_value: float, second_value: float) -> float:
        dominant = first_value if abs(first_value) >= abs(second_value) else second_value
        contrast = abs(first_value - second_value) * self.gap_contrast_gain
        if dominant < SHEAR_ZERO_VALUE:
            return dominant - contrast
        return dominant + contrast

    def _monotonic_between(self, fraction: np.ndarray, first_value: float, second_value: float) -> np.ndarray:
        return first_value + ((second_value - first_value) * fraction)

    def _opposite_signs(self, first_value: float, second_value: float) -> bool:
        return (first_value < SHEAR_ZERO_VALUE < second_value) or (second_value < SHEAR_ZERO_VALUE < first_value)

    def _apply_negative_policy(self, values: np.ndarray) -> np.ndarray:
        if self.show_negative:
            return values
        return np.maximum(values, SHEAR_ZERO_VALUE)

    def _dominant_values(self, current_values: np.ndarray, candidate_values: np.ndarray) -> np.ndarray:
        candidates = self._apply_negative_policy(np.asarray(candidate_values, dtype=np.float64))
        current = np.asarray(current_values, dtype=np.float64)
        use_candidate = np.abs(candidates) > np.abs(current)
        return np.where(use_candidate, candidates, current)
