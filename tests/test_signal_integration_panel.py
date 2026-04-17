"""Tests for the Signal Integration tab's voltage HPF display helpers."""

import unittest

import numpy as np

from config_constants import (
    DEFAULT_HPF_CUTOFF_HZ,
    DEFAULT_INTEGRATION_WINDOW_SAMPLES,
    IADC_RESOLUTION_BITS,
    SIGNAL_INTEGRATION_DISABLED_HPF_CUTOFF_HZ,
)
from data_processing.adc_filter_engine import ADCFilterEngine
from gui.signal_integration_panel import SignalIntegrationPanelMixin


class SignalIntegrationPanelHarness(SignalIntegrationPanelMixin):
    """Minimal harness for exercising non-Qt plotting helper methods."""

    VREF_VOLTS = 3.3

    def __init__(self):
        self.signal_integration_hpf_cutoff_hz = SIGNAL_INTEGRATION_DISABLED_HPF_CUTOFF_HZ
        self.signal_integration_window_samples = DEFAULT_INTEGRATION_WINDOW_SAMPLES
        self._signal_integration_filter_engine = ADCFilterEngine()
        self._signal_integration_filter_warning = ""
        self.log_messages = []

    def get_vref_voltage(self):
        return self.VREF_VOLTS

    def log_status(self, message):
        self.log_messages.append(message)


class SignalIntegrationPanelTests(unittest.TestCase):
    """Verify display-only voltage conversion, HPF, and integration."""

    SAMPLE_RATE_HZ = 1000.0
    SAMPLE_COUNT = 500
    INTEGRATION_WINDOW_SAMPLES = 3

    def test_counts_to_voltage_ignores_time_series_units(self):
        harness = SignalIntegrationPanelHarness()
        max_adc_value = (2 ** IADC_RESOLUTION_BITS) - 1
        counts = np.asarray([0.0, max_adc_value / 2.0, float(max_adc_value)], dtype=np.float64)

        voltage_data = harness._convert_signal_integration_counts_to_voltage(counts)
        expected = np.asarray([0.0, harness.VREF_VOLTS / 2.0, harness.VREF_VOLTS], dtype=np.float64)

        np.testing.assert_allclose(voltage_data, expected, rtol=1e-6, atol=1e-6)

    def test_hpf_removes_constant_dc_bias_without_integration(self):
        harness = SignalIntegrationPanelHarness()
        harness.signal_integration_hpf_cutoff_hz = DEFAULT_HPF_CUTOFF_HZ
        sample_times = np.arange(self.SAMPLE_COUNT, dtype=np.float64) / self.SAMPLE_RATE_HZ
        biased_signal = np.full(self.SAMPLE_COUNT, harness.VREF_VOLTS / 2.0, dtype=np.float64)

        filtered = harness._remove_signal_integration_dc_bias(biased_signal, sample_times)

        self.assertEqual(filtered.shape, biased_signal.shape)
        self.assertLess(float(np.max(np.abs(filtered))), DEFAULT_HPF_CUTOFF_HZ / self.SAMPLE_RATE_HZ)

    def test_integration_window_produces_moving_sum(self):
        harness = SignalIntegrationPanelHarness()
        harness.signal_integration_window_samples = self.INTEGRATION_WINDOW_SAMPLES
        filtered_voltage = np.asarray([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float64)

        integrated = harness._integrate_signal_integration_voltage_samples(filtered_voltage)

        np.testing.assert_allclose(
            integrated,
            np.asarray([1.0, 3.0, 6.0, 9.0, 12.0], dtype=np.float64),
        )

    def test_prepare_integrated_series_applies_voltage_hpf_and_integration(self):
        harness = SignalIntegrationPanelHarness()
        harness.signal_integration_window_samples = 2
        max_adc_value = (2 ** IADC_RESOLUTION_BITS) - 1
        data = np.asarray(
            [[0.0], [max_adc_value / 4.0], [max_adc_value / 2.0]],
            dtype=np.float32,
        )
        timestamps = np.asarray([0.0, 0.001, 0.002], dtype=np.float64)

        integrated_data, integrated_times = harness._prepare_signal_integration_integrated_series(
            {"sample_indices": [0]},
            data,
            timestamps,
            avg_sample_time_sec=0.001,
            max_samples_per_series=self.SAMPLE_COUNT,
        )

        expected_voltage = np.asarray([0.0, harness.VREF_VOLTS / 4.0, harness.VREF_VOLTS / 2.0])
        expected_integrated = np.asarray([
            expected_voltage[0],
            expected_voltage[0] + expected_voltage[1],
            expected_voltage[1] + expected_voltage[2],
        ])
        np.testing.assert_allclose(integrated_data, expected_integrated, rtol=1e-6, atol=1e-6)
        np.testing.assert_allclose(integrated_times, timestamps)

    def test_prepare_integrated_series_uses_history_before_visible_start(self):
        harness = SignalIntegrationPanelHarness()
        harness.signal_integration_window_samples = self.INTEGRATION_WINDOW_SAMPLES
        max_adc_value = (2 ** IADC_RESOLUTION_BITS) - 1
        one_volt_count = max_adc_value / harness.VREF_VOLTS
        data = np.full((5, 1), one_volt_count, dtype=np.float32)
        timestamps = np.arange(5, dtype=np.float64) / self.SAMPLE_RATE_HZ

        integrated_data, integrated_times = harness._prepare_signal_integration_integrated_series(
            {"sample_indices": [0]},
            data,
            timestamps,
            avg_sample_time_sec=1.0 / self.SAMPLE_RATE_HZ,
            max_samples_per_series=self.SAMPLE_COUNT,
            visible_start_time_sec=timestamps[2],
        )

        np.testing.assert_allclose(
            integrated_data,
            np.full(3, float(self.INTEGRATION_WINDOW_SAMPLES), dtype=np.float64),
            rtol=1e-6,
            atol=1e-6,
        )
        np.testing.assert_allclose(integrated_times, timestamps[2:])


if __name__ == "__main__":
    unittest.main()
