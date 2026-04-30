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
from constants.pressure_map import (
    DEFAULT_PRESSURE_SHOW_MARKER,
    DEFAULT_HPF_CUTOFF_HZ,
    DEFAULT_INTEGRATION_WINDOW_SAMPLES,
    SIGNAL_INTEGRATION_DISABLED_HPF_CUTOFF_HZ,
)
from constants.shear import SHEAR_SENSOR_POSITIONS
from data_processing.adc_filter_engine import ADCFilterEngine
from data_processing.normal_force_calculator import NormalForceCalculator
from data_processing.pressure_map_generator import DEFAULT_PRESSURE_SHOW_NEGATIVE, PressureMapGenerator
from data_processing.shear_detector import ShearDetector
from gui.pressure_map_widget import PressureMapWidget
from gui.signal_integration_panel import PressureMapPanelMixin


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


class SignalIntegrationPanelHarness(PressureMapPanelMixin):
    """Minimal harness for exercising non-Qt plotting helper methods."""

    VREF_VOLTS = 3.3

    def __init__(self):
        self.config = {
            "channel_selection_source": "manual",
            "selected_array_sensors": [],
        }
        self.signal_integration_hpf_cutoff_hz = SIGNAL_INTEGRATION_DISABLED_HPF_CUTOFF_HZ
        self.signal_integration_window_samples = DEFAULT_INTEGRATION_WINDOW_SAMPLES
        self.signal_integration_display_window_sec = 1.0
        self._signal_integration_filter_engine = ADCFilterEngine()
        self._signal_integration_filter_warning = ""
        self._shear_settings_loading = False
        self._shear_autosave_enabled = False
        self._pressure_package_sensor_gains = {}
        self._latest_shear_result = None
        self.log_messages = []
        self.active_sensor_reverse_polarity = False
        self.sensor_package_groups = []
        self.active_sensor_configuration = {"array_layout": {"cells": []}}

    def get_vref_voltage(self):
        return self.VREF_VOLTS

    def is_active_sensor_reverse_polarity(self):
        return self.active_sensor_reverse_polarity

    def log_status(self, message):
        self.log_messages.append(message)

    def _get_last_shear_settings_path(self):
        return self._last_shear_settings_path

    def is_array_sensor_selection_mode(self):
        return str(self.config.get("channel_selection_source", "")).lower() == "array"

    def get_sensor_package_groups(self, required_channels, channels=None):
        return list(self.sensor_package_groups)

    def get_active_sensor_configuration(self):
        return dict(self.active_sensor_configuration)


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
        harness._pressure_package_sensor_gains = {
            "PZT3": {position: float(index + 1.25) for index, position in enumerate(SHEAR_SENSOR_POSITIONS)}
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
        harness.pressure_decay_rate_spin = DummySpinBox(0.9)
        harness.pressure_decay_ref_distance_spin = DummySpinBox(2.25)
        harness.pressure_show_negative_check = DummyCheckBox(True)
        harness.pressure_show_marker_check = DummyCheckBox(False)

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
        harness._pressure_package_sensor_gains = {
            "PZT3": {
                position: (2.0 if position == "R" else 1.0)
                for position in SHEAR_SENSOR_POSITIONS
            }
        }
        latest_values = {"C": 0.1, "L": -0.6, "R": 0.7, "T": 0.0, "B": 0.8}

        calibrated = harness._calibrate_signal_integration_values_for_shear(latest_values, "PZT3")

        self.assertEqual(calibrated["C"], 0.0)
        self.assertEqual(calibrated["L"], -0.6)
        self.assertEqual(calibrated["R"], 1.4)
        self.assertEqual(calibrated["T"], 0.0)
        self.assertEqual(calibrated["B"], 0.8)

    def test_package_specific_gains_override_default_processing_gains(self):
        harness = SignalIntegrationPanelHarness()
        harness.shear_noise_threshold_spin = DummySpinBox(0.0)
        harness._pressure_package_sensor_gains = {
            "PZT3": {
                "R": 2.0,
                "L": 0.5,
            }
        }
        latest_values = {"C": 0.0, "L": -1.0, "R": 1.0, "T": 0.0, "B": 0.0}

        calibrated_pzt3 = harness._calibrate_signal_integration_values_for_shear(latest_values, "pzt3")
        calibrated_other = harness._calibrate_signal_integration_values_for_shear(latest_values, "PZT5")

        self.assertEqual(calibrated_pzt3["R"], 2.0)
        self.assertEqual(calibrated_pzt3["L"], -0.5)
        self.assertEqual(calibrated_other["R"], 1.0)
        self.assertEqual(calibrated_other["L"], -1.0)

    def test_array_package_plumbing_tracks_values_and_grid_positions(self):
        harness = SignalIntegrationPanelHarness()
        harness.config = {
            "channel_selection_source": "array",
            "selected_array_sensors": ["PZT3", "PZT5", "PZT7"],
        }
        harness.sensor_package_groups = [
            {"sensor_id": "PZT3", "mux": 1, "channels": [0, 1, 2, 3, 4]},
            {"sensor_id": "PZT5", "mux": 1, "channels": [5, 6, 7, 8, 9]},
            {"sensor_id": "PZT7", "mux": 2, "channels": [0, 1, 2, 3, 4]},
        ]
        harness.active_sensor_configuration = {
            "array_layout": {
                "cells": [
                    [None, "PZT3", None],
                    ["PZT5", None, None],
                    [None, None, "PZT7"],
                ]
            }
        }
        values_by_package = {}

        for index, position in enumerate(SHEAR_SENSOR_POSITIONS):
            spec = {"key": ("sensor", "PZT3", position, index), "label": f"PZT3_{position}"}
            harness._record_signal_integration_package_value(
                values_by_package,
                spec,
                index,
                position,
                float(index + 1),
            )
        harness._record_signal_integration_package_value(
            values_by_package,
            {"key": ("sensor", "PZT5", "C", 5), "label": "PZT5_C"},
            5,
            "C",
            10.0,
        )

        first_complete = harness._first_complete_signal_integration_package_values(values_by_package)
        layout = harness._get_signal_integration_package_layout()

        self.assertEqual(set(values_by_package), {"PZT3", "PZT5"})
        self.assertEqual(first_complete, values_by_package["PZT3"])
        self.assertEqual(layout[0]["sensor_id"], "PZT3")
        self.assertEqual(layout[0]["grid_position"], (0, 1))
        self.assertEqual(layout[1]["sensor_id"], "PZT5")
        self.assertEqual(layout[1]["grid_position"], (1, 0))
        self.assertEqual(layout[2]["sensor_id"], "PZT7")
        self.assertEqual(layout[2]["grid_position"], (2, 2))

    def test_array_package_displays_are_built_per_complete_sensor_package(self):
        harness = SignalIntegrationPanelHarness()
        harness.pressure_map_widget = PressureMapWidget()
        self.addCleanup(harness.pressure_map_widget.close)
        harness.shear_detector = ShearDetector()
        harness.normal_force_calculator = NormalForceCalculator()
        harness.pressure_map_generator = PressureMapGenerator()
        harness.shear_noise_threshold_spin = DummySpinBox(0.0)
        harness._latest_signal_integration_values_by_package = {
            "PZT3": {"C": 0.0, "L": -1.0, "R": 1.0, "T": 0.0, "B": 0.0},
            "PZT5": {"C": 0.0, "L": 0.0, "R": 0.0, "T": 1.0, "B": -1.0},
        }
        harness._latest_signal_integration_package_layout = [
            {"sensor_id": "PZT3", "grid_position": (0, 1), "color_slot": 0},
            {"sensor_id": "PZT5", "grid_position": (1, 0), "color_slot": 1},
        ]

        packages = harness._build_pressure_map_package_displays()

        self.assertEqual([package.sensor_id for package in packages], ["PZT3", "PZT5"])
        self.assertEqual(packages[0].grid_position, (0, 1))
        self.assertEqual(packages[1].grid_position, (1, 0))
        self.assertNotEqual(packages[0].color, packages[1].color)
        self.assertTrue(packages[0].shear_result.has_shear)

    def test_multi_package_force_mode_enabled_only_for_multiple_array_packages(self):
        harness = SignalIntegrationPanelHarness()
        harness.config = {"channel_selection_source": "array", "selected_array_sensors": ["PZT3", "PZT5"]}

        enabled = harness._is_multi_package_force_mode([
            {"sensor_id": "PZT3"},
            {"sensor_id": "PZT5"},
        ])
        disabled = harness._is_multi_package_force_mode([{"sensor_id": "PZT3"}])

        self.assertTrue(enabled)
        self.assertFalse(disabled)

    def test_compute_package_total_force_series_returns_one_force_trace(self):
        harness = SignalIntegrationPanelHarness()
        harness.shear_detector = ShearDetector()
        harness.normal_force_calculator = NormalForceCalculator()
        harness.shear_noise_threshold_spin = DummySpinBox(0.0)

        times = np.asarray([0.0, 0.01, 0.02], dtype=np.float64)
        position_series = {
            "C": (np.asarray([1.0, 0.8, 0.6], dtype=np.float64), times),
            "L": (np.asarray([-1.0, -0.5, -0.25], dtype=np.float64), times),
            "R": (np.asarray([1.0, 0.5, 0.25], dtype=np.float64), times),
            "T": (np.asarray([0.0, 0.0, 0.0], dtype=np.float64), times),
            "B": (np.asarray([0.0, 0.0, 0.0], dtype=np.float64), times),
        }

        computed_times, total_force = harness._compute_package_total_force_series(position_series)

        self.assertEqual(computed_times.shape, times.shape)
        np.testing.assert_allclose(computed_times, times)
        self.assertEqual(total_force.shape, times.shape)
        self.assertTrue(np.all(total_force >= 0.0))
        self.assertGreater(float(np.max(total_force)), 0.0)

    def test_compute_package_total_force_series_matches_pipeline_total_force(self):
        harness = SignalIntegrationPanelHarness()
        harness.shear_detector = ShearDetector()
        harness.normal_force_calculator = NormalForceCalculator()
        harness.shear_noise_threshold_spin = DummySpinBox(0.0)

        times = np.asarray([0.0, 0.01, 0.02, 0.03], dtype=np.float64)
        position_series = {
            "C": (np.asarray([0.2, 0.1, 0.0, -0.1], dtype=np.float64), times),
            "L": (np.asarray([-1.0, -0.6, -0.4, -0.2], dtype=np.float64), times),
            "R": (np.asarray([1.2, 0.9, 0.5, 0.3], dtype=np.float64), times),
            "T": (np.asarray([0.7, 0.4, 0.1, -0.1], dtype=np.float64), times),
            "B": (np.asarray([-0.5, -0.2, 0.0, 0.2], dtype=np.float64), times),
        }

        _computed_times, total_force = harness._compute_package_total_force_series(position_series)

        expected = np.zeros_like(total_force)
        for idx in range(len(total_force)):
            sample_values = {
                position: float(position_series[position][0][idx])
                for position in SHEAR_SENSOR_POSITIONS
            }
            shear_result = harness.shear_detector.detect(sample_values)
            normal_force_result = harness.normal_force_calculator.compute(shear_result.residual)
            expected[idx] = float(normal_force_result.total_force)

        np.testing.assert_allclose(total_force, expected, rtol=1e-7, atol=1e-7)

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
            self.assertEqual(settings["processing"]["package_sensor_gains"]["PZT3"]["C"], 1.25)
            self.assertFalse(settings["visualization"]["arrow_width_scales"])
            self.assertEqual(settings["pressure_map"]["sensor_spacing_mm"], 1.75)
            self.assertEqual(settings["pressure_map"]["circle_diameter_mm"], 5.5)
            self.assertEqual(settings["pressure_map"]["grid_resolution"], 25)
            self.assertEqual(settings["pressure_map"]["grid_margin"], 3)
            self.assertEqual(settings["pressure_map"]["decay_rate"], 0.9)
            self.assertEqual(settings["pressure_map"]["decay_ref_distance_mm"], 2.25)
            self.assertTrue(settings["pressure_map"]["show_negative"])
            self.assertFalse(settings["pressure_map"]["show_marker"])

            settings["processing"]["package_sensor_gains"] = {
                "PZT3": {"R": 2.5, "L": 0.25}
            }
            settings_path.write_text(json.dumps(payload), encoding="utf-8")

            harness.signal_integration_hpf_spin.setValue(1.0)
            harness.signal_integration_window_spin.setValue(2)
            harness.shear_noise_threshold_spin.setValue(3.0)
            harness.shear_arrow_width_scales_check.setChecked(True)
            harness.pressure_sensor_spacing_spin.setValue(2.0)
            harness.pressure_circle_diameter_spin.setValue(6.0)
            harness.pressure_grid_resolution_spin.setValue(21)
            harness.pressure_grid_margin_spin.setValue(1)
            harness.pressure_decay_rate_spin.setValue(0.1)
            harness.pressure_decay_ref_distance_spin.setValue(0.5)
            harness.pressure_show_negative_check.setChecked(DEFAULT_PRESSURE_SHOW_NEGATIVE)
            harness.pressure_show_marker_check.setChecked(DEFAULT_PRESSURE_SHOW_MARKER)

            applied = harness.load_shear_settings_from_path(settings_path, log_message=True)

            self.assertTrue(applied)
            self.assertEqual(harness.signal_integration_hpf_spin.value(), 12.5)
            self.assertEqual(harness.signal_integration_window_spin.value(), 44)
            self.assertEqual(harness.shear_noise_threshold_spin.value(), 0.75)
            self.assertFalse(harness.shear_arrow_width_scales_check.isChecked())
            self.assertEqual(harness.pressure_sensor_spacing_spin.value(), 1.75)
            self.assertEqual(harness.pressure_circle_diameter_spin.value(), 5.5)
            self.assertEqual(harness.pressure_grid_resolution_spin.value(), 25)
            self.assertEqual(harness.pressure_grid_margin_spin.value(), 3)
            self.assertEqual(harness.pressure_decay_rate_spin.value(), 0.9)
            self.assertEqual(harness.pressure_decay_ref_distance_spin.value(), 2.25)
            self.assertTrue(harness.pressure_show_negative_check.isChecked())
            self.assertFalse(harness.pressure_show_marker_check.isChecked())
            self.assertEqual(harness._pressure_package_sensor_gains["PZT3"]["R"], 2.5)
            self.assertEqual(harness._pressure_package_sensor_gains["PZT3"]["L"], 0.25)

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
                "pressure_decay_rate_spin": "distance gain",
                "pressure_decay_ref_distance_spin": "reference distance",
                "pressure_show_negative_check": "negative release values",
                "pressure_show_marker_check": "pressure-point marker",
            }

            for widget_name, expected_text in expected_tooltips.items():
                widget = getattr(harness, widget_name)
                self.assertIn(expected_text, widget.toolTip().lower(), msg=widget_name)
        finally:
            tab.close()


if __name__ == "__main__":
    unittest.main()
