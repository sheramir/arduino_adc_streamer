import unittest
from unittest.mock import patch

from serial_communication.force_serial import ForceSerialMixin


class FakePort:
    def __init__(self, is_open=True):
        self.is_open = is_open


class ForceSerialHarness(ForceSerialMixin):
    def __init__(self):
        self._force_disconnect_in_progress = False
        self.force_serial_port = object()
        self.force_serial_thread = object()
        self.logged = []
        self.disconnect_calls = 0
        self.reset_calls = 0

    def log_status(self, message):
        self.logged.append(message)

    def disconnect_force_serial(self):
        self.disconnect_calls += 1

    def reset_force_baseline_from_recent_samples(self):
        self.reset_calls += 1
        return True


class ForceSerialTests(unittest.TestCase):
    def test_debug_message_does_not_trigger_disconnect(self):
        harness = ForceSerialHarness()

        with patch("serial_communication.force_serial.QTimer.singleShot") as single_shot:
            harness._handle_force_reader_error("Force reader parsed sample 1: x=1.0, z=2.0")

        self.assertEqual(harness.disconnect_calls, 0)
        single_shot.assert_not_called()

    def test_read_error_schedules_disconnect(self):
        harness = ForceSerialHarness()

        with patch("serial_communication.force_serial.QTimer.singleShot") as single_shot:
            harness._handle_force_reader_error("Force sensor read error: device lost")

        self.assertEqual(harness.disconnect_calls, 0)
        single_shot.assert_called_once()

    def test_reset_load_cell_uses_recent_samples_when_connected(self):
        harness = ForceSerialHarness()
        harness.force_serial_port = FakePort(is_open=True)

        harness.reset_force_load_cell()

        self.assertEqual(harness.reset_calls, 1)
        self.assertTrue(any(message.startswith("Resetting load cell baseline") for message in harness.logged))

    def test_reset_load_cell_warns_when_disconnected(self):
        harness = ForceSerialHarness()
        harness.force_serial_port = None

        harness.reset_force_load_cell()

        self.assertEqual(harness.reset_calls, 0)
        self.assertIn("WARNING: Connect the force sensor before resetting the load cell", harness.logged)


if __name__ == "__main__":
    unittest.main()
