import unittest

from config.adc_config_state import ADCConfigurationState, build_default_adc_config_state


class ADCConfigStateTests(unittest.TestCase):
    def test_default_state_matches_expected_defaults(self):
        state = build_default_adc_config_state()

        self.assertIsInstance(state, ADCConfigurationState)
        self.assertEqual(state.channels, [])
        self.assertEqual(state.channel_selection_source, "none")
        self.assertEqual(state.selected_array_sensors, [])
        self.assertEqual(state.array_operation_mode, "PZT")
        self.assertEqual(state.repeat, 1)
        self.assertEqual(state.reference, "vdd")

    def test_mapping_compatibility_helpers_work_for_known_fields(self):
        state = build_default_adc_config_state()

        state["channels"] = [0, 1, 2]
        state.update({"repeat": 4, "use_ground": True})

        self.assertEqual(state["channels"], [0, 1, 2])
        self.assertEqual(state.get("repeat"), 4)
        self.assertTrue(state.get("use_ground"))
        self.assertEqual(state.get("missing", "fallback"), "fallback")

    def test_unknown_keys_are_rejected(self):
        state = build_default_adc_config_state()

        with self.assertRaises(KeyError):
            _ = state["missing"]
        with self.assertRaises(KeyError):
            state["missing"] = 1


if __name__ == "__main__":
    unittest.main()
