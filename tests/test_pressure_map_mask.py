"""Tests for immutable pressure-map mask geometry and grid rasterization."""

import numpy as np
import pytest

from data_processing.pressure_map_mask import PressureMapMaskGeometry, mask_inside_grid


def test_geometry_normalizes_to_immutable_float_tuples():
    geometry = PressureMapMaskGeometry("  Triangle  ", ((0, 0), (2, 0), (0, 2)))

    assert geometry.name == "Triangle"
    assert geometry.points_mm == ((0.0, 0.0), (2.0, 0.0), (0.0, 2.0))
    with pytest.raises(AttributeError):
        geometry.name = "Other"


def test_geometry_normalizes_an_optional_duplicate_closing_point():
    geometry = PressureMapMaskGeometry("Square", ((0, 0), (1, 0), (1, 1), (0, 1), (0, 0)))

    assert geometry.points_mm == ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))


@pytest.mark.parametrize(
    "points",
    [
        ((0, 0), (1, 1)),
        ((0, 0), (1, 0), (2, 0)),
        ((0, 0), (1, 0), (1, np.inf)),
        ((0, 0), (1, 0), (1, np.nan)),
        ((0, 0), (1, 0), (1, 0), (0, 1)),
    ],
)
def test_geometry_rejects_invalid_polygons(points):
    with pytest.raises(ValueError):
        PressureMapMaskGeometry("Invalid", points)


def test_mask_inside_grid_classifies_inside_outside_and_all_edge_orientations():
    # The triangle has horizontal, vertical, and diagonal edges.
    points = ((0.0, 0.0), (2.0, 0.0), (0.0, 2.0))
    x_grid, y_grid = np.meshgrid(
        np.asarray([-0.1, 0.0, 0.5, 1.0, 2.0, 2.1]),
        np.asarray([-0.1, 0.0, 0.5, 1.0, 2.0, 2.1]),
    )

    mask = mask_inside_grid(points, x_grid, y_grid)

    assert mask.dtype == np.bool_
    assert mask.shape == x_grid.shape
    assert mask[2, 2]  # clearly inside
    assert not mask[4, 4]  # outside beyond the diagonal
    assert mask[1, 2]  # horizontal edge y=0
    assert mask[2, 1]  # vertical edge x=0
    assert mask[3, 3]  # diagonal edge x+y=2


def test_mask_inside_grid_requires_matching_coordinate_shapes():
    with pytest.raises(ValueError, match="matching shapes"):
        mask_inside_grid(
            ((0, 0), (1, 0), (0, 1)),
            np.zeros((2, 2)),
            np.zeros((3, 2)),
        )
