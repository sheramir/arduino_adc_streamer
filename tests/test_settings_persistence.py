import json
import shutil
import unittest
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from gui.heatmap_panel import HeatmapPanelMixin
from gui.shear_panel import ShearPanelMixin
from gui.spectrum_panel import SpectrumPanelMixin


@contextmanager
def workspace_tempdir(prefix: str):
    root = Path(".codex_test_tmp")
    root.mkdir(exist_ok=True)
    path = root / f"{prefix}_{uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class SimpleSpin:
    def __init__(self, value=0.0):
        self._value = value

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = value


class SimpleCheck:
    def __init__(self, checked=False):
        self._checked = checked

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        self._checked = bool(checked)


class SimpleCombo:
    def __init__(self, items, current=None):
        self._items = list(items)
        self._text = current if current is not None else self._items[0]

    def currentText(self):
        return self._text

    def setCurrentText(self, text):
        self._text = text

    def currentIndex(self):
        try:
            return self._items.index(self._text)
        except ValueError:
            return -1

    def setCurrentIndex(self, index):
        self._text = self._items[index]


class SimpleTimer:
    def __init__(self):
        self.interval_ms = 0

    def setInterval(self, interval_ms):
        self.interval_ms = int(interval_ms)


class HeatmapSettingsHarness(HeatmapPanelMixin):
    def __init__(self, settings_path: Path):
        self._settings_path = settings_path
        self._heatmap_autosave_enabled = True
        self._heatmap_settings_loading = False
        self.log_messages = []
        self.global_threshold_spins = [SimpleSpin(v) for v in (1, 2, 3, 4, 5)]
        self.global_release_threshold_spins = [SimpleSpin(v) for v in (6, 7, 8, 9, 10)]
        self.sensor_calibration_spins = {
            "PZT1": {
                "threshold_spins": [SimpleSpin(v) for v in (11, 12, 13, 14, 15)],
                "gain_spins": [SimpleSpin(v) for v in (1.1, 1.2, 1.3, 1.4, 1.5)],
            }
        }
        self.sensor_size_spin = SimpleSpin(1.25)
        self.intensity_scale_spin = SimpleSpin(0.45)
        self.blob_sigma_x_spin = SimpleSpin(0.31)
        self.blob_sigma_y_spin = SimpleSpin(0.41)
        self.smooth_alpha_spin = SimpleSpin(0.51)
        self.hpf_cutoff_spin = SimpleSpin(3.5)
        self.r555_cop_smooth_alpha_spin = SimpleSpin(0.61)
        self.r555_intensity_min_spin = SimpleSpin(5.0)
        self.r555_intensity_max_spin = SimpleSpin(95.0)
        self.r555_axis_adapt_spin = SimpleSpin(0.71)
        self.r555_map_smooth_alpha_spin = SimpleSpin(0.81)
        self.rms_window_spin = SimpleSpin(55)
        self.dc_removal_combo = SimpleCombo(["Bias (2s)", "High-pass"], current="High-pass")
        self.magnitude_threshold_spin = SimpleSpin(0.0)

    def _get_last_heatmap_settings_path(self):
        return self._settings_path

    def _get_heatmap_mode_key(self):
        return "pzt"

    def get_active_channel_sensor_map(self):
        return ["T", "B", "R", "L", "C"]

    def log_status(self, message: str):
        self.log_messages.append(message)


class ShearSettingsHarness(ShearPanelMixin):
    def __init__(self, settings_path: Path):
        self._settings_path = settings_path
        self._shear_autosave_enabled = True
        self.log_messages = []
        self.shear_window_spin = SimpleSpin(21.0)
        self.shear_conditioning_alpha_spin = SimpleSpin(0.11)
        self.shear_baseline_alpha_spin = SimpleSpin(0.12)
        self.shear_deadband_spin = SimpleSpin(0.013)
        self.shear_confidence_ref_spin = SimpleSpin(0.014)
        self.shear_sigma_x_spin = SimpleSpin(0.22)
        self.shear_sigma_y_spin = SimpleSpin(0.23)
        self.shear_intensity_scale_spin = SimpleSpin(1.8)
        self.shear_arrow_scale_spin = SimpleSpin(1.9)
        self.shear_gain_spins = [SimpleSpin(v) for v in (2.1, 2.2, 2.3, 2.4, 2.5)]
        self.shear_baseline_spins = [SimpleSpin(v) for v in (3.1, 3.2, 3.3, 3.4, 3.5)]

    def _get_last_shear_settings_path(self):
        return self._settings_path

    def get_active_channel_sensor_map(self):
        return ["T", "B", "R", "L", "C"]

    def log_status(self, message: str):
        self.log_messages.append(message)


