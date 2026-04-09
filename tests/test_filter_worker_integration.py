import threading
import unittest

import numpy as np

from data_processing.filter_processor import FilterProcessorMixin


class FilterWorkerHarness(FilterProcessorMixin):
    MAX_SWEEPS_BUFFER = 8

    def __init__(self):
        self.device_mode = "adc"
        self.filtering_enabled = True
        self.buffer_lock = threading.Lock()
        self.processed_data_buffer = np.zeros((self.MAX_SWEEPS_BUFFER, 2), dtype=np.float32)
        self.raw_data_buffer = np.zeros_like(self.processed_data_buffer)
        self.config = {"channels": [0, 1], "repeat": 1}
        self.buffer_write_index = 4
        self.plot_updates = 0
        self.spectrum_updates = 0
        self.current_tab = "Time Series"
        self.filter_last_error = None
        self.logged = []

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
    def test_worker_result_updates_processed_buffer_for_live_adc(self):
        harness = FilterWorkerHarness()
        block = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=np.float32)

        harness.on_adc_filter_worker_result({
            "write_base": 2,
            "sweeps_in_block": 2,
            "filtered_block": block,
        })

        np.testing.assert_allclose(harness.processed_data_buffer[2:4], block)
        self.assertEqual(harness.plot_updates, 1)

    def test_stale_worker_result_is_dropped(self):
        harness = FilterWorkerHarness()
        harness.buffer_write_index = 20
        original = harness.processed_data_buffer.copy()

        harness.on_adc_filter_worker_result({
            "write_base": 1,
            "sweeps_in_block": 2,
            "filtered_block": np.array([[1.0, 1.0], [2.0, 2.0]], dtype=np.float32),
        })

        np.testing.assert_allclose(harness.processed_data_buffer, original)

    def test_worker_error_disables_filtering(self):
        harness = FilterWorkerHarness()

        harness.on_adc_filter_worker_error("boom")

        self.assertFalse(harness.filtering_enabled)
        self.assertEqual(harness.filter_last_error, "boom")
        self.assertIn("live ADC filtering disabled", harness.logged[-1])


if __name__ == "__main__":
    unittest.main()
