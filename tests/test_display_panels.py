"""Tests for DisplayPanelsMixin PZT ghost-removal control wiring."""

import unittest

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


class DisplayPanelsHarnessWithoutForceDisplay(DisplayPanelsMixin):
    """No Force Display mixed in yet -- the reset hook must be optional."""

    def __init__(self):
        self.remove_ghost_check = DummyCheckBox(True)
        self.remove_ghost_attenuation_spin = DummySpinBox(0.5)
        self.settings_calls = []

    def set_pzt_ghost_removal_settings(self, enabled, attenuation):
        self.settings_calls.append((enabled, attenuation))


class DisplayPanelsPztGhostControlTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
