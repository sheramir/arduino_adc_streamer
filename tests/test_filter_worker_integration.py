import threading
import unittest

import numpy as np

from data_processing.adc_filter_engine import ADCFilterEngine
from data_processing.filter_processor import FilterProcessorMixin


class FakeWorker:
    def __init__(self):
        self.submissions = []

    def submit(self, payload):
        self.submissions.append(payload)


class FilterWorkerHarness(FilterProcessorMixin):
    MAX_SWEEPS_BUFFER = 8

    def __init__(self):
        self.device_mode = "adc"
        self.filtering_enabled = True
        self.buffer_lock = threading.Lock()
        self.processed_data_buffer = np.full((self.MAX_SWEEPS_BUFFER, 2), 9.0, dtype=np.float32)
        self.raw_data_buffer = np.arange(self.MAX_SWEEPS_BUFFER * 2, dtype=np.float32).reshape(self.MAX_SWEEPS_BUFFER, 2)
        self.sweep_timestamps_buffer = np.linspace(0.0, 0.7, self.MAX_SWEEPS_BUFFER, dtype=np.float64)
        self.config = {"channels": [0, 1], "repeat": 1, "sample_rate": 0}
        self.filter_settings = self.get_default_filter_settings()
        self.adc_filter_engine = ADCFilterEngine()
        self.adc_filter_worker = FakeWorker()
        self.buffer_write_index = 4
        self.sweep_count = 4
        self.plot_updates = 0
        self.spectrum_updates = 0
        self.current_tab = "Time Series"
        self.filter_last_error = None
        self.logged = []
        self._live_filtered_start_abs = 0
        self._live_filtered_ready_abs = 0
        self._live_filter_generation = 0
        self._timeseries_filter_pending_key = None
        self._timeseries_filter_cached_key = None
        self._timeseries_filter_cached_data = None
        self._timeseries_filter_cached_timestamps = None
        self.filter_apply_pending = True
        self._filter_total_fs_hz = 0.0
        self._filter_channels_signature = None
        self._filter_channel_runtime = {}
        self.is_capturing = True
        self.is_full_view = False
        self.timing_state = type(
            "Timing",
            (),
            {"arduino_sample_times": [1000.0], "timing_data": {}},
        )()

    def should_update_live_timeseries_display(self):
        return self.current_tab == "Time Series"

    def get_current_visualization_tab_name(self):
        return self.current_tab

    def trigger_plot_update(self):
        self.plot_updates += 1

    def update_spectrum(self):
        self.spectrum_updates += 1

    def log_status(self, message):
        self.logged.append(message)


