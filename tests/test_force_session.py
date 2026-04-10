import unittest
from unittest.mock import patch

from config_constants import FORCE_SENSOR_BAUD_RATE
from serial_communication.force_session import ForceSessionController


class FakeSignal:
    def __init__(self):
        self.connected = []

    def connect(self, callback):
        self.connected.append(callback)


class FakeSerialPort:
    def __init__(self, *, close_error=None):
        self.is_open = True
        self.close_error = close_error
        self.reset_input_buffer_calls = 0

    def reset_input_buffer(self):
        self.reset_input_buffer_calls += 1

    def close(self):
        if self.close_error is not None:
            raise self.close_error
        self.is_open = False


class FakeForceReaderThread:
    def __init__(self, serial_port, *, wait_result=True, start_error=None):
        self.serial_port = serial_port
        self.force_data_received = FakeSignal()
        self.error_occurred = FakeSignal()
        self.started = False
        self.stop_calls = 0
        self.wait_calls = []
        self.wait_result = wait_result
        self.start_error = start_error

    def start(self):
        if self.start_error is not None:
            raise self.start_error
        self.started = True

    def stop(self):
        self.stop_calls += 1

    def wait(self, timeout_ms):
        self.wait_calls.append(timeout_ms)
        return self.wait_result


class ForceSessionControllerTests(unittest.TestCase):
    def test_connect_opens_port_clears_buffer_and_starts_reader_thread(self):
        fake_port = FakeSerialPort()
        created_threads = []

        def build_thread(port):
            thread = FakeForceReaderThread(port)
            created_threads.append(thread)
            return thread

        on_force_data = object()
        on_error = object()
        session = ForceSessionController(on_force_data, on_error)

        with patch("serial_communication.force_session.serial.Serial", return_value=fake_port) as serial_ctor, patch(
            "serial_communication.force_session.ForceReaderThread",
            side_effect=build_thread,
        ), patch("serial_communication.force_session.time.sleep"):
            port, thread = session.connect("COM20")

        serial_ctor.assert_called_once_with(port="COM20", baudrate=FORCE_SENSOR_BAUD_RATE, timeout=1.0)
        self.assertIs(port, fake_port)
        self.assertEqual(fake_port.reset_input_buffer_calls, 1)
        self.assertIs(thread, created_threads[0])
        self.assertTrue(thread.started)
        self.assertEqual(thread.force_data_received.connected, [on_force_data])
        self.assertEqual(thread.error_occurred.connected, [on_error])
        self.assertIs(session.serial_port, fake_port)
        self.assertIs(session.serial_thread, thread)

    def test_disconnect_stops_thread_and_collects_warnings(self):
        fake_port = FakeSerialPort(close_error=RuntimeError("close failed"))
        fake_thread = FakeForceReaderThread(fake_port, wait_result=False)
        session = ForceSessionController(lambda *_: None, lambda *_: None)
        session.serial_port = fake_port
        session.serial_thread = fake_thread

        warnings = session.disconnect(thread_wait_ms=321)

        self.assertEqual(fake_thread.stop_calls, 1)
        self.assertEqual(fake_thread.wait_calls, [321])
        self.assertIn("Force serial thread shutdown timed out; continuing disconnect", warnings)
        self.assertIn("Failed to close force serial port cleanly: close failed", warnings)
        self.assertIsNone(session.serial_port)
        self.assertIsNone(session.serial_thread)

    def test_connect_closes_port_if_reader_start_fails(self):
        fake_port = FakeSerialPort()

        def build_thread(port):
            return FakeForceReaderThread(port, start_error=RuntimeError("thread failed"))

        session = ForceSessionController(lambda *_: None, lambda *_: None)

        with patch("serial_communication.force_session.serial.Serial", return_value=fake_port), patch(
            "serial_communication.force_session.ForceReaderThread",
            side_effect=build_thread,
        ), patch("serial_communication.force_session.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "thread failed"):
                session.connect("COM9")

        self.assertFalse(fake_port.is_open)
        self.assertIsNone(session.serial_port)
        self.assertIsNone(session.serial_thread)


if __name__ == "__main__":
    unittest.main()
