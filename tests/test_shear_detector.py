"""Tests for calibrated-signal shear detection and extraction."""

import unittest

from data_processing.shear_detector import ShearDetector


class ShearDetectorTests(unittest.TestCase):
    """Verify shear components, vector direction, and residual signs."""

    def setUp(self):
        self.detector = ShearDetector()

    def test_pure_compression_has_no_shear(self):
        signals = {"C": 5.0, "L": 3.0, "R": 3.0, "T": 3.0, "B": 3.0}

        result = self.detector.detect(signals)

        self.assertFalse(result.has_shear)
        self.assertEqual(result.residual, signals)

    def test_pure_horizontal_shear_points_right(self):
        result = self.detector.detect({"C": 5.0, "L": -3.0, "R": 4.0, "T": 0.0, "B": 0.0})

        self.assertTrue(result.has_shear)
        self.assertEqual(result.b_lr, 3.0)
        self.assertEqual(result.b_tb, 0.0)
        self.assertAlmostEqual(result.shear_angle_deg, 0.0)

    def test_pure_vertical_shear_points_up(self):
        result = self.detector.detect({"C": 5.0, "L": 0.0, "R": 0.0, "T": 2.0, "B": -3.0})

        self.assertTrue(result.has_shear)
        self.assertEqual(result.b_lr, 0.0)
        self.assertEqual(result.b_tb, 2.0)
        self.assertAlmostEqual(result.shear_angle_deg, 90.0)

    def test_combined_shear_has_both_components(self):
        result = self.detector.detect({"C": 8.0, "L": -2.0, "R": 6.0, "T": 7.0, "B": -3.0})

        self.assertTrue(result.has_shear)
        self.assertEqual(result.b_lr, 2.0)
        self.assertEqual(result.b_tb, 3.0)
        self.assertGreater(result.shear_magnitude, 0.0)

    def test_horizontal_residual_pair_is_same_sign_or_zero(self):
        result = self.detector.detect({"C": 8.0, "L": -2.0, "R": 6.0, "T": 0.0, "B": 0.0})

        left = result.residual["L"]
        right = result.residual["R"]
        self.assertTrue(left == 0.0 or right == 0.0 or (left > 0.0) == (right > 0.0))

    def test_vertical_residual_pair_is_same_sign_or_zero(self):
        result = self.detector.detect({"C": 8.0, "L": 0.0, "R": 0.0, "T": 7.0, "B": -3.0})

        top = result.residual["T"]
        bottom = result.residual["B"]
        self.assertTrue(top == 0.0 or bottom == 0.0 or (top > 0.0) == (bottom > 0.0))

    def test_zero_inputs_have_zero_residuals(self):
        result = self.detector.detect({"C": 0.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.0})

        self.assertFalse(result.has_shear)
        self.assertTrue(all(value == 0.0 for value in result.residual.values()))


if __name__ == "__main__":
    unittest.main()