class FilterWorkerIntegrationTests(unittest.TestCase):
    def test_live_timeseries_prefers_raw_buffer_while_capturing(self):
        harness = FilterWorkerHarness()

        active = harness.get_active_data_buffer()

        self.assertIs(active, harness.raw_data_buffer)

    def test_request_live_timeseries_filter_snapshot_submits_latest_window(self):
        harness = FilterWorkerHarness()
        data = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=np.float32)
        timestamps = np.array([0.2, 0.3], dtype=np.float64)
        snapshot_key = (0, 4, 2)

        submitted = harness.request_live_timeseries_filter_snapshot(data, timestamps, snapshot_key)

        self.assertTrue(submitted)
        self.assertEqual(len(harness.adc_filter_worker.submissions), 1)
        payload = harness.adc_filter_worker.submissions[0]
        self.assertEqual(payload["mode"], "timeseries_window")
        self.assertEqual(payload["snapshot_key"], snapshot_key)
        np.testing.assert_allclose(payload["window_data"], data)
        np.testing.assert_allclose(payload["sweep_timestamps_sec"], timestamps)
        self.assertEqual(harness._timeseries_filter_pending_key, snapshot_key)

    def test_duplicate_live_timeseries_snapshot_request_is_skipped(self):
        harness = FilterWorkerHarness()
        data = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=np.float32)
        timestamps = np.array([0.2, 0.3], dtype=np.float64)
        snapshot_key = (0, 4, 2)

        first = harness.request_live_timeseries_filter_snapshot(data, timestamps, snapshot_key)
        second = harness.request_live_timeseries_filter_snapshot(data, timestamps, snapshot_key)

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(harness.adc_filter_worker.submissions), 1)

    def test_timeseries_worker_result_caches_window_and_requests_replot(self):
        harness = FilterWorkerHarness()
        snapshot_key = (0, 4, 2)
        filtered = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=np.float32)
        timestamps = np.array([0.2, 0.3], dtype=np.float64)
        harness._timeseries_filter_pending_key = snapshot_key

        harness.on_adc_filter_worker_result({
            "mode": "timeseries_window",
            "generation": 0,
            "snapshot_key": snapshot_key,
            "sweep_timestamps_sec": timestamps,
            "filtered_data": filtered,
        })

        self.assertIsNone(harness._timeseries_filter_pending_key)
        self.assertEqual(harness._timeseries_filter_cached_key, snapshot_key)
        np.testing.assert_allclose(harness._timeseries_filter_cached_data, filtered)
        np.testing.assert_allclose(harness._timeseries_filter_cached_timestamps, timestamps)
        self.assertEqual(harness.plot_updates, 1)

    def test_stale_timeseries_worker_result_updates_cached_window(self):
        harness = FilterWorkerHarness()
        harness._timeseries_filter_pending_key = (0, 5, 2)
        filtered = np.array([[1.0, 1.0], [2.0, 2.0]], dtype=np.float32)
        timestamps = np.array([0.2, 0.3], dtype=np.float64)

        harness.on_adc_filter_worker_result({
            "mode": "timeseries_window",
            "generation": 0,
            "snapshot_key": (0, 4, 2),
            "sweep_timestamps_sec": timestamps,
            "filtered_data": filtered,
        })

        self.assertEqual(harness._timeseries_filter_pending_key, (0, 5, 2))
        self.assertEqual(harness._timeseries_filter_cached_key, (0, 4, 2))
        np.testing.assert_allclose(harness._timeseries_filter_cached_data, filtered)
        np.testing.assert_allclose(harness._timeseries_filter_cached_timestamps, timestamps)
        self.assertEqual(harness.plot_updates, 1)

    def test_live_timeseries_uses_latest_cached_filtered_window_while_newer_one_is_pending(self):
        harness = FilterWorkerHarness()
        harness._timeseries_filter_cached_key = (0, 4, 2)
        harness._timeseries_filter_cached_data = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=np.float32)
        harness._timeseries_filter_cached_timestamps = np.array([0.2, 0.3], dtype=np.float64)
        harness._timeseries_filter_pending_key = (0, 5, 2)

        data = np.array([[20.0, 21.0], [22.0, 23.0]], dtype=np.float32)
        timestamps = np.array([0.4, 0.5], dtype=np.float64)

        filtered_data, filtered_timestamps = harness.maybe_get_live_timeseries_filtered_snapshot(
            data,
            timestamps,
            (0, 6, 2),
        )

        np.testing.assert_allclose(
            filtered_data,
            np.array([[10.0, 11.0], [12.0, 13.0]], dtype=np.float32),
        )
        np.testing.assert_allclose(filtered_timestamps, np.array([0.2, 0.3], dtype=np.float64))
        self.assertEqual(harness._timeseries_filter_pending_key, (0, 6, 2))
        self.assertEqual(len(harness.adc_filter_worker.submissions), 1)

    def test_first_live_timeseries_request_falls_back_to_raw_until_filter_result_arrives(self):
        harness = FilterWorkerHarness()
        data = np.array([[20.0, 21.0], [22.0, 23.0]], dtype=np.float32)
        timestamps = np.array([0.4, 0.5], dtype=np.float64)

        filtered_data, filtered_timestamps = harness.maybe_get_live_timeseries_filtered_snapshot(
            data,
            timestamps,
            (0, 6, 2),
        )

        np.testing.assert_allclose(filtered_data, data)
        np.testing.assert_allclose(filtered_timestamps, timestamps)
        self.assertEqual(harness._timeseries_filter_pending_key, (0, 6, 2))
        self.assertEqual(len(harness.adc_filter_worker.submissions), 1)

    def test_worker_error_disables_filtering(self):
        harness = FilterWorkerHarness()

        harness.on_adc_filter_worker_error("boom")

        self.assertFalse(harness.filtering_enabled)
        self.assertEqual(harness.filter_last_error, "boom")
        self.assertIn("live ADC filtering disabled", harness.logged[-1])

    def test_spectrum_source_state_uses_raw_buffer_on_spectrum_tab(self):
        harness = FilterWorkerHarness()
        harness.current_tab = "Spectrum"
        harness._live_filtered_start_abs = 10
        harness._live_filtered_ready_abs = 14

        data_buffer, start_abs, end_abs = harness.get_spectrum_source_state()

        self.assertIs(data_buffer, harness.raw_data_buffer)
        self.assertEqual(start_abs, 0)
        self.assertEqual(end_abs, harness.buffer_write_index)

    def test_worker_result_from_old_generation_is_ignored(self):
        harness = FilterWorkerHarness()
        harness._live_filter_generation = 2
        harness._timeseries_filter_pending_key = (2, 4, 2)

        harness.on_adc_filter_worker_result({
            "mode": "timeseries_window",
            "generation": 1,
            "snapshot_key": (2, 4, 2),
            "sweep_timestamps_sec": np.array([0.2, 0.3], dtype=np.float64),
            "filtered_data": np.array([[5.0, 5.0], [6.0, 6.0]], dtype=np.float32),
        })

        self.assertEqual(harness._timeseries_filter_pending_key, (2, 4, 2))
        self.assertIsNone(harness._timeseries_filter_cached_key)


if __name__ == "__main__":
    unittest.main()
