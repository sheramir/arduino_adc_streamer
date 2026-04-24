"""Tests for Step 6 pressure-map quadrant planes and piecewise evaluation."""

import unittest

import numpy as np

from constants.shear import (
    DEFAULT_PRESSURE_GRID_MARGIN,
    DEFAULT_PRESSURE_GRID_RESOLUTION,
    DEFAULT_PRESSURE_SENSOR_SPACING_MM,
    PRESSURE_ACTIVE_QUADRANTS,
    PRESSURE_GRID_MARGIN_SIDE_COUNT,
    PRESSURE_QUADRANT_BOTTOM_LEFT,
    PRESSURE_QUADRANT_BOTTOM_RIGHT,
    PRESSURE_QUADRANT_TOP_LEFT,
    PRESSURE_QUADRANT_TOP_RIGHT,
    SHEAR_SENSOR_POSITIONS,
)
from data_processing.pressure_map_generator import PressureMapGenerator, PressureQuadrantPlane


class PressureMapGeneratorTests(unittest.TestCase):
    """Verify pressure-grid shape, plane coefficients, and clamping."""

    def setUp(self):
        self.generator = PressureMapGenerator()

    def _grid_value(self, result, x_mm, y_mm):
        row = int(np.argmin(np.abs(result.y_coordinates_mm - y_mm)))
        col = int(np.argmin(np.abs(result.x_coordinates_mm - x_mm)))
        return float(result.pressure_grid[row, col])

    def _planes_by_label(self, result):
        return {plane.label: plane for plane in result.quadrant_planes}

    def _plane_value(self, plane: PressureQuadrantPlane, x_mm: float, y_mm: float) -> float:
        value = (plane.a * x_mm) + (plane.b * y_mm) + plane.c
        if plane.sign < 0.0:
            return min(0.0, value)
        return max(0.0, value)

    def test_equal_sensors_produce_uniform_map_inside_circle(self):
        result = self.generator.generate({position: 5.0 for position in SHEAR_SENSOR_POSITIONS})
        planes = self._planes_by_label(result)

        self.assertEqual(set(result.active_quadrants), set(PRESSURE_ACTIVE_QUADRANTS))
        for plane in planes.values():
            self.assertAlmostEqual(plane.a, 0.0)
            self.assertAlmostEqual(plane.b, 0.0)
            self.assertAlmostEqual(plane.c, 5.0)
        np.testing.assert_allclose(result.pressure_grid[result.circle_mask], 5.0, rtol=1e-6, atol=1e-6)

    def test_positive_center_with_tr_outers_keeps_other_quadrants_active_via_zero_decay(self):
        signals = {"C": 10.0, "R": 5.0, "T": 3.0, "L": 0.0, "B": 0.0}
        result = self.generator.generate(signals)
        planes = self._planes_by_label(result)

        self.assertEqual(set(result.active_quadrants), set(PRESSURE_ACTIVE_QUADRANTS))
        self.assertAlmostEqual(self._plane_value(planes[PRESSURE_QUADRANT_TOP_RIGHT], 0.0, 0.0), 10.0)
        self.assertAlmostEqual(
            self._plane_value(planes[PRESSURE_QUADRANT_TOP_RIGHT], DEFAULT_PRESSURE_SENSOR_SPACING_MM, 0.0),
            5.0,
        )
        self.assertAlmostEqual(
            self._plane_value(planes[PRESSURE_QUADRANT_TOP_RIGHT], 0.0, DEFAULT_PRESSURE_SENSOR_SPACING_MM),
            3.0,
        )
        self.assertAlmostEqual(
            self._plane_value(planes[PRESSURE_QUADRANT_TOP_LEFT], -DEFAULT_PRESSURE_SENSOR_SPACING_MM, 0.0),
            0.0,
        )
        self.assertAlmostEqual(
            self._plane_value(planes[PRESSURE_QUADRANT_BOTTOM_RIGHT], 0.0, -DEFAULT_PRESSURE_SENSOR_SPACING_MM),
            0.0,
        )

    def test_two_opposing_quadrants_with_conflicts_leave_other_regions_zero(self):
        signals = {"C": 0.0, "R": 5.0, "T": 5.0, "L": -4.0, "B": -4.0}
        result = self.generator.generate(signals)

        self.assertEqual(set(result.active_quadrants), {
            PRESSURE_QUADRANT_TOP_RIGHT,
            PRESSURE_QUADRANT_BOTTOM_LEFT,
        })
        self.assertGreater(self._grid_value(result, 1.0, 1.0), 0.0)
        self.assertLess(self._grid_value(result, -1.0, -1.0), 0.0)
        self.assertEqual(self._grid_value(result, -1.0, 1.0), 0.0)
        self.assertEqual(self._grid_value(result, 1.0, -1.0), 0.0)
        self.assertGreater(self._grid_value(result, 0.0, 1.0), 0.0)
        self.assertLess(self._grid_value(result, 0.0, -1.0), 0.0)

    def test_all_zero_inputs_produce_empty_zero_map(self):
        result = self.generator.generate({"C": 0.0, "R": 0.0, "T": 0.0, "L": 0.0, "B": 0.0})

        self.assertEqual(result.active_quadrants, ())
        self.assertEqual(result.quadrant_planes, ())
        self.assertTrue(np.all(result.pressure_grid == 0.0))

    def test_center_zero_and_positive_tr_triplet_produce_expected_tr_plane(self):
        result = self.generator.generate({"C": 0.0, "R": 8.0, "T": 6.0, "L": 0.0, "B": 0.0})
        planes = self._planes_by_label(result)
        tr_plane = planes[PRESSURE_QUADRANT_TOP_RIGHT]

        self.assertIn(PRESSURE_QUADRANT_TOP_RIGHT, result.active_quadrants)
        self.assertAlmostEqual(tr_plane.a, 8.0 / DEFAULT_PRESSURE_SENSOR_SPACING_MM)
        self.assertAlmostEqual(tr_plane.b, 6.0 / DEFAULT_PRESSURE_SENSOR_SPACING_MM)
        self.assertAlmostEqual(tr_plane.c, 0.0)
        self.assertAlmostEqual(self._plane_value(tr_plane, 0.0, 0.0), 0.0)
        self.assertAlmostEqual(
            self._plane_value(tr_plane, DEFAULT_PRESSURE_SENSOR_SPACING_MM, 0.0),
            8.0,
        )
        self.assertAlmostEqual(
            self._plane_value(tr_plane, 0.0, DEFAULT_PRESSURE_SENSOR_SPACING_MM),
            6.0,
        )

    def test_boundary_continuity_matches_on_shared_axis(self):
        signals = {"C": 10.0, "R": 5.0, "T": 3.0, "L": 0.0, "B": 0.0}
        result = self.generator.generate(signals)
        planes = self._planes_by_label(result)
        y_coord = DEFAULT_PRESSURE_SENSOR_SPACING_MM / 2.0

        tr_value = self._plane_value(planes[PRESSURE_QUADRANT_TOP_RIGHT], 0.0, y_coord)
        tl_value = self._plane_value(planes[PRESSURE_QUADRANT_TOP_LEFT], 0.0, y_coord)

        self.assertAlmostEqual(tr_value, tl_value)

    def test_positive_plane_values_are_clamped_at_zero_when_extrapolation_crosses_below_zero(self):
        signals = {"C": 10.0, "R": 5.0, "T": 3.0, "L": 0.0, "B": 0.0}
        result = self.generator.generate(signals)
        tr_plane = self._planes_by_label(result)[PRESSURE_QUADRANT_TOP_RIGHT]

        self.assertEqual(self._plane_value(tr_plane, 2.5, 2.5), 0.0)

    def test_tension_planes_remain_nonpositive_after_clamping(self):
        signals = {"C": -6.0, "L": -3.0, "R": -2.5, "T": -2.0, "B": -3.0}
        result = self.generator.generate(signals)

        self.assertEqual(set(result.active_quadrants), set(PRESSURE_ACTIVE_QUADRANTS))
        self.assertLessEqual(float(np.max(result.pressure_grid[result.circle_mask])), 0.0)

    def test_exact_sensor_values_match_plane_coefficients(self):
        signals = {"C": 7.0, "R": 2.0, "T": 5.0, "L": 9.0, "B": 3.0}
        result = self.generator.generate(signals)
        planes = self._planes_by_label(result)

        self.assertAlmostEqual(self._plane_value(planes[PRESSURE_QUADRANT_TOP_RIGHT], 0.0, 0.0), 7.0)
        self.assertAlmostEqual(
            self._plane_value(planes[PRESSURE_QUADRANT_TOP_RIGHT], DEFAULT_PRESSURE_SENSOR_SPACING_MM, 0.0),
            2.0,
        )
        self.assertAlmostEqual(
            self._plane_value(planes[PRESSURE_QUADRANT_TOP_LEFT], -DEFAULT_PRESSURE_SENSOR_SPACING_MM, 0.0),
            9.0,
        )
        self.assertAlmostEqual(
            self._plane_value(planes[PRESSURE_QUADRANT_BOTTOM_RIGHT], 0.0, -DEFAULT_PRESSURE_SENSOR_SPACING_MM),
            3.0,
        )

    def test_output_shape_includes_margin_cells(self):
        result = self.generator.generate({"C": 0.0, "R": 0.0, "T": 0.0, "L": 0.0, "B": 0.0})
        expected_side = DEFAULT_PRESSURE_GRID_RESOLUTION + (
            PRESSURE_GRID_MARGIN_SIDE_COUNT * DEFAULT_PRESSURE_GRID_MARGIN
        )

        self.assertEqual(result.pressure_grid.shape, (expected_side, expected_side))
        self.assertEqual(result.circle_mask.shape, (expected_side, expected_side))

    def test_margin_zero_uses_exact_grid_resolution(self):
        generator = PressureMapGenerator(grid_margin=0)
        result = generator.generate({"C": 0.0, "R": 0.0, "T": 0.0, "L": 0.0, "B": 0.0})

        self.assertEqual(
            result.pressure_grid.shape,
            (DEFAULT_PRESSURE_GRID_RESOLUTION, DEFAULT_PRESSURE_GRID_RESOLUTION),
        )

    def test_margin_area_contains_extrapolated_plane_values(self):
        generator = PressureMapGenerator(grid_margin=2)
        result = generator.generate({"C": 10.0, "R": 5.0, "T": 3.0, "L": 0.0, "B": 0.0})
        edge_value = self._grid_value(result, result.x_coordinates_mm[-1], 0.0)

        self.assertGreaterEqual(edge_value, 0.0)
        self.assertLess(edge_value, 10.0)


if __name__ == "__main__":
    unittest.main()
