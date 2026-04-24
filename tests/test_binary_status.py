import threading
import unittest
from unittest.mock import patch

import numpy as np

from data_processing.binary_processor import BinaryProcessorMixin


class FakeLabel:
    def __init__(self):
        self.text = ''

    def setText(self, text):
        self.text = text


class FakeSpinBox:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value


class BinaryStatusHarness(BinaryProcessorMixin):
    MAX_SWEEPS_BUFFER = 50000

    def __init__(self):
        self.is_capturing = True
        self.buffer_lock = threading.Lock()
        self.sweep_count = 60000
        self.buffer_write_index = 60000
        self.samples_per_sweep = 5
        self.raw_data_buffer = np.zeros((self.MAX_SWEEPS_BUFFER, self.samples_per_sweep), dtype=np.float32)
        self.processed_data_buffer = np.zeros_like(self.raw_data_buffer)
        self.sweep_timestamps_buffer = np.zeros(self.MAX_SWEEPS_BUFFER, dtype=np.float64)
        self.force_data = []
        self.config = {'repeat': 1}
        self.plot_info_label = FakeLabel()
        self.window_size_spin = FakeSpinBox(2000)
        self.is_full_view = False
        self._last_plot_update_time = float('inf')
        self._debug_capture_blocks_seen = 99
        self.filtering_enabled = False
        self._cached_avg_sample_time_sec = 0.0
        self._block_timing_file = None
        self._archive_writer = None
        self.signal_trigger_count = 0
        self.signal_update_count = 0
        self.logged = []
        self._timing_state = type('TimingStateObj', (), {
            'buffer_receipt_times': [],
            'trim_recent': lambda *args, **kwargs: None,
            'arduino_sample_times': [],
            'mcu_block_start_us': [],
            'mcu_block_end_us': [],
            'mcu_block_gap_us': [],
            'mcu_last_block_end_us': None,
            'capture_start_time': None,
            'last_buffer_time': None,
            'block_sample_counts': [],
            'block_sweeps_counts': [],
            'block_samples_per_sweep': [],
            'last_buffer_end_time': None,
            'buffer_gap_times': [],
        })()

    @property
    def timing_state(self):
        return self._timing_state

    def should_store_capture_data(self):
        return True

    def get_effective_samples_per_sweep(self):
        return self.samples_per_sweep

    def filter_sweeps_block(self, block_samples_array, total_fs_hz):
        return block_samples_array

    def update_plot(self):
        return None

    def update_force_plot(self):
        return None

    def trigger_signal_integration_update(self):
        self.signal_trigger_count += 1

    def update_signal_integration_plot(self):
        self.signal_update_count += 1

    def update_timing_display(self):
        return None

    def log_status(self, message):
        self.logged.append(message)


class StreamingBinaryStatusHarness(BinaryStatusHarness):
    def __init__(self):
        super().__init__()
        self.signal_stream_count = 0

    def process_signal_integration_block(self, block_samples_array, sweep_timestamps_sec, avg_sample_time_us):
        self.signal_stream_count += 1
        return True


class BinaryStatusTests(unittest.TestCase):
    def test_runtime_status_uses_true_sweep_count_for_total_samples(self):
        harness = BinaryStatusHarness()
        samples = np.arange(10, dtype=np.uint16)

        harness.process_binary_sweep(samples, avg_sample_time_us=100, block_start_us=1000, block_end_us=1900)

        self.assertIn('ADC - Sweeps: 60002', harness.plot_info_label.text)
        self.assertIn('Samples: 300010', harness.plot_info_label.text)
        self.assertIn('(showing last 2000)', harness.plot_info_label.text)

    def test_pressure_map_refresh_is_queued_from_binary_handler(self):
        harness = BinaryStatusHarness()
        harness.should_update_live_timeseries_display = lambda: False
        harness.should_update_signal_integration_display = lambda: True
        samples = np.arange(10, dtype=np.uint16)

        with patch("data_processing.binary_processor.time.time", return_value=10.0):
            harness.process_binary_sweep(samples, avg_sample_time_us=100, block_start_us=1000, block_end_us=1900)

        self.assertEqual(harness.signal_trigger_count, 1)
        self.assertEqual(harness.signal_update_count, 0)

    def test_binary_handler_streams_pressure_map_without_duplicate_refresh(self):
        harness = StreamingBinaryStatusHarness()
        harness.should_update_live_timeseries_display = lambda: False
        harness.should_update_signal_integration_display = lambda: True
        samples = np.arange(10, dtype=np.uint16)

        with patch("data_processing.binary_processor.time.time", return_value=10.0):
            harness.process_binary_sweep(samples, avg_sample_time_us=100, block_start_us=1000, block_end_us=1900)

        self.assertEqual(harness.signal_stream_count, 1)
        self.assertEqual(harness.signal_trigger_count, 0)
        self.assertEqual(harness.signal_update_count, 0)


if __name__ == '__main__':
    unittest.main()
