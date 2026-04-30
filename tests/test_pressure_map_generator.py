"""Tests for pressure-point pressure-map generation."""

import unittest

import numpy as np

from constants.shear import (
    DEFAULT_PRESSURE_SENSOR_SPACING_MM,
    PRESSURE_ACTIVE_QUADRANTS,
    PRESSURE_GRID_MARGIN_SIDE_COUNT,
    PRESSURE_QUADRANT_BOTTOM_LEFT,
    PRESSURE_QUADRANT_BOTTOM_RIGHT,
    PRESSURE_QUADRANT_TOP_LEFT,
    PRESSURE_QUADRANT_TOP_RIGHT,
    SHEAR_SENSOR_POSITIONS,
)
from data_processing.pressure_map_generator import (
    DEFAULT_PRESSURE_SHOW_NEGATIVE,
    PRESSURE_QUADRANT_MODE_PEAKED,
    PRESSURE_QUADRANT_MODE_PEAKLESS,
    PressureMapGenerator,
)


class PressureMapGeneratorTests(unittest.TestCase):
    """Verify pressure-point placement, interpolation, and clamping."""

    def setUp(self):
        self.generator = PressureMapGenerator(grid_resolution=23, grid_margin=2)

    def _grid_value(self, result, x_mm, y_mm):
        row = int(np.argmin(np.abs(result.y_coordinates_mm - y_mm)))
        col = int(np.argmin(np.abs(result.x_coordinates_mm - x_mm)))
        return float(result.pressure_grid[row, col])

    def _planes_by_label(self, result):
        return {plane.label: plane for plane in result.quadrant_planes}

    def _quadrant_value(self, plane, x_mm, y_mm):
        return float(
            self.generator._evaluate_quadrant_for_region(
                plane,
                np.array([x_mm], dtype=np.float64),
                np.array([y_mm], dtype=np.float64),
            )[0]
        )

    def test_sensor_positions_reproduce_sensor_values_on_grid(self):
        signals = {"C": 5.0, "R": 3.0, "T": 7.0, "L": 2.0, "B": 1.0}
        result = self.generator.generate(signals)

        for sensor, expected_value in signals.items():
            x_mm, y_mm = result.sensor_positions[sensor]
            self.assertAlmostEqual(self._grid_value(result, x_mm, y_mm), expected_value, places=6)

    def test_peak_height_is_reproduced_at_peak_location(self):
        generator = PressureMapGenerator(grid_resolution=45, grid_margin=0)
        result = generator.generate({position: 5.0 for position in SHEAR_SENSOR_POSITIONS})
        tr_plane = {plane.label: plane for plane in result.quadrant_planes}[PRESSURE_QUADRANT_TOP_RIGHT]
        peak_x, peak_y = tr_plane.peak_point

        self.assertEqual(tr_plane.mode, PRESSURE_QUADRANT_MODE_PEAKED)
        self.assertAlmostEqual(peak_x, DEFAULT_PRESSURE_SENSOR_SPACING_MM / 2.0)
        self.assertAlmostEqual(peak_y, DEFAULT_PRESSURE_SENSOR_SPACING_MM / 2.0)
        self.assertAlmostEqual(
            float(tr_plane.peak_height),
            self._grid_value(result, peak_x, peak_y),
            places=6,
        )

    def test_default_mode_uses_positive_signals_for_pressure_point(self):
        self.assertFalse(DEFAULT_PRESSURE_SHOW_NEGATIVE)
        result = self.generator.generate({"C": -5.0, "R": -3.0, "T": -3.0, "L": 0.0, "B": 0.0})
        tr_plane = self._planes_by_label(result)[PRESSURE_QUADRANT_TOP_RIGHT]

        self.assertEqual(tr_plane.mode, PRESSURE_QUADRANT_MODE_PEAKLESS)

    def test_show_negative_mode_uses_absolute_magnitude_for_pressure_point(self):
        generator = PressureMapGenerator(grid_resolution=23, grid_margin=2, show_negative=True)
        result = generator.generate({"C": -5.0, "R": -3.0, "T": -3.0, "L": 0.0, "B": 0.0})
        tr_plane = self._planes_by_label(result)[PRESSURE_QUADRANT_TOP_RIGHT]

        self.assertEqual(tr_plane.mode, PRESSURE_QUADRANT_MODE_PEAKED)
        self.assertIsNotNone(tr_plane.peak_point)
        peak_x, peak_y = tr_plane.peak_point
        self.assertGreater(peak_x, 0.0)
        self.assertGreater(peak_y, 0.0)

    def test_continuity_matches_on_shared_x_axis(self):
        signals = {"C": 5.0, "R": 3.0, "T": 7.0, "L": 2.0, "B": 4.0}
        result = self.generator.generate(signals)
        planes = self._planes_by_label(result)
        x_coord = DEFAULT_PRESSURE_SENSOR_SPACING_MM / 2.0

        tr_value = self._quadrant_value(planes[PRESSURE_QUADRANT_TOP_RIGHT], x_coord, 0.0)
        br_value = self._quadrant_value(planes[PRESSURE_QUADRANT_BOTTOM_RIGHT], x_coord, 0.0)

        self.assertAlmostEqual(tr_value, br_value, places=6)

    def test_only_center_nonzero_decays_monotonically_to_outer_zero_sensors(self):
        result = self.generator.generate({"C": 5.0, "R": 0.0, "T": 0.0, "L": 0.0, "B": 0.0})
        spacing = DEFAULT_PRESSURE_SENSOR_SPACING_MM

        center = self._grid_value(result, 0.0, 0.0)
        halfway = self._grid_value(result, spacing / 2.0, 0.0)
        outer = self._grid_value(result, spacing, 0.0)

        self.assertGreater(center, halfway)
        self.assertGreater(halfway, outer)
        self.assertAlmostEqual(outer, 0.0, places=6)

    def test_compression_and_tension_clamping(self):
        compression = self.generator.generate({"C": 5.0, "R": 0.0, "T": 8.0, "L": 3.0, "B": 2.0})
        tension = self.generator.generate({"C": -5.0, "R": -3.0, "T": -3.0, "L": -3.0, "B": -3.0})

        self.assertGreaterEqual(float(np.min(compression.pressure_grid[compression.circle_mask])), 0.0)
        self.assertLessEqual(float(np.max(tension.pressure_grid[tension.circle_mask])), 0.0)

    def test_symmetric_inputs_produce_nearly_symmetric_map(self):
        result = self.generator.generate({"C": 5.0, "R": 3.0, "T": 3.0, "L": 3.0, "B": 3.0})
        grid = result.pressure_grid

        np.testing.assert_allclose(grid, np.flip(grid, axis=0), rtol=1e-6, atol=1e-6)
        np.testing.assert_allclose(grid, np.flip(grid, axis=1), rtol=1e-6, atol=1e-6)

    def test_all_zero_inputs_produce_empty_zero_map(self):
        result = self.generator.generate({"C": 0.0, "R": 0.0, "T": 0.0, "L": 0.0, "B": 0.0})

        self.assertEqual(result.active_quadrants, ())
        self.assertEqual(result.quadrant_planes, ())
        self.assertTrue(np.all(result.pressure_grid == 0.0))

    def test_only_one_outer_nonzero_produces_peakless_axis_ridge(self):
        result = self.generator.generate({"C": 0.0, "R": 5.0, "T": 0.0, "L": 0.0, "B": 0.0})
        planes = self._planes_by_label(result)
        spacing = DEFAULT_PRESSURE_SENSOR_SPACING_MM

        self.assertEqual(planes[PRESSURE_QUADRANT_TOP_RIGHT].mode, PRESSURE_QUADRANT_MODE_PEAKLESS)
        self.assertEqual(planes[PRESSURE_QUADRANT_BOTTOM_RIGHT].mode, PRESSURE_QUADRANT_MODE_PEAKLESS)
        self.assertAlmostEqual(self._grid_value(result, spacing, 0.0), 5.0, places=6)
        self.assertAlmostEqual(
            self._quadrant_value(planes[PRESSURE_QUADRANT_TOP_RIGHT], spacing / 2.0, 0.0),
            self._quadrant_value(planes[PRESSURE_QUADRANT_BOTTOM_RIGHT], spacing / 2.0, 0.0),
            places=6,
        )

    def test_peakless_and_peaked_classification_for_zero_outer_axis(self):
        result = self.generator.generate({"C": 4.0, "R": 4.0, "T": 3.0, "L": 2.0, "B": 0.0})
        planes = self._planes_by_label(result)

        self.assertEqual(planes[PRESSURE_QUADRANT_TOP_RIGHT].mode, PRESSURE_QUADRANT_MODE_PEAKED)
        self.assertEqual(planes[PRESSURE_QUADRANT_TOP_LEFT].mode, PRESSURE_QUADRANT_MODE_PEAKED)
        self.assertEqual(planes[PRESSURE_QUADRANT_BOTTOM_LEFT].mode, PRESSURE_QUADRANT_MODE_PEAKLESS)
        self.assertEqual(planes[PRESSURE_QUADRANT_BOTTOM_RIGHT].mode, PRESSURE_QUADRANT_MODE_PEAKLESS)

    def test_mixed_inputs_peak_only_in_quadrants_with_two_outer_signals(self):
        result = self.generator.generate({"C": 5.0, "R": 0.0, "T": 8.0, "L": 3.0, "B": 2.0})
        planes = self._planes_by_label(result)

        self.assertEqual(planes[PRESSURE_QUADRANT_TOP_LEFT].mode, PRESSURE_QUADRANT_MODE_PEAKED)
        self.assertEqual(planes[PRESSURE_QUADRANT_BOTTOM_LEFT].mode, PRESSURE_QUADRANT_MODE_PEAKED)
        self.assertEqual(planes[PRESSURE_QUADRANT_TOP_RIGHT].mode, PRESSURE_QUADRANT_MODE_PEAKLESS)
        self.assertEqual(planes[PRESSURE_QUADRANT_BOTTOM_RIGHT].mode, PRESSURE_QUADRANT_MODE_PEAKLESS)

    def test_center_zero_places_peak_at_corner_and_collapses_outer_triangles(self):
        result = self.generator.generate({"C": 0.0, "R": 5.0, "T": 7.0, "L": 0.0, "B": 0.0})
        tr_plane = self._planes_by_label(result)[PRESSURE_QUADRANT_TOP_RIGHT]
        spacing = DEFAULT_PRESSURE_SENSOR_SPACING_MM

        self.assertEqual(tr_plane.mode, PRESSURE_QUADRANT_MODE_PEAKED)
        self.assertEqual(tr_plane.peak_point, (spacing, spacing))
        self.assertEqual(tuple(triangle.name for triangle in tr_plane.triangles), ("inner-x", "inner-y"))
        self.assertAlmostEqual(
            self._quadrant_value(tr_plane, spacing, spacing),
            float(tr_plane.peak_height),
            places=6,
        )

    def test_opposing_sign_conflicts_leave_quadrants_inactive(self):
        result = self.generator.generate({"C": 0.0, "R": 5.0, "T": 5.0, "L": -4.0, "B": -4.0})

        self.assertEqual(
            set(result.active_quadrants),
            {PRESSURE_QUADRANT_TOP_RIGHT, PRESSURE_QUADRANT_BOTTOM_LEFT},
        )
        self.assertGreater(self._grid_value(result, 1.0, 1.0), 0.0)
        self.assertLess(self._grid_value(result, -1.0, -1.0), 0.0)
        self.assertEqual(self._grid_value(result, -1.0, 1.0), 0.0)
        self.assertEqual(self._grid_value(result, 1.0, -1.0), 0.0)

    def test_output_shape_includes_margin_cells(self):
        result = self.generator.generate({"C": 0.0, "R": 0.0, "T": 0.0, "L": 0.0, "B": 0.0})
        expected_side = self.generator.grid_resolution + (
            PRESSURE_GRID_MARGIN_SIDE_COUNT * self.generator.grid_margin
        )

        self.assertEqual(result.pressure_grid.shape, (expected_side, expected_side))
        self.assertEqual(result.circle_mask.shape, (expected_side, expected_side))

    def test_active_quadrants_still_follow_standard_order(self):
        result = self.generator.generate({position: 1.0 for position in SHEAR_SENSOR_POSITIONS})

        self.assertEqual(result.active_quadrants, PRESSURE_ACTIVE_QUADRANTS)


if __name__ == "__main__":
    unittest.main()
