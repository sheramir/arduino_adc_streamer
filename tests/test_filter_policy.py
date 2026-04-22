import unittest

import numpy as np

from data_processing.adc_filter_engine import ADCFilterEngine, SCIPY_FILTERS_AVAILABLE
from data_processing.filter_processor import FilterProcessorMixin
from constants.ui import TIME_SERIES_TAB_NAME
from gui.spectrum_panel import SpectrumPanelMixin


class SimpleWidget:
    def __init__(self):
        self.enabled = True

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)


class SimpleValueWidget(SimpleWidget):
    def __init__(self, value):
        super().__init__()
        self._value = value

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = value


class SimpleComboWidget(SimpleWidget):
    def __init__(self, text):
        super().__init__()
        self._text = text

    def currentText(self):
        return self._text

    def setCurrentText(self, text):
        self._text = text


class SimpleCheck(SimpleWidget):
    def __init__(self, checked=False):
        super().__init__()
        self._checked = bool(checked)

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        self._checked = bool(checked)

    def blockSignals(self, _blocked):
        return False


class FilterPolicyHarness(FilterProcessorMixin):
    def __init__(self, device_mode, *, is_capturing=False, current_tab=TIME_SERIES_TAB_NAME):
        self.device_mode = device_mode
        self.filtering_enabled = True
        self.filter_settings = self.get_default_filter_settings()
        self.adc_filter_engine = ADCFilterEngine()
        self.processed_data_buffer = np.array([[9.0, 9.0]], dtype=np.float32)
        self.raw_data_buffer = np.array([[1.0, 2.0]], dtype=np.float32)
        self.raw_data = np.array([[1.0, 2.0]], dtype=np.float32)
        self.sweep_timestamps = np.array([0.0], dtype=np.float64)
        self.samples_per_sweep = 2
        self.timing_state = type("Timing", (), {"arduino_sample_times": [], "timing_data": {}})()
        self.config = {"channels": [0, 1], "repeat": 1, "sample_rate": 0}
        self._filter_channel_runtime = {}
        self._filter_total_fs_hz = 0.0
        self._filter_channels_signature = None
        self.filter_apply_pending = True
        self.filter_last_error = None
        self.is_capturing = is_capturing
        self.is_full_view = False
        self.current_tab = current_tab
        self._full_view_filter_cache_key = None
        self._full_view_filter_cache_data = None
        self._full_view_filter_cache_timestamps = None

    def should_update_live_timeseries_display(self):
        return self.current_tab == TIME_SERIES_TAB_NAME


class SpectrumFilterAvailabilityHarness(SpectrumPanelMixin):
    def __init__(self, supported):
        self._supported = supported
        self.filtering_enabled = True
        self.filter_master_check = SimpleCheck(True)
        self.filter_main_type_combo = SimpleWidget()
        self.filter_order_spin = SimpleWidget()
        self.filter_low_cutoff_spin = SimpleWidget()
        self.filter_high_cutoff_spin = SimpleWidget()
        self.notch1_enable_check = SimpleWidget()
        self.notch1_freq_spin = SimpleWidget()
        self.notch1_q_spin = SimpleWidget()
        self.notch2_enable_check = SimpleWidget()
        self.notch2_freq_spin = SimpleWidget()
        self.notch2_q_spin = SimpleWidget()
        self.notch3_enable_check = SimpleWidget()
        self.notch3_freq_spin = SimpleWidget()
        self.notch3_q_spin = SimpleWidget()
        self.filter_apply_btn = SimpleWidget()
        self.filter_disable_btn = SimpleWidget()
        self.filter_reset_btn = SimpleWidget()
        self.log_messages = []

    def is_adc_filter_supported_mode(self):
        return self._supported

    def log_status(self, message):
        self.log_messages.append(message)


class SpectrumFilterApplyHarness(SpectrumPanelMixin):
    def __init__(self):
        self.filtering_enabled = False
        self.filter_master_check = SimpleCheck(False)
        self.filter_main_type_combo = SimpleComboWidget("None")
        self.filter_order_spin = SimpleValueWidget(2)
        self.filter_low_cutoff_spin = SimpleValueWidget(5.0)
        self.filter_high_cutoff_spin = SimpleValueWidget(200.0)
        self.notch1_enable_check = SimpleCheck(True)
        self.notch1_freq_spin = SimpleValueWidget(60.0)
        self.notch1_q_spin = SimpleValueWidget(10.0)
        self.notch2_enable_check = SimpleCheck(False)
        self.notch2_freq_spin = SimpleValueWidget(120.0)
        self.notch2_q_spin = SimpleValueWidget(30.0)
        self.notch3_enable_check = SimpleCheck(False)
        self.notch3_freq_spin = SimpleValueWidget(180.0)
        self.notch3_q_spin = SimpleValueWidget(30.0)
        self.filter_disable_btn = SimpleWidget()
        self.log_messages = []
        self.applied_calls = []
        self.plot_updates = 0
        self.spectrum_updates = 0
        self.is_capturing = False

    def apply_filter_settings(self, settings, reprocess_existing=True):
        self.applied_calls.append((settings, reprocess_existing))
        self.filtering_enabled = bool(settings.get("enabled", False))
        return True, ""

    def log_status(self, message):
        self.log_messages.append(message)

    def trigger_plot_update(self):
        self.plot_updates += 1

    def update_spectrum(self):
        self.spectrum_updates += 1


