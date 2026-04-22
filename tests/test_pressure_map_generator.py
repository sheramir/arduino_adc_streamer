"""Tests for Step 6 pressure-map peak generation and additive kernels."""

import unittest

import numpy as np

from constants.shear import (
    DEFAULT_PRESSURE_GRID_MARGIN,
    DEFAULT_PRESSURE_GRID_RESOLUTION,
    DEFAULT_PRESSURE_SENSOR_SPACING_MM,
    PRESSURE_GRID_MARGIN_SIDE_COUNT,
    PRESSURE_PEAK_KIND_FALLBACK,
    PRESSURE_PEAK_KIND_QUADRANT,
    PRESSURE_QUADRANT_BOTTOM_LEFT,
    PRESSURE_QUADRANT_BOTTOM_RIGHT,
    PRESSURE_QUADRANT_TOP_LEFT,
    PRESSURE_QUADRANT_TOP_RIGHT,
    SHEAR_SENSOR_POSITIONS,
)
from data_processing.pressure_map_generator import PressureMapGenerator


class PressureMapGeneratorTests(unittest.TestCase):
    """Verify pressure-grid shape, quadrant peaks, fallbacks, and kernels."""

    def setUp(self):
        self.generator = PressureMapGenerator()

    def _grid_value(self, result, x_mm, y_mm):
        row = int(np.argmin(np.abs(result.y_coordinates_mm - y_mm)))
        col = int(np.argmin(np.abs(result.x_coordinates_mm - x_mm)))
        return float(result.pressure_grid[row, col])

    def _peak_sources(self, result):
        return {peak.source for peak in result.peaks}

    def test_equal_sensors_activate_all_quadrants_and_symmetric_map(self):
        result = self.generator.generate({position: 5.0 for position in SHEAR_SENSOR_POSITIONS})

        self.assertEqual(set(result.active_quadrants), {
            PRESSURE_QUADRANT_TOP_RIGHT,
            PRESSURE_QUADRANT_TOP_LEFT,
            PRESSURE_QUADRANT_BOTTOM_LEFT,
            PRESSURE_QUADRANT_BOTTOM_RIGHT,
        })
        self.assertEqual(len(result.peaks), 4)
        self.assertTrue(all(peak.kind == PRESSURE_PEAK_KIND_QUADRANT for peak in result.peaks))
        np.testing.assert_allclose(result.pressure_grid, np.flipud(result.pressure_grid), rtol=1e-6, atol=1e-6)
        np.testing.assert_allclose(result.pressure_grid, np.fliplr(result.pressure_grid), rtol=1e-6, atol=1e-6)

    def test_single_quadrant_active_creates_upper_right_peak(self):
        result = self.generator.generate({"C": 10.0, "R": 5.0, "T": 3.0, "L": 0.0, "B": 0.0})
        peak = result.peaks[0]

        self.assertEqual(result.active_quadrants, (PRESSURE_QUADRANT_TOP_RIGHT,))
        self.assertEqual(peak.source, PRESSURE_QUADRANT_TOP_RIGHT)
        self.assertGreater(peak.x_mm, 0.0)
        self.assertGreater(peak.y_mm, 0.0)
        self.assertGreater(
            self._grid_value(result, peak.x_mm, peak.y_mm),
            self._grid_value(result, -DEFAULT_PRESSURE_SENSOR_SPACING_MM, -DEFAULT_PRESSURE_SENSOR_SPACING_MM),
        )

    def test_two_opposing_quadrants_create_two_separate_peaks(self):
        result = self.generator.generate({"C": 0.0, "R": 5.0, "T": 5.0, "L": -4.0, "B": -4.0})

        self.assertEqual(set(result.active_quadrants), {
            PRESSURE_QUADRANT_TOP_RIGHT,
            PRESSURE_QUADRANT_BOTTOM_LEFT,
        })
        self.assertEqual(len(result.peaks), 2)

    def test_all_zero_inputs_produce_empty_zero_map(self):
        result = self.generator.generate({"C": 0.0, "R": 0.0, "T": 0.0, "L": 0.0, "B": 0.0})

        self.assertEqual(result.active_quadrants, ())
        self.assertEqual(result.peaks, ())
        self.assertTrue(np.all(result.pressure_grid == 0.0))

    def test_zero_outer_sensor_deactivates_quadrant(self):
        result = self.generator.generate({"C": 5.0, "R": 10.0, "T": 0.0, "L": 0.0, "B": 0.0})

        self.assertNotIn(PRESSURE_QUADRANT_TOP_RIGHT, result.active_quadrants)
        self.assertIn("R", self._peak_sources(result))
        self.assertTrue(all(peak.source != PRESSURE_QUADRANT_TOP_RIGHT for peak in result.peaks))

    def test_center_zero_allows_outer_only_quadrant_peak_at_corner(self):
        result = self.generator.generate({"C": 0.0, "R": 8.0, "T": 6.0, "L": 0.0, "B": 0.0})
        peak = result.peaks[0]

        self.assertEqual(result.active_quadrants, (PRESSURE_QUADRANT_TOP_RIGHT,))
        self.assertAlmostEqual(peak.x_mm, DEFAULT_PRESSURE_SENSOR_SPACING_MM)
        self.assertAlmostEqual(peak.y_mm, DEFAULT_PRESSURE_SENSOR_SPACING_MM)

    def test_additive_stacking_exceeds_either_individual_map(self):
        tr_result = self.generator.generate({"C": 5.0, "R": 8.0, "T": 6.0, "L": 0.0, "B": 0.0})
        br_result = self.generator.generate({"C": 5.0, "R": 8.0, "T": 0.0, "L": 0.0, "B": 6.0})
        combined = self.generator.generate({"C": 5.0, "R": 8.0, "T": 6.0, "L": 0.0, "B": 6.0})

        combined_value = self._grid_value(combined, DEFAULT_PRESSURE_SENSOR_SPACING_MM, 0.0)
        individual_value = max(
            self._grid_value(tr_result, DEFAULT_PRESSURE_SENSOR_SPACING_MM, 0.0),
            self._grid_value(br_result, DEFAULT_PRESSURE_SENSOR_SPACING_MM, 0.0),
        )
        self.assertGreater(combined_value, individual_value)

    def test_single_sensor_fallback_fires_at_sensor_position(self):
        result = self.generator.generate({"C": 0.0, "R": 5.0, "T": 0.0, "L": 0.0, "B": 0.0})
        peak = result.peaks[0]

        self.assertEqual(result.active_quadrants, ())
        self.assertEqual(len(result.peaks), 1)
        self.assertEqual(peak.kind, PRESSURE_PEAK_KIND_FALLBACK)
        self.assertEqual(peak.source, "R")
        self.assertAlmostEqual(peak.x_mm, DEFAULT_PRESSURE_SENSOR_SPACING_MM)
        self.assertAlmostEqual(peak.y_mm, 0.0)

    def test_fallback_does_not_fire_when_sensor_is_covered(self):
        result = self.generator.generate({"C": 5.0, "R": 8.0, "T": 6.0, "L": 0.0, "B": 0.0})

        self.assertEqual(result.active_quadrants, (PRESSURE_QUADRANT_TOP_RIGHT,))
        self.assertEqual(len(result.peaks), 1)
        self.assertEqual(result.peaks[0].source, PRESSURE_QUADRANT_TOP_RIGHT)

    def test_mixed_quadrant_has_only_covered_quadrant_peak(self):
        result = self.generator.generate({"C": 5.0, "R": 8.0, "T": 0.0, "L": 0.0, "B": 3.0})

        self.assertEqual(result.active_quadrants, (PRESSURE_QUADRANT_BOTTOM_RIGHT,))
        self.assertEqual(len(result.peaks), 1)
        self.assertEqual(result.peaks[0].source, PRESSURE_QUADRANT_BOTTOM_RIGHT)

    def test_smaller_kernel_radius_produces_sharper_peak(self):
        narrow = PressureMapGenerator(peak_kernel_radius_mm=DEFAULT_PRESSURE_SENSOR_SPACING_MM / 4.0)
        broad = PressureMapGenerator(peak_kernel_radius_mm=DEFAULT_PRESSURE_SENSOR_SPACING_MM)
        signals = {"C": 0.0, "R": 5.0, "T": 0.0, "L": 0.0, "B": 0.0}

        narrow_result = narrow.generate(signals)
        broad_result = broad.generate(signals)
        narrow_high_cells = np.count_nonzero(narrow_result.pressure_grid > np.max(narrow_result.pressure_grid) / 2.0)
        broad_high_cells = np.count_nonzero(broad_result.pressure_grid > np.max(broad_result.pressure_grid) / 2.0)

        self.assertGreater(broad_high_cells, narrow_high_cells)

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

        self.assertEqual(result.pressure_grid.shape, (DEFAULT_PRESSURE_GRID_RESOLUTION, DEFAULT_PRESSURE_GRID_RESOLUTION))

    def test_margin_area_receives_low_nonzero_kernel_tail(self):
        generator = PressureMapGenerator(grid_margin=2)
        result = generator.generate({"C": 0.0, "R": 5.0, "T": 0.0, "L": 0.0, "B": 0.0})
        edge_value = self._grid_value(result, result.x_coordinates_mm[-1], 0.0)

        self.assertGreater(edge_value, 0.0)
        self.assertLess(edge_value, 5.0)


if __name__ == "__main__":
    unittest.main()
