import unittest

from config.mcu_detector import MCUDetectorMixin


class _LabelStub:
    def __init__(self):
        self.text = ""

    def setText(self, value):
        self.text = value


class _Harness(MCUDetectorMixin):
    def __init__(self):
        self.current_mcu = None
        self.device_mode = "adc"
        self.mcu_label = _LabelStub()
        self.logged = []
        self._array_pzt_pzr1_defaults_applied = True

    def log_status(self, message):
        self.logged.append(message)


class MCUDetectorMixinTests(unittest.TestCase):
    def test_locked_ground_pin_mapping_for_special_mcus(self):
        self.assertEqual(MCUDetectorMixin._get_locked_ground_pin_for_mcu_name("Array_PZT_PZR1"), 10)
        self.assertEqual(MCUDetectorMixin._get_locked_ground_pin_for_mcu_name("array_pzt_pzr1.7"), 15)
        self.assertIsNone(MCUDetectorMixin._get_locked_ground_pin_for_mcu_name("Array_PZT_PZR_v1"))

    def test_special_mcu_detection_includes_both_variants(self):
        self.assertTrue(MCUDetectorMixin._is_ground_default_mcu_name("Array_PZT_PZR1"))
        self.assertTrue(MCUDetectorMixin._is_ground_default_mcu_name("Array_PZT_PZR1.7"))
        self.assertFalse(MCUDetectorMixin._is_ground_default_mcu_name("Teensy4.1"))

    def test_defaults_are_rearmed_when_mcu_name_changes(self):
        harness = _Harness()

        state = type(
            "State",
            (),
            {
                "current_mcu": "Array_PZT_PZR1.7",
                "label_text": "MCU: Array_PZT_PZR1.7",
                "device_mode": "adc",
                "log_message": None,
            },
        )()
        harness._apply_mcu_state(state)

        self.assertFalse(harness._array_pzt_pzr1_defaults_applied)


if __name__ == "__main__":
    unittest.main()
