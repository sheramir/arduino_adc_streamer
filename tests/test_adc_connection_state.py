import unittest

from serial_communication.adc_connection_state import (
    build_connected_view_state,
    build_default_arduino_status,
    build_default_last_sent_config,
    build_disconnected_view_state,
)


class ADCConnectionStateTests(unittest.TestCase):
    def test_default_last_sent_config_has_expected_keys(self):
        default_config = build_default_last_sent_config()

        self.assertEqual(
            set(default_config.keys()),
            {"channels", "repeat", "ground_pin", "use_ground", "osr", "gain", "reference"},
        )
        self.assertTrue(all(value is None for value in default_config.values()))

    def test_default_arduino_status_has_expected_keys(self):
        status = build_default_arduino_status()

        self.assertEqual(
            set(status.keys()),
            {
                "channels", "repeat", "ground_pin", "use_ground", "osr", "gain",
                "reference", "buffer", "rb", "rk", "cf", "rxmax",
            },
        )
        self.assertTrue(all(value is None for value in status.values()))

    def test_connected_and_disconnected_view_states_match_expected_ui_flags(self):
        connected = build_connected_view_state()
        disconnected = build_disconnected_view_state()

        self.assertEqual(connected.connect_button_text, "Disconnect")
        self.assertTrue(connected.configure_enabled)
        self.assertFalse(connected.port_selection_enabled)
        self.assertEqual(disconnected.connect_button_text, "Connect")
        self.assertFalse(disconnected.configure_enabled)
        self.assertTrue(disconnected.port_selection_enabled)


if __name__ == "__main__":
    unittest.main()
