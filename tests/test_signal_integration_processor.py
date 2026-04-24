"""Tests for the live signal integration display-buffer adapter."""

import unittest
from unittest.mock import patch

import numpy as np

from constants.plotting import MICROSECONDS_PER_SECOND
from constants.signal_integration import (
    DEFAULT_HPF_CUTOFF_HZ,
    DEFAULT_INTEGRATION_WINDOW_SAMPLES,
    SIGNAL_INTEGRATION_CHANNEL_COUNT,
    SIGNAL_INTEGRATION_DISPLAY_BUFFER_MARGIN_SAMPLES,
    SIGNAL_INTEGRATION_MAX_TOTAL_POINTS_TO_DISPLAY,
    SIGNAL_INTEGRATION_PLOT_UPDATE_FPS,
    SIGNAL_INTEGRATION_PLOT_UPDATE_INTERVAL_SEC,
    SIGNAL_INTEGRATION_POSITION_ORDER,
)
from data_processing.signal_integration_processor import (
    SIGNAL_INTEGRATION_SAMPLE_RATE_TOLERANCE_FRACTION,
    SignalIntegrationProcessorMixin,
)


class SignalIntegrationProcessorHarness(SignalIntegrationProcessorMixin):
    CHANNELS = [1, 2, 3, 4, 5]
    REPEAT_COUNT = 1
    VREF_VOLTS = 3.3

    def __init__(self):
        self.config = {
            "channels": list(self.CHANNELS),
            "repeat": self.REPEAT_COUNT,
        }
        self.active_sensor_reverse_polarity = False
        self.plot_update_count = 0
        self.log_messages = []
        self._init_signal_integration_state()

    def get_active_channel_sensor_map(self):
        return list(SIGNAL_INTEGRATION_POSITION_ORDER)

    def get_sensor_package_groups(self, required_channels, channels=None):
        return [{
            "sensor_id": "PZT1",
            "mux": 1,
            "channels": list(self.CHANNELS[:required_channels]),
            "positions": list(range(required_channels)),
        }]

    def is_array_pzt1_mode(self):
        return False

    def is_active_sensor_reverse_polarity(self):
        return self.active_sensor_reverse_polarity

    def get_vref_voltage(self):
        return self.VREF_VOLTS

    def update_signal_integration_plot(self):
        self.plot_update_count += 1

    def log_status(self, message):
        self.log_messages.append(message)


