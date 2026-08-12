"""Tests for the pressure-map heatmap widget update behavior."""

import os
import unittest
from dataclasses import replace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWidgets import QGraphicsEllipseItem

from constants.pressure_map import (
    PRESSURE_DISPLAY_MODE_MAGNITUDE,
    PRESSURE_DISPLAY_MODE_SIGNED,
    PRESSURE_MAP_BACKGROUND_COLOR,
    PRESSURE_MAP_OVERLAY_COLOR,
)
from data_processing.normal_force_calculator import NormalForceCalculator
from data_processing.pressure_force_display import ForceMapArrayResult, ForceMapPackageResult
from data_processing.pressure_map_array_generator import PressureMapArrayGenerator, PressureMapArrayPackage
from data_processing.pressure_map_geometry import PressureMapGeometry
from data_processing.pressure_map_mask import mask_inside_grid
from data_processing.pressure_map_generator import PressureMapGenerator
from data_processing.shear_detector import ShearDetector
from gui.pressure_map_widget import (
    PressureMapPackageDisplay,
    PressureMapWidget,
    image_rect_from_centers,
)


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

    def test_force_render_uses_a_stable_newton_scale_instead_of_jerk_intensity(self):
        self.widget.configure_intensity(max_intensity=2.0)
        self.widget.configure_force_intensity(max_force_n=0.2)
        levels, fade_levels = self.widget._force_render_levels(
            np.asarray([[0.0, 0.04], [0.08, -0.12]], dtype=float)
        )

        self.assertEqual(levels[0], 0.0)
        self.assertAlmostEqual(levels[1], 0.2)
        self.assertAlmostEqual(fade_levels[0], 0.0)
        self.assertAlmostEqual(fade_levels[1], 0.0025)

    def test_force_alpha_uses_physical_floor_and_opaque_force_lookup_table(self):
        self.widget.configure_force_display_floor(noise_equivalent_n=0.0025)
        lookup = self.widget._color_lookup_table(force_mode=True)
        if lookup.shape[1] == 4:
            self.assertTrue(np.all(lookup[:, 3] == 255))
        rgba = self.widget._rgba_image(
            np.asarray([[0.0, 0.0025, 0.005]], dtype=float),
            (0.0, 0.25),
            fade_levels=(0.0, 0.0025),
            force_mode=True,
        )
        self.assertEqual(rgba[0, 0, 3], 0)
        self.assertGreater(rgba[0, 1, 3], 0)
        self.assertEqual(rgba[0, 2, 3], 255)

    def test_force_visibility_is_identical_for_opposite_signed_values(self):
        self.widget.configure_display_mode(display_mode=PRESSURE_DISPLAY_MODE_SIGNED)
        levels, fade_levels = self.widget._force_render_levels(np.asarray([[1.0]], dtype=float))
        positive = self.widget._rgba_image(
            np.asarray([[1.0, 0.1]], dtype=float), levels,
            fade_levels=fade_levels, force_mode=True,
        )
        negative = self.widget._rgba_image(
            np.asarray([[-1.0, -0.1]], dtype=float), levels,
            fade_levels=fade_levels, force_mode=True,
        )

        np.testing.assert_array_equal(positive, negative)
        self.assertEqual(levels, (0.0, self.widget.force_max_intensity_n))

    def test_force_readout_retains_signed_normal_force(self):
        geometry = PressureMapGeometry()
        template = self.generator.generate({"C": 0.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.0})
        result = ForceMapPackageResult(
            sensor_id="PZT1",
            force_grid_n=-np.ones_like(template.pressure_grid),
            normal_force_n=-0.125,
            shear_x_n=-0.02,
            shear_y_n=0.01,
            geometry=geometry,
            x_coordinates_mm=template.x_coordinates_mm,
            y_coordinates_mm=template.y_coordinates_mm,
            sensor_positions=template.sensor_positions,
            grid_position=(0, 0),
            frame_id=1,
        )
        self.widget.configure_display_mode(display_mode=PRESSURE_DISPLAY_MODE_SIGNED)
        self.widget.update_force_display(result)

        self.assertEqual(result.normal_force_n, -0.125)
        self.assertIn("Normal Force: -0.125 N", self.widget.readout_label.text())

    def test_configure_arrow_sets_the_force_specific_width_reference_magnitude(self):
        from constants.shear import SHEAR_ARROW_WIDTH_REFERENCE_MAGNITUDE

        self.assertEqual(self.widget.arrow_width_reference_magnitude, SHEAR_ARROW_WIDTH_REFERENCE_MAGNITUDE)

        self.widget.configure_arrow(arrow_width_reference_magnitude=0.25)

        self.assertEqual(self.widget.arrow_width_reference_magnitude, 0.25)

    def test_force_display_draws_shear_arrow_from_force_derived_result(self):
        geometry = PressureMapGeometry()
        template = self.generator.generate({"C": 0.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.0})
        shear_result = self.detector.detect({"C": 0.0, "L": -1.0, "R": 1.0, "T": 0.0, "B": 0.0})
        result = ForceMapPackageResult(
            sensor_id="PZT1",
            force_grid_n=np.zeros_like(template.pressure_grid),
            normal_force_n=0.0,
            shear_x_n=shear_result.b_lr,
            shear_y_n=shear_result.b_tb,
            geometry=geometry,
            x_coordinates_mm=template.x_coordinates_mm,
            y_coordinates_mm=template.y_coordinates_mm,
            sensor_positions=template.sensor_positions,
            grid_position=(0, 0),
            frame_id=1,
            shear_result=shear_result,
        )

        self.widget.update_force_display(result)

        self.assertTrue(self.widget.last_arrow_geometry.visible)
        self.assertTrue(self.widget.arrow_line_item.isVisible())
        expected_geometry = self.widget.calculate_arrow_geometry(shear_result)
        self.assertAlmostEqual(self.widget.last_arrow_geometry.length, expected_geometry.length)
        self.assertAlmostEqual(self.widget.last_arrow_geometry.angle_deg, expected_geometry.angle_deg)

    def test_force_display_hides_arrow_without_shear_result_or_below_threshold(self):
        geometry = PressureMapGeometry()
        template = self.generator.generate({"C": 0.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.0})
        no_shear = self.detector.detect({"C": 0.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.0})
        result = ForceMapPackageResult(
            sensor_id="PZT1",
            force_grid_n=np.zeros_like(template.pressure_grid),
            normal_force_n=0.0,
            shear_x_n=0.0,
            shear_y_n=0.0,
            geometry=geometry,
            x_coordinates_mm=template.x_coordinates_mm,
            y_coordinates_mm=template.y_coordinates_mm,
            sensor_positions=template.sensor_positions,
            grid_position=(0, 0),
            frame_id=1,
            shear_result=no_shear,
        )

        self.widget.update_force_display(result)
        self.assertFalse(self.widget.last_arrow_geometry.visible)
        self.assertFalse(self.widget.arrow_line_item.isVisible())

        # A fresh/reset package (shear_result=None) also hides the arrow.
        none_result = replace(result, shear_result=None, frame_id=2)
        self.widget.update_force_display(none_result)
        self.assertFalse(self.widget.last_arrow_geometry.visible)
        self.assertFalse(self.widget.arrow_line_item.isVisible())

        # Nonzero shear below an explicit threshold is also hidden.
        self.widget.configure_arrow(arrow_min_threshold=10.0)
        shear_result = self.detector.detect({"C": 0.0, "L": -1.0, "R": 1.0, "T": 0.0, "B": 0.0})
        thresholded = replace(
            result,
            shear_x_n=shear_result.b_lr,
            shear_y_n=shear_result.b_tb,
            shear_result=shear_result,
            frame_id=3,
        )
        self.widget.update_force_display(thresholded)
        self.assertFalse(self.widget.last_arrow_geometry.visible)

    def test_force_array_reuses_jerk_package_background_primitives(self):
        geometry = PressureMapGeometry()
        template = self.generator.generate({"C": 0.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.0})
        package_grid = np.zeros_like(template.pressure_grid)
        packages = [
            ForceMapPackageResult(
                sensor_id=sensor_id,
                force_grid_n=package_grid.copy(),
                normal_force_n=0.0,
                shear_x_n=0.0,
                shear_y_n=0.0,
                geometry=geometry,
                x_coordinates_mm=template.x_coordinates_mm,
                y_coordinates_mm=template.y_coordinates_mm,
                sensor_positions=template.sensor_positions,
                grid_position=(0, index),
                frame_id=index + 1,
            )
            for index, sensor_id in enumerate(("PZT1", "PZT2"))
        ]
        array = ForceMapArrayResult(
            force_grid_n=np.zeros((template.y_coordinates_mm.size, template.x_coordinates_mm.size)),
            magnitude_force_grid_n=np.zeros((template.y_coordinates_mm.size, template.x_coordinates_mm.size)),
            x_coordinates_mm=template.x_coordinates_mm,
            y_coordinates_mm=template.y_coordinates_mm,
            package_centers={"PZT1": (-5.0, 0.0), "PZT2": (5.0, 0.0)},
            frame_id=1,
        )
        self.widget.configure_mask(
            mask_enabled=True,
            mask_points_mm=((-8.0, -8.0), (8.0, -8.0), (8.0, 8.0), (-8.0, 8.0)),
        )
        self.widget.configure_boundary_visibility(show_outer_boundary=True)
        self.widget.update_force_array_display(array, packages)

        self.assertTrue(self.widget.package_circle_items[0].isVisible())
        self.assertTrue(self.widget.package_outer_boundary_items[1].isVisible())
        self.assertEqual(len(self.widget.package_sensor_marker_items[0].points()), 5)
        self.assertFalse(self.widget.package_label_items[1].isVisible())
        self.assertTrue(self.widget.force_callout_items[1].isVisible())
        self.assertIn("N:", self.widget.force_callout_items[1].toPlainText())
        self.assertIn("S:", self.widget.force_callout_items[1].toPlainText())
        self.assertEqual(len(self.widget.package_peak_marker_items[0].points()), 0)
        self.assertTrue(self.widget.mask_outline_item.isVisible())

        initial_size_hint = self.widget.sizeHint().width()
        initial_range = self.widget.plot_widget.getViewBox().viewRange()
        updated_packages = [
            replace(item, normal_force_n=(-1.0 if index else 1.0), shear_x_n=0.123)
            for index, item in enumerate(packages)
        ]
        updated_array = replace(array, force_grid_n=np.full_like(array.force_grid_n, 0.1), frame_id=2)
        self.widget.update_force_array_display(updated_array, updated_packages)

        self.assertEqual(self.widget.sizeHint().width(), initial_size_hint)
        self.assertEqual(self.widget.plot_widget.getViewBox().viewRange(), initial_range)
        self.assertFalse(self.widget.readout_label.isVisible())

    def test_force_array_draws_per_package_shear_arrow_and_hides_for_zero_package(self):
        geometry = PressureMapGeometry()
        template = self.generator.generate({"C": 0.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.0})
        shear_result = self.detector.detect({"C": 0.0, "L": -1.0, "R": 1.0, "T": 0.0, "B": 0.0})
        packages = [
            ForceMapPackageResult(
                sensor_id="PZT1",
                force_grid_n=np.zeros_like(template.pressure_grid),
                normal_force_n=0.0,
                shear_x_n=shear_result.b_lr,
                shear_y_n=shear_result.b_tb,
                geometry=geometry,
                x_coordinates_mm=template.x_coordinates_mm,
                y_coordinates_mm=template.y_coordinates_mm,
                sensor_positions=template.sensor_positions,
                grid_position=(0, 0),
                frame_id=1,
                shear_result=shear_result,
            ),
            ForceMapPackageResult(
                sensor_id="PZT2",
                force_grid_n=np.zeros_like(template.pressure_grid),
                normal_force_n=0.0,
                shear_x_n=0.0,
                shear_y_n=0.0,
                geometry=geometry,
                x_coordinates_mm=template.x_coordinates_mm,
                y_coordinates_mm=template.y_coordinates_mm,
                sensor_positions=template.sensor_positions,
                grid_position=(0, 1),
                frame_id=2,
                shear_result=None,
            ),
        ]
        array = ForceMapArrayResult(
            force_grid_n=np.zeros((template.y_coordinates_mm.size, template.x_coordinates_mm.size)),
            magnitude_force_grid_n=np.zeros((template.y_coordinates_mm.size, template.x_coordinates_mm.size)),
            x_coordinates_mm=template.x_coordinates_mm,
            y_coordinates_mm=template.y_coordinates_mm,
            package_centers={"PZT1": (-5.0, 0.0), "PZT2": (5.0, 0.0)},
            frame_id=1,
        )

        self.widget.update_force_array_display(array, packages)

        self.assertTrue(self.widget.package_arrow_items[0][0].isVisible())
        self.assertFalse(self.widget.package_arrow_items[1][0].isVisible())

    def test_force_callouts_choose_outward_top_and_center_positions_without_collision(self):
        bounds = (-20.0, 20.0, -20.0, 20.0)
        array_center = (0.0, 0.0)
        top = self.widget._force_callout_position(
            0.0, 8.0, array_center, bounds, 6.0, []
        )
        center = self.widget._force_callout_position(
            0.0, 0.0, array_center, bounds, 6.0, [top]
        )

        self.assertGreaterEqual(top[1], 8.0 + 6.0 + 1.5)
        self.assertFalse(abs(top[0] - center[0]) < 4.8 and abs(top[1] - center[1]) < 2.6)

    def test_update_display_skips_unchanged_image_upload(self):
        normal_result = self.calculator.compute({"C": 0.0, "R": 5.0, "T": 0.0, "L": 0.0, "B": 0.0})
        pressure_result = self.generator.generate(normal_result.normalized)

        self.widget.update_display(normal_result, pressure_result)

        image_uploads: list[int] = []
        original_set_image = self.widget.image_item.setImage

        def counting_set_image(*args, **kwargs):
            image_uploads.append(1)
            return original_set_image(*args, **kwargs)

        self.widget.image_item.setImage = counting_set_image
        self.widget.update_display(normal_result, pressure_result)

        self.assertEqual(len(image_uploads), 0)

    def test_new_frame_id_refreshes_image_when_grid_storage_is_reused(self):
        normal_result = self.calculator.compute({"C": 0.0, "R": 5.0, "T": 0.0, "L": 0.0, "B": 0.0})
        pressure_result = self.generator.generate(normal_result.normalized)
        self.widget.update_display(normal_result, pressure_result)
        uploads: list[int] = []
        original_set_image = self.widget.image_item.setImage

        def counting_set_image(*args, **kwargs):
            uploads.append(1)
            return original_set_image(*args, **kwargs)

        self.widget.image_item.setImage = counting_set_image
        pressure_result.pressure_grid[:, :] = 0.0
        refreshed = replace(pressure_result, frame_id=pressure_result.frame_id + 1)
        self.widget.update_display(normal_result, refreshed)
        self.assertEqual(len(uploads), 1)

    def test_rapid_center_outer_edge_frames_never_blank_the_widget(self):
        generator = PressureMapGenerator(natural_decay_reference_distance_mm=1.5)
        self.widget.configure_boundary_visibility(show_outer_boundary=True)
        for index in range(20):
            center, outer = ((0.1, 1.0) if index % 2 else (1.0, 0.4))
            normal_result = self.calculator.compute(
                {"C": center, "R": outer, "T": 0.0, "L": 0.0, "B": 0.0}
            )
            pressure_result = generator.generate(normal_result.normalized)
            self.widget.update_display(normal_result, pressure_result)
            self.assertIs(self.widget.last_pressure_result, pressure_result)
            self.assertTrue(self.widget.outer_boundary_item.isVisible())
            self.assertNotEqual(self.widget.readout_label.text(), "No Data")

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

    def test_multiple_package_displays_skip_unchanged_image_uploads(self):
        first_shear = self.detector.detect({"C": 0.0, "L": -1.0, "R": 1.0, "T": 0.0, "B": 0.0})
        second_shear = self.detector.detect({"C": 0.0, "L": 0.0, "R": 0.0, "T": 1.0, "B": -1.0})
        first_normal = self.calculator.compute(first_shear.residual)
        second_normal = self.calculator.compute(second_shear.residual)
        first_pressure = self.generator.generate(first_normal.normalized)
        second_pressure = self.generator.generate(second_normal.normalized)
        packages = [
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
                grid_position=(0, 1),
                color=self.widget.package_color_for_index(1),
            ),
        ]

        self.widget.update_package_displays(packages)

        image_uploads: list[int] = []
        original_methods = [item.setImage for item in self.widget.package_image_items[:2]]

        for item, original_set_image in zip(self.widget.package_image_items[:2], original_methods):
            def counting_set_image(*args, _original=original_set_image, **kwargs):
                image_uploads.append(1)
                return _original(*args, **kwargs)

            item.setImage = counting_set_image

        self.widget.update_package_displays(packages)

        self.assertEqual(len(image_uploads), 0)

    def test_view_ranges_update_only_when_mode_geometry_or_mirror_changes(self):
        def build_frame(first_values, second_values):
            first_normal = self.calculator.compute(first_values)
            second_normal = self.calculator.compute(second_values)
            first_pressure = self.generator.generate(first_normal.normalized)
            second_pressure = self.generator.generate(second_normal.normalized)
            packages = [
                PressureMapPackageDisplay(
                    sensor_id="PZT3",
                    normal_force_result=first_normal,
                    pressure_result=first_pressure,
                    grid_position=(0, 0),
                    color=self.widget.package_color_for_index(0),
                    calibrated_values=dict(first_values),
                ),
                PressureMapPackageDisplay(
                    sensor_id="PZT5",
                    normal_force_result=second_normal,
                    pressure_result=second_pressure,
                    grid_position=(0, 1),
                    color=self.widget.package_color_for_index(1),
                    calibrated_values=dict(second_values),
                ),
            ]
            array_result = PressureMapArrayGenerator().generate([
                PressureMapArrayPackage(
                    sensor_id=package.sensor_id,
                    grid_position=package.grid_position,
                    normal_force_result=package.normal_force_result,
                    pressure_result=package.pressure_result,
                )
                for package in packages
            ])
            return packages, array_result

        first_packages, first_array = build_frame(
            {"C": 0.0, "L": 0.0, "R": 4.0, "T": 0.0, "B": 0.0},
            {"C": 0.0, "L": 2.0, "R": 0.0, "T": 0.0, "B": 0.0},
        )
        second_packages, second_array = build_frame(
            {"C": 1.0, "L": 0.0, "R": 1.0, "T": 0.0, "B": 0.0},
            {"C": 2.0, "L": 1.0, "R": 0.0, "T": 0.0, "B": 0.0},
        )
        self.widget.update_package_displays(first_packages)

        x_range_calls: list[int] = []
        y_range_calls: list[int] = []
        original_set_x_range = self.widget.plot_widget.setXRange
        original_set_y_range = self.widget.plot_widget.setYRange

        def counting_set_x_range(*args, **kwargs):
            x_range_calls.append(1)
            return original_set_x_range(*args, **kwargs)

        def counting_set_y_range(*args, **kwargs):
            y_range_calls.append(1)
            return original_set_y_range(*args, **kwargs)

        self.widget.plot_widget.setXRange = counting_set_x_range
        self.widget.plot_widget.setYRange = counting_set_y_range

        # New signal values and frame IDs do not change separate-package ranges.
        self.widget.update_package_displays(second_packages)
        self.assertEqual((len(x_range_calls), len(y_range_calls)), (0, 0))

        # A structural mode change resets the signature exactly once.
        self.widget.update_array_display(second_array, second_packages)
        self.assertEqual((len(x_range_calls), len(y_range_calls)), (1, 1))
        x_range_calls.clear()
        y_range_calls.clear()

        # Array ranges also remain stable across signal-dependent fields.
        self.widget.update_array_display(first_array, first_packages)
        self.assertEqual((len(x_range_calls), len(y_range_calls)), (0, 0))

        # Mirror changes invalidate and reapply the current array range.
        self.widget.configure_mirror(mirror=not self.widget.mirror)
        self.assertEqual((len(x_range_calls), len(y_range_calls)), (1, 1))
        x_range_calls.clear()
        y_range_calls.clear()

        # Single mode gets one range update, then keeps it for later frames.
        self.widget.update_display(
            first_packages[0].normal_force_result,
            first_packages[0].pressure_result,
        )
        self.assertEqual((len(x_range_calls), len(y_range_calls)), (1, 1))
        x_range_calls.clear()
        y_range_calls.clear()
        self.widget.update_display(
            second_packages[0].normal_force_result,
            second_packages[0].pressure_result,
        )
        self.assertEqual((len(x_range_calls), len(y_range_calls)), (0, 0))

    def test_array_display_uses_single_image_and_package_overlays(self):
        first_shear = self.detector.detect({"C": 0.0, "L": 0.0, "R": 5.0, "T": 0.0, "B": 0.0})
        second_shear = self.detector.detect({"C": 0.0, "L": 2.0, "R": 0.0, "T": 0.0, "B": 0.0})
        first_normal = self.calculator.compute(first_shear.residual)
        second_normal = self.calculator.compute(second_shear.residual)
        first_pressure = self.generator.generate(first_normal.normalized)
        second_pressure = self.generator.generate(second_normal.normalized)
        packages = [
            PressureMapPackageDisplay(
                sensor_id="PZT3",
                normal_force_result=first_normal,
                pressure_result=first_pressure,
                shear_result=first_shear,
                grid_position=(0, 0),
                color=self.widget.package_color_for_index(0),
                calibrated_values={"C": 0.0, "L": 0.0, "R": 5.0, "T": 0.0, "B": 0.0},
            ),
            PressureMapPackageDisplay(
                sensor_id="PZT6",
                normal_force_result=second_normal,
                pressure_result=second_pressure,
                shear_result=second_shear,
                grid_position=(0, 1),
                color=self.widget.package_color_for_index(1),
                calibrated_values={"C": 0.0, "L": 2.0, "R": 0.0, "T": 0.0, "B": 0.0},
            ),
        ]
        array_result = PressureMapArrayGenerator().generate([
            PressureMapArrayPackage(
                sensor_id=package.sensor_id,
                grid_position=package.grid_position,
                normal_force_result=package.normal_force_result,
                pressure_result=package.pressure_result,
            )
            for package in packages
        ])

        self.widget.configure_boundary_visibility(
            show_near_outer_boundary=True,
            show_outer_boundary=True,
            show_mid_boundary=True,
        )
        self.widget.update_array_display(array_result, packages)

        self.assertEqual(self.widget.last_array_result, array_result)
        self.assertEqual(len(self.widget.last_package_displays), 2)
        self.assertFalse(self.widget.package_image_items[0].isVisible())
        self.assertTrue(self.widget.package_circle_items[0].isVisible())
        self.assertTrue(self.widget.package_circle_items[1].isVisible())
        self.assertTrue(self.widget.package_outer_boundary_items[0].isVisible())
        self.assertTrue(self.widget.package_mid_boundary_items[0].isVisible())
        self.assertNotEqual(
            self.widget.package_outer_boundary_items[0].pen().dashPattern(),
            self.widget.package_mid_boundary_items[0].pen().dashPattern(),
        )
        self.assertIn("PZT3", self.widget.readout_label.text())
        self.assertIn("PZT6", self.widget.readout_label.text())

        self.widget.configure_intensity(max_intensity=1.0)
        self.widget.update_array_display(array_result, packages)
        expected_saturation = self.widget._saturated_pixel_percentage(array_result.pressure_grid)
        self.assertAlmostEqual(self.widget.saturated_pixel_percentage, expected_saturation, places=12)
        np.testing.assert_array_equal(
            self.widget.debug_saturation_mask,
            np.abs(array_result.pressure_grid) >= self.widget.max_intensity,
        )

    def test_array_magnitude_mode_uses_separately_blended_magnitude_grid(self):
        normal = self.calculator.compute({"C": 0.0, "L": 0.0, "R": 2.0, "T": 0.0, "B": 0.0})
        pressure = self.generator.generate(normal.normalized)
        array_result = PressureMapArrayGenerator().generate([
            PressureMapArrayPackage("A", (0, 0), normal, pressure),
        ])
        magnitude = np.full_like(array_result.pressure_grid, 0.75)
        signed = np.zeros_like(array_result.pressure_grid)
        synthetic = replace(
            array_result,
            pressure_grid=signed,
            magnitude_pressure_grid=magnitude,
        )

        self.widget.configure_display_mode(display_mode=PRESSURE_DISPLAY_MODE_MAGNITUDE)
        np.testing.assert_array_equal(self.widget._array_display_grid(synthetic), magnitude)
        self.widget.configure_display_mode(display_mode=PRESSURE_DISPLAY_MODE_SIGNED)
        np.testing.assert_array_equal(self.widget._array_display_grid(synthetic), signed)

    def test_boundary_overlays_use_peak_support_outer_support_and_midpoint_dash_styles(self):
        signals = {"C": 0.0, "R": 5.0, "T": 0.0, "L": 0.0, "B": 0.0}
        normal_result = self.calculator.compute(signals)
        pressure_result = self.generator.generate(signals)
        self.widget.configure_boundary_visibility(
            show_near_outer_boundary=True,
            show_outer_boundary=True,
            show_mid_boundary=True,
        )
        self.widget.update_display(normal_result, pressure_result)

        expected_radius = self.generator.sensor_spacing_mm + self.generator.near_outer_peak_offset_mm
        self.assertAlmostEqual(self.widget.circle_item.rect().width(), expected_radius * 2.0, places=9)
        self.assertTrue(self.widget.circle_item.isVisible())
        self.assertTrue(self.widget.outer_boundary_item.isVisible())
        self.assertTrue(self.widget.mid_boundary_item.isVisible())
        self.assertAlmostEqual(
            self.widget.mid_boundary_item.rect().width(),
            pressure_result.mid_boundary_half_width_mm * 2.0,
        )

        self.widget.configure_boundary_visibility(show_near_outer_boundary=False)
        self.widget.update_display(normal_result, pressure_result)
        self.assertFalse(self.widget.circle_item.isVisible())
        self.assertTrue(self.widget.outer_boundary_item.isVisible())

    def test_grayscale_lookup_table_runs_from_black_to_white(self):
        lookup_table = self.widget._grayscale_lookup_table()

        self.assertTrue(np.array_equal(lookup_table[0], np.array([0, 0, 0], dtype=np.uint8)))
        self.assertTrue(np.array_equal(lookup_table[-1], np.array([255, 255, 255], dtype=np.uint8)))

    def test_color_scale_updates_single_and_package_image_lookup_tables(self):
        self.widget._ensure_package_item_count(1)
        grayscale_lookup = self.widget.image_item.lut.copy()

        self.widget.configure_color_scale(color_scale="Viridis")

        self.assertEqual(self.widget.color_scale, "Viridis")
        self.assertFalse(np.array_equal(self.widget.image_item.lut, grayscale_lookup))
        np.testing.assert_array_equal(self.widget.package_image_items[0].lut, self.widget.image_item.lut)

    def test_red_heavy_color_scales_use_white_shear_arrows(self):
        shear_result = self.detector.detect({"C": 0.0, "L": -1.0, "R": 1.0, "T": 0.0, "B": 0.0})
        normal_result = self.calculator.compute(shear_result.residual)
        pressure_result = self.generator.generate(normal_result.normalized)
        self.widget.update_display(normal_result, pressure_result, shear_result)

        self.widget.configure_color_scale(color_scale="Thermal")

        self.assertEqual(self.widget.arrow_color, "#FFFFFF")
        self.assertEqual(self.widget.arrow_line_item.pen().color().name().upper(), "#FFFFFF")

    def test_pressure_levels_use_fixed_max_intensity(self):
        pressure_grid = np.array([[6.0, 0.0], [3.0, 1.0]], dtype=np.float64)
        single_sensor_result = self.calculator.compute({"C": 0.0, "R": 6.0, "T": 0.0, "L": 0.0, "B": 0.0})
        all_sensor_result = self.calculator.compute({"C": 10.0, "R": 4.0, "T": 4.0, "L": 4.0, "B": 4.0})
        self.widget.configure_intensity(max_intensity=7.5)

        single_levels = self.widget._pressure_levels(single_sensor_result, pressure_grid)
        all_levels = self.widget._pressure_levels(all_sensor_result, pressure_grid)

        self.assertEqual(single_levels, (0.0, 7.5))
        self.assertEqual(all_levels, (0.0, 7.5))

    def test_noise_floor_controls_smooth_display_alpha_not_numeric_levels(self):
        pressure_grid = np.array([[6.0, 0.0], [3.0, 1.0]], dtype=np.float64)
        result = self.calculator.compute({"C": 0.0, "R": 6.0, "T": 0.0, "L": 0.0, "B": 0.0})
        self.widget.configure_intensity(max_intensity=7.5)
        self.widget.configure_noise_floor(noise_floor=0.8)

        self.assertEqual(self.widget._pressure_levels(result, pressure_grid), (0.0, 7.5))
        rgba = self.widget._rgba_image(np.array([[0.8, 0.9, 1.0]]), (0.0, 7.5))
        self.assertEqual(int(rgba[0, 0, 3]), 0)
        self.assertGreater(int(rgba[0, 1, 3]), 0)
        self.assertGreater(int(rgba[0, 2, 3]), int(rgba[0, 1, 3]))

    def test_pressure_levels_use_fixed_max_intensity_for_tension(self):
        pressure_grid = np.array([[-4.0, 0.0], [-2.0, -1.0]], dtype=np.float64)
        tension_result = self.calculator.compute({"C": -4.0, "R": 0.0, "T": 0.0, "L": 0.0, "B": 0.0})
        self.widget.configure_intensity(max_intensity=5.0)

        levels = self.widget._pressure_levels(tension_result, pressure_grid)

        self.assertEqual(levels, (0.0, 5.0))

    def test_display_mode_changes_rendering_without_changing_backend_data(self):
        normal_result = self.calculator.compute({"C": -1.0, "R": -2.0, "T": -2.0, "L": -2.0, "B": -2.0})
        pressure_result = self.generator.generate(normal_result.normalized)
        original_grid = pressure_result.pressure_grid.copy()

        self.widget.configure_display_mode(display_mode=PRESSURE_DISPLAY_MODE_MAGNITUDE)
        np.testing.assert_allclose(self.widget._display_grid(pressure_result.pressure_grid), np.abs(original_grid))
        self.widget.configure_display_mode(display_mode=PRESSURE_DISPLAY_MODE_SIGNED)
        np.testing.assert_allclose(self.widget._display_grid(pressure_result.pressure_grid), original_grid)
        self.assertEqual(self.widget._pressure_levels(normal_result, original_grid), (-self.widget.max_intensity, self.widget.max_intensity))
        np.testing.assert_allclose(pressure_result.pressure_grid, original_grid)
        lookup_table = self.widget._color_lookup_table()
        self.assertTrue(np.all(lookup_table[len(lookup_table) // 2, :3] <= 2))

    def test_arrow_scale_uses_outer_boundary_not_near_outer_peak_offset(self):
        shear_result = self.detector.detect({"C": 0.0, "L": -1.0, "R": 1.0, "T": 0.0, "B": 0.0})
        normal_result = self.calculator.compute(shear_result.residual)
        pressure_result = PressureMapGenerator(near_outer_peak_offset_mm=2.0).generate(normal_result.normalized)

        self.widget.update_display(normal_result, pressure_result, shear_result)

        self.assertEqual(self.widget.circle_radius_mm, pressure_result.outer_boundary_half_width_mm)

    def test_pressure_levels_revert_to_normalized_when_max_intensity_is_zero(self):
        pressure_grid = np.array([[6.0, 0.0], [3.0, 1.0]], dtype=np.float64)
        all_sensor_result = self.calculator.compute({"C": 10.0, "R": 4.0, "T": 4.0, "L": 4.0, "B": 4.0})
        self.widget.configure_intensity(max_intensity=0.0)

        levels = self.widget._pressure_levels(all_sensor_result, pressure_grid)

        self.assertEqual(levels, (0.0, 6.0))

    def test_image_rectangle_expands_one_half_cell_and_mirrors_centres(self):
        x_values = np.asarray([-1.0, 0.0, 1.0])
        y_values = np.asarray([2.0, 3.0, 4.0])
        rect = image_rect_from_centers(x_values, y_values)
        self.assertEqual(rect.getRect(), (-1.5, 1.5, 3.0, 3.0))
        mirrored = image_rect_from_centers(x_values, y_values, mirror_x=True, offset_x=4.0)
        self.assertEqual(mirrored.getRect(), (2.5, 1.5, 3.0, 3.0))

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

    def test_boundary_visibility_toggles_are_independent(self):
        signals = {"C": 0.0, "R": 5.0, "T": 0.0, "L": 0.0, "B": 0.0}
        normal_result = self.calculator.compute(signals)
        pressure_result = self.generator.generate(signals)

        self.widget.configure_boundary_visibility(
            show_near_outer_boundary=True,
            show_outer_boundary=False,
            show_mid_boundary=False,
        )
        self.widget.update_display(normal_result, pressure_result)
        self.assertIsInstance(self.widget.circle_item, QGraphicsEllipseItem)
        self.assertTrue(self.widget.circle_item.isVisible())
        self.assertEqual(self.widget.circle_item.pen().style(), Qt.PenStyle.DotLine)
        self.assertEqual(len(self.widget.sensor_marker_item.points()), len(pressure_result.sensor_positions))

        self.widget.configure_boundary_visibility(
            show_near_outer_boundary=False,
            show_outer_boundary=True,
            show_mid_boundary=True,
        )
        self.assertFalse(self.widget.circle_item.isVisible())
        self.assertTrue(self.widget.outer_boundary_item.isVisible())
        self.assertTrue(self.widget.mid_boundary_item.isVisible())
        self.assertNotEqual(
            self.widget.outer_boundary_item.pen().dashPattern(),
            self.widget.mid_boundary_item.pen().dashPattern(),
        )
        self.assertEqual(len(self.widget.sensor_marker_item.points()), len(pressure_result.sensor_positions))

    def test_mirror_can_be_enabled_and_disabled(self):
        self.widget.configure_mirror(mirror=False)
        self.assertFalse(self.widget.mirror)

        self.widget.configure_mirror(mirror=True)
        self.assertTrue(self.widget.mirror)

    def test_mirror_flips_sensor_marker_positions(self):
        signals = {"C": 0.0, "R": 5.0, "T": 0.0, "L": 0.0, "B": 0.0}
        normal_result = self.calculator.compute(signals)
        pressure_result = self.generator.generate(signals)

        # Without mirror
        self.widget.configure_mirror(mirror=False)
        self.widget.update_display(normal_result, pressure_result)
        points_unmirrored = self.widget.sensor_marker_item.points()
        unmirrored_positions = [(pt.pos().x(), pt.pos().y()) for pt in points_unmirrored]

        # With mirror
        self.widget.configure_mirror(mirror=True)
        self.widget.update_display(normal_result, pressure_result)
        points_mirrored = self.widget.sensor_marker_item.points()
        mirrored_positions = [(pt.pos().x(), pt.pos().y()) for pt in points_mirrored]

        # Verify mirroring flips x coordinates
        self.assertEqual(len(unmirrored_positions), len(mirrored_positions))
        for unmirrored, mirrored in zip(unmirrored_positions, mirrored_positions):
            # X should be negated, Y should be the same
            self.assertAlmostEqual(mirrored[0], -unmirrored[0], places=5)
            self.assertAlmostEqual(mirrored[1], unmirrored[1], places=5)

    def test_mirror_flips_peak_marker_positions(self):
        signals = {"C": 5.0, "R": 5.0, "T": 5.0, "L": 5.0, "B": 5.0}
        normal_result = self.calculator.compute(signals)
        pressure_result = self.generator.generate(signals)

        self.widget.configure_markers(show_marker=True)

        # Without mirror
        self.widget.configure_mirror(mirror=False)
        self.widget.update_display(normal_result, pressure_result)
        points_unmirrored = self.widget.peak_marker_item.points()
        unmirrored_peaks = [(pt.pos().x(), pt.pos().y()) for pt in points_unmirrored]

        # With mirror
        self.widget.configure_mirror(mirror=True)
        self.widget.update_display(normal_result, pressure_result)
        points_mirrored = self.widget.peak_marker_item.points()
        mirrored_peaks = [(pt.pos().x(), pt.pos().y()) for pt in points_mirrored]

        # Verify mirroring flips x coordinates
        self.assertEqual(len(unmirrored_peaks), len(mirrored_peaks))
        for unmirrored, mirrored in zip(unmirrored_peaks, mirrored_peaks):
            self.assertAlmostEqual(mirrored[0], -unmirrored[0], places=5)
            self.assertAlmostEqual(mirrored[1], unmirrored[1], places=5)

    def test_configure_mirror_repaints_cached_single_display(self):
        normal_result = self.calculator.compute({"C": 0.0, "R": 5.0, "T": 0.0, "L": 0.0, "B": 0.0})
        pressure_result = self.generator.generate(normal_result.normalized)

        self.widget.update_display(normal_result, pressure_result)

        original_x_positions = [point.pos().x() for point in self.widget.sensor_marker_item.points()]

        self.widget.configure_mirror(mirror=True)

        mirrored_x_positions = [point.pos().x() for point in self.widget.sensor_marker_item.points()]
        np.testing.assert_allclose(
            mirrored_x_positions,
            [-x_position for x_position in original_x_positions],
            rtol=1e-7,
            atol=1e-7,
        )

    def test_configure_mirror_repaints_cached_arrow_geometry(self):
        shear_result = self.detector.detect({"C": 0.0, "L": -1.0, "R": 1.0, "T": 0.0, "B": 0.0})
        normal_result = self.calculator.compute(shear_result.residual)
        pressure_result = self.generator.generate(normal_result.normalized)

        self.widget.update_display(normal_result, pressure_result, shear_result)

        original_tip_x = self.widget.last_arrow_geometry.tip_x
        original_tip_y = self.widget.last_arrow_geometry.tip_y

        self.widget.configure_mirror(mirror=True)

        self.assertAlmostEqual(self.widget.last_arrow_geometry.tip_x, -original_tip_x)
        self.assertAlmostEqual(self.widget.last_arrow_geometry.tip_y, original_tip_y)

    def test_multi_package_mirror_flips_all_sensors(self):
        first_shear = self.detector.detect({"C": 0.0, "L": -1.0, "R": 1.0, "T": 0.0, "B": 0.0})
        second_shear = self.detector.detect({"C": 0.0, "L": 0.0, "R": 0.0, "T": 1.0, "B": -1.0})
        first_normal = self.calculator.compute(first_shear.residual)
        second_normal = self.calculator.compute(second_shear.residual)
        first_pressure = self.generator.generate(first_normal.normalized)
        second_pressure = self.generator.generate(second_normal.normalized)
        
        packages = [
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
                grid_position=(0, 1),
                color=self.widget.package_color_for_index(1),
            ),
        ]

        # Without mirror
        self.widget.configure_mirror(mirror=False)
        self.widget.update_package_displays(packages)
        unmirrored_centers = [
            (self.widget.package_circle_items[i].rect().center().x(),
             self.widget.package_circle_items[i].rect().center().y())
            for i in range(2)
        ]

        # With mirror
        self.widget.configure_mirror(mirror=True)
        self.widget.update_package_displays(packages)
        mirrored_centers = [
            (self.widget.package_circle_items[i].rect().center().x(),
             self.widget.package_circle_items[i].rect().center().y())
            for i in range(2)
        ]

        # Verify package centers are mirrored
        self.assertEqual(len(unmirrored_centers), len(mirrored_centers))
        for unmirrored, mirrored in zip(unmirrored_centers, mirrored_centers):
            # X should be negated, Y should be the same
            self.assertAlmostEqual(mirrored[0], -unmirrored[0], places=5)
            self.assertAlmostEqual(mirrored[1], unmirrored[1], places=5)

    def test_configure_mirror_repaints_cached_multi_package_display(self):
        self.widget.configure_markers(show_marker=True)
        first_shear = self.detector.detect({"C": 0.0, "L": -1.0, "R": 1.0, "T": 0.0, "B": 0.0})
        second_shear = self.detector.detect({"C": 0.0, "L": 0.0, "R": 0.0, "T": 1.0, "B": -1.0})
        first_normal = self.calculator.compute(first_shear.residual)
        second_normal = self.calculator.compute(second_shear.residual)
        first_pressure = self.generator.generate(first_normal.normalized)
        second_pressure = self.generator.generate(second_normal.normalized)
        packages = [
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
                grid_position=(0, 1),
                color=self.widget.package_color_for_index(1),
            ),
        ]

        self.widget.update_package_displays(packages)

        original_centers = [
            self.widget.package_circle_items[index].rect().center().x()
            for index in range(2)
        ]
        original_marker_x_positions = [
            point.pos().x()
            for point in self.widget.package_sensor_marker_items[0].points()
        ]
        original_peak_x_positions = [
            point.pos().x()
            for point in self.widget.package_peak_marker_items[0].points()
        ]

        self.widget.configure_mirror(mirror=True)

        mirrored_centers = [
            self.widget.package_circle_items[index].rect().center().x()
            for index in range(2)
        ]
        mirrored_marker_x_positions = [
            point.pos().x()
            for point in self.widget.package_sensor_marker_items[0].points()
        ]
        mirrored_peak_x_positions = [
            point.pos().x()
            for point in self.widget.package_peak_marker_items[0].points()
        ]

        np.testing.assert_allclose(
            mirrored_centers,
            [-center_x for center_x in original_centers],
            rtol=1e-7,
            atol=1e-7,
        )
        np.testing.assert_allclose(
            mirrored_marker_x_positions,
            [-x_position for x_position in original_marker_x_positions],
            rtol=1e-7,
            atol=1e-7,
        )
        np.testing.assert_allclose(
            mirrored_peak_x_positions,
            [-x_position for x_position in original_peak_x_positions],
            rtol=1e-7,
            atol=1e-7,
        )


class PressureMapMaskWidgetTests(unittest.TestCase):
    """Verify array-only alpha masking and its reusable polygon overlay."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widget = PressureMapWidget()
        self.calculator = NormalForceCalculator()
        self.generator = PressureMapGenerator()

    def tearDown(self):
        self.widget.close()

    def _array_frame(self):
        first_normal = self.calculator.compute({"C": 0.0, "L": 0.0, "R": 4.0, "T": 0.0, "B": 0.0})
        second_normal = self.calculator.compute({"C": 0.0, "L": 2.0, "R": 0.0, "T": 0.0, "B": 0.0})
        first_pressure = self.generator.generate(first_normal.normalized)
        second_pressure = self.generator.generate(second_normal.normalized)
        packages = [
            PressureMapPackageDisplay("PZT1", first_normal, first_pressure, grid_position=(0, 0)),
            PressureMapPackageDisplay("PZT2", second_normal, second_pressure, grid_position=(0, 1)),
        ]
        array_result = PressureMapArrayGenerator().generate([
            PressureMapArrayPackage(package.sensor_id, package.grid_position, package.normal_force_result, package.pressure_result)
            for package in packages
        ])
        return packages, array_result

    def test_mask_alpha_preserves_inside_floor_fade_and_backend_grid(self):
        packages, array_result = self._array_frame()
        points = ((-2.0, -4.0), (2.0, -4.0), (2.0, 4.0), (-2.0, 4.0))
        original_grid = array_result.pressure_grid.copy()
        self.widget.configure_mask(mask_enabled=True, mask_points_mm=points)
        visibility_mask, _ = self.widget._array_visibility_mask(array_result)
        grid = self.widget._array_display_grid(array_result)
        levels = self.widget._pressure_levels(packages[0].normal_force_result, grid)

        unmasked = self.widget._rgba_image(grid, levels)
        masked = self.widget._rgba_image(grid, levels, visibility_mask=visibility_mask)

        self.assertTrue(np.all(masked[..., 3][~visibility_mask] == 0))
        np.testing.assert_array_equal(masked[..., 3][visibility_mask], unmasked[..., 3][visibility_mask])
        np.testing.assert_array_equal(array_result.pressure_grid, original_grid)

    def test_mask_cache_reuses_identical_grid_and_invalidates_resolution(self):
        _packages, array_result = self._array_frame()
        self.widget.configure_mask(
            mask_enabled=True,
            mask_points_mm=((-2.0, -4.0), (2.0, -4.0), (2.0, 4.0), (-2.0, 4.0)),
        )
        with patch("gui.pressure_map_widget.mask_inside_grid", wraps=mask_inside_grid) as rasterize:
            first_mask, _ = self.widget._array_visibility_mask(array_result)
            second_mask, _ = self.widget._array_visibility_mask(array_result)
            self.assertIs(first_mask, second_mask)
            self.assertEqual(rasterize.call_count, 1)

            x_coords = np.linspace(
                array_result.x_coordinates_mm[0], array_result.x_coordinates_mm[-1], array_result.x_coordinates_mm.size + 2,
            )
            y_coords = np.linspace(
                array_result.y_coordinates_mm[0], array_result.y_coordinates_mm[-1], array_result.y_coordinates_mm.size + 2,
            )
            x_grid, y_grid = np.meshgrid(x_coords, y_coords)
            resized = replace(
                array_result,
                pressure_grid=np.zeros_like(x_grid),
                magnitude_pressure_grid=np.zeros_like(x_grid),
                x_coordinates_mm=x_coords,
                y_coordinates_mm=y_coords,
                x_grid_mm=x_grid,
                y_grid_mm=y_grid,
                cell_size_x_mm=float(x_coords[1] - x_coords[0]),
                cell_size_y_mm=float(y_coords[1] - y_coords[0]),
                actual_pixels_per_mm=array_result.actual_pixels_per_mm * 2.0,
            )
            self.widget._array_visibility_mask(resized)
            self.assertEqual(rasterize.call_count, 2)

    def test_mask_mirrors_with_image_and_outline_and_hides_outside_array_mode(self):
        packages, array_result = self._array_frame()
        points = ((-2.0, -4.0), (2.0, -4.0), (2.0, 4.0), (-2.0, 4.0))
        self.widget.configure_mask(mask_enabled=True, mask_points_mm=points)
        self.widget.update_array_display(array_result, packages)

        outline = self.widget.mask_outline_item
        self.assertTrue(outline.isVisible())
        self.assertEqual(outline.brush().style(), Qt.BrushStyle.NoBrush)
        self.assertTrue(outline.pen().isCosmetic())
        original_x = [outline.polygon().at(index).x() for index in range(outline.polygon().count())]
        self.widget.configure_mirror(mirror=True)
        mirrored_x = [outline.polygon().at(index).x() for index in range(outline.polygon().count())]
        np.testing.assert_allclose(mirrored_x, -np.asarray(original_x))

        self.widget.update_package_displays(packages)
        self.assertFalse(outline.isVisible())
        self.widget.update_display(packages[0].normal_force_result, packages[0].pressure_result)
        self.assertFalse(outline.isVisible())
        self.widget.update_display(None, None)
        self.assertFalse(outline.isVisible())

    def test_disabled_mask_uses_original_rgba_image(self):
        grid = np.asarray([[0.0, 1.0], [0.5, 0.75]])
        points = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))
        visible = np.asarray([[True, False], [True, False]])
        self.widget.configure_mask(mask_enabled=True, mask_points_mm=points)
        cropped = self.widget._rgba_image(grid, (0.0, 1.0), visibility_mask=visible)
        self.widget.configure_mask(mask_enabled=False)
        restored = self.widget._rgba_image(grid, (0.0, 1.0))

        self.assertTrue(np.any(cropped[..., 3] != restored[..., 3]))
        np.testing.assert_array_equal(restored, self.widget._rgba_image(grid, (0.0, 1.0)))


if __name__ == "__main__":
    unittest.main()
