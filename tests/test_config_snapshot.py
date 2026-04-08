import unittest

from config.config_snapshot import (
    VREF_LABEL_TO_COMMAND,
    build_adc_configuration_snapshot,
    normalize_gain,
    normalize_reference,
)


class ConfigSnapshotTests(unittest.TestCase):
    def test_normalize_reference_uses_vref_map_when_control_is_active(self):
        self.assertEqual(
            normalize_reference(
                current_reference="vdd",
                vref_label="1.2V (Internal)",
                use_vref_control=True,
            ),
            "1.2",
        )
        self.assertEqual(VREF_LABEL_TO_COMMAND["3.3V (VDD)"], "vdd")

    def test_normalize_gain_strips_multiplication_symbol(self):
        self.assertEqual(normalize_gain(current_gain=1, gain_label="8×"), 8)
        self.assertEqual(normalize_gain(current_gain=2, gain_label=None), 2)

    def test_build_snapshot_applies_widget_values_and_fallbacks(self):
        snapshot = build_adc_configuration_snapshot(
            current_reference="vdd",
            vref_label="1.2V (Internal)",
            use_vref_control=True,
            current_osr=2,
            osr_label="8",
            current_gain=1,
            gain_label="4×",
            current_repeat=1,
            repeat_value=5,
            current_use_ground=False,
            use_ground_checked=True,
            current_ground_pin=-1,
            ground_pin_value=3,
            current_conv_speed="med",
            conv_speed_label="high",
            current_samp_speed="med",
            samp_speed_label="low",
            current_sample_rate=0,
            sample_rate_value=1234,
            current_array_operation_mode="PZT",
            array_operation_mode="PZR",
            current_rb_ohms=1000.0,
            rb_value=1100.0,
            current_rk_ohms=2000.0,
            rk_value=2200.0,
            cf_farads=1e-9,
            current_rxmax_ohms=5000.0,
            rxmax_value=5500.0,
        )

        self.assertEqual(snapshot.reference, "1.2")
        self.assertEqual(snapshot.osr, 8)
        self.assertEqual(snapshot.gain, 4)
        self.assertEqual(snapshot.repeat, 5)
        self.assertTrue(snapshot.use_ground)
        self.assertEqual(snapshot.ground_pin, 3)
        self.assertEqual(snapshot.array_operation_mode, "PZR")
        self.assertEqual(snapshot.as_config_updates()["rxmax_ohms"], 5500.0)


if __name__ == "__main__":
    unittest.main()
