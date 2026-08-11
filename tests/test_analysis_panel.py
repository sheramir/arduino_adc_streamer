import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from constants.pzt_force import PZT_FORCE_DEFAULT_SETTINGS
from gui.analysis_panel import AnalysisPanelMixin


class FakePlot:
    def __init__(self):
        self.visible = None

    def setVisible(self, visible):
        self.visible = bool(visible)


class FakeSplitter:
    def __init__(self):
        self.minimum_height = None
        self.sizes = None

    def setMinimumHeight(self, minimum_height):
        self.minimum_height = minimum_height

    def setSizes(self, sizes):
        self.sizes = list(sizes)


class AnalysisPlotVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.harness = AnalysisPanelMixin()
        self.harness.analysis_signal_plot = FakePlot()
        self.harness.analysis_integration_plot = FakePlot()
        self.harness.analysis_derived_plot = FakePlot()
        self.harness.analysis_force_plot = FakePlot()
        self.harness.analysis_plot_splitter = FakeSplitter()

    def test_hides_unrequested_empty_plots_and_collapses_their_space(self):
        self.harness._update_analysis_plot_visibility(
            show_signal=True,
            show_integration=False,
            show_derived=False,
            show_force=False,
        )

        self.assertTrue(self.harness.analysis_signal_plot.visible)
        self.assertFalse(self.harness.analysis_integration_plot.visible)
        self.assertFalse(self.harness.analysis_derived_plot.visible)
        self.assertFalse(self.harness.analysis_force_plot.visible)
        self.assertEqual(self.harness.analysis_plot_splitter.minimum_height, 360)
        self.assertEqual(self.harness.analysis_plot_splitter.sizes, [360, 0, 0, 0])

    def test_shows_each_available_requested_plot(self):
        self.harness._update_analysis_plot_visibility(
            show_signal=True,
            show_integration=True,
            show_derived=True,
            show_force=True,
        )

        self.assertTrue(self.harness.analysis_integration_plot.visible)
        self.assertTrue(self.harness.analysis_derived_plot.visible)
        self.assertTrue(self.harness.analysis_force_plot.visible)
        self.assertEqual(self.harness.analysis_plot_splitter.minimum_height, 1160)
        self.assertEqual(self.harness.analysis_plot_splitter.sizes, [360, 260, 240, 300])


class DummySpin:
    """Small value-only stand-in for a Qt spin box."""

    def __init__(self, value=0.0):
        self._value = value

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = value

    def setVisible(self, _visible):
        pass

    def setEnabled(self, _enabled):
        pass


class DummyCheck:
    """Small checked-state stand-in for a Qt check box."""

    def __init__(self, checked=False):
        self._checked = checked

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        self._checked = bool(checked)


class DummyCombo:
    """Small index/text stand-in for a Qt combo box."""

    def __init__(self, index=0, text=""):
        self._index = index
        self._text = text

    def currentIndex(self):
        return self._index

    def setCurrentIndex(self, index):
        self._index = index

    def currentText(self):
        return self._text

    def setCurrentText(self, text):
        self._text = str(text)


class DummyTextWidget:
    """Small text-only stand-in for a Qt label/line edit."""

    def __init__(self, text=""):
        self._text = text

    def text(self):
        return self._text

    def setText(self, text):
        self._text = str(text)

    def setPlainText(self, text):
        self._text = str(text)


class AnalysisPanelHarness(AnalysisPanelMixin):
    """Minimal harness exercising the PZT force settings save/restore path."""

    def __init__(self, settings_path):
        self._settings_path = Path(settings_path)
        self._init_analysis_state()
        self.log_messages = []

        self.analysis_source_combo = DummyCombo()
        self.analysis_axis_combo = DummyCombo()
        self.analysis_zoom_combo = DummyCombo()
        self.analysis_filter_check = DummyCheck()
        self.analysis_marker_check = DummyCheck(True)
        self.analysis_shear_check = DummyCheck()
        self.analysis_normal_check = DummyCheck()
        self.analysis_integration_check = DummyCheck()
        self.analysis_pzt_force_check = DummyCheck()

        self.analysis_pzt_center_capacitance_spin = DummySpin(float(PZT_FORCE_DEFAULT_SETTINGS["center_capacitance_value"]))
        self.analysis_pzt_outer_capacitance_spin = DummySpin(float(PZT_FORCE_DEFAULT_SETTINGS["outer_capacitance_value"]))
        self.analysis_pzt_capacitance_unit_combo = DummyCombo(text=str(PZT_FORCE_DEFAULT_SETTINGS["capacitance_unit"]))
        self.analysis_pzt_rleak_spin = DummySpin(float(PZT_FORCE_DEFAULT_SETTINGS["rleak_ohm"]))
        self.analysis_pzt_d33_spin = DummySpin(float(PZT_FORCE_DEFAULT_SETTINGS["d33_pc_per_n"]))
        self.analysis_pzt_noise_spin = DummySpin(float(PZT_FORCE_DEFAULT_SETTINGS["noise_threshold_v"]))
        self.analysis_pzt_quiet_duration_spin = DummySpin(float(PZT_FORCE_DEFAULT_SETTINGS["quiet_duration_s"]))
        self.analysis_pzt_noise_k_spin = DummySpin(float(PZT_FORCE_DEFAULT_SETTINGS["noise_sigma_multiplier"]))
        self.analysis_pzt_mux_timing_combo = DummyCombo(text="Auto")
        self.analysis_pzt_mux_connected_ms_spin = DummySpin(float(PZT_FORCE_DEFAULT_SETTINGS["mux_connected_time_s"]) * 1000.0)
        self.analysis_pzt_mux_timing_status = DummyTextWidget()
        self.analysis_pzt_off_mux_leak_check = DummyCheck()
        self.analysis_pzt_off_mux_rleak_spin = DummySpin(float(PZT_FORCE_DEFAULT_SETTINGS["rleak_ohm"]))
        self.analysis_pzt_stuck_failsafe_check = DummyCheck(bool(PZT_FORCE_DEFAULT_SETTINGS["stuck_force_failsafe_enabled"]))
        self.analysis_pzt_stuck_hold_spin = DummySpin(float(PZT_FORCE_DEFAULT_SETTINGS["stuck_force_quiet_hold_s"]))
        self.analysis_pzt_stuck_tau_spin = DummySpin(float(PZT_FORCE_DEFAULT_SETTINGS["stuck_force_decay_tau_s"]))
        self.analysis_pzt_zero_floor_spin = DummySpin(float(PZT_FORCE_DEFAULT_SETTINGS["force_zero_band_min_n"]))
        self.analysis_pzt_zero_band_fraction_spin = DummySpin(float(PZT_FORCE_DEFAULT_SETTINGS["force_zero_band_fraction"]))
        self.analysis_pzt_min_event_peak_spin = DummySpin(float(PZT_FORCE_DEFAULT_SETTINGS["force_zero_min_event_peak_n"]))
        self.analysis_pzt_quiet_release_spin = DummySpin(float(PZT_FORCE_DEFAULT_SETTINGS["quiet_hold_release_fraction"]))
        self.analysis_pzt_quiet_hold_spin = DummySpin(float(PZT_FORCE_DEFAULT_SETTINGS["quiet_hold_clear_s"]))
        self.analysis_pzt_baseline_results = DummyTextWidget()
        self.analysis_csv_path_edit = DummyTextWidget()
        self.analysis_metadata_path_edit = DummyTextWidget()

    def _get_last_analysis_settings_path(self):
        return self._settings_path

    def log_status(self, message):
        self.log_messages.append(message)


