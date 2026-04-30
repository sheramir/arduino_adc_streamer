"""Tests for the pressure-map heatmap widget update behavior."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6.QtWidgets import QApplication

from constants.pressure_map import PRESSURE_MAP_BACKGROUND_COLOR, PRESSURE_MAP_OVERLAY_COLOR
from data_processing.normal_force_calculator import NormalForceCalculator
from data_processing.pressure_map_generator import PressureMapGenerator
from data_processing.shear_detector import ShearDetector
from gui.pressure_map_widget import PressureMapPackageDisplay, PressureMapWidget


class PressureMapWidgetTests(unittest.TestCase):
    """Verify pressure-map widget readout and overlay state."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widget = PressureMapWidget()
        self.calculator = NormalForceCalculator()
        self.generator = PressureMapGenerator()
        self.detector = ShearDetector()

    def tearDown(self):
        self.widget.close()

    def test_no_data_clears_readout_and_markers(self):
        self.widget.update_display(None, None)

        self.assertEqual(self.widget.readout_label.text(), "No Data")
        self.assertEqual(len(self.widget.sensor_marker_item.points()), 0)

    def test_update_display_shows_force_readout_and_sensor_markers(self):
        normal_result = self.calculator.compute({"C": 0.0, "R": 5.0, "T": 0.0, "L": 0.0, "B": 0.0})
        pressure_result = self.generator.generate(normal_result.normalized)

        self.widget.update_display(normal_result, pressure_result)

        self.assertIn("Normal:", self.widget.readout_label.text())
        self.assertIn("Quadrants:", self.widget.readout_label.text())
        self.assertEqual(self.widget.last_pressure_result, pressure_result)
        self.assertEqual(len(self.widget.sensor_marker_item.points()), len(pressure_result.sensor_positions))
        self.assertTrue(self.widget.circle_item.isVisible())

    def test_pressure_map_uses_combined_dark_axisless_overlay(self):
        shear_result = self.detector.detect({"C": 0.0, "L": -1.0, "R": 1.0, "T": 0.0, "B": 0.0})
        normal_result = self.calculator.compute(shear_result.residual)
        pressure_result = self.generator.generate(normal_result.normalized)

        self.widget.update_display(normal_result, pressure_result, shear_result)

        self.assertEqual(
            self.widget.plot_widget.backgroundBrush().color().name().lower(),
            PRESSURE_MAP_BACKGROUND_COLOR.lower(),
        )
        self.assertFalse(self.widget.plot_widget.getPlotItem().getAxis("bottom").isVisible())
        self.assertFalse(self.widget.plot_widget.getPlotItem().getAxis("left").isVisible())
        self.assertEqual(
            self.widget.circle_item.pen().color().name().lower(),
            PRESSURE_MAP_OVERLAY_COLOR.lower(),
        )
        self.assertEqual(
            self.widget.sensor_marker_item.points()[0].brush().color().name().lower(),
            PRESSURE_MAP_OVERLAY_COLOR.lower(),
        )
        self.assertTrue(self.widget.last_arrow_geometry.visible)
        self.assertTrue(self.widget.arrow_line_item.isVisible())
        self.assertIn("Shear:", self.widget.readout_label.text())

    def test_multiple_package_displays_use_grid_positions_and_distinct_colors(self):
        first_shear = self.detector.detect({"C": 0.0, "L": -1.0, "R": 1.0, "T": 0.0, "B": 0.0})
        second_shear = self.detector.detect({"C": 0.0, "L": 0.0, "R": 0.0, "T": 1.0, "B": -1.0})
        first_normal = self.calculator.compute(first_shear.residual)
        second_normal = self.calculator.compute(second_shear.residual)
        first_pressure = self.generator.generate(first_normal.normalized)
        second_pressure = self.generator.generate(second_normal.normalized)
        first_color = self.widget.package_color_for_index(0)
        second_color = self.widget.package_color_for_index(1)

        self.widget.update_package_displays([
            PressureMapPackageDisplay(
                sensor_id="PZT3",
                normal_force_result=first_normal,
                pressure_result=first_pressure,
                shear_result=first_shear,
                grid_position=(0, 0),
                color=first_color,
            ),
            PressureMapPackageDisplay(
                sensor_id="PZT5",
                normal_force_result=second_normal,
                pressure_result=second_pressure,
                shear_result=second_shear,
                grid_position=(0, 1),
                color=second_color,
            ),
        ])

        self.assertEqual(len(self.widget.last_package_displays), 2)
        self.assertTrue(self.widget.package_circle_items[0].isVisible())
        self.assertTrue(self.widget.package_circle_items[1].isVisible())
        self.assertNotEqual(
            self.widget.package_circle_items[0].rect().center().x(),
            self.widget.package_circle_items[1].rect().center().x(),
        )
        self.assertEqual(
            self.widget.package_circle_items[0].pen().color().name().lower(),
            first_color.lower(),
        )
        self.assertEqual(
            self.widget.package_sensor_marker_items[1].points()[0].brush().color().name().lower(),
            second_color.lower(),
        )
        self.assertTrue(self.widget.package_arrow_items[0][0].isVisible())
        self.assertTrue(self.widget.package_arrow_items[1][0].isVisible())
        self.assertTrue(self.widget.package_label_items[0].isVisible())
        self.assertTrue(self.widget.package_label_items[1].isVisible())
        self.assertEqual(self.widget.package_label_items[0].toPlainText(), "PZT3")
        self.assertEqual(self.widget.package_label_items[1].toPlainText(), "PZT5")
        self.assertIn("PZT3", self.widget.readout_label.text())
        self.assertIn("PZT5", self.widget.readout_label.text())

    def test_multiple_package_display_range_contains_full_circles(self):
        first_shear = self.detector.detect({"C": 0.0, "L": -1.0, "R": 1.0, "T": 0.0, "B": 0.0})
        second_shear = self.detector.detect({"C": 0.0, "L": 0.0, "R": 0.0, "T": 1.0, "B": -1.0})
        first_normal = self.calculator.compute(first_shear.residual)
        second_normal = self.calculator.compute(second_shear.residual)
        first_pressure = self.generator.generate(first_normal.normalized)
        second_pressure = self.generator.generate(second_normal.normalized)

        self.widget.update_package_displays([
            PressureMapPackageDisplay(
                sensor_id="PZT3",
                normal_force_result=first_normal,
                pressure_result=first_pressure,
                shear_result=first_shear,
                grid_position=(0, 0),
                color=self.widget.package_color_for_index(0),
            ),
            PressureMapPackageDisplay(
                sensor_id="PZT5",
                normal_force_result=second_normal,
                pressure_result=second_pressure,
                shear_result=second_shear,
                grid_position=(0, 2),
                color=self.widget.package_color_for_index(1),
            ),
            PressureMapPackageDisplay(
                sensor_id="PZT7",
                normal_force_result=second_normal,
                pressure_result=second_pressure,
                shear_result=second_shear,
                grid_position=(1, 1),
                color=self.widget.package_color_for_index(2),
            ),
        ])

        (x_min, x_max), (y_min, y_max) = self.widget.plot_widget.viewRange()
        for circle_item in self.widget.package_circle_items[:3]:
            circle_rect = circle_item.rect()
            self.assertGreaterEqual(circle_rect.left(), x_min)
            self.assertLessEqual(circle_rect.right(), x_max)
            self.assertGreaterEqual(circle_rect.top(), y_min)
            self.assertLessEqual(circle_rect.bottom(), y_max)

    def test_grayscale_lookup_table_runs_from_black_to_white(self):
        lookup_table = self.widget._grayscale_lookup_table()

        self.assertTrue(np.array_equal(lookup_table[0], np.array([0, 0, 0], dtype=np.uint8)))
        self.assertTrue(np.array_equal(lookup_table[-1], np.array([255, 255, 255], dtype=np.uint8)))

    def test_pressure_levels_use_fixed_max_intensity(self):
        pressure_grid = np.array([[6.0, 0.0], [3.0, 1.0]], dtype=np.float64)
        single_sensor_result = self.calculator.compute({"C": 0.0, "R": 6.0, "T": 0.0, "L": 0.0, "B": 0.0})
        all_sensor_result = self.calculator.compute({"C": 10.0, "R": 4.0, "T": 4.0, "L": 4.0, "B": 4.0})
        self.widget.configure_intensity(max_intensity=7.5)

        single_levels = self.widget._pressure_levels(single_sensor_result, pressure_grid)
        all_levels = self.widget._pressure_levels(all_sensor_result, pressure_grid)

        self.assertEqual(single_levels, (0.0, 7.5))
        self.assertEqual(all_levels, (0.0, 7.5))

    def test_pressure_levels_use_fixed_max_intensity_for_tension(self):
        pressure_grid = np.array([[-4.0, 0.0], [-2.0, -1.0]], dtype=np.float64)
        tension_result = self.calculator.compute({"C": -4.0, "R": 0.0, "T": 0.0, "L": 0.0, "B": 0.0})
        self.widget.configure_intensity(max_intensity=5.0)

        levels = self.widget._pressure_levels(tension_result, pressure_grid)

        self.assertEqual(levels, (0.0, 5.0))

    def test_pressure_levels_revert_to_normalized_when_max_intensity_is_zero(self):
        pressure_grid = np.array([[6.0, 0.0], [3.0, 1.0]], dtype=np.float64)
        all_sensor_result = self.calculator.compute({"C": 10.0, "R": 4.0, "T": 4.0, "L": 4.0, "B": 4.0})
        self.widget.configure_intensity(max_intensity=0.0)

        levels = self.widget._pressure_levels(all_sensor_result, pressure_grid)

        self.assertEqual(levels, (0.0, 12.0))

    def test_peak_markers_render_for_peaked_quadrants(self):
        signals = {"C": 5.0, "R": 5.0, "T": 5.0, "L": 5.0, "B": 5.0}
        normal_result = self.calculator.compute(signals)
        pressure_result = self.generator.generate(signals)

        self.widget.configure_markers(show_marker=True)
        self.widget.update_display(normal_result, pressure_result)

        self.assertGreater(len(self.widget.peak_marker_item.points()), 0)

    def test_peak_markers_can_be_hidden(self):
        signals = {"C": 5.0, "R": 5.0, "T": 5.0, "L": 5.0, "B": 5.0}
        normal_result = self.calculator.compute(signals)
        pressure_result = self.generator.generate(signals)

        self.widget.configure_markers(show_marker=False)
        self.widget.update_display(normal_result, pressure_result)

        self.assertEqual(len(self.widget.peak_marker_item.points()), 0)


if __name__ == "__main__":
    unittest.main()
