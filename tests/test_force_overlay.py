import threading
import unittest

import numpy as np

from data_processing.force_overlay import ForceOverlayMixin


class FakeSpinBox:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value


class ForceOverlayHarness(ForceOverlayMixin):
    MAX_SWEEPS_BUFFER = 5

    def __init__(self):
        self.buffer_lock = threading.Lock()
        self.window_size_spin = FakeSpinBox(3)
        self.sweep_timestamps_buffer = np.zeros(self.MAX_SWEEPS_BUFFER, dtype=np.float64)
        self.sweep_timestamps = np.array([], dtype=np.float64)
        self.sweep_count = 0
        self.buffer_write_index = 0
        self.is_capturing = False
        self.is_full_view = False
        self.force_data = []


class ForceOverlayTests(unittest.TestCase):
    def test_time_window_uses_trailing_capture_window_before_wrap(self):
        harness = ForceOverlayHarness()
        harness.is_capturing = True
        harness.sweep_count = 4
        harness.buffer_write_index = 4
        harness.sweep_timestamps_buffer[:4] = [1.0, 2.0, 3.0, 4.0]

        self.assertEqual(harness._get_force_plot_time_window(), (2.0, 4.0))

    def test_time_window_uses_wrapped_ring_order_while_capturing(self):
        harness = ForceOverlayHarness()
        harness.is_capturing = True
        harness.sweep_count = 8
        harness.buffer_write_index = 8
        harness.sweep_timestamps_buffer[:] = [6.0, 7.0, 8.0, 4.0, 5.0]

        self.assertEqual(harness._get_force_plot_time_window(), (6.0, 8.0))

    def test_time_window_uses_full_retained_span_after_capture(self):
        harness = ForceOverlayHarness()
        harness.is_capturing = False
        harness.sweep_count = 8
        harness.buffer_write_index = 8
        harness.sweep_timestamps_buffer[:] = [6.0, 7.0, 8.0, 4.0, 5.0]

        self.assertEqual(harness._get_force_plot_time_window(), (4.0, 8.0))

    def test_time_window_uses_full_view_timestamp_span(self):
        harness = ForceOverlayHarness()
        harness.is_full_view = True
        harness.sweep_count = 3
        harness.buffer_write_index = 3
        harness.sweep_timestamps = np.array([1.0, 2.0, 3.0], dtype=np.float64)

        self.assertEqual(harness._get_force_plot_time_window(), (1.0, 3.0))

    def test_time_window_returns_none_without_adc_sweeps(self):
        harness = ForceOverlayHarness()
        harness.force_data = [
            (0.25, 1.0, 2.0),
            (0.75, 1.5, 2.5),
            (1.50, 2.0, 3.0),
        ]

        self.assertIsNone(harness._get_force_plot_time_window())


if __name__ == '__main__':
    unittest.main()
