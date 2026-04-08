import unittest

from config.mcu_state import (
    build_detected_mcu_state,
    build_disconnected_mcu_state,
    build_unknown_mcu_state,
)


class MCUStateTests(unittest.TestCase):
    def test_detected_state_populates_label_and_log(self):
        state = build_detected_mcu_state("Teensy4.1")

        self.assertEqual(state.current_mcu, "Teensy4.1")
        self.assertEqual(state.label_text, "MCU: Teensy4.1")
        self.assertEqual(state.log_message, "Detected MCU: Teensy4.1")
        self.assertIsNone(state.device_mode)

    def test_unknown_state_resets_to_unknown_label(self):
        state = build_unknown_mcu_state()

        self.assertIsNone(state.current_mcu)
        self.assertEqual(state.label_text, "MCU: Unknown")
        self.assertIn("timeout", state.log_message)

    def test_disconnected_state_resets_label_and_device_mode(self):
        state = build_disconnected_mcu_state()

        self.assertIsNone(state.current_mcu)
        self.assertEqual(state.label_text, "MCU: -")
        self.assertIsNone(state.log_message)
        self.assertEqual(state.device_mode, "adc")


if __name__ == "__main__":
    unittest.main()
