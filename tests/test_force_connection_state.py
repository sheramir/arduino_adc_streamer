import unittest

from serial_communication.force_connection_state import (
    ForceConnectionViewState,
    build_force_connected_view_state,
    build_force_disconnected_view_state,
)


class ForceConnectionStateTests(unittest.TestCase):
    def test_connected_and_disconnected_view_states_match_expected_ui_flags(self):
        connected = build_force_connected_view_state()
        disconnected = build_force_disconnected_view_state()

        self.assertIsInstance(connected, ForceConnectionViewState)
        self.assertIsInstance(disconnected, ForceConnectionViewState)
        self.assertEqual(connected.connect_button_text, "Disconnect Force")
        self.assertFalse(connected.port_selection_enabled)
        self.assertEqual(disconnected.connect_button_text, "Connect Force")
        self.assertTrue(disconnected.port_selection_enabled)


if __name__ == "__main__":
    unittest.main()