class SignalIntegrationProcessorTests(unittest.TestCase):
    DISPLAY_WINDOW_SEC = 0.1
    PHYSICAL_SAMPLE_INTERVAL_US = 1000.0
    SWEEP_COUNT = 30
    SAMPLES_PER_SWEEP = 5

    def test_signal_integration_refresh_rate_is_configured_for_pressure_map_tab(self):
        self.assertEqual(SIGNAL_INTEGRATION_PLOT_UPDATE_FPS, 15.0)
        self.assertAlmostEqual(SIGNAL_INTEGRATION_PLOT_UPDATE_INTERVAL_SEC, 1.0 / 15.0)

    def _process_block(
        self,
        harness,
        *,
        sweep_count=SWEEP_COUNT,
        physical_sample_interval_us=PHYSICAL_SAMPLE_INTERVAL_US,
    ):
        sweep_period_sec = (
            self.SAMPLES_PER_SWEEP * physical_sample_interval_us
        ) / MICROSECONDS_PER_SECOND
        timestamps = np.arange(sweep_count, dtype=np.float64) * sweep_period_sec
        block = np.tile(
            np.arange(self.SAMPLES_PER_SWEEP, dtype=np.float64),
            (sweep_count, 1),
        )
        return harness.process_signal_integration_block(
            block,
            timestamps,
            physical_sample_interval_us,
        )

    def test_display_buffers_are_limited_to_current_display_window_capacity(self):
        harness = SignalIntegrationProcessorHarness()
        harness.apply_signal_integration_settings(
            hpf_cutoff_hz=DEFAULT_HPF_CUTOFF_HZ,
            integration_window_samples=DEFAULT_INTEGRATION_WINDOW_SAMPLES,
            display_window_sec=self.DISPLAY_WINDOW_SEC,
        )

        self._process_block(harness)

        expected_capacity = (
            SIGNAL_INTEGRATION_MAX_TOTAL_POINTS_TO_DISPLAY // SIGNAL_INTEGRATION_CHANNEL_COUNT
        ) + SIGNAL_INTEGRATION_DISPLAY_BUFFER_MARGIN_SAMPLES
        self.assertEqual(harness._signal_integration_display_buffer_capacity, expected_capacity)
        for buffers in harness.signal_integration_display_buffers.values():
            self.assertLessEqual(len(buffers["time"]), expected_capacity)
            self.assertLessEqual(len(buffers["value"]), expected_capacity)

    def test_streaming_processor_converts_counts_to_voltage_before_integration(self):
        harness = SignalIntegrationProcessorHarness()
        harness.apply_signal_integration_settings(
            hpf_cutoff_hz=0.0,
            integration_window_samples=1,
            display_window_sec=self.DISPLAY_WINDOW_SEC,
        )
        block = np.asarray([[0.0, 4095.0, 0.0, 0.0, 0.0]], dtype=np.float32)
        timestamps = np.asarray([0.0], dtype=np.float64)

        self.assertTrue(
            harness.process_signal_integration_block(
                block,
                timestamps,
                self.PHYSICAL_SAMPLE_INTERVAL_US,
            )
        )

        snapshot = harness.get_signal_integration_display_snapshot(labels={"B"})
        self.assertAlmostEqual(float(snapshot["B"][1][-1]), harness.VREF_VOLTS)

    def test_live_processing_queues_display_refresh_when_available(self):
        harness = SignalIntegrationProcessorHarness()
        trigger_count = 0

        def trigger_update():
            nonlocal trigger_count
            trigger_count += 1

        harness.trigger_signal_integration_update = trigger_update

        with patch("data_processing.signal_integration_processor.time.time", return_value=1.0):
            processed = self._process_block(harness)

        self.assertTrue(processed)
        self.assertEqual(trigger_count, 1)
        self.assertEqual(harness.plot_update_count, 0)

    def test_display_snapshot_can_copy_only_requested_visible_labels(self):
        harness = SignalIntegrationProcessorHarness()
        harness.apply_signal_integration_settings(
            hpf_cutoff_hz=DEFAULT_HPF_CUTOFF_HZ,
            integration_window_samples=DEFAULT_INTEGRATION_WINDOW_SAMPLES,
            display_window_sec=self.DISPLAY_WINDOW_SEC,
        )
        self._process_block(harness)

        snapshot = harness.get_signal_integration_display_snapshot(labels={"T"})

        self.assertEqual(set(snapshot), {"T"})
        self.assertGreater(snapshot["T"][0].size, 0)
        self.assertEqual(snapshot["T"][0].shape, snapshot["T"][1].shape)

    def test_high_rate_display_buffers_store_decimated_points_only(self):
        harness = SignalIntegrationProcessorHarness()
        harness.apply_signal_integration_settings(
            hpf_cutoff_hz=DEFAULT_HPF_CUTOFF_HZ,
            integration_window_samples=DEFAULT_INTEGRATION_WINDOW_SAMPLES,
            display_window_sec=self.DISPLAY_WINDOW_SEC,
        )

        high_rate_interval_us = 1.0
        high_rate_sweeps = 1000
        self._process_block(
            harness,
            sweep_count=high_rate_sweeps,
            physical_sample_interval_us=high_rate_interval_us,
        )

        self.assertGreater(harness.signal_integration_display_decimation, 1)
        for buffers in harness.signal_integration_display_buffers.values():
            self.assertLess(len(buffers["time"]), high_rate_sweeps)

    def test_reverse_polarity_flips_display_buffer_values(self):
        normal_harness = SignalIntegrationProcessorHarness()
        reverse_harness = SignalIntegrationProcessorHarness()
        reverse_harness.active_sensor_reverse_polarity = True

        self._process_block(normal_harness, sweep_count=5)
        self._process_block(reverse_harness, sweep_count=5)

        normal_values = normal_harness.get_signal_integration_display_snapshot(labels={"R"})["R"][1]
        reverse_values = reverse_harness.get_signal_integration_display_snapshot(labels={"R"})["R"][1]

        np.testing.assert_allclose(reverse_values, -normal_values, rtol=1e-6, atol=1e-6)

    def test_current_display_values_apply_reverse_polarity(self):
        harness = SignalIntegrationProcessorHarness()
        harness.active_sensor_reverse_polarity = True
        harness.apply_signal_integration_settings(
            hpf_cutoff_hz=0.0,
            integration_window_samples=1,
            display_window_sec=self.DISPLAY_WINDOW_SEC,
        )
        self._process_block(harness, sweep_count=5)

        current_values = harness.get_signal_integration_current_values()
        display_values = harness.get_signal_integration_current_display_values()

        self.assertAlmostEqual(display_values["R"], -current_values["R"])

    def test_sample_rate_jitter_reuses_stable_rate(self):
        harness = SignalIntegrationProcessorHarness()

        first_rate = 1000.0
        jittered_rate = first_rate * (1.0 + (SIGNAL_INTEGRATION_SAMPLE_RATE_TOLERANCE_FRACTION / 2.0))
        self.assertEqual(harness._stable_signal_integration_sample_rate(first_rate), first_rate)
        self.assertEqual(harness._stable_signal_integration_sample_rate(jittered_rate), first_rate)

        shifted_rate = first_rate * (1.0 + (SIGNAL_INTEGRATION_SAMPLE_RATE_TOLERANCE_FRACTION * 2.0))
        self.assertEqual(harness._stable_signal_integration_sample_rate(shifted_rate), shifted_rate)


if __name__ == "__main__":
    unittest.main()
