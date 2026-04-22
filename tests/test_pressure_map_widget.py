"""Tests for the pressure-map heatmap widget update behavior."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from data_processing.normal_force_calculator import NormalForceCalculator
from data_processing.pressure_map_generator import PressureMapGenerator
from gui.pressure_map_widget import PressureMapWidget


class PressureMapWidgetTests(unittest.TestCase):
    """Verify pressure-map widget readout and overlay state."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widget = PressureMapWidget()
        self.calculator = NormalForceCalculator()
        self.generator = PressureMapGenerator()

    def tearDown(self):
        self.widget.close()

    def test_no_data_clears_readout_and_markers(self):
        self.widget.update_display(None, None)

        self.assertEqual(self.widget.readout_label.text(), "No Data")
        self.assertEqual(len(self.widget.peak_marker_item.points()), 0)

    def test_update_display_shows_force_readout_and_peak_marker(self):
        normal_result = self.calculator.compute({"C": 0.0, "R": 5.0, "T": 0.0, "L": 0.0, "B": 0.0})
        pressure_result = self.generator.generate(normal_result.normalized)

        self.widget.update_display(normal_result, pressure_result)

        self.assertIn("Normal:", self.widget.readout_label.text())
        self.assertIn("Peaks:", self.widget.readout_label.text())
        self.assertEqual(self.widget.last_pressure_result, pressure_result)
        self.assertEqual(len(self.widget.peak_marker_item.points()), len(pressure_result.peaks))
        self.assertTrue(self.widget.circle_item.isVisible())


if __name__ == "__main__":
    unittest.main()
