import unittest
import threading

import numpy as np

from data_processing.adc_plotting import ADCPlottingMixin


class DummySpinBox:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value


class DummyComboBox:
    def __init__(self, text):
        self._text = text

    def currentText(self):
        return self._text


class DummyCheckBox:
    def __init__(self, checked):
        self._checked = checked

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        self._checked = bool(checked)


class ADCPlottingHarness(ADCPlottingMixin):
    MAX_SWEEPS_BUFFER = 5

    def __init__(self):
        self.buffer_lock = threading.Lock()
        self.window_size_spin = DummySpinBox(2)
        self._live_filter_generation = 0
        self.sweep_count = 0
        self.buffer_write_index = 0
        self.sweep_timestamps_buffer = np.array([10.0, 11.0, 12.0, 13.0, 14.0], dtype=np.float64)
        self.device_mode = "adc"
        self.yaxis_units_combo = DummyComboBox("ADC Value")
        self.subtract_baseline_check = DummyCheckBox(False)
        self.plot_baselines = {}
        self.channel_plot_baselines = {}
        self.active_sensor_reverse_polarity = False
        self._active_data_buffer = None
        self.samples_per_sweep = 1
        self._display_specs = []
        self.status_messages = []

    def is_active_sensor_reverse_polarity(self):
        return self.active_sensor_reverse_polarity

    def get_vref_voltage(self):
        return 3.3

    def get_active_data_buffer(self):
        return self._active_data_buffer

    def get_display_channel_specs(self):
        return self._display_specs

    def log_status(self, message):
        self.status_messages.append(str(message))