class AnalysisPztForceEventTunablesRoundTripTests(unittest.TestCase):
    """Work item D3: the five natural-reset event tunables (Part D) round
    trip through save/restore, and a legacy payload lacking them falls back
    to the shared defaults."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_five_event_tunables_survive_save_and_restore(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "last_used_analysis_settings.json"
            harness = AnalysisPanelHarness(settings_path)

            harness.analysis_pzt_zero_floor_spin.setValue(0.05)
            harness.analysis_pzt_zero_band_fraction_spin.setValue(0.2)
            harness.analysis_pzt_min_event_peak_spin.setValue(0.1)
            harness.analysis_pzt_quiet_release_spin.setValue(0.4)
            harness.analysis_pzt_quiet_hold_spin.setValue(0.3)

            harness.on_analysis_settings_changed()

            payload = json.loads(settings_path.read_text(encoding="utf-8"))
            saved_pzt_force = payload["analysis_settings"]["pzt_force"]
            self.assertEqual(saved_pzt_force["force_zero_band_min_n"], 0.05)
            self.assertEqual(saved_pzt_force["force_zero_band_fraction"], 0.2)
            self.assertEqual(saved_pzt_force["force_zero_min_event_peak_n"], 0.1)
            self.assertEqual(saved_pzt_force["quiet_hold_release_fraction"], 0.4)
            self.assertEqual(saved_pzt_force["quiet_hold_clear_s"], 0.3)

            restored = AnalysisPanelHarness(settings_path)
            restored.load_last_analysis_settings()

            self.assertEqual(restored.analysis_pzt_zero_floor_spin.value(), 0.05)
            self.assertEqual(restored.analysis_pzt_zero_band_fraction_spin.value(), 0.2)
            self.assertEqual(restored.analysis_pzt_min_event_peak_spin.value(), 0.1)
            self.assertEqual(restored.analysis_pzt_quiet_release_spin.value(), 0.4)
            self.assertEqual(restored.analysis_pzt_quiet_hold_spin.value(), 0.3)

    def test_legacy_payload_missing_the_five_keys_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "legacy_analysis_settings.json"
            legacy_payload = {
                "version": 1,
                "analysis_settings": {
                    "pzt_force": {
                        "enabled": True,
                        "rleak_ohm": 2_000_000.0,
                        # The five Part-C/D tunables are absent, as an older
                        # save predating this work item would be.
                    },
                },
            }
            settings_path.write_text(json.dumps(legacy_payload), encoding="utf-8")

            harness = AnalysisPanelHarness(settings_path)
            harness.analysis_pzt_zero_floor_spin.setValue(0.999)  # must not survive the load

            harness.load_last_analysis_settings()

            self.assertEqual(
                harness.analysis_pzt_zero_floor_spin.value(),
                float(PZT_FORCE_DEFAULT_SETTINGS["force_zero_band_min_n"]),
            )
            self.assertEqual(
                harness.analysis_pzt_zero_band_fraction_spin.value(),
                float(PZT_FORCE_DEFAULT_SETTINGS["force_zero_band_fraction"]),
            )
            self.assertEqual(
                harness.analysis_pzt_min_event_peak_spin.value(),
                float(PZT_FORCE_DEFAULT_SETTINGS["force_zero_min_event_peak_n"]),
            )
            self.assertEqual(
                harness.analysis_pzt_quiet_release_spin.value(),
                float(PZT_FORCE_DEFAULT_SETTINGS["quiet_hold_release_fraction"]),
            )
            self.assertEqual(
                harness.analysis_pzt_quiet_hold_spin.value(),
                float(PZT_FORCE_DEFAULT_SETTINGS["quiet_hold_clear_s"]),
            )
            # An untouched pre-existing key survives alongside the defaults.
            self.assertEqual(harness.analysis_pzt_rleak_spin.value(), 2_000_000.0)


if __name__ == "__main__":
    unittest.main()