class SpectrumSettingsHarness(SpectrumPanelMixin):
    def __init__(self, settings_path: Path):
        self._settings_path = settings_path
        self.log_messages = []
        self.applied_filter_settings = None
        self.spectrum_timer = SimpleTimer()
        self.spectrum_window_ms_spin = SimpleSpin(250)
        self.spectrum_nfft_combo = SimpleCombo(["Auto (next power of 2)", "2048"], current="2048")
        self.spectrum_mode_combo = SimpleCombo(["Welch PSD", "Single FFT"], current="Single FFT")
        self.spectrum_window_combo = SimpleCombo(["Hann", "Hamming", "Blackman", "Rectangular"], current="Blackman")
        self.spectrum_seg_len_spin = SimpleSpin(512)
        self.spectrum_overlap_spin = SimpleSpin(37.5)
        self.spectrum_averaging_combo = SimpleCombo(["EMA", "N-Averages"], current="N-Averages")
        self.spectrum_ema_alpha_spin = SimpleSpin(0.42)
        self.spectrum_navg_spin = SimpleSpin(9)
        self.spectrum_fmin_spin = SimpleSpin(12.0)
        self.spectrum_fmax_spin = SimpleSpin(345.0)
        self.spectrum_band_fmin_spin = SimpleSpin(25.0)
        self.spectrum_band_fmax_spin = SimpleSpin(125.0)
        self.spectrum_y_scale_combo = SimpleCombo(["dB", "Linear"], current="Linear")
        self.spectrum_x_scale_combo = SimpleCombo(["Linear", "Log"], current="Log")
        self.spectrum_update_rate_spin = SimpleSpin(7)
        self.spectrum_remove_dc_check = SimpleCheck(False)
        self.spectrum_snap_peak_check = SimpleCheck(True)
        self.filter_master_check = SimpleCheck(True)
        self.filter_main_type_combo = SimpleCombo(["None", "Low-pass", "High-pass", "Band-pass"], current="Band-pass")
        self.filter_order_spin = SimpleSpin(3)
        self.filter_low_cutoff_spin = SimpleSpin(44.0)
        self.filter_high_cutoff_spin = SimpleSpin(333.0)
        self.notch1_enable_check = SimpleCheck(True)
        self.notch1_freq_spin = SimpleSpin(60.0)
        self.notch1_q_spin = SimpleSpin(25.0)
        self.notch2_enable_check = SimpleCheck(False)
        self.notch2_freq_spin = SimpleSpin(120.0)
        self.notch2_q_spin = SimpleSpin(30.0)
        self.notch3_enable_check = SimpleCheck(True)
        self.notch3_freq_spin = SimpleSpin(180.0)
        self.notch3_q_spin = SimpleSpin(35.0)

    def _get_last_spectrum_settings_path(self):
        return self._settings_path

    def apply_filter_settings(self, settings: dict, reprocess_existing: bool = True):
        self.applied_filter_settings = (settings, reprocess_existing)
        return True, ""

    def log_status(self, message: str):
        self.log_messages.append(message)


class SettingsPersistenceTests(unittest.TestCase):
    def test_heatmap_save_last_and_load_last_round_trip(self):
        with workspace_tempdir("heatmap_settings") as tmpdir:
            settings_path = tmpdir / "heatmap.json"
            harness = HeatmapSettingsHarness(settings_path)

            harness.save_last_heatmap_settings()

            payload = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 2)
            self.assertEqual(payload["heatmap_settings"]["rms_window_ms"], 55)
            self.assertNotIn("cop_smooth_alpha", payload["heatmap_settings"])

            harness.global_threshold_spins[0].setValue(999.0)
            harness.sensor_calibration_spins["PZT1"]["gain_spins"][0].setValue(9.9)
            harness.dc_removal_combo.setCurrentText("Bias (2s)")

            applied = harness.load_last_heatmap_settings()

            self.assertTrue(applied)
            self.assertEqual(harness.global_threshold_spins[0].value(), 3.0)
            self.assertEqual(harness.sensor_calibration_spins["PZT1"]["gain_spins"][0].value(), 1.1)
            self.assertEqual(harness.dc_removal_combo.currentText(), "High-pass")

    def test_shear_save_last_and_load_last_round_trip(self):
        with workspace_tempdir("shear_settings") as tmpdir:
            settings_path = tmpdir / "shear.json"
            harness = ShearSettingsHarness(settings_path)

            harness.save_last_shear_settings()

            payload = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 1)
            self.assertEqual(payload["shear_settings"]["integration_window_ms"], 21.0)
            self.assertEqual(payload["shear_settings"]["sensor_gains"]["C"], 2.1)

            harness.shear_window_spin.setValue(99.0)
            harness.shear_gain_spins[0].setValue(7.7)

            applied = harness.load_last_shear_settings()

            self.assertTrue(applied)
            self.assertEqual(harness.shear_window_spin.value(), 21.0)
            self.assertEqual(harness.shear_gain_spins[0].value(), 2.1)

    def test_spectrum_save_last_and_load_last_round_trip(self):
        with workspace_tempdir("spectrum_settings") as tmpdir:
            settings_path = tmpdir / "spectrum.json"
            harness = SpectrumSettingsHarness(settings_path)

            harness.save_last_spectrum_settings()

            payload = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 1)
            self.assertEqual(payload["spectrum_settings"]["mode"], "fft")
            self.assertEqual(payload["spectrum_settings"]["filter_settings"]["main_type"], "bandpass")

            harness.spectrum_mode_combo.setCurrentText("Welch PSD")
            harness.filter_main_type_combo.setCurrentText("Low-pass")
            harness.spectrum_update_rate_spin.setValue(3)

            harness.load_last_spectrum_settings()

            self.assertEqual(harness.spectrum_mode_combo.currentText(), "Single FFT")
            self.assertEqual(harness.filter_main_type_combo.currentText(), "Band-pass")
            self.assertEqual(harness.spectrum_timer.interval_ms, int(1000 / 7))
            self.assertIsNotNone(harness.applied_filter_settings)
            self.assertFalse(harness.applied_filter_settings[1])


if __name__ == "__main__":
    unittest.main()
