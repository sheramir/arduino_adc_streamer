import threading
import unittest

from data_processing.capture_lifecycle import CaptureLifecycleMixin


class FakeControl:
    def __init__(self):
        self.enabled = None

    def setEnabled(self, value):
        self.enabled = bool(value)


class FakeTimedRunCheck(FakeControl):
    def __init__(self, checked):
        super().__init__()
        self._checked = checked

    def isChecked(self):
        return self._checked


class CaptureLifecycleHarness(CaptureLifecycleMixin):
    def __init__(self):
        self.serial_port = None
        self.port_combo = FakeControl()
        self.refresh_ports_btn = FakeControl()
        self.vref_combo = FakeControl()
        self.osr_combo = FakeControl()
        self.gain_combo = FakeControl()
        self.channels_input = FakeControl()
        self.array_mode_combo = FakeControl()
        self.pzt_sequence_input = FakeControl()
        self.pzr_sequence_input = FakeControl()
        self.ground_pin_spin = FakeControl()
        self.use_ground_check = FakeControl()
        self.repeat_spin = FakeControl()
        self.buffer_spin = FakeControl()
        self.timed_run_check = FakeTimedRunCheck(True)
        self.timed_run_spin = FakeControl()
        self.window_size_spin = FakeControl()


class CaptureLifecycleTests(unittest.TestCase):
    def test_reset_capture_buffer_state_resets_force_display_state(self):
        harness = CaptureLifecycleHarness()
        harness.buffer_lock = threading.Lock()
        harness.raw_data = []
        harness.sweep_timestamps = []
        harness.sweep_count = 0
        harness.buffer_write_index = 0
        harness.raw_data_buffer = None
        harness.processed_data_buffer = None
        harness.sweep_timestamps_buffer = None
        reset_calls = []
        harness.reset_pressure_force_display_for_baseline_change = (
            lambda: reset_calls.append(True)
        )

        harness._reset_capture_buffer_state()

        # Clearing the shared baseline must also clear any Force history that
        # was integrated against it.
        self.assertEqual(harness.plot_baselines, {})
        self.assertEqual(reset_calls, [True])

    def test_set_controls_enabled_updates_acquisition_controls(self):
        harness = CaptureLifecycleHarness()

        harness.set_controls_enabled(False)
        self.assertFalse(harness.vref_combo.enabled)
        self.assertFalse(harness.timed_run_spin.enabled)
        self.assertFalse(harness.window_size_spin.enabled)

        harness.set_controls_enabled(True)
        self.assertTrue(harness.vref_combo.enabled)
        self.assertTrue(harness.channels_input.enabled)
        self.assertTrue(harness.timed_run_spin.enabled)
        self.assertTrue(harness.window_size_spin.enabled)


if __name__ == "__main__":
    unittest.main()
