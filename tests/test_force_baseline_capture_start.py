import unittest

from data_processing.capture_lifecycle import CaptureLifecycleMixin


class FakePort:
    def __init__(self, is_open):
        self.is_open = is_open


class ForceBaselineCaptureHarness(CaptureLifecycleMixin):
    def __init__(self):
        self.force_serial_port = None
        self.calibration_calls = 0
        self.logged = []

    def log_status(self, message):
        self.logged.append(message)

    def calibrate_force_sensors(self):
        self.calibration_calls += 1


class ForceBaselineCaptureTests(unittest.TestCase):
    def test_capture_start_rezeros_force_baseline_when_force_port_is_connected(self):
        harness = ForceBaselineCaptureHarness()
        harness.force_serial_port = FakePort(is_open=True)

        harness._restart_force_baseline_measurement_if_connected()

        self.assertEqual(harness.calibration_calls, 1)
        self.assertTrue(any("Re-zeroing force sensors at capture start" in message for message in harness.logged))

    def test_capture_start_skips_force_rezero_when_force_port_is_disconnected(self):
        harness = ForceBaselineCaptureHarness()
        harness.force_serial_port = FakePort(is_open=False)

        harness._restart_force_baseline_measurement_if_connected()

        self.assertEqual(harness.calibration_calls, 0)


if __name__ == "__main__":
    unittest.main()
