"""
Spectrum Panel Package Selector
===============================
Covers the package combo, the channel-checkbox labels that follow it, and the
persistence of the selection.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel

from constants.ui import SPECTRUM_CHANNELS_PER_PACKAGE
from gui.spectrum_panel import SpectrumPanelMixin


PLACEMENTS = ["T", "B", "R", "L", "C"]
PACKAGES = ["PZT1", "PZT3", "PZT5"]




class _PanelHost(SpectrumPanelMixin):
    """Panel host wired to fake package data, without a full main window."""

    def __init__(self, packages=PACKAGES, array_mode=True):
        self._packages = list(packages)
        self._array_mode = array_mode
        self.spectrum_selected_package = None
        self.saved_settings_count = 0

        self.spectrum_package_label = QLabel("Package:")
        self.spectrum_package_combo = QComboBox()
        self.spectrum_package_combo.currentTextChanged.connect(self._on_spectrum_package_changed)
        self.spectrum_channel_checks = [
            QCheckBox(f"Ch_{i}") for i in range(SPECTRUM_CHANNELS_PER_PACKAGE)
        ]

    # --- collaborators the panel calls into -------------------------------
    def get_spectrum_available_packages(self):
        return list(self._packages) if self._array_mode else []

    def _resolve_spectrum_channel_specs(self):
        if not self._array_mode:
            specs = [{"key": ("adc", n), "label": f"Ch {n}"} for n in range(5)]
            return specs, None
        selected = self.spectrum_selected_package
        if selected not in self._packages:
            selected = self._packages[0] if self._packages else None
        if selected is None:
            return [], None
        specs = [
            {"key": ("sensor", selected, p, 0), "label": f"{selected}_{p}"}
            for p in PLACEMENTS
        ]
        return specs, selected

    @staticmethod
    def _spectrum_channel_label(spec, package_id):
        label = str(spec.get("label", ""))
        if package_id is not None:
            return label
        key = spec.get("key")
        if isinstance(key, tuple) and len(key) >= 2 and key[0] == "adc":
            return f"Ch_{key[1]}"
        return label.replace(" ", "_")

    def reset_spectrum_averaging(self):
        return None

    def save_last_spectrum_settings(self):
        self.saved_settings_count += 1


class PackageComboTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Keep the reference: a garbage-collected QApplication crashes Qt.
        cls.app = QApplication.instance() or QApplication([])

    def test_combo_populates_and_defaults_to_first_package(self):
        host = _PanelHost()

        host.refresh_spectrum_package_options()

        items = [host.spectrum_package_combo.itemText(i) for i in range(host.spectrum_package_combo.count())]
        self.assertEqual(items, PACKAGES)
        self.assertEqual(host.spectrum_selected_package, "PZT1")

    def test_combo_is_visible_in_array_mode(self):
        host = _PanelHost()

        host.refresh_spectrum_package_options()

        self.assertTrue(host.spectrum_package_combo.isVisibleTo(host.spectrum_package_combo))
        self.assertTrue(host.spectrum_package_label.isVisibleTo(host.spectrum_package_label))

    def test_combo_is_hidden_in_manual_mode(self):
        host = _PanelHost(array_mode=False)

        host.refresh_spectrum_package_options()

        self.assertFalse(host.spectrum_package_combo.isVisible())
        self.assertFalse(host.spectrum_package_label.isVisible())
        self.assertIsNone(host.spectrum_selected_package)

    def test_selection_survives_a_refresh_when_the_package_remains(self):
        host = _PanelHost()
        host.refresh_spectrum_package_options()
        host.spectrum_package_combo.setCurrentText("PZT5")

        host.refresh_spectrum_package_options()

        self.assertEqual(host.spectrum_selected_package, "PZT5")

    def test_selection_falls_back_when_the_package_disappears(self):
        host = _PanelHost()
        host.refresh_spectrum_package_options()
        host.spectrum_package_combo.setCurrentText("PZT5")

        host._packages = ["PZT1", "PZT3"]
        host.refresh_spectrum_package_options()

        self.assertEqual(host.spectrum_selected_package, "PZT1")


class ChannelLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Keep the reference: a garbage-collected QApplication crashes Qt.
        cls.app = QApplication.instance() or QApplication([])

    def test_checkbox_labels_follow_the_selected_package(self):
        host = _PanelHost()
        host.refresh_spectrum_package_options()

        self.assertEqual(
            [check.text() for check in host.spectrum_channel_checks],
            [f"PZT1_{p}" for p in PLACEMENTS],
        )

        host.spectrum_package_combo.setCurrentText("PZT3")

        self.assertEqual(
            [check.text() for check in host.spectrum_channel_checks],
            [f"PZT3_{p}" for p in PLACEMENTS],
        )

    def test_manual_mode_uses_underscore_channel_labels(self):
        host = _PanelHost(array_mode=False)

        host.refresh_spectrum_package_options()

        self.assertEqual(
            [check.text() for check in host.spectrum_channel_checks],
            [f"Ch_{n}" for n in range(SPECTRUM_CHANNELS_PER_PACKAGE)],
        )

    def test_changing_package_persists_the_choice(self):
        host = _PanelHost()
        host.refresh_spectrum_package_options()
        before = host.saved_settings_count

        host.spectrum_package_combo.setCurrentText("PZT5")

        self.assertGreater(host.saved_settings_count, before)


if __name__ == "__main__":
    unittest.main()
