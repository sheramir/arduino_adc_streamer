import unittest

import numpy as np

from data_processing.filter_processor import FilterProcessorMixin
from gui.spectrum_panel import SpectrumPanelMixin


class SimpleWidget:
    def __init__(self):
        self.enabled = True

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)


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
    def __init__(self, device_mode):
        self.device_mode = device_mode
        self.filtering_enabled = True
        self.filter_settings = self.get_default_filter_settings()
        self.processed_data_buffer = np.array([[9.0, 9.0]], dtype=np.float32)
        self.raw_data_buffer = np.array([[1.0, 2.0]], dtype=np.float32)
        self.samples_per_sweep = 2
        self.timing_state = type("Timing", (), {"arduino_sample_times": [], "timing_data": {}})()
        self.config = {"channels": [0, 1], "repeat": 1, "sample_rate": 0}
        self._filter_channel_runtime = {}
        self._filter_total_fs_hz = 0.0
        self._filter_channels_signature = None
        self.filter_apply_pending = True
        self.filter_last_error = None


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
        self.filter_reset_btn = SimpleWidget()
        self.log_messages = []

    def is_adc_filter_supported_mode(self):
        return self._supported

    def log_status(self, message):
        self.log_messages.append(message)


class FilterPolicyTests(unittest.TestCase):
    def test_processed_buffer_is_bypassed_in_555_mode(self):
        harness = FilterPolicyHarness(device_mode="555")

        active = harness.get_active_data_buffer()

        self.assertIs(active, harness.raw_data_buffer)
        self.assertFalse(harness.should_filter_adc_data())

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
        self.assertFalse(harness.filtering_enabled)
        self.assertIn("Filtering is available only for ADC mode data", harness.log_messages[-1])


if __name__ == "__main__":
    unittest.main()
