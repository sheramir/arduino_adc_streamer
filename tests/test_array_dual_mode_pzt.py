import unittest

import numpy as np

from config.config_handlers import ConfigurationMixin
from constants.pzt_rs import (
    PZT_RS_RS_OHMS_PER_WIRE_UNIT,
    PZT_RS_RS_UNITS_LABEL,
    get_pzt_rs_ohms_per_wire_unit,
)


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
                "PZT1": {"mux": 1, "channels": [0, 1, 2, 3, 4], "rs_channels": [8, 9]},
                "PZT2": {"mux": 1, "channels": [5, 6, 7, 8, 9], "rs_channels": [10, 11]},
                "PZT3": {"mux": 2, "channels": [0, 1, 2, 3, 4], "rs_channels": [12, 13]},
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

    def test_pzt_rs_mode_uses_sensor_groups_with_five_pzt_and_two_rs_values(self):
        harness = DualModePZTHarness()
        harness.current_mcu = "Array_PZT_PZR1.7"
        harness.array_mode_combo = DummyCombo("PZT_RS")

        self.assertTrue(harness.is_array_pzt_rs_mode())
        self.assertEqual(harness.get_supported_array_operation_modes(), ("PZT", "PZR", "PZT_RS"))
        self.assertEqual(harness.get_effective_channel_multiplier(), 1)
        self.assertEqual(harness.get_channels_for_arduino_command(), harness.config["channels"])
        self.assertEqual(harness.get_pzt_muxes_for_arduino_command(), [1, 1, 2])
        self.assertEqual(harness.get_rs_mux_channels_for_arduino_command(), [8, 9, 10, 11, 12, 13])
        self.assertEqual(harness.get_effective_samples_per_sweep(), 21)

        pzt_specs = harness.get_display_channel_specs()
        rs_specs = harness.get_rosette_display_channel_specs()

        self.assertEqual(pzt_specs[0]["sample_indices"], [0])
        self.assertEqual(pzt_specs[1]["sample_indices"], [1])
        self.assertEqual(pzt_specs[5]["sample_indices"], [7])
        self.assertEqual(rs_specs[0]["sample_indices"], [5])
        self.assertEqual(rs_specs[1]["sample_indices"], [6])
        self.assertEqual(rs_specs[-1]["sample_indices"], [20])
        self.assertTrue(all(spec["key"][0] == "rs" for spec in rs_specs))

    def test_pzt_rs_routing_summary_reports_mux_adc_and_rs_channels(self):
        harness = DualModePZTHarness()
        harness.current_mcu = "Array_PZT_PZR1.7"
        harness.array_mode_combo = DummyCombo("PZT_RS")
        harness.config["selected_array_sensors"] = ["PZT1", "PZT3"]

        self.assertEqual(
            harness.get_pzt_rs_sensor_routing_summary(),
            "PZT1:M1 ADC[0,1,2,3,4] RS[8,9] | PZT3:M2 ADC[0,1,2,3,4] RS[12,13]",
        )

    def test_pzt_rs_allows_duplicate_rs_channel_pair_for_one_sensor(self):
        harness = DualModePZTHarness()
        harness.current_mcu = "Array_PZT_PZR1.7"
        harness.array_mode_combo = DummyCombo("PZT_RS")
        harness.config["selected_array_sensors"] = ["PZT1"]
        harness.get_active_sensor_configuration = lambda: {
            "mux_mapping": {
                "PZT1": {"mux": 1, "channels": [0, 1, 2, 3, 4], "rs_channels": [14, 14]},
            }
        }

        self.assertEqual(harness.get_rs_mux_channels_for_arduino_command(), [14, 14])
        self.assertEqual(
            harness.get_pzt_rs_sensor_routing_summary(),
            "PZT1:M1 ADC[0,1,2,3,4] RS[14,14]",
        )

    def test_pcb17_five_sensor_layout_uses_seven_values_per_sensor(self):
        harness = DualModePZTHarness()
        harness.current_mcu = "Array_PZT_PZR1.7"
        harness.array_mode_combo = DummyCombo("PZT_RS")
        harness.config["selected_array_sensors"] = ["PZT1", "PZT3", "PZT6", "PZT5", "PZT7"]
        harness.config["channels"] = [
            0, 1, 2, 3, 4,
            5, 6, 7, 8, 9,
            10, 11, 12, 13, 14,
            0, 1, 2, 3, 4,
            5, 6, 7, 8, 9,
        ]

        def pcb17_config():
            return {
                "mux_mapping": {
                    "PZT1": {"mux": 1, "channels": [0, 1, 2, 3, 4], "rs_channels": [9, 8]},
                    "PZT3": {"mux": 1, "channels": [5, 6, 7, 8, 9], "rs_channels": [7, 6]},
                    "PZT6": {"mux": 1, "channels": [10, 11, 12, 13, 14], "rs_channels": [2, 3]},
                    "PZT5": {"mux": 2, "channels": [0, 1, 2, 3, 4], "rs_channels": [5, 4]},
                    "PZT7": {"mux": 2, "channels": [5, 6, 7, 8, 9], "rs_channels": [1, 0]},
                }
            }

        harness.get_active_sensor_configuration = pcb17_config

        self.assertEqual(harness.get_channels_for_arduino_command(), harness.config["channels"])
        self.assertEqual(harness.get_effective_samples_per_sweep(), 35)

        rs_channels = harness.get_rs_mux_channels_for_arduino_command()
        self.assertEqual(harness.get_pzt_muxes_for_arduino_command(), [1, 1, 1, 2, 2])
        self.assertEqual(len(rs_channels), 10)
        self.assertEqual(rs_channels, [9, 8, 7, 6, 2, 3, 5, 4, 1, 0])

    def test_pcb17_two_sensor_subset_rs_indices_are_independent(self):
        """PZT1+PZT3 subset: RS sample indices must be independently computed per sensor.

        Regression test for multi-sensor RS display showing "almost constant signals":
        if Python reads RS data from the same column for both sensors, both displays
        would track the same physical sensor and the other would appear flat.
        """
        harness = DualModePZTHarness()
        harness.current_mcu = "Array_PZT_PZR1.7"
        harness.array_mode_combo = DummyCombo("PZT_RS")
        harness.config["selected_array_sensors"] = ["PZT1", "PZT3"]
        harness.config["channels"] = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]

        def pcb17_config():
            return {
                "mux_mapping": {
                    "PZT1": {"mux": 1, "channels": [0, 1, 2, 3, 4], "rs_channels": [9, 8]},
                    "PZT3": {"mux": 1, "channels": [5, 6, 7, 8, 9], "rs_channels": [7, 6]},
                }
            }

        harness.get_active_sensor_configuration = pcb17_config

        self.assertEqual(harness.get_effective_samples_per_sweep(), 14)
        self.assertEqual(harness.get_channels_for_arduino_command(), [0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
        self.assertEqual(harness.get_pzt_muxes_for_arduino_command(), [1, 1])
        self.assertEqual(harness.get_rs_mux_channels_for_arduino_command(), [9, 8, 7, 6])

        rs_specs = harness.get_rosette_display_channel_specs()

        self.assertEqual(len(rs_specs), 4)

        pzt1_rs1 = next(s for s in rs_specs if s["key"] == ("rs", "PZT1", 1, 9))
        pzt1_rs2 = next(s for s in rs_specs if s["key"] == ("rs", "PZT1", 2, 8))
        pzt3_rs1 = next(s for s in rs_specs if s["key"] == ("rs", "PZT3", 1, 7))
        pzt3_rs2 = next(s for s in rs_specs if s["key"] == ("rs", "PZT3", 2, 6))

        # PZT1 RS values are at buffer columns 5 and 6 (sensor_index=0, base=0, +5/+6)
        self.assertEqual(pzt1_rs1["sample_indices"], [5])
        self.assertEqual(pzt1_rs2["sample_indices"], [6])

        # PZT3 RS values are at buffer columns 12 and 13 (sensor_index=1, base=7, +5/+6)
        self.assertEqual(pzt3_rs1["sample_indices"], [12])
        self.assertEqual(pzt3_rs2["sample_indices"], [13])

        # All indices must be within the 14-column buffer (2 sensors × 7 values)
        all_indices = [idx for s in rs_specs for idx in s["sample_indices"]]
        self.assertTrue(all(0 <= i < 14 for i in all_indices), f"Out-of-range indices: {all_indices}")

        # PZT3 columns must be distinct from PZT1 columns
        pzt1_cols = set(pzt1_rs1["sample_indices"] + pzt1_rs2["sample_indices"])
        pzt3_cols = set(pzt3_rs1["sample_indices"] + pzt3_rs2["sample_indices"])
        self.assertEqual(pzt1_cols, {5, 6})
        self.assertEqual(pzt3_cols, {12, 13})
        self.assertFalse(pzt1_cols & pzt3_cols, "PZT1 and PZT3 RS columns must not overlap")

    def test_pzt_rs_rosette_scaling_only_touches_rs_columns(self):
        harness = DualModePZTHarness()
        harness.current_mcu = "Array_PZT_PZR1.7"
        harness.array_mode_combo = DummyCombo("PZT_RS")
        harness.config["selected_array_sensors"] = ["PZT1", "PZT3"]
        harness.config["channels"] = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]

        def pcb17_config():
            return {
                "mux_mapping": {
                    "PZT1": {"mux": 1, "channels": [0, 1, 2, 3, 4], "rs_channels": [9, 8]},
                    "PZT3": {"mux": 1, "channels": [5, 6, 7, 8, 9], "rs_channels": [7, 6]},
                }
            }

        harness.get_active_sensor_configuration = pcb17_config

        sample_matrix = np.asarray(
            [
                [10, 11, 12, 13, 14, 12345, 23456, 20, 21, 22, 23, 24, 34567, 45678],
                [30, 31, 32, 33, 34, 22345, 33456, 40, 41, 42, 43, 44, 44567, 55678],
            ],
            dtype=np.float32,
        )

        harness.scale_pzt_rs_rosette_samples_inplace(sample_matrix)

        np.testing.assert_allclose(sample_matrix[:, :5], [[10, 11, 12, 13, 14], [30, 31, 32, 33, 34]])
        np.testing.assert_allclose(sample_matrix[:, 7:12], [[20, 21, 22, 23, 24], [40, 41, 42, 43, 44]])
        np.testing.assert_allclose(sample_matrix[:, 5], np.asarray([12345, 22345], dtype=np.float32) * PZT_RS_RS_OHMS_PER_WIRE_UNIT)
        np.testing.assert_allclose(sample_matrix[:, 6], np.asarray([23456, 33456], dtype=np.float32) * PZT_RS_RS_OHMS_PER_WIRE_UNIT)
        np.testing.assert_allclose(sample_matrix[:, 12], np.asarray([34567, 44567], dtype=np.float32) * PZT_RS_RS_OHMS_PER_WIRE_UNIT)
        np.testing.assert_allclose(sample_matrix[:, 13], np.asarray([45678, 55678], dtype=np.float32) * PZT_RS_RS_OHMS_PER_WIRE_UNIT)

    def test_pzt_rs_rosette_scaling_handles_one_sweep_vector(self):
        harness = DualModePZTHarness()
        harness.current_mcu = "Array_PZT_PZR1.7"
        harness.array_mode_combo = DummyCombo("PZT_RS")
        harness.config["selected_array_sensors"] = ["PZT1"]
        harness.config["channels"] = [0, 1, 2, 3, 4]
        harness.get_active_sensor_configuration = lambda: {
            "mux_mapping": {
                "PZT1": {"mux": 1, "channels": [0, 1, 2, 3, 4], "rs_channels": [14, 14]},
            }
        }

        sweep = np.asarray([1, 2, 3, 4, 5, 12345, 23456], dtype=np.float32)

        harness.scale_pzt_rs_rosette_samples_inplace(sweep)

        np.testing.assert_allclose(
            sweep,
            [1, 2, 3, 4, 5, 12345 * PZT_RS_RS_OHMS_PER_WIRE_UNIT, 23456 * PZT_RS_RS_OHMS_PER_WIRE_UNIT],
        )

    def test_pzt_rs_archive_unit_helper_supports_current_and_legacy_units(self):
        self.assertEqual(get_pzt_rs_ohms_per_wire_unit(), PZT_RS_RS_OHMS_PER_WIRE_UNIT)
        self.assertEqual(get_pzt_rs_ohms_per_wire_unit(PZT_RS_RS_UNITS_LABEL), PZT_RS_RS_OHMS_PER_WIRE_UNIT)
        self.assertEqual(get_pzt_rs_ohms_per_wire_unit("deciohm"), 0.1)
        self.assertEqual(get_pzt_rs_ohms_per_wire_unit("centiohm"), 0.01)
        self.assertIsNone(get_pzt_rs_ohms_per_wire_unit("unknown"))

    def test_array_pzt_pzr1_selects_pzt_rs_when_requested(self):
        harness = DualModePZTHarness()
        harness.array_mode_combo = DummyCombo("PZT_RS")

        self.assertEqual(harness.get_selected_array_operation_mode(), "PZT_RS")
        self.assertTrue(harness.is_array_pzt_rs_mode())
        self.assertEqual(harness.get_supported_array_operation_modes(), ("PZT", "PZR", "PZT_RS"))


if __name__ == "__main__":
    unittest.main()