class FilterPolicyTests(unittest.TestCase):
    def test_processed_buffer_is_bypassed_in_555_mode(self):
        harness = FilterPolicyHarness(device_mode="555")

        active = harness.get_active_data_buffer()

        self.assertIs(active, harness.raw_data_buffer)
        self.assertFalse(harness.should_filter_adc_data())

    def test_live_adc_filtering_uses_raw_buffer_for_timeseries_capture(self):
        harness = FilterPolicyHarness(device_mode="adc", is_capturing=True, current_tab=TIME_SERIES_TAB_NAME)

        active = harness.get_active_data_buffer()

        self.assertIs(active, harness.raw_data_buffer)

    @unittest.skipUnless(SCIPY_FILTERS_AVAILABLE, "SciPy not available")
    def test_full_view_snapshot_uses_filtered_dataset_when_enabled(self):
        harness = FilterPolicyHarness(device_mode="adc")
        harness.is_full_view = True
        harness.raw_data = np.array([[0.0], [100.0], [0.0], [100.0], [0.0], [100.0]], dtype=np.float32)
        harness.sweep_timestamps = np.arange(6, dtype=np.float64) / 100.0
        harness.config = {"channels": [0], "repeat": 1, "sample_rate": 100.0}
        harness.filter_settings["main_type"] = "lowpass"
        harness.filter_settings["low_cutoff_hz"] = 5.0
        harness.filter_settings["notches"] = []

        filtered_data, filtered_timestamps = harness.get_full_view_plot_snapshot()

        self.assertEqual(filtered_data.shape, harness.raw_data.shape)
        np.testing.assert_allclose(filtered_timestamps, harness.sweep_timestamps)
        self.assertFalse(np.allclose(filtered_data, harness.raw_data))

    def test_filter_block_bypasses_when_mode_not_supported(self):
        harness = FilterPolicyHarness(device_mode="555")
        block = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)

        filtered = harness.filter_sweeps_block(block, total_fs_hz=1000.0)

        np.testing.assert_allclose(filtered, block)

    def test_spectrum_filter_controls_disable_outside_adc_mode(self):
        harness = SpectrumFilterAvailabilityHarness(supported=False)

        harness.refresh_spectrum_filter_availability(log_message=True)

        self.assertFalse(harness.filter_master_check.isChecked())
        self.assertFalse(harness.filter_main_type_combo.enabled)
        self.assertFalse(harness.filter_apply_btn.enabled)
        self.assertFalse(harness.filter_disable_btn.enabled)
        self.assertFalse(harness.filtering_enabled)
        self.assertIn("Filtering is available only for ADC mode data", harness.log_messages[-1])

    def test_apply_filter_auto_enables_master_when_notch_selected(self):
        harness = SpectrumFilterApplyHarness()

        harness.on_apply_filter_clicked()

        self.assertTrue(harness.filter_master_check.isChecked())
        self.assertTrue(harness.filter_disable_btn.enabled)
        self.assertTrue(harness.applied_calls)
        self.assertTrue(harness.applied_calls[-1][0]["enabled"])
        self.assertTrue(any("enabled automatically" in message for message in harness.log_messages))

    def test_turn_off_filter_button_disables_filter_but_preserves_settings(self):
        harness = SpectrumFilterApplyHarness()
        harness.filtering_enabled = True
        harness.filter_master_check.setChecked(True)
        harness.filter_main_type_combo.setCurrentText("Low-pass")
        harness.filter_low_cutoff_spin.setValue(123.0)
        harness.notch1_enable_check.setChecked(True)
        harness.refresh_filter_action_buttons()

        harness.on_turn_off_filter_clicked()

        self.assertFalse(harness.filter_master_check.isChecked())
        self.assertFalse(harness.filter_disable_btn.enabled)
        self.assertTrue(harness.applied_calls)
        turned_off_settings = harness.applied_calls[-1][0]
        self.assertFalse(turned_off_settings["enabled"])
        self.assertEqual(turned_off_settings["main_type"], "lowpass")
        self.assertAlmostEqual(turned_off_settings["low_cutoff_hz"], 123.0)
        self.assertTrue(turned_off_settings["notches"][0]["enabled"])
        self.assertIn("Filtering turned OFF", harness.log_messages[-1])


if __name__ == "__main__":
    unittest.main()
