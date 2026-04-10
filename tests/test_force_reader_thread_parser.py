import unittest

from serial_communication.serial_threads import parse_force_sensor_line


class ForceReaderThreadParserTests(unittest.TestCase):
    def test_parse_simple_x_z_csv_line(self):
        self.assertEqual(parse_force_sensor_line("12.5,34.75"), (12.5, 34.75))

    def test_parse_timestamp_x_z_csv_line(self):
        self.assertEqual(parse_force_sensor_line("123456,12.5,34.75"), (12.5, 34.75))

    def test_parse_labeled_numeric_line_uses_last_two_values(self):
        self.assertEqual(parse_force_sensor_line("t=123 x=12.5 z=34.75"), (12.5, 34.75))

    def test_parse_returns_none_for_malformed_line(self):
        self.assertIsNone(parse_force_sensor_line("hello world"))

    def test_parse_returns_none_for_empty_line(self):
        self.assertIsNone(parse_force_sensor_line(""))


if __name__ == "__main__":
    unittest.main()
