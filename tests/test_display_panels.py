"""Tests for DisplayPanelsMixin PZT ghost-removal control wiring."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from gui.display_panels import DisplayPanelsMixin


class DummyCheckBox:
    def __init__(self, checked):
        self._checked = checked

    def isChecked(self):
        return self._checked


class DummySpinBox:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value


class DisplayPanelsHarness(DisplayPanelsMixin):
    def __init__(self):
        self.remove_ghost_check = DummyCheckBox(True)
        self.remove_ghost_attenuation_spin = DummySpinBox(0.5)
        self.settings_calls = []
        self.reset_calls = []

    def set_pzt_ghost_removal_settings(self, enabled, attenuation):
        self.settings_calls.append((enabled, attenuation))

    def reset_pressure_force_display_for_baseline_change(self):
        self.reset_calls.append(True)

    def select_all_channels(self):
        pass

    def deselect_all_channels(self):
        pass

    def on_yaxis_range_changed(self):
        pass

    def on_yaxis_units_changed(self):
        pass

    def reset_graph_view(self):
        pass

    def full_graph_view(self):
        pass

    def trigger_plot_update(self):
        pass

    def zero_plot_baselines(self):
        pass


class DisplayPanelsHarnessWithoutForceDisplay(DisplayPanelsMixin):
    """No Force Display mixed in yet -- the reset hook must be optional."""

    def __init__(self):
        self.remove_ghost_check = DummyCheckBox(True)
        self.remove_ghost_attenuation_spin = DummySpinBox(0.5)
        self.settings_calls = []

    def set_pzt_ghost_removal_settings(self, enabled, attenuation):
        self.settings_calls.append((enabled, attenuation))


class DisplayPanelsPztGhostControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_toggle_applies_settings_and_resets_force_display(self):
        harness = DisplayPanelsHarness()

        harness._on_pzt_ghost_controls_changed()

        self.assertEqual(harness.settings_calls, [(True, 0.5)])
        # Flipping ghost removal changes whether buffered/incoming blocks are
        # net-space or raw, invalidating any accumulated Force Display state.
        self.assertEqual(harness.reset_calls, [True])

    def test_missing_force_reset_hook_is_tolerated(self):
        harness = DisplayPanelsHarnessWithoutForceDisplay()

        # Must not raise even when the Force Display isn't wired up yet.
        harness._on_pzt_ghost_controls_changed()

        self.assertEqual(harness.settings_calls, [(True, 0.5)])

    def test_visualization_controls_default_to_adaptive_y_range(self):
        harness = DisplayPanelsHarness()

        controls = harness.create_visualization_controls()

        self.assertEqual(harness.yaxis_range_combo.currentText(), "Adaptive")
        controls.deleteLater()


if __name__ == '__main__':
    unittest.main()
