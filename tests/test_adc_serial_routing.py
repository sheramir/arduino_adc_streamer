import unittest

from config.mcu_detector import MCUDetectorMixin
from config_constants import COMMAND_TERMINATOR
from serial_communication.adc_serial import ADCSerialMixin
from serial_communication.adc_session import ADCSessionController


class FakeLabel:
    def __init__(self):
        self.text = ""

    def setText(self, text: str):
        self.text = text


class FakeSerialPort:
    def __init__(self, on_write=None):
        self.is_open = True
        self.on_write = on_write
        self.writes = []

    def write(self, payload: bytes):
        self.writes.append(payload)
        if self.on_write is not None:
            self.on_write(payload)

    def flush(self):
        return None

    def reset_input_buffer(self):
        return None

    def reset_output_buffer(self):
        return None


class DummyAdcRouting(ADCSerialMixin, MCUDetectorMixin):
    def __init__(self):
        self.adc_session = ADCSessionController(
            self.process_serial_data,
            self.process_binary_sweep,
            self._handle_serial_reader_error,
        )
        self.serial_port = None
        self.serial_thread = None
        self.current_mcu = None
        self.mcu_label = FakeLabel()
        self.logged = []

    def log_status(self, message: str):
        self.logged.append(message)

    def process_serial_data(self, line: str):
        return None

    def process_binary_sweep(self, *args):
        return None

    def _handle_serial_reader_error(self, message: str):
        self.logged.append(message)


class AdcSerialRoutingTests(unittest.TestCase):
    def test_parse_ack_line(self):
        self.assertEqual(ADCSerialMixin._parse_ack_line("#OK 123"), (True, "123"))
        self.assertEqual(ADCSerialMixin._parse_ack_line("#NOT_OK bad"), (False, "bad"))
        self.assertIsNone(ADCSerialMixin._parse_ack_line("# Teensy4.1"))

    def test_send_command_and_wait_ack_uses_routed_adc_lines(self):
        harness = DummyAdcRouting()

        def on_write(payload: bytes):
            if payload.decode("utf-8") == f"gain 42{COMMAND_TERMINATOR}":
                harness._handle_adc_text_line("#OK 42")

        harness.adc_session.serial_port = FakeSerialPort(on_write=on_write)
        harness.serial_port = harness.adc_session.serial_port
        success, value = harness.send_command_and_wait_ack(
            "gain 42",
            expected_value="42",
            timeout=0.05,
            max_retries=1,
        )

        self.assertTrue(success)
        self.assertEqual(value, "42")
        self.assertEqual(harness.serial_port.writes, [f"gain 42{COMMAND_TERMINATOR}".encode("utf-8")])
        self.assertEqual(harness.adc_session._adc_line_waiters, [])

    def test_detect_mcu_uses_routed_adc_lines(self):
        harness = DummyAdcRouting()

        def on_write(payload: bytes):
            if payload.decode("utf-8") == f"mcu{COMMAND_TERMINATOR}":
                harness._handle_adc_text_line("# Teensy4.1")

        harness.adc_session.serial_port = FakeSerialPort(on_write=on_write)
        harness.serial_port = harness.adc_session.serial_port
        harness.detect_mcu()

        self.assertEqual(harness.current_mcu, "Teensy4.1")
        self.assertEqual(harness.mcu_label.text, "MCU: Teensy4.1")
        self.assertIn("Detected MCU: Teensy4.1", harness.logged)


if __name__ == "__main__":
    unittest.main()
