import unittest
from unittest.mock import patch

from serial_communication.force_serial import ForceSerialMixin


class ForceSerialHarness(ForceSerialMixin):
    def __init__(self):
        self._force_disconnect_in_progress = False
        self.force_serial_port = object()
        self.force_serial_thread = object()
        self.logged = []
        self.disconnect_calls = 0

    def log_status(self, message):
        self.logged.append(message)

    def disconnect_force_serial(self):
        self.disconnect_calls += 1


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


if __name__ == "__main__":
    unittest.main()
