"""Tests for the Signal Integration tab's voltage HPF display helpers."""

import os
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from constants.plotting import IADC_RESOLUTION_BITS
from constants.signal_integration import (
    DEFAULT_HPF_CUTOFF_HZ,
    DEFAULT_INTEGRATION_WINDOW_SAMPLES,
    SIGNAL_INTEGRATION_DISABLED_HPF_CUTOFF_HZ,
)
from constants.shear import SHEAR_SENSOR_POSITIONS
from data_processing.adc_filter_engine import ADCFilterEngine
from gui.signal_integration_panel import SignalIntegrationPanelMixin


class DummySpinBox:
    """Small value-only stand-in for Qt spin boxes."""

    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = value


class DummyCheckBox:
    """Small checked-state stand-in for Qt check boxes."""

    def __init__(self, checked):
        self._checked = checked

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        self._checked = bool(checked)


class SignalIntegrationPanelHarness(SignalIntegrationPanelMixin):
    """Minimal harness for exercising non-Qt plotting helper methods."""

    VREF_VOLTS = 3.3

    def __init__(self):
        self.signal_integration_hpf_cutoff_hz = SIGNAL_INTEGRATION_DISABLED_HPF_CUTOFF_HZ
        self.signal_integration_window_samples = DEFAULT_INTEGRATION_WINDOW_SAMPLES
        self.signal_integration_display_window_sec = 1.0
        self._signal_integration_filter_engine = ADCFilterEngine()
        self._signal_integration_filter_warning = ""
        self._shear_settings_loading = False
        self._shear_autosave_enabled = False
        self._latest_shear_result = None
        self.log_messages = []
        self.active_sensor_reverse_polarity = False

    def get_vref_voltage(self):
        return self.VREF_VOLTS

    def is_active_sensor_reverse_polarity(self):
        return self.active_sensor_reverse_polarity

    def log_status(self, message):
        self.log_messages.append(message)

    def _get_last_shear_settings_path(self):
        return self._last_shear_settings_path


