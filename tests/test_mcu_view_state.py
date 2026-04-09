import unittest

from config.mcu_profile import resolve_mcu_profile
from config.mcu_view_state import build_mcu_view_state


class MCUViewStateTests(unittest.TestCase):
    def test_555_profile_maps_to_hidden_adc_controls(self):
        profile = resolve_mcu_profile("555 Analyzer")
        view_state = build_mcu_view_state(profile)

        self.assertFalse(view_state.show_ground_controls)
        self.assertTrue(view_state.show_555_controls)
        self.assertFalse(view_state.osr_visible)
        self.assertEqual(view_state.yaxis_units_value, "Values")

    def test_teensy_profile_maps_to_teensy_controls_and_averaging_label(self):
        profile = resolve_mcu_profile("Teensy4.1")
        view_state = build_mcu_view_state(profile)

        self.assertTrue(view_state.show_teensy_controls)
        self.assertEqual(view_state.osr_label_text, "Averaging:")
        self.assertEqual(view_state.osr_default, "4")

    def test_array_pzt_profile_keeps_reference_hidden_and_osr_visible(self):
        profile = resolve_mcu_profile("Array_PZT1")
        view_state = build_mcu_view_state(profile)

        self.assertFalse(view_state.show_reference_control)
        self.assertTrue(view_state.osr_visible)
        self.assertEqual(view_state.osr_default, "4")


if __name__ == "__main__":
    unittest.main()
