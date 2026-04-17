"""Tests for the Shear Visualization widget geometry and readout state."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from constants.shear import (
    DEFAULT_SENSOR_SPACING_MM,
    SHEAR_LAYOUT_MIN_VISIBLE_LINE_WIDTH_PX,
    SHEAR_POSITION_BOTTOM,
    SHEAR_POSITION_CENTER,
    SHEAR_POSITION_LEFT,
    SHEAR_POSITION_RIGHT,
    SHEAR_POSITION_TOP,
)
from data_processing.shear_detector import ShearDetector
from gui.shear_visualization_widget import ShearVisualizationWidget


class ShearVisualizationWidgetTests(unittest.TestCase):
    """Verify arrow visibility, direction, scaling, clamping, and layout."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.detector = ShearDetector()
        self.widget = ShearVisualizationWidget()

    def tearDown(self):
        self.widget.close()

    def test_zero_shear_hides_arrow(self):
        result = self.detector.detect({"C": 0.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.0})

        self.widget.update_display(result)

        self.assertFalse(self.widget.last_arrow_geometry.visible)
        self.assertFalse(self.widget.arrow_line_item.isVisible())
        self.assertEqual(self.widget.readout_label.text(), "No Shear")

    def test_horizontal_shear_points_right(self):
        result = self.detector.detect({"C": 0.0, "L": -1.0, "R": 1.0, "T": 0.0, "B": 0.0})

        geometry = self.widget.calculate_arrow_geometry(result)

        self.assertTrue(geometry.visible)
        self.assertGreater(geometry.tip_x, geometry.origin_x)
        self.assertAlmostEqual(geometry.tip_y, geometry.origin_y)

    def test_vertical_shear_points_up(self):
        result = self.detector.detect({"C": 0.0, "L": 0.0, "R": 0.0, "T": 1.0, "B": -1.0})

        geometry = self.widget.calculate_arrow_geometry(result)

        self.assertTrue(geometry.visible)
        self.assertGreater(geometry.tip_y, geometry.origin_y)
        self.assertAlmostEqual(geometry.tip_x, geometry.origin_x)

    def test_diagonal_shear_points_upper_right(self):
        result = self.detector.detect({"C": 0.0, "L": -1.0, "R": 1.0, "T": 1.0, "B": -1.0})

        geometry = self.widget.calculate_arrow_geometry(result)

        self.assertTrue(geometry.visible)
        self.assertGreater(geometry.tip_x, geometry.origin_x)
        self.assertGreater(geometry.tip_y, geometry.origin_y)
        self.assertAlmostEqual(geometry.tip_x, geometry.tip_y)

    def test_arrow_length_scales_with_magnitude(self):
        small = self.detector.detect({"C": 0.0, "L": -1.0, "R": 1.0, "T": 0.0, "B": 0.0})
        large = self.detector.detect({"C": 0.0, "L": -2.0, "R": 2.0, "T": 0.0, "B": 0.0})

        small_geometry = self.widget.calculate_arrow_geometry(small)
        large_geometry = self.widget.calculate_arrow_geometry(large)

        self.assertGreater(large_geometry.length, small_geometry.length)

    def test_arrow_length_clamps_to_circle_radius(self):
        huge = self.detector.detect({"C": 0.0, "L": -100.0, "R": 100.0, "T": 0.0, "B": 0.0})

        geometry = self.widget.calculate_arrow_geometry(huge)

        self.assertLessEqual(geometry.length, self.widget.circle_radius_mm)

    def test_arrow_width_scales_with_magnitude(self):
        small = self.detector.detect({"C": 0.0, "L": -1.0, "R": 1.0, "T": 0.0, "B": 0.0})
        large = self.detector.detect({"C": 0.0, "L": -2.0, "R": 2.0, "T": 0.0, "B": 0.0})

        small_geometry = self.widget.calculate_arrow_geometry(small)
        large_geometry = self.widget.calculate_arrow_geometry(large)

        self.assertGreater(large_geometry.width_px, small_geometry.width_px)

    def test_scaled_arrow_width_is_not_smaller_than_selected_base_width(self):
        result = self.detector.detect({"C": 0.0, "L": -1.0, "R": 1.0, "T": 0.0, "B": 0.0})

        self.widget.configure(arrow_base_width_px=6.0, arrow_width_scales=True)
        geometry = self.widget.calculate_arrow_geometry(result)

        self.assertGreaterEqual(geometry.width_px, 6.0)

    def test_arrow_shaft_pen_width_uses_scaled_width(self):
        result = self.detector.detect({"C": 0.0, "L": -1.0, "R": 1.0, "T": 0.0, "B": 0.0})

        self.widget.configure(arrow_base_width_px=1.0, arrow_width_scales=False)
        self.widget.update_display(result)
        fixed_width = self.widget.arrow_line_item.pen().widthF()

        self.widget.configure(arrow_base_width_px=1.0, arrow_width_scales=True)
        self.widget.update_display(result)
        scaled_width = self.widget.arrow_line_item.pen().widthF()

        self.assertGreater(scaled_width, fixed_width)
        self.assertAlmostEqual(scaled_width, self.widget.last_arrow_geometry.width_px)

    def test_arrow_width_does_not_scale_with_arrow_gain(self):
        result = self.detector.detect({"C": 0.0, "L": -1.0, "R": 1.0, "T": 0.0, "B": 0.0})

        self.widget.configure(arrow_gain=1.0)
        normal_gain_geometry = self.widget.calculate_arrow_geometry(result)
        self.widget.configure(arrow_gain=10.0)
        high_gain_geometry = self.widget.calculate_arrow_geometry(result)

        self.assertGreater(high_gain_geometry.length, normal_gain_geometry.length)
        self.assertAlmostEqual(high_gain_geometry.width_px, normal_gain_geometry.width_px)

    def test_arrow_shaft_ends_at_head_base_not_tip(self):
        result = self.detector.detect({"C": 0.0, "L": -1.0, "R": 1.0, "T": 0.0, "B": 0.0})

        self.widget.update_display(result)
        line = self.widget.arrow_line_item.line()
        geometry = self.widget.last_arrow_geometry

        self.assertLess(line.x2(), geometry.tip_x)
        self.assertAlmostEqual(line.y2(), geometry.tip_y)

    def test_arrow_head_tip_points_away_from_body(self):
        result = self.detector.detect({"C": 0.0, "L": -1.0, "R": 1.0, "T": 0.0, "B": 0.0})

        self.widget.update_display(result)
        polygon = self.widget.arrow_head_item.polygon()
        left_base = polygon.at(0)
        tip = polygon.at(1)
        right_base = polygon.at(2)

        self.assertGreater(tip.x(), left_base.x())
        self.assertGreater(tip.x(), right_base.x())

    def test_static_and_arrow_pens_are_cosmetic(self):
        result = self.detector.detect({"C": 0.0, "L": -1.0, "R": 1.0, "T": 0.0, "B": 0.0})

        self.widget.update_display(result)

        self.assertTrue(self.widget.circle_item.pen().isCosmetic())
        self.assertTrue(self.widget.sensor_items[SHEAR_POSITION_CENTER].pen().isCosmetic())
        self.assertTrue(self.widget.arrow_line_item.pen().isCosmetic())

    def test_static_layout_pen_widths_remain_visible(self):
        self.assertGreaterEqual(
            self.widget.circle_item.pen().widthF(),
            SHEAR_LAYOUT_MIN_VISIBLE_LINE_WIDTH_PX,
        )
        self.assertGreaterEqual(
            self.widget.sensor_items[SHEAR_POSITION_CENTER].pen().widthF(),
            SHEAR_LAYOUT_MIN_VISIBLE_LINE_WIDTH_PX,
        )

    def test_sensor_positions_are_drawn_at_expected_coordinates(self):
        positions = self.widget.sensor_positions

        self.assertEqual(positions[SHEAR_POSITION_CENTER], (0.0, 0.0))
        self.assertEqual(positions[SHEAR_POSITION_LEFT], (-DEFAULT_SENSOR_SPACING_MM, 0.0))
        self.assertEqual(positions[SHEAR_POSITION_RIGHT], (DEFAULT_SENSOR_SPACING_MM, 0.0))
        self.assertEqual(positions[SHEAR_POSITION_TOP], (0.0, DEFAULT_SENSOR_SPACING_MM))
        self.assertEqual(positions[SHEAR_POSITION_BOTTOM], (0.0, -DEFAULT_SENSOR_SPACING_MM))
        self.assertEqual(set(self.widget.sensor_items), set(positions))


if __name__ == "__main__":
    unittest.main()
