"""
Serial Status Parser
====================
Covers the malformed-line handling of SerialParserMixin.parse_status_line.
"""

import unittest
from dataclasses import dataclass

from serial_communication.serial_parser import SerialParserMixin


@dataclass
class FakeArduinoStatus:
    channels: list | None = None
    repeat: int | None = None
    ground_pin: int | None = None
    use_ground: bool | None = None
    osr: int | None = None
    gain: int | None = None
    reference: str | None = None


class DummyParser(SerialParserMixin):
    def __init__(self):
        self.arduino_status = FakeArduinoStatus()
        self.logged = []

    def log_status(self, message: str):
        self.logged.append(message)


class SerialStatusParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = DummyParser()

    def test_parses_channel_list(self):
        self.parser.parse_status_line("#   1,2,3,4,5")
        self.assertEqual(self.parser.arduino_status.channels, [1, 2, 3, 4, 5])

    def test_parses_scalar_fields(self):
        self.parser.parse_status_line("# repeatCount: 4")
        self.parser.parse_status_line("# groundPin: 7")
        self.parser.parse_status_line("# useGroundBeforeEach: true")
        self.parser.parse_status_line("# osr: 16")
        self.parser.parse_status_line("# gain: 2")

        status = self.parser.arduino_status
        self.assertEqual(status.repeat, 4)
        self.assertEqual(status.ground_pin, 7)
        self.assertTrue(status.use_ground)
        self.assertEqual(status.osr, 16)
        self.assertEqual(status.gain, 2)

    def test_maps_reference_names(self):
        self.parser.parse_status_line("# adcReference: INTERNAL1V2")
        self.assertEqual(self.parser.arduino_status.reference, "1.2")

        self.parser.parse_status_line("# adcReference: VDD")
        self.assertEqual(self.parser.arduino_status.reference, "vdd")

    def test_unknown_reference_falls_back_to_lowercase(self):
        self.parser.parse_status_line("# adcReference: SomethingElse")
        self.assertEqual(self.parser.arduino_status.reference, "somethingelse")

    def test_non_numeric_values_are_ignored_without_raising(self):
        # Malformed firmware output must not propagate out of the parser.
        for line in (
            "# repeatCount: not-a-number",
            "# groundPin: ",
            "# osr: 1.5",
            "# gain: 0x10",
            "#   1,2,oops",
        ):
            with self.subTest(line=line):
                self.parser.parse_status_line(line)

        status = self.parser.arduino_status
        self.assertIsNone(status.repeat)
        self.assertIsNone(status.ground_pin)
        self.assertIsNone(status.osr)
        self.assertIsNone(status.gain)
        self.assertIsNone(status.channels)

    def test_partial_channel_line_leaves_previous_value(self):
        self.parser.parse_status_line("#   1,2,3")
        self.parser.parse_status_line("#   4,bad,6")
        self.assertEqual(self.parser.arduino_status.channels, [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
