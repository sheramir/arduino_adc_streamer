import unittest

import numpy as np

from data_processing.adc_filter_engine import (
    ADCFilterEngine,
    SCIPY_FILTERS_AVAILABLE,
    build_default_filter_settings,
)


class ADCFilterEngineTests(unittest.TestCase):
    def test_default_filter_settings_shape(self):
        settings = build_default_filter_settings()

        self.assertIn("enabled", settings)
        self.assertIn("main_type", settings)
        self.assertIn("notches", settings)
        self.assertEqual(len(settings["notches"]), 3)

    def test_validate_settings_rejects_invalid_bandpass(self):
        engine = ADCFilterEngine()
        settings = build_default_filter_settings()
        settings["main_type"] = "bandpass"
        settings["low_cutoff_hz"] = 500.0
        settings["high_cutoff_hz"] = 100.0
        settings["notches"] = []

        valid, error = engine.validate_settings(settings, channel_fs_hz=2000.0)

        self.assertFalse(valid)
        self.assertIn("low cutoff", error.lower())

    @unittest.skipUnless(SCIPY_FILTERS_AVAILABLE, "SciPy not available")
    def test_build_runtime_plan_and_filter_block(self):
        engine = ADCFilterEngine()
        settings = build_default_filter_settings()
        settings["main_type"] = "none"
        settings["notches"] = []

        plan = engine.build_runtime_plan(settings, total_fs_hz=1000.0, channels=[0, 1], repeat_count=1)
        block = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)

        filtered = engine.filter_block(plan, block)

        self.assertEqual(set(plan.keys()), {0, 1})
        np.testing.assert_allclose(filtered, block)


if __name__ == "__main__":
    unittest.main()
