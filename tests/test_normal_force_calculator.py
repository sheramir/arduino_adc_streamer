"""Tests for Step 5 normal-force computation from shear residuals."""

import unittest

from constants.shear import (
    DEFAULT_NORMAL_FORCE_SENSOR_SPACING_MM,
    SHEAR_FORCE_TYPE_COMPRESSION,
    SHEAR_FORCE_TYPE_NONE,
    SHEAR_FORCE_TYPE_TENSION,
)
from data_processing.normal_force_calculator import NormalForceCalculator


class NormalForceCalculatorTests(unittest.TestCase):
    """Verify force type, baseline normalization, total force, and centroid."""

    def setUp(self):
        self.calculator = NormalForceCalculator()

    def test_symmetric_compression_centers_position_and_preserves_total(self):
        result = self.calculator.compute({"C": 10.0, "L": 4.0, "R": 4.0, "T": 4.0, "B": 4.0})

        self.assertEqual(result.force_type, SHEAR_FORCE_TYPE_COMPRESSION)
        self.assertAlmostEqual(result.total_force, 26.0)
        self.assertAlmostEqual(result.x_mm, 0.0)
        self.assertAlmostEqual(result.y_mm, 0.0)

    def test_off_center_press_moves_toward_top_left(self):
        result = self.calculator.compute({"C": 7.0, "L": 9.0, "R": 2.0, "T": 5.0, "B": 3.0})

        self.assertEqual(result.force_type, SHEAR_FORCE_TYPE_COMPRESSION)
        self.assertLess(result.x_mm, 0.0)
        self.assertGreater(result.y_mm, 0.0)
        self.assertGreaterEqual(result.x_mm, -DEFAULT_NORMAL_FORCE_SENSOR_SPACING_MM)
        self.assertLessEqual(result.y_mm, DEFAULT_NORMAL_FORCE_SENSOR_SPACING_MM)

    def test_all_negative_inputs_are_tension(self):
        result = self.calculator.compute({"C": -10.0, "L": -4.0, "R": -4.0, "T": -4.0, "B": -4.0})

        self.assertEqual(result.force_type, SHEAR_FORCE_TYPE_TENSION)
        self.assertLess(result.total_force, 0.0)

    def test_all_zero_inputs_have_no_force(self):
        result = self.calculator.compute({"C": 0.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.0})

        self.assertEqual(result.force_type, SHEAR_FORCE_TYPE_NONE)
        self.assertEqual(result.total_force, 0.0)
        self.assertEqual(result.x_mm, 0.0)
        self.assertEqual(result.y_mm, 0.0)

    def test_center_zero_edge_press_infers_compression_from_outer_sensors(self):
        result = self.calculator.compute({"C": 0.0, "L": 0.0, "R": 8.0, "T": 6.0, "B": 0.0})

        self.assertEqual(result.force_type, SHEAR_FORCE_TYPE_COMPRESSION)
        self.assertAlmostEqual(result.x_mm, DEFAULT_NORMAL_FORCE_SENSOR_SPACING_MM)
        self.assertAlmostEqual(result.y_mm, DEFAULT_NORMAL_FORCE_SENSOR_SPACING_MM)

    def test_center_zero_mixed_outer_tie_uses_larger_signed_magnitude(self):
        result = self.calculator.compute({"C": 0.0, "L": 3.0, "R": -2.0, "T": 0.0, "B": 0.0})

        self.assertEqual(result.force_type, SHEAR_FORCE_TYPE_COMPRESSION)

    def test_negative_outer_under_compression_does_not_lift_quiet_sensors(self):
        # A bipolar jerk sample can put the pressed sensor below zero while the
        # centre stays positive.  An unclamped baseline would blank the pressed
        # sensor and raise every quiet sensor to its magnitude.
        result = self.calculator.compute({"C": 0.5, "L": -10.0, "R": 0.0, "T": 0.0, "B": 0.0})

        self.assertEqual(result.force_type, SHEAR_FORCE_TYPE_COMPRESSION)
        self.assertEqual(result.baseline_offset, 0.0)
        self.assertEqual(result.normalized, result.residual)
        self.assertLess(result.x_mm, 0.0)

    def test_positive_outer_under_tension_does_not_pull_quiet_sensors(self):
        result = self.calculator.compute({"C": -0.5, "L": 0.0, "R": 10.0, "T": 0.0, "B": 0.0})

        self.assertEqual(result.force_type, SHEAR_FORCE_TYPE_TENSION)
        self.assertEqual(result.baseline_offset, 0.0)
        self.assertEqual(result.normalized, result.residual)

    def test_common_outer_lift_is_still_removed(self):
        result = self.calculator.compute({"C": 10.0, "L": 6.0, "R": 4.0, "T": 5.0, "B": 7.0})

        self.assertEqual(result.baseline_offset, 4.0)
        self.assertAlmostEqual(result.normalized["R"], 0.0)
        self.assertAlmostEqual(result.total_force, 32.0)


if __name__ == "__main__":
    unittest.main()
