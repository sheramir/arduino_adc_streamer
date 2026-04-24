import unittest
from collections import deque
from unittest.mock import patch

from constants.force import (
    FORCE_CALIBRATION_SAMPLES,
    FORCE_STATUS_UPDATE_INTERVAL_SAMPLES,
)
from data_processing.force_processor import ForceProcessorMixin


class FakeTimer:
    def __init__(self):
        self.active = False
        self.started = []

    def isActive(self):
        return self.active

    def start(self, interval_ms):
        self.active = True
        self.started.append(interval_ms)


class FakeLabel:
    def __init__(self):
        self.text = ""

    def setText(self, text):
        self.text = text


class ForceProcessorHarness(ForceProcessorMixin):
    def __init__(self):
        self.force_calibrating = False
        self.calibration_samples = {'x': [], 'z': []}
        self.force_calibration_offset = {'x': 0.0, 'z': 0.0}
        self.force_data = deque(maxlen=32)
        self.force_start_time = None
        self.is_capturing = False
        self.sweep_count = 0
        self.samples_per_sweep = 0
        self.force_plot_timer = FakeTimer()
        self.force_plot_debounce_ms = 25
        self.plot_info_label = FakeLabel()
        self.logged = []

    def log_status(self, message):
        self.logged.append(message)


class ForceProcessorTests(unittest.TestCase):
    def test_force_calibration_logs_ready_status_when_offsets_complete(self):
        harness = ForceProcessorHarness()
        harness.calibrate_force_sensors()

        for value in range(FORCE_CALIBRATION_SAMPLES):
            harness.process_force_data(float(value), float(value + 100.0))

        self.assertFalse(harness.force_calibrating)
        self.assertIn("Force sensors ready (calibrated to zero)", harness.logged)
        self.assertTrue(
            any(message.startswith("Force calibration complete:") for message in harness.logged)
        )

    def test_force_samples_do_not_buffer_before_capture_starts(self):
        harness = ForceProcessorHarness()
        harness.calibrate_force_sensors()

        for value in range(FORCE_CALIBRATION_SAMPLES):
            harness.process_force_data(float(value), float(value))

        self.assertFalse(harness.force_calibrating)
        self.assertEqual(len(harness.force_data), 0)

        with patch("data_processing.force_processor.time.time", return_value=10.0):
            harness.process_force_data(20.0, 30.0)

        self.assertEqual(len(harness.force_data), 0)
        self.assertEqual(harness.force_plot_timer.started, [])

    def test_force_samples_buffer_during_active_capture(self):
        harness = ForceProcessorHarness()
        harness.force_calibration_offset = {'x': 1.0, 'z': 2.0}
        harness.is_capturing = True
        harness.force_start_time = 5.0

        with patch("data_processing.force_processor.time.time", return_value=12.0):
            harness.process_force_data(11.0, 22.0)

        self.assertEqual(len(harness.force_data), 1)
        timestamp, x_force, z_force = harness.force_data[0]
        self.assertAlmostEqual(timestamp, 7.0)
        self.assertAlmostEqual(x_force, 10.0)
        self.assertAlmostEqual(z_force, 20.0)
        self.assertEqual(harness.force_plot_timer.started, [25])

    def test_force_samples_buffer_without_redraw_when_timeseries_hidden(self):
        harness = ForceProcessorHarness()
        harness.force_calibration_offset = {'x': 1.0, 'z': 2.0}
        harness.is_capturing = True
        harness.force_start_time = 5.0
        harness.should_update_live_timeseries_display = lambda: False

        with patch("data_processing.force_processor.time.time", return_value=12.0):
            harness.process_force_data(11.0, 22.0)

        self.assertEqual(len(harness.force_data), 1)
        self.assertEqual(harness.force_plot_timer.started, [])

    def test_force_status_label_updates_on_interval_boundary(self):
        harness = ForceProcessorHarness()
        harness.force_calibration_offset = {'x': 0.0, 'z': 0.0}
        harness.is_capturing = True
        harness.force_start_time = 5.0
        harness.sweep_count = 4
        harness.samples_per_sweep = 5

        for sample_index in range(FORCE_STATUS_UPDATE_INTERVAL_SAMPLES):
            with patch(
                "data_processing.force_processor.time.time",
                return_value=10.0 + sample_index,
            ):
                harness.process_force_data(float(sample_index), float(sample_index))

        self.assertEqual(
            harness.plot_info_label.text,
            "ADC - Sweeps: 4 | Samples: 20  |  Force: 10 samples",
        )

    def test_force_reset_uses_recent_raw_samples_not_capture_buffered_values(self):
        harness = ForceProcessorHarness()

        for index in range(FORCE_CALIBRATION_SAMPLES):
            harness.process_force_data(float(index + 10), float(index + 110))

        self.assertTrue(harness.reset_force_baseline_from_recent_samples())
        self.assertAlmostEqual(
            harness.force_calibration_offset['x'],
            sum(range(10, 10 + FORCE_CALIBRATION_SAMPLES)) / FORCE_CALIBRATION_SAMPLES,
        )
        self.assertAlmostEqual(
            harness.force_calibration_offset['z'],
            sum(range(110, 110 + FORCE_CALIBRATION_SAMPLES)) / FORCE_CALIBRATION_SAMPLES,
        )
        self.assertTrue(any(message.startswith("Load cell reset complete:") for message in harness.logged))


if __name__ == "__main__":
    unittest.main()
