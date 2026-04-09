import unittest

from config.mcu_profile import resolve_mcu_profile


class MCUProfileTests(unittest.TestCase):
    def test_resolves_array_dual_pzr_as_555_mode(self):
        profile = resolve_mcu_profile("Array_PZT_PZR_v1", selected_array_mode="PZR")

        self.assertTrue(profile.is_array_dual)
        self.assertTrue(profile.is_555_mode)
        self.assertEqual(profile.device_mode, "555")
        self.assertEqual(profile.device_mode_log_label, "PZR")
        self.assertFalse(profile.show_ground_controls)
        self.assertEqual(profile.buffer_size_max, 256)

    def test_resolves_teensy_as_adc_with_teensy_controls(self):
        profile = resolve_mcu_profile("Teensy4.1")

        self.assertTrue(profile.is_teensy)
        self.assertFalse(profile.is_555_mode)
        self.assertEqual(profile.device_mode, "adc")
        self.assertTrue(profile.show_teensy_controls)
        self.assertFalse(profile.show_reference_control)
        self.assertEqual(profile.osr_label_text, "Averaging:")

    def test_resolves_array_pzt1_as_adc_with_hidden_reference(self):
        profile = resolve_mcu_profile("Array_PZT1")

        self.assertTrue(profile.is_array_mcu)
        self.assertTrue(profile.is_array_pzt1)
        self.assertFalse(profile.is_555_mode)
        self.assertFalse(profile.show_reference_control)
        self.assertEqual(profile.osr_default, "4")


if __name__ == "__main__":
    unittest.main()
