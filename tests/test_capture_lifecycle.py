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
