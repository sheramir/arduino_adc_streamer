"""Geometry validation and rasterization for display-only pressure-map masks."""

from __future__ import annotations

from dataclasses import dataclass
import numbers
from typing import Iterable, Sequence

import numpy as np


_MINIMUM_POLYGON_AREA_MM2 = 1e-12


@dataclass(frozen=True, slots=True)
class PressureMapMaskGeometry:
    """An immutable, world-space polygon used to crop an array image display.

    ``points_mm`` contains polygon vertices in winding order.  The final edge
    from the last point back to the first is implicit.
    """

    name: str
    points_mm: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("pressure-map mask name must be non-empty")

        try:
            raw_points = tuple(self.points_mm)
        except TypeError as exc:
            raise ValueError("pressure-map mask points must be a sequence") from exc

        normalized: list[tuple[float, float]] = []
        for raw_point in raw_points:
            if isinstance(raw_point, (str, bytes)):
                raise ValueError("each pressure-map mask point must contain x and y coordinates")
            try:
                x_raw, y_raw = raw_point
            except (TypeError, ValueError) as exc:
                raise ValueError("each pressure-map mask point must contain x and y coordinates") from exc
            if (
                not isinstance(x_raw, numbers.Real)
                or not isinstance(y_raw, numbers.Real)
                or isinstance(x_raw, (bool, np.bool_))
                or isinstance(y_raw, (bool, np.bool_))
            ):
                raise ValueError("pressure-map mask coordinates must be finite numeric values")
            x, y = float(x_raw), float(y_raw)
            if not (np.isfinite(x) and np.isfinite(y)):
                raise ValueError("pressure-map mask coordinates must be finite numeric values")
            normalized.append((x, y))

        # A repeated first point is a common closed-polygon representation.
        # Store only the implicit-open form used by the rasterizer.
        if len(normalized) > 1 and normalized[-1] == normalized[0]:
            normalized.pop()

        if len(normalized) < 3 or len(set(normalized)) < 3:
            raise ValueError("pressure-map mask requires at least three unique points")
        if any(first == second for first, second in zip(normalized, normalized[1:])):
            raise ValueError("pressure-map mask cannot contain consecutive duplicate points")

        coordinates = np.asarray(normalized, dtype=np.float64)
        twice_area = float(
            np.dot(coordinates[:, 0], np.roll(coordinates[:, 1], -1))
            - np.dot(coordinates[:, 1], np.roll(coordinates[:, 0], -1))
        )
        extent = max(
            float(np.ptp(coordinates[:, 0])),
            float(np.ptp(coordinates[:, 1])),
            1.0,
        )
        if abs(twice_area) * 0.5 <= max(_MINIMUM_POLYGON_AREA_MM2, extent * extent * 1e-12):
            raise ValueError("pressure-map mask polygon area must be non-zero")

        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "points_mm", tuple(normalized))


def _normalized_points(points_mm: Sequence[Sequence[float]]) -> tuple[tuple[float, float], ...]:
    """Validate anonymous points through the public geometry contract."""

    return PressureMapMaskGeometry(name="mask", points_mm=tuple(points_mm)).points_mm


def mask_inside_grid(
    points_mm: Sequence[Sequence[float]],
    x_grid_mm: np.ndarray,
    y_grid_mm: np.ndarray,
) -> np.ndarray:
    """Return an inclusive polygon-membership mask for matching coordinate grids.

    The loop is deliberately over polygon edges only.  Every edge operation is
    vectorized over the two-dimensional raster, avoiding a pixels-by-edges
    temporary allocation for large pressure-map grids.
    """

    points = _normalized_points(points_mm)
    x_grid = np.asarray(x_grid_mm, dtype=np.float64)
    y_grid = np.asarray(y_grid_mm, dtype=np.float64)
    if x_grid.shape != y_grid.shape:
        raise ValueError("x_grid_mm and y_grid_mm must have matching shapes")

    finite_grid = np.isfinite(x_grid) & np.isfinite(y_grid)
    inside = np.zeros(x_grid.shape, dtype=bool)
    on_edge = np.zeros(x_grid.shape, dtype=bool)
    epsilon = np.finfo(np.float64).eps * 64.0

    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        delta_x = x2 - x1
        delta_y = y2 - y1
        edge_scale = max(1.0, abs(delta_x), abs(delta_y))
        coordinate_tolerance = epsilon * edge_scale
        cross_tolerance = epsilon * edge_scale * edge_scale

        cross_product = ((x_grid - x1) * delta_y) - ((y_grid - y1) * delta_x)
        within_bounds = (
            (x_grid >= min(x1, x2) - coordinate_tolerance)
            & (x_grid <= max(x1, x2) + coordinate_tolerance)
            & (y_grid >= min(y1, y2) - coordinate_tolerance)
            & (y_grid <= max(y1, y2) + coordinate_tolerance)
        )
        on_edge |= finite_grid & (np.abs(cross_product) <= cross_tolerance) & within_bounds

        # Horizontal edges are excluded from ray crossings.  This half-open
        # convention counts each vertex once while the explicit edge check
        # above keeps boundary pixels visible.
        if delta_y == 0.0:
            continue
        crosses_scanline = (y1 > y_grid) != (y2 > y_grid)
        x_intersection = x1 + ((y_grid - y1) * delta_x / delta_y)
        inside ^= finite_grid & crosses_scanline & (x_grid < x_intersection)

    return inside | on_edge
