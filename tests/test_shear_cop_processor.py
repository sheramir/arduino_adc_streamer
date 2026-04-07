import unittest

import numpy as np

from data_processing.shear_cop_processor import (
    SHEAR_SENSOR_ORDER,
    ShearCoPProcessor,
    extract_shear_pair,
)


def default_settings():
    return {
        "integration_window_ms": 16.0,
        "conditioning_alpha": 0.0,
        "baseline_alpha": 0.0,
        "deadband_threshold": 0.0,
        "sensor_gains": {name: 1.0 for name in SHEAR_SENSOR_ORDER},
        "sensor_baselines": {name: 0.0 for name in SHEAR_SENSOR_ORDER},
        "confidence_signal_ref": 0.01,
    }


class ShearCoPProcessorTests(unittest.TestCase):
    def test_right_to_left_pair(self):
        shear, residual_r, residual_l = extract_shear_pair(-3.0, 4.0)
        self.assertEqual(shear, -3.0)
        self.assertEqual(residual_r, -0.0)
        self.assertEqual(residual_l, 1.0)

    def test_left_to_right_pair(self):
        shear, residual_r, residual_l = extract_shear_pair(2.0, -3.0)
        self.assertEqual(shear, 2.0)
        self.assertEqual(residual_r, 0.0)
        self.assertEqual(residual_l, -1.0)

    def test_same_sign_pair_has_no_shear(self):
        shear, residual_r, residual_l = extract_shear_pair(2.0, 5.0)
        self.assertEqual(shear, 0.0)
        self.assertEqual(residual_r, 2.0)
        self.assertEqual(residual_l, 5.0)

    def test_diagonal_combined_direction(self):
        processor = ShearCoPProcessor()
        samples = {
            "C": np.zeros(16, dtype=np.float64),
            "R": np.full(16, 2.0),
            "L": np.full(16, -3.0),
            "T": np.full(16, 4.0),
            "B": np.full(16, -5.0),
        }
        result = processor.process(samples, sample_rate_hz=1000.0, settings=default_settings())

        self.assertAlmostEqual(result.shear_x, 0.032, places=6)
        self.assertAlmostEqual(result.shear_y, 0.064, places=6)
        self.assertGreater(result.shear_angle_deg, 0.0)
        self.assertLess(result.shear_angle_deg, 90.0)

    def test_near_zero_is_low_confidence(self):
        processor = ShearCoPProcessor()
        settings = default_settings()
        settings["deadband_threshold"] = 0.01
        quiet = {name: np.zeros(16, dtype=np.float64) for name in SHEAR_SENSOR_ORDER}

        result = processor.process(quiet, sample_rate_hz=1000.0, settings=settings)

        self.assertAlmostEqual(result.shear_magnitude, 0.0, places=9)
        self.assertLess(result.confidence, 0.1)
        self.assertAlmostEqual(result.cop_x, 0.0, places=9)
        self.assertAlmostEqual(result.cop_y, 0.0, places=9)


if __name__ == "__main__":
    unittest.main()
