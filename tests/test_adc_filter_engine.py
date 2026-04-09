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

    def test_estimate_channel_sample_rates_uses_sweep_timestamps(self):
        engine = ADCFilterEngine()
        sweep_rate_hz = 1488.0
        sweep_timestamps = np.arange(16, dtype=np.float64) / sweep_rate_hz

        rates = engine.estimate_channel_sample_rates(
            total_fs_hz=83333.33,
            channels=[0, 1, 2, 3, 4],
            repeat_count=1,
            sweep_timestamps_sec=sweep_timestamps,
        )

        self.assertEqual(set(rates.keys()), {0, 1, 2, 3, 4})
        self.assertAlmostEqual(rates[0], sweep_rate_hz, delta=5.0)

    @unittest.skipUnless(SCIPY_FILTERS_AVAILABLE, "SciPy not available")
    def test_filter_signal_preserves_constant_level_without_zero_drop(self):
        engine = ADCFilterEngine()
        settings = build_default_filter_settings()
        settings["main_type"] = "lowpass"
        settings["low_cutoff_hz"] = 50.0
        settings["notches"] = []
        samples = np.full(64, 1.65, dtype=np.float64)

        filtered = engine.filter_signal(settings, samples, channel_fs_hz=1500.0)

        self.assertAlmostEqual(float(filtered[0]), 1.65, places=3)


if __name__ == "__main__":
    unittest.main()