class ADCPlottingTests(unittest.TestCase):
    def test_extract_recent_buffer_window_without_wrap(self):
        harness = ADCPlottingHarness()
        data = np.array(
            [
                [100, 101],
                [110, 111],
                [120, 121],
                [130, 131],
                [140, 141],
            ],
            dtype=np.float32,
        )

        window_data, window_timestamps = harness._extract_recent_buffer_window(
            data,
            actual_sweeps=3,
            current_write_index=3,
            window_sweeps=2,
        )

        np.testing.assert_array_equal(window_data, np.array([[110, 111], [120, 121]], dtype=np.float32))
        np.testing.assert_array_equal(window_timestamps, np.array([11.0, 12.0], dtype=np.float64))

    def test_extract_recent_buffer_window_with_wrap(self):
        harness = ADCPlottingHarness()
        harness.sweep_timestamps_buffer = np.array([13.0, 14.0, 10.0, 11.0, 12.0], dtype=np.float64)
        data = np.array(
            [
                [300, 301],
                [400, 401],
                [100, 101],
                [200, 201],
                [0, 1],
            ],
            dtype=np.float32,
        )

        window_data, window_timestamps = harness._extract_recent_buffer_window(
            data,
            actual_sweeps=5,
            current_write_index=2,
            window_sweeps=3,
        )

        np.testing.assert_array_equal(
            window_data,
            np.array([[0, 1], [300, 301], [400, 401]], dtype=np.float32),
        )
        np.testing.assert_array_equal(window_timestamps, np.array([12.0, 13.0, 14.0], dtype=np.float64))

    def test_get_live_plot_filter_snapshot_includes_history_for_warmup(self):
        harness = ADCPlottingHarness()
        harness.window_size_spin = DummySpinBox(2)
        harness.sweep_count = 5
        harness.buffer_write_index = 5
        data = np.array(
            [
                [100, 101],
                [110, 111],
                [120, 121],
                [130, 131],
                [140, 141],
            ],
            dtype=np.float32,
        )

        filter_data, filter_timestamps, display_sweeps, snapshot_key = harness._get_live_plot_filter_snapshot(data)

        np.testing.assert_array_equal(
            filter_data,
            np.array(
                [[100, 101], [110, 111], [120, 121], [130, 131], [140, 141]],
                dtype=np.float32,
            ),
        )
        np.testing.assert_array_equal(filter_timestamps, np.array([10.0, 11.0, 12.0, 13.0, 14.0], dtype=np.float64))
        self.assertEqual(display_sweeps, 2)
        self.assertEqual(snapshot_key, (0, 5, 2, 3))

    def test_get_live_plot_filter_snapshot_handles_wrapped_history(self):
        harness = ADCPlottingHarness()
        harness.window_size_spin = DummySpinBox(2)
        harness.sweep_count = 5
        harness.buffer_write_index = 2
        harness.sweep_timestamps_buffer = np.array([13.0, 14.0, 10.0, 11.0, 12.0], dtype=np.float64)
        data = np.array(
            [
                [300, 301],
                [400, 401],
                [100, 101],
                [200, 201],
                [0, 1],
            ],
            dtype=np.float32,
        )

        filter_data, filter_timestamps, display_sweeps, snapshot_key = harness._get_live_plot_filter_snapshot(data)

        np.testing.assert_array_equal(
            filter_data,
            np.array(
                [[100, 101], [200, 201], [0, 1], [300, 301], [400, 401]],
                dtype=np.float32,
            ),
        )
        np.testing.assert_array_equal(filter_timestamps, np.array([10.0, 11.0, 12.0, 13.0, 14.0], dtype=np.float64))
        self.assertEqual(display_sweeps, 2)
        self.assertEqual(snapshot_key, (0, 2, 2, 3))

    def test_prepare_channel_plot_series_flips_non_rs_adc_traces_when_reverse_polarity_enabled(self):
        harness = ADCPlottingHarness()
        spec = {"key": ("adc", 3), "sample_indices": [0]}
        data = np.array([[1.0], [3.0], [5.0]], dtype=np.float32)
        timestamps = np.array([0.0, 0.1, 0.2], dtype=np.float64)

        normal_data, normal_times, normal_latest = harness._prepare_channel_plot_series(
            spec,
            data,
            timestamps,
            avg_sample_time_sec=0.0,
            max_samples_per_series=100,
        )

        harness.active_sensor_reverse_polarity = True
        reversed_data, reversed_times, reversed_latest = harness._prepare_channel_plot_series(
            spec,
            data,
            timestamps,
            avg_sample_time_sec=0.0,
            max_samples_per_series=100,
        )

        np.testing.assert_allclose(reversed_data, -normal_data, rtol=1e-6, atol=1e-6)
        np.testing.assert_allclose(reversed_times, normal_times, rtol=1e-6, atol=1e-6)
        self.assertEqual(reversed_latest, -normal_latest)

    def test_prepare_channel_plot_series_does_not_flip_rs_streams(self):
        harness = ADCPlottingHarness()
        harness.active_sensor_reverse_polarity = True
        spec = {"key": ("rs", "PZT1", 1, 4), "sample_indices": [0], "stream": "rs"}
        data = np.array([[10.0], [20.0], [30.0]], dtype=np.float32)
        timestamps = np.array([0.0, 0.1, 0.2], dtype=np.float64)

        channel_data, channel_times, latest_value = harness._prepare_channel_plot_series(
            spec,
            data,
            timestamps,
            avg_sample_time_sec=0.0,
            max_samples_per_series=100,
        )

        np.testing.assert_allclose(channel_data, np.array([10.0, 20.0, 30.0]), rtol=1e-6, atol=1e-6)
        np.testing.assert_allclose(channel_times, timestamps, rtol=1e-6, atol=1e-6)
        self.assertEqual(latest_value, 30.0)

    def test_voltage_mode_subtract_baseline_uses_voltage_converted_baseline(self):
        harness = ADCPlottingHarness()
        harness.yaxis_units_combo = DummyComboBox("Voltage")
        harness.subtract_baseline_check = DummyCheckBox(True)
        spec = {"key": ("adc", 3), "sample_indices": [0], "label": "CH3"}
        max_adc_value = (2 ** 12) - 1
        baseline_counts = max_adc_value / 2.0
        data = np.array([[baseline_counts], [baseline_counts + 10.0]], dtype=np.float32)
        timestamps = np.array([0.0, 0.001], dtype=np.float64)
        harness.plot_baselines[("adc", 3)] = baseline_counts

        channel_data, channel_times, latest_value = harness._prepare_channel_plot_series(
            spec,
            data,
            timestamps,
            avg_sample_time_sec=0.0,
            max_samples_per_series=100,
        )

        expected_delta_v = (10.0 / max_adc_value) * harness.get_vref_voltage()
        np.testing.assert_allclose(channel_data, np.array([0.0, expected_delta_v]), rtol=1e-6, atol=1e-6)
        np.testing.assert_allclose(channel_times, timestamps, rtol=1e-6, atol=1e-6)
        self.assertAlmostEqual(latest_value, expected_delta_v, places=6)

    def test_capture_current_plot_baselines_uses_median_window_value(self):
        harness = ADCPlottingHarness()
        harness.sweep_count = 3
        harness.buffer_write_index = 3
        harness.samples_per_sweep = 1
        harness.sweep_timestamps_buffer = np.array([0.0, 1.0, 2.0], dtype=np.float64)
        harness._active_data_buffer = np.array([[1.0], [100.0], [2.0]], dtype=np.float32)
        harness._display_specs = [{"key": ("adc", 7), "sample_indices": [0], "label": "CH7"}]

        success = harness.capture_current_plot_baselines(window_sec=10.0, log_message=False)

        self.assertTrue(success)
        self.assertEqual(harness.plot_baselines[("adc", 7)], 2.0)
        self.assertEqual(harness.channel_plot_baselines[7], 2.0)
        self.assertTrue(harness.subtract_baseline_check.isChecked())


if __name__ == "__main__":
    unittest.main()
