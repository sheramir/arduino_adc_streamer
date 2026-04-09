import unittest

from config.config_handlers import ConfigurationMixin


class DummyCombo:
    def __init__(self, text):
        self._text = text

    def currentText(self):
        return self._text


class DualModePZTHarness(ConfigurationMixin):
    def __init__(self):
        self.current_mcu = "Array_PZT_PZR1"
        self.device_mode = "adc"
        self.array_mode_combo = DummyCombo("PZT")
        self.config = {
            "channels": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0, 1, 2, 3, 4],
            "channel_selection_source": "array",
            "selected_array_sensors": ["PZT1", "PZT2", "PZT3"],
            "repeat": 1,
        }

    def get_active_sensor_configuration(self):
        return {
            "mux_mapping": {
                "PZT1": {"mux": 1, "channels": [0, 1, 2, 3, 4]},
                "PZT2": {"mux": 1, "channels": [5, 6, 7, 8, 9]},
                "PZT3": {"mux": 2, "channels": [0, 1, 2, 3, 4]},
            }
        }

    def get_active_channel_sensor_map(self):
        return ["T", "R", "C", "L", "B"]


class ArrayDualModePZTTests(unittest.TestCase):
    def test_dual_mode_pzt_is_treated_as_paired_mux_mode(self):
        harness = DualModePZTHarness()

        self.assertTrue(harness.is_array_pzt1_mode())
        self.assertEqual(harness.get_channels_for_arduino_command(), list(range(10)))
        self.assertEqual(harness.get_effective_samples_per_sweep(), 20)

    def test_dual_mode_pzt_display_specs_map_within_unique_channel_stream(self):
        harness = DualModePZTHarness()

        specs = harness.get_display_channel_specs()

        self.assertEqual(len(specs), 15)
        sensor3_specs = [spec for spec in specs if spec["label"].startswith("PZT3_")]
        self.assertEqual(sensor3_specs[0]["sample_indices"], [1])
        self.assertEqual(sensor3_specs[-1]["sample_indices"], [9])
        all_indices = [index for spec in specs for index in spec["sample_indices"]]
        self.assertTrue(all(0 <= index < 20 for index in all_indices))


if __name__ == "__main__":
    unittest.main()
