import unittest
from unittest.mock import patch

from config.config_handlers import ConfigurationMixin
from config_constants import MAX_PLOT_COLUMNS


class FakeSignal:
    def __init__(self):
        self.connected = []

    def connect(self, callback):
        self.connected.append(callback)


class FakeCheckbox:
    def __init__(self, label):
        self.label = label
        self.checked = False
        self.style = ""
        self.stateChanged = FakeSignal()

    def setChecked(self, checked):
        self.checked = bool(checked)

    def setStyleSheet(self, style):
        self.style = style


class FakeLayout:
    def __init__(self):
        self.widgets = []

    def addWidget(self, widget, row, col):
        self.widgets.append((widget, row, col))


class FakePort:
    def __init__(self, is_open):
        self.is_open = is_open


class ForceCheckboxHarness(ConfigurationMixin):
    def __init__(self):
        self.channel_checkboxes_layout = FakeLayout()
        self.force_serial_port = None
        self.force_x_checkbox = None
        self.force_z_checkbox = None
        self.triggered = 0

    def trigger_plot_update(self):
        self.triggered += 1


class ForceChannelCheckboxTests(unittest.TestCase):
    def test_add_force_channel_checkboxes_only_when_force_port_is_connected(self):
        harness = ForceCheckboxHarness()

        with patch("PyQt6.QtWidgets.QCheckBox", FakeCheckbox):
            harness._add_force_channel_checkboxes(start_index=2)
        self.assertEqual(harness.channel_checkboxes_layout.widgets, [])
        self.assertIsNone(harness.force_x_checkbox)
        self.assertIsNone(harness.force_z_checkbox)

        harness.force_serial_port = FakePort(is_open=True)
        with patch("PyQt6.QtWidgets.QCheckBox", FakeCheckbox):
            harness._add_force_channel_checkboxes(start_index=MAX_PLOT_COLUMNS - 1)

        self.assertEqual(len(harness.channel_checkboxes_layout.widgets), 2)
        self.assertEqual(harness.channel_checkboxes_layout.widgets[0][1:], (0, MAX_PLOT_COLUMNS - 1))
        self.assertEqual(harness.channel_checkboxes_layout.widgets[1][1:], (1, 0))
        self.assertEqual(harness.force_x_checkbox.label, "X Force [N]")
        self.assertEqual(harness.force_z_checkbox.label, "Z Force [N]")
        self.assertTrue(harness.force_x_checkbox.checked)
        self.assertTrue(harness.force_z_checkbox.checked)

    def test_force_checkbox_selection_helper_toggles_both_widgets(self):
        harness = ForceCheckboxHarness()
        harness.force_x_checkbox = FakeCheckbox("X Force [N]")
        harness.force_z_checkbox = FakeCheckbox("Z Force [N]")

        harness._set_force_channel_checkboxes_checked(True)
        self.assertTrue(harness.force_x_checkbox.checked)
        self.assertTrue(harness.force_z_checkbox.checked)

        harness._set_force_channel_checkboxes_checked(False)
        self.assertFalse(harness.force_x_checkbox.checked)
        self.assertFalse(harness.force_z_checkbox.checked)

    def test_force_checkbox_refs_reset_when_layout_rebuilds(self):
        harness = ForceCheckboxHarness()
        harness.force_x_checkbox = FakeCheckbox("X Force [N]")
        harness.force_z_checkbox = FakeCheckbox("Z Force [N]")

        harness._reset_force_channel_checkbox_refs()

        self.assertIsNone(harness.force_x_checkbox)
        self.assertIsNone(harness.force_z_checkbox)


if __name__ == "__main__":
    unittest.main()