class SignalIntegrationPanelTests(unittest.TestCase):
    """Verify display-only voltage conversion, HPF, and integration."""

    SAMPLE_RATE_HZ = 1000.0
    SAMPLE_COUNT = 500
    INTEGRATION_WINDOW_SAMPLES = 3

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _install_shear_setting_widgets(self, harness):
        harness.signal_integration_hpf_spin = DummySpinBox(12.5)
        harness.signal_integration_window_spin = DummySpinBox(44)
        harness.signal_integration_display_window_spin = DummySpinBox(2.5)
        harness.shear_noise_threshold_spin = DummySpinBox(0.75)
        harness.shear_gain_spins = {
            position: DummySpinBox(index + 1.25)
            for index, position in enumerate(SHEAR_SENSOR_POSITIONS)
        }
        harness.shear_arrow_gain_spin = DummySpinBox(9.5)
        harness.shear_arrow_threshold_spin = DummySpinBox(0.33)
        harness.shear_arrow_max_length_spin = DummySpinBox(1.4)
        harness.shear_arrow_base_width_spin = DummySpinBox(0.6)
        harness.shear_arrow_width_scales_check = DummyCheckBox(False)
        harness.pressure_sensor_spacing_spin = DummySpinBox(1.75)
        harness.pressure_circle_diameter_spin = DummySpinBox(5.5)
        harness.pressure_grid_resolution_spin = DummySpinBox(25)
        harness.pressure_grid_margin_spin = DummySpinBox(3)
        harness.pressure_idw_power_spin = DummySpinBox(2.5)
        harness.pressure_decay_rate_spin = DummySpinBox(0.9)
        harness.pressure_decay_ref_distance_spin = DummySpinBox(1.6)
        harness.pressure_kernel_radius_spin = DummySpinBox(0.8)

    def test_counts_to_voltage_ignores_time_series_units(self):
        harness = SignalIntegrationPanelHarness()
        max_adc_value = (2 ** IADC_RESOLUTION_BITS) - 1
        counts = np.asarray([0.0, max_adc_value / 2.0, float(max_adc_value)], dtype=np.float64)

        voltage_data = harness._convert_signal_integration_counts_to_voltage(counts)
        expected = np.asarray([0.0, harness.VREF_VOLTS / 2.0, harness.VREF_VOLTS], dtype=np.float64)

        np.testing.assert_allclose(voltage_data, expected, rtol=1e-6, atol=1e-6)

    def test_hpf_removes_constant_dc_bias_without_integration(self):
        harness = SignalIntegrationPanelHarness()
        harness.signal_integration_hpf_cutoff_hz = DEFAULT_HPF_CUTOFF_HZ
        sample_times = np.arange(self.SAMPLE_COUNT, dtype=np.float64) / self.SAMPLE_RATE_HZ
        biased_signal = np.full(self.SAMPLE_COUNT, harness.VREF_VOLTS / 2.0, dtype=np.float64)

        filtered = harness._remove_signal_integration_dc_bias(biased_signal, sample_times)

        self.assertEqual(filtered.shape, biased_signal.shape)
        self.assertLess(float(np.max(np.abs(filtered))), DEFAULT_HPF_CUTOFF_HZ / self.SAMPLE_RATE_HZ)

    def test_integration_window_produces_moving_sum(self):
        harness = SignalIntegrationPanelHarness()
        harness.signal_integration_window_samples = self.INTEGRATION_WINDOW_SAMPLES
        filtered_voltage = np.asarray([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float64)

        integrated = harness._integrate_signal_integration_voltage_samples(filtered_voltage)

        np.testing.assert_allclose(
            integrated,
            np.asarray([1.0, 3.0, 6.0, 9.0, 12.0], dtype=np.float64),
        )

    def test_prepare_integrated_series_applies_voltage_hpf_and_integration(self):
        harness = SignalIntegrationPanelHarness()
        harness.signal_integration_window_samples = 2
        max_adc_value = (2 ** IADC_RESOLUTION_BITS) - 1
        data = np.asarray(
            [[0.0], [max_adc_value / 4.0], [max_adc_value / 2.0]],
            dtype=np.float32,
        )
        timestamps = np.asarray([0.0, 0.001, 0.002], dtype=np.float64)

        integrated_data, integrated_times, latest_value = harness._prepare_signal_integration_integrated_series(
            {"sample_indices": [0]},
            data,
            timestamps,
            avg_sample_time_sec=0.001,
            max_samples_per_series=self.SAMPLE_COUNT,
        )

        expected_voltage = np.asarray([0.0, harness.VREF_VOLTS / 4.0, harness.VREF_VOLTS / 2.0])
        expected_integrated = np.asarray([
            expected_voltage[0],
            expected_voltage[0] + expected_voltage[1],
            expected_voltage[1] + expected_voltage[2],
        ])
        np.testing.assert_allclose(integrated_data, expected_integrated, rtol=1e-6, atol=1e-6)
        np.testing.assert_allclose(integrated_times, timestamps)
        self.assertAlmostEqual(latest_value, expected_integrated[-1])

    def test_prepare_integrated_series_applies_reverse_polarity_after_integration(self):
        harness = SignalIntegrationPanelHarness()
        harness.active_sensor_reverse_polarity = True
        harness.signal_integration_window_samples = 2
        max_adc_value = (2 ** IADC_RESOLUTION_BITS) - 1
        data = np.asarray(
            [[0.0], [max_adc_value / 4.0], [max_adc_value / 2.0]],
            dtype=np.float32,
        )
        timestamps = np.asarray([0.0, 0.001, 0.002], dtype=np.float64)

        integrated_data, _integrated_times, latest_value = harness._prepare_signal_integration_integrated_series(
            {"sample_indices": [0]},
            data,
            timestamps,
            avg_sample_time_sec=0.001,
            max_samples_per_series=self.SAMPLE_COUNT,
        )

        expected_voltage = np.asarray([0.0, harness.VREF_VOLTS / 4.0, harness.VREF_VOLTS / 2.0])
        expected_integrated = -np.asarray([
            expected_voltage[0],
            expected_voltage[0] + expected_voltage[1],
            expected_voltage[1] + expected_voltage[2],
        ])
        np.testing.assert_allclose(integrated_data, expected_integrated, rtol=1e-6, atol=1e-6)
        self.assertAlmostEqual(latest_value, expected_integrated[-1])

    def test_prepare_integrated_series_uses_history_before_visible_start(self):
        harness = SignalIntegrationPanelHarness()
        harness.signal_integration_window_samples = self.INTEGRATION_WINDOW_SAMPLES
        max_adc_value = (2 ** IADC_RESOLUTION_BITS) - 1
        one_volt_count = max_adc_value / harness.VREF_VOLTS
        data = np.full((5, 1), one_volt_count, dtype=np.float32)
        timestamps = np.arange(5, dtype=np.float64) / self.SAMPLE_RATE_HZ

        integrated_data, integrated_times, latest_value = harness._prepare_signal_integration_integrated_series(
            {"sample_indices": [0]},
            data,
            timestamps,
            avg_sample_time_sec=1.0 / self.SAMPLE_RATE_HZ,
            max_samples_per_series=self.SAMPLE_COUNT,
            visible_start_time_sec=timestamps[2],
        )

        np.testing.assert_allclose(
            integrated_data,
            np.full(3, float(self.INTEGRATION_WINDOW_SAMPLES), dtype=np.float64),
            rtol=1e-6,
            atol=1e-6,
        )
        np.testing.assert_allclose(integrated_times, timestamps[2:])
        self.assertAlmostEqual(latest_value, float(self.INTEGRATION_WINDOW_SAMPLES), places=6)

    def test_shear_calibration_applies_threshold_then_gain(self):
        harness = SignalIntegrationPanelHarness()
        harness.shear_noise_threshold_spin = DummySpinBox(0.5)
        harness.shear_gain_spins = {
            position: DummySpinBox(2.0 if position == "R" else 1.0)
            for position in SHEAR_SENSOR_POSITIONS
        }
        latest_values = {"C": 0.1, "L": -0.6, "R": 0.7, "T": 0.0, "B": 0.8}

        calibrated = harness._calibrate_signal_integration_values_for_shear(latest_values)

        self.assertEqual(calibrated["C"], 0.0)
        self.assertEqual(calibrated["L"], -0.6)
        self.assertEqual(calibrated["R"], 1.4)
        self.assertEqual(calibrated["T"], 0.0)
        self.assertEqual(calibrated["B"], 0.8)

    def test_shear_settings_save_and_load_round_trip(self):
        harness = SignalIntegrationPanelHarness()
        self._install_shear_setting_widgets(harness)

        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "shear_settings.json"

            harness.save_shear_settings_to_path(settings_path, log_message=True)

            payload = json.loads(settings_path.read_text(encoding="utf-8"))
            settings = payload["shear_settings"]
            self.assertEqual(payload["version"], 1)
            self.assertEqual(settings["signal_integration"]["hpf_cutoff_hz"], 12.5)
            self.assertEqual(settings["signal_integration"]["integration_window_samples"], 44)
            self.assertEqual(settings["processing"]["noise_threshold"], 0.75)
            self.assertEqual(settings["processing"]["sensor_gains"]["C"], 1.25)
            self.assertFalse(settings["visualization"]["arrow_width_scales"])
            self.assertEqual(settings["pressure_map"]["grid_resolution"], 25)
            self.assertEqual(settings["pressure_map"]["grid_margin"], 3)
            self.assertEqual(settings["pressure_map"]["idw_power"], 2.5)

            harness.signal_integration_hpf_spin.setValue(1.0)
            harness.signal_integration_window_spin.setValue(2)
            harness.shear_noise_threshold_spin.setValue(3.0)
            harness.shear_gain_spins["C"].setValue(4.0)
            harness.shear_arrow_width_scales_check.setChecked(True)
            harness.pressure_grid_resolution_spin.setValue(21)
            harness.pressure_grid_margin_spin.setValue(1)
            harness.pressure_idw_power_spin.setValue(1.0)

            applied = harness.load_shear_settings_from_path(settings_path, log_message=True)

            self.assertTrue(applied)
            self.assertEqual(harness.signal_integration_hpf_spin.value(), 12.5)
            self.assertEqual(harness.signal_integration_window_spin.value(), 44)
            self.assertEqual(harness.shear_noise_threshold_spin.value(), 0.75)
            self.assertEqual(harness.shear_gain_spins["C"].value(), 1.25)
            self.assertFalse(harness.shear_arrow_width_scales_check.isChecked())
            self.assertEqual(harness.pressure_grid_resolution_spin.value(), 25)
            self.assertEqual(harness.pressure_grid_margin_spin.value(), 3)
            self.assertEqual(harness.pressure_idw_power_spin.value(), 2.5)

    def test_pressure_map_tab_controls_expose_tooltips(self):
        harness = SignalIntegrationPanelHarness()

        tab = harness.create_signal_integration_tab()
        try:
            expected_tooltips = {
                "signal_integration_hpf_spin": "high-pass cutoff",
                "signal_integration_window_spin": "recent high-pass-filtered samples",
                "signal_integration_display_window_spin": "recent history",
                "signal_integration_reset_btn": "refresh the integrated preview",
                "shear_noise_threshold_spin": "zeros each integrated channel",
                "shear_arrow_gain_spin": "displayed arrow length",
                "shear_arrow_threshold_spin": "hides only the displayed arrow",
                "shear_arrow_max_length_spin": "circle radius",
                "shear_arrow_base_width_spin": "base shaft width",
                "shear_arrow_width_scales_check": "shaft becomes wider",
                "shear_save_settings_btn": "save the current pressure map tab settings",
                "shear_load_settings_btn": "load pressure map tab settings",
                "pressure_sensor_spacing_spin": "sensor spacing",
                "pressure_circle_diameter_spin": "pressure footprint",
                "pressure_grid_resolution_spin": "grid cells across the pressure-circle diameter",
                "pressure_grid_margin_spin": "extra grid cells",
                "pressure_idw_power_spin": "inverse-distance weighting",
                "pressure_decay_rate_spin": "quadrant peak height",
                "pressure_decay_ref_distance_spin": "reference distance",
                "pressure_kernel_radius_spin": "additive pressure kernel",
            }

            for widget_name, expected_text in expected_tooltips.items():
                widget = getattr(harness, widget_name)
                self.assertIn(expected_text, widget.toolTip().lower(), msg=widget_name)

            for position, gain_spin in harness.shear_gain_spins.items():
                self.assertIn(
                    f"calibration multiplier for the {position.lower()} integrated channel",
                    gain_spin.toolTip().lower(),
                    msg=position,
                )
        finally:
            tab.close()


if __name__ == "__main__":
    unittest.main()
