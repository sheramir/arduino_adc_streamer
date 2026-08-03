"""Tests for pressure-point pressure-map generation."""

import unittest

import numpy as np

from constants.pressure_map import (
    DEFAULT_PRESSURE_SENSOR_SPACING_MM,
    PRESSURE_ACTIVE_QUADRANTS,
    PRESSURE_QUADRANT_BOTTOM_LEFT,
    PRESSURE_QUADRANT_BOTTOM_RIGHT,
    PRESSURE_QUADRANT_TOP_LEFT,
    PRESSURE_QUADRANT_TOP_RIGHT,
)
from constants.shear import (
    SHEAR_SENSOR_POSITIONS,
)
from data_processing.pressure_map_generator import (
    DEFAULT_PRESSURE_SHOW_NEGATIVE,
    PRESSURE_PACKAGE_MODE_CENTER_PLUS_ONE_OUTER,
    PRESSURE_PACKAGE_MODE_ALL_INACTIVE,
    PRESSURE_PACKAGE_MODE_GENERAL_MULTI_SENSOR,
    PRESSURE_QUADRANT_MODE_SIGNED_TRANSITION,
    PRESSURE_QUADRANT_MODE_PEAKED,
    PRESSURE_QUADRANT_MODE_PEAKLESS,
    PRESSURE_QUADRANT_MODE_ISOLATED_OUTER_PEAKED,
    PRESSURE_QUADRANT_MODE_SINGLE_AXIS_PEAKED,
    PressureMapGenerator,
    evaluate_pressure_map_result_at,
    ray_square_exit_distance,
    ray_square_intersection_point,
    smoothstep_fade,
)
from data_processing.pressure_map_geometry import PressureMapGeometry


class PressureMapGeneratorTests(unittest.TestCase):
    """Verify pressure-point placement, interpolation, and clamping."""

    def setUp(self):
        self.generator = PressureMapGenerator()

    def _grid_value(self, result, x_mm, y_mm):
        row = int(np.argmin(np.abs(result.y_coordinates_mm - y_mm)))
        col = int(np.argmin(np.abs(result.x_coordinates_mm - x_mm)))
        return float(result.pressure_grid[row, col])

    def _planes_by_label(self, result):
        return {plane.label: plane for plane in result.quadrant_planes}

    def _quadrant_value(self, plane, x_mm, y_mm):
        return float(
            self.generator._evaluate_quadrant_for_region(
                plane,
                np.array([x_mm], dtype=np.float64),
                np.array([y_mm], dtype=np.float64),
            )[0]
        )

    def test_sensor_positions_reproduce_sensor_values_on_grid(self):
        signals = {"C": 5.0, "R": 3.0, "T": 7.0, "L": 2.0, "B": 1.0}
        result = self.generator.generate(signals)

        for sensor, expected_value in signals.items():
            x_mm, y_mm = result.sensor_positions[sensor]
            self.assertAlmostEqual(self._grid_value(result, x_mm, y_mm), expected_value, places=6)

    def test_peak_height_is_reproduced_at_peak_location(self):
        generator = PressureMapGenerator()
        result = generator.generate({position: 5.0 for position in SHEAR_SENSOR_POSITIONS})
        tr_plane = {plane.label: plane for plane in result.quadrant_planes}[PRESSURE_QUADRANT_TOP_RIGHT]
        peak_x, peak_y = tr_plane.peak_point

        self.assertEqual(tr_plane.mode, PRESSURE_QUADRANT_MODE_PEAKED)
        self.assertAlmostEqual(peak_x, DEFAULT_PRESSURE_SENSOR_SPACING_MM / 2.0)
        self.assertAlmostEqual(peak_y, DEFAULT_PRESSURE_SENSOR_SPACING_MM / 2.0)
        self.assertAlmostEqual(
            float(tr_plane.peak_height),
            self._grid_value(result, peak_x, peak_y),
            places=6,
        )

    def test_backend_peak_location_uses_magnitude_independently_of_display_mode(self):
        self.assertFalse(DEFAULT_PRESSURE_SHOW_NEGATIVE)
        result = self.generator.generate({"C": -5.0, "R": -3.0, "T": -3.0, "L": 0.0, "B": 0.0})
        tr_plane = self._planes_by_label(result)[PRESSURE_QUADRANT_TOP_RIGHT]

        self.assertEqual(tr_plane.mode, PRESSURE_QUADRANT_MODE_PEAKED)

    def test_show_negative_mode_uses_absolute_magnitude_for_pressure_point(self):
        generator = PressureMapGenerator(show_negative=True)
        result = generator.generate({"C": -5.0, "R": -3.0, "T": -3.0, "L": 0.0, "B": 0.0})
        tr_plane = self._planes_by_label(result)[PRESSURE_QUADRANT_TOP_RIGHT]

        self.assertEqual(tr_plane.mode, PRESSURE_QUADRANT_MODE_PEAKED)
        self.assertIsNotNone(tr_plane.peak_point)
        peak_x, peak_y = tr_plane.peak_point
        self.assertGreater(peak_x, 0.0)
        self.assertGreater(peak_y, 0.0)

    def test_continuity_matches_on_shared_x_axis(self):
        signals = {"C": 5.0, "R": 3.0, "T": 7.0, "L": 2.0, "B": 4.0}
        result = self.generator.generate(signals)
        planes = self._planes_by_label(result)
        x_coord = DEFAULT_PRESSURE_SENSOR_SPACING_MM / 2.0

        tr_value = self._quadrant_value(planes[PRESSURE_QUADRANT_TOP_RIGHT], x_coord, 0.0)
        br_value = self._quadrant_value(planes[PRESSURE_QUADRANT_BOTTOM_RIGHT], x_coord, 0.0)

        self.assertAlmostEqual(tr_value, br_value, places=6)

    def test_only_center_nonzero_decays_monotonically_to_outer_zero_sensors(self):
        result = self.generator.generate({"C": 5.0, "R": 0.0, "T": 0.0, "L": 0.0, "B": 0.0})
        spacing = DEFAULT_PRESSURE_SENSOR_SPACING_MM

        center = self._grid_value(result, 0.0, 0.0)
        halfway = self._grid_value(result, spacing / 2.0, 0.0)
        outer = self._grid_value(result, spacing, 0.0)

        self.assertGreater(center, halfway)
        self.assertGreater(halfway, outer)
        self.assertAlmostEqual(outer, 0.0, places=6)

    def test_signed_backend_preserves_mixed_sign_anchors_without_clamping(self):
        compression = self.generator.generate({"C": 5.0, "R": 0.0, "T": 8.0, "L": 3.0, "B": 2.0})
        tension = self.generator.generate({"C": -5.0, "R": -3.0, "T": -3.0, "L": -3.0, "B": -3.0})

        self.assertAlmostEqual(self._grid_value(compression, -2.0, 0.0), 3.0)
        self.assertLessEqual(float(np.max(tension.pressure_grid[tension.circle_mask])), 0.0)

    def test_symmetric_inputs_produce_nearly_symmetric_map(self):
        result = self.generator.generate({"C": 5.0, "R": 3.0, "T": 3.0, "L": 3.0, "B": 3.0})
        grid = result.pressure_grid

        np.testing.assert_allclose(grid, np.flip(grid, axis=0), rtol=1e-6, atol=1e-6)
        np.testing.assert_allclose(grid, np.flip(grid, axis=1), rtol=1e-6, atol=1e-6)

    def test_equal_outer_ring_has_no_extrapolated_corner_peak(self):
        result = self.generator.generate({"C": 0.0, "R": 2.0, "T": 2.0, "L": 2.0, "B": 2.0})
        spacing = self.generator.sensor_spacing_mm
        core = result.pressure_grid[
            (np.abs(result.y_grid_mm) <= spacing) & (np.abs(result.x_grid_mm) <= spacing)
        ]
        self.assertAlmostEqual(self._grid_value(result, 0.0, 0.0), 0.0, places=12)
        self.assertLessEqual(float(np.max(core)), 2.0)
        np.testing.assert_allclose(result.pressure_grid, np.flip(result.pressure_grid, axis=0), atol=1e-12)
        np.testing.assert_allclose(result.pressure_grid, np.flip(result.pressure_grid, axis=1), atol=1e-12)

    def test_all_zero_inputs_produce_empty_zero_map(self):
        result = self.generator.generate({"C": 0.0, "R": 0.0, "T": 0.0, "L": 0.0, "B": 0.0})

        self.assertEqual(result.active_quadrants, ())
        self.assertEqual(result.quadrant_planes, ())
        self.assertTrue(np.all(result.pressure_grid == 0.0))

    def test_only_one_outer_nonzero_moves_peak_beyond_sensor_with_bounded_gain(self):
        result = self.generator.generate({"C": 0.0, "R": 5.0, "T": 0.0, "L": 0.0, "B": 0.0})
        planes = self._planes_by_label(result)
        spacing = DEFAULT_PRESSURE_SENSOR_SPACING_MM
        plane = planes["R"]

        self.assertEqual(plane.mode, PRESSURE_QUADRANT_MODE_ISOLATED_OUTER_PEAKED)
        self.assertEqual(plane.peak_point, (spacing + self.generator.near_outer_peak_offset_mm, 0.0))
        self.assertGreater(float(plane.peak_height), 5.0)
        self.assertLessEqual(float(plane.peak_height), 5.0 * self.generator.maximum_peak_gain)
        self.assertGreater(self._grid_value(result, spacing, 0.0), 0.0)
        self.assertGreater(
            float(evaluate_pressure_map_result_at(
                result,
                np.asarray([spacing + self.generator.near_outer_peak_offset_mm]),
                np.asarray([0.0]),
            )[0]),
            float(evaluate_pressure_map_result_at(
                result,
                np.asarray([spacing + self.generator.near_outer_peak_offset_mm]),
                np.asarray([spacing]),
            )[0]),
        )

    def test_default_geometry_uses_fixed_outer_support_and_pixels_per_mm(self):
        result = self.generator.generate({position: 0.0 for position in SHEAR_SENSOR_POSITIONS})

        self.assertEqual(self.generator.sensor_spacing_mm, 2.0)
        self.assertEqual(self.generator.package_center_spacing_mm, 7.5)
        self.assertEqual(self.generator.outer_boundary_reach_mm, 1.75)
        self.assertEqual(self.generator.pixels_per_mm, 10.0)
        self.assertEqual(result.facing_sensor_gap_mm, 3.5)
        self.assertEqual(result.mid_boundary_half_width_mm, 3.75)
        self.assertEqual(result.outer_boundary_half_width_mm, 5.5)
        self.assertEqual(result.support_bounds_mm, (-5.5, 5.5, -5.5, 5.5))

    def test_each_isolated_outer_sensor_uses_the_same_radial_offset(self):
        offset = 0.75
        generator = PressureMapGenerator(near_outer_peak_offset_mm=offset)
        expected_points = {
            "R": (generator.sensor_spacing_mm + offset, 0.0),
            "L": (-generator.sensor_spacing_mm - offset, 0.0),
            "T": (0.0, generator.sensor_spacing_mm + offset),
            "B": (0.0, -generator.sensor_spacing_mm - offset),
        }
        for sensor, expected_point in expected_points.items():
            result = generator.generate({position: 4.0 if position == sensor else 0.0 for position in SHEAR_SENSOR_POSITIONS})
            self.assertEqual(result.quadrant_planes[0].peak_point, expected_point)
            self.assertGreater(float(result.quadrant_planes[0].peak_height), 4.0)

    def test_center_or_two_outer_sensors_do_not_use_isolated_outer_mode(self):
        center_active = self.generator.generate({"C": 1.0, "R": 5.0, "T": 0.0, "L": 0.0, "B": 0.0})
        two_outer_active = self.generator.generate({"C": 0.0, "R": 5.0, "T": 4.0, "L": 0.0, "B": 0.0})
        self.assertFalse(any(plane.mode == PRESSURE_QUADRANT_MODE_ISOLATED_OUTER_PEAKED for plane in center_active.quadrant_planes))
        self.assertFalse(any(plane.mode == PRESSURE_QUADRANT_MODE_ISOLATED_OUTER_PEAKED for plane in two_outer_active.quadrant_planes))

    def test_visual_circle_is_not_a_computational_crop(self):
        generator = PressureMapGenerator(
            sensor_spacing_mm=1.0,
            package_center_spacing_mm=7.0,
            outer_boundary_reach_mm=2.0,
            pixels_per_mm=10.0,
        )
        result = generator.generate({"C": 0.0, "R": 5.0, "T": 0.0, "L": 0.0, "B": 0.0})
        x_mm = generator.sensor_spacing_mm + generator.near_outer_peak_offset_mm + 0.4
        y_mm = 0.0
        row = int(np.argmin(np.abs(result.y_coordinates_mm - y_mm)))
        col = int(np.argmin(np.abs(result.x_coordinates_mm - x_mm)))
        self.assertFalse(bool(result.circle_mask[row, col]))
        self.assertGreater(float(result.pressure_grid[row, col]), 0.0)

    def test_isolated_outer_field_is_zero_on_and_beyond_its_support_boundary(self):
        result = self.generator.generate({"C": 0.0, "R": 5.0, "T": 0.0, "L": 0.0, "B": 0.0})
        _left, right, _bottom, _top = result.support_bounds_mm
        values = evaluate_pressure_map_result_at(
            result,
            np.asarray([right, right + 0.5]),
            np.asarray([0.0, 0.0]),
        )
        np.testing.assert_allclose(values, np.zeros(2), rtol=0.0, atol=1e-12)

    def test_natural_decay_can_end_before_the_terminal_outer_boundary(self):
        generator = PressureMapGenerator(
            sensor_spacing_mm=1.0,
            package_center_spacing_mm=7.0,
            outer_boundary_reach_mm=2.0,
            pixels_per_mm=10.0,
            decay_rate=0.8,
            decay_ref_distance_mm=1.5,
        )
        low = generator.generate({"C": 0.0, "R": 0.1, "T": 0.0, "L": 0.0, "B": 0.0})
        high = generator.generate({"C": 0.0, "R": 5.0, "T": 0.0, "L": 0.0, "B": 0.0})
        probe_x = 4.0
        low_value = evaluate_pressure_map_result_at(low, np.asarray([probe_x]), np.asarray([0.0]))[0]
        high_value = evaluate_pressure_map_result_at(high, np.asarray([probe_x]), np.asarray([0.0]))[0]
        self.assertAlmostEqual(float(low_value), 0.0, places=12)
        self.assertGreater(float(high_value), 0.0)

    def test_terminal_guard_only_zeroes_the_final_outer_strip_for_a_strong_lobe(self):
        result = self.generator.generate({"C": 0.0, "R": 5.0, "T": 0.0, "L": 0.0, "B": 0.0})
        _left, right, _bottom, _top = result.support_bounds_mm
        before_guard = evaluate_pressure_map_result_at(result, np.asarray([5.0]), np.asarray([0.0]))[0]
        inside_guard = evaluate_pressure_map_result_at(result, np.asarray([right - 0.05]), np.asarray([0.0]))[0]
        boundary = evaluate_pressure_map_result_at(result, np.asarray([right]), np.asarray([0.0]))[0]
        self.assertGreater(float(before_guard), float(inside_guard))
        self.assertGreater(float(inside_guard), 0.0)
        self.assertEqual(float(boundary), 0.0)

    def test_general_model_uses_complete_peakless_quadrants_for_zero_outer_axes(self):
        result = self.generator.generate({"C": 4.0, "R": 4.0, "T": 3.0, "L": 2.0, "B": 0.0})
        planes = self._planes_by_label(result)

        self.assertEqual(planes[PRESSURE_QUADRANT_TOP_RIGHT].mode, PRESSURE_QUADRANT_MODE_PEAKED)
        self.assertEqual(planes[PRESSURE_QUADRANT_TOP_LEFT].mode, PRESSURE_QUADRANT_MODE_PEAKED)
        self.assertEqual(planes[PRESSURE_QUADRANT_BOTTOM_LEFT].mode, PRESSURE_QUADRANT_MODE_PEAKLESS)
        self.assertEqual(planes[PRESSURE_QUADRANT_BOTTOM_RIGHT].mode, PRESSURE_QUADRANT_MODE_PEAKLESS)

    def test_center_plus_one_side_creates_single_axis_peak_between_sensors(self):
        spacing = DEFAULT_PRESSURE_SENSOR_SPACING_MM
        result = self.generator.generate({"C": 5.0, "R": 3.0, "T": 0.0, "L": 0.0, "B": 0.0})
        axis_plane = result.quadrant_planes[0]

        self.assertEqual(result.package_mode, PRESSURE_PACKAGE_MODE_CENTER_PLUS_ONE_OUTER)
        self.assertEqual(axis_plane.mode, PRESSURE_QUADRANT_MODE_SINGLE_AXIS_PEAKED)
        self.assertIsNotNone(axis_plane.peak_point)
        peak_x, peak_y = axis_plane.peak_point
        self.assertGreater(peak_x, 0.0)
        self.assertLess(peak_x, spacing)
        self.assertAlmostEqual(peak_y, 0.0, places=6)

        on_axis = self._grid_value(result, peak_x, 0.0)
        off_axis = self._grid_value(result, peak_x, spacing / 2.0)
        self.assertGreater(on_axis, off_axis)

    def test_general_model_has_no_duplicated_quadrant_single_axis_lobes(self):
        result = self.generator.generate({"C": 5.0, "R": 0.0, "T": 8.0, "L": 3.0, "B": 2.0})
        planes = self._planes_by_label(result)

        self.assertEqual(planes[PRESSURE_QUADRANT_TOP_LEFT].mode, PRESSURE_QUADRANT_MODE_PEAKED)
        self.assertEqual(planes[PRESSURE_QUADRANT_BOTTOM_LEFT].mode, PRESSURE_QUADRANT_MODE_PEAKED)
        self.assertEqual(planes[PRESSURE_QUADRANT_TOP_RIGHT].mode, PRESSURE_QUADRANT_MODE_PEAKLESS)
        self.assertEqual(planes[PRESSURE_QUADRANT_BOTTOM_RIGHT].mode, PRESSURE_QUADRANT_MODE_PEAKLESS)

    def test_degenerate_corner_peak_falls_back_to_complete_peakless_split(self):
        result = self.generator.generate({"C": 0.0, "R": 5.0, "T": 7.0, "L": 0.0, "B": 0.0})
        tr_plane = self._planes_by_label(result)[PRESSURE_QUADRANT_TOP_RIGHT]
        spacing = DEFAULT_PRESSURE_SENSOR_SPACING_MM

        self.assertEqual(tr_plane.mode, PRESSURE_QUADRANT_MODE_PEAKLESS)
        self.assertIsNone(tr_plane.peak_point)
        self.assertEqual(
            tuple(triangle.name for triangle in tr_plane.triangles),
            ("core-horizontal", "core-vertical"),
        )
        self.assertEqual(float(tr_plane.corner_value), 4.8)
        self.assertAlmostEqual(self._quadrant_value(tr_plane, spacing, spacing), 4.8, places=6)

    def test_opposing_sign_conflicts_keep_signed_transition_quadrants(self):
        result = self.generator.generate({"C": 0.0, "R": 5.0, "T": 5.0, "L": -4.0, "B": -4.0})

        self.assertEqual(result.package_mode, PRESSURE_PACKAGE_MODE_GENERAL_MULTI_SENSOR)
        self.assertEqual(set(result.active_quadrants), set(PRESSURE_ACTIVE_QUADRANTS))
        self.assertGreater(self._grid_value(result, 1.0, 1.0), 0.0)
        self.assertLess(self._grid_value(result, -1.0, -1.0), 0.0)
        planes = self._planes_by_label(result)
        self.assertEqual(planes[PRESSURE_QUADRANT_TOP_LEFT].mode, PRESSURE_QUADRANT_MODE_SIGNED_TRANSITION)
        self.assertEqual(planes[PRESSURE_QUADRANT_BOTTOM_RIGHT].mode, PRESSURE_QUADRANT_MODE_SIGNED_TRANSITION)

    def test_output_grid_uses_outer_boundary_and_at_least_requested_density(self):
        result = self.generator.generate({"C": 0.0, "R": 0.0, "T": 0.0, "L": 0.0, "B": 0.0})
        expected_side = (2 * int(round(
            self.generator.outer_boundary_half_width_mm / self.generator.cell_size_mm
        ))) + 1

        self.assertEqual(result.pressure_grid.shape, (expected_side, expected_side))
        self.assertEqual(result.circle_mask.shape, (expected_side, expected_side))
        self.assertAlmostEqual(result.x_coordinates_mm[0], -self.generator.outer_boundary_half_width_mm)
        self.assertAlmostEqual(result.x_coordinates_mm[-1], self.generator.outer_boundary_half_width_mm)
        self.assertLessEqual(result.cell_size_mm, 1.0 / self.generator.pixels_per_mm)
        self.assertEqual(result.actual_pixels_per_mm, 1.0 / result.cell_size_mm)

    def test_active_quadrants_still_follow_standard_order(self):
        result = self.generator.generate({position: 1.0 for position in SHEAR_SENSOR_POSITIONS})

        self.assertEqual(result.active_quadrants, PRESSURE_ACTIVE_QUADRANTS)

    def test_single_axis_modes_reconstruct_center_and_outer_anchors_with_both_signs(self):
        for sensor, coordinate in (("R", (2.0, 0.0)), ("L", (-2.0, 0.0)), ("T", (0.0, 2.0)), ("B", (0.0, -2.0))):
            for sign in (1.0, -1.0):
                signals = {position: 0.0 for position in SHEAR_SENSOR_POSITIONS}
                signals["C"] = sign * 5.0
                signals[sensor] = sign * 3.0
                result = self.generator.generate(signals)
                center = evaluate_pressure_map_result_at(result, np.asarray([0.0]), np.asarray([0.0]))[0]
                outer = evaluate_pressure_map_result_at(
                    result, np.asarray([coordinate[0]]), np.asarray([coordinate[1]])
                )[0]
                self.assertAlmostEqual(float(center), signals["C"], places=10)
                self.assertAlmostEqual(float(outer), signals[sensor], places=10)

    def test_signal_activity_threshold_is_independent_of_geometry_epsilon(self):
        generator = PressureMapGenerator(signal_activity_threshold=0.25)
        below_threshold = generator.generate({"C": 0.0, "R": 0.24, "T": 0.0, "L": 0.0, "B": 0.0})
        at_threshold = generator.generate({"C": 0.0, "R": 0.25, "T": 0.0, "L": 0.0, "B": 0.0})
        above_threshold = generator.generate({"C": 0.0, "R": 0.250001, "T": 0.0, "L": 0.0, "B": 0.0})

        self.assertEqual(below_threshold.active_quadrants, ())
        self.assertEqual(at_threshold.active_quadrants, ())
        self.assertEqual(above_threshold.quadrant_planes[0].mode, PRESSURE_QUADRANT_MODE_ISOLATED_OUTER_PEAKED)

    def test_zero_threshold_never_classifies_an_exact_zero_as_active(self):
        result = PressureMapGenerator(signal_activity_threshold=0.0).generate(
            {position: 0.0 for position in SHEAR_SENSOR_POSITIONS}
        )

        self.assertEqual(result.package_mode, PRESSURE_PACKAGE_MODE_ALL_INACTIVE)
        self.assertEqual(result.package_activity_confidence, 0.0)
        self.assertTrue(np.all(result.pressure_grid == 0.0))

    def test_quadrant_corner_is_a_bounded_convex_estimate(self):
        examples = (
            ({"C": 0.0, "R": 1.0, "T": 1.0, "L": 0.0, "B": 0.0}, 0.8),
            ({"C": 1.0, "R": 0.0, "T": 0.0, "L": 0.0, "B": 0.0}, 0.2),
            ({"C": 2.0, "R": 2.0, "T": 2.0, "L": 0.0, "B": 0.0}, 2.0),
        )
        for signals, expected in examples:
            plane = self._planes_by_label(self.generator.generate(signals))[PRESSURE_QUADRANT_TOP_RIGHT]
            anchors = (signals["C"], signals["R"], signals["T"])
            self.assertAlmostEqual(float(plane.corner_value), expected, places=12)
            self.assertGreaterEqual(float(plane.corner_value), min(anchors))
            self.assertLessEqual(float(plane.corner_value), max(anchors))

    def test_general_quadrant_extension_uses_its_own_local_decay_origin(self):
        result = self.generator.generate({"C": 1.0, "R": 8.0, "T": 1.0, "L": 1.0, "B": 1.0})
        origins = self._planes_by_label(result)
        self.assertNotEqual(
            origins[PRESSURE_QUADRANT_TOP_RIGHT].decay_origin,
            origins[PRESSURE_QUADRANT_BOTTOM_LEFT].decay_origin,
        )
        self.assertGreater(origins[PRESSURE_QUADRANT_TOP_RIGHT].decay_origin[0], 0.0)
        self.assertGreater(origins[PRESSURE_QUADRANT_TOP_RIGHT].decay_origin[1], 0.0)

    def test_geometry_alignment_places_default_landmarks_on_samples(self):
        geometry = PressureMapGeometry(pixels_per_mm=3.0)
        result = PressureMapGenerator(geometry=geometry).generate(
            {position: 0.0 for position in SHEAR_SENSOR_POSITIONS}
        )
        self.assertAlmostEqual(geometry.geometry_quantum_mm, 0.25)
        self.assertAlmostEqual(result.cell_size_mm, 0.25)
        self.assertAlmostEqual(result.actual_pixels_per_mm, 4.0)
        for landmark in (0.0, geometry.sensor_spacing_mm, geometry.mid_boundary_half_width_mm, geometry.outer_boundary_half_width_mm):
            self.assertTrue(np.any(np.isclose(result.x_coordinates_mm, landmark)))

    def test_sensor_anchors_are_exact_for_positive_negative_and_mixed_vectors(self):
        for signals in (
            {"C": 3.0, "L": 2.0, "R": 1.0, "T": 4.0, "B": 5.0},
            {"C": -3.0, "L": -2.0, "R": -1.0, "T": -4.0, "B": -5.0},
            {"C": 3.0, "L": -2.0, "R": 1.0, "T": -4.0, "B": 0.0},
        ):
            result = self.generator.generate(signals)
            for sensor, expected in signals.items():
                x_coord, y_coord = result.sensor_positions[sensor]
                actual = evaluate_pressure_map_result_at(
                    result, np.asarray([x_coord]), np.asarray([y_coord])
                )[0]
                self.assertAlmostEqual(float(actual), expected, places=12)

    def test_core_extension_is_value_continuous_and_outer_boundary_is_zero(self):
        result = self.generator.generate({"C": 5.0, "R": 3.0, "T": 7.0, "L": 2.0, "B": 1.0})
        just_inside = evaluate_pressure_map_result_at(result, np.asarray([1.999999]), np.asarray([0.8]))[0]
        just_outside = evaluate_pressure_map_result_at(result, np.asarray([2.000001]), np.asarray([0.8]))[0]
        self.assertAlmostEqual(float(just_inside), float(just_outside), places=4)
        _left, right, _bottom, _top = result.support_bounds_mm
        self.assertEqual(float(evaluate_pressure_map_result_at(result, np.asarray([right]), np.asarray([0.0]))[0]), 0.0)

    def test_geometry_helpers_are_finite_for_zero_and_edge_rays(self):
        bounds = (-2.0, 2.0, -2.0, 2.0)
        self.assertEqual(ray_square_exit_distance(0.0, 0.0, 0.0, 0.0, bounds), 0.0)
        self.assertEqual(ray_square_exit_distance(2.0, 0.0, 1.0, 0.0, bounds), 0.0)
        self.assertEqual(ray_square_intersection_point((0.0, 0.0), (3.0, 0.0), bounds), (2.0, 0.0))
        np.testing.assert_allclose(smoothstep_fade(np.asarray([0.0, 0.5, 1.0]), 1.0), [1.0, 0.5, 0.0])

    def test_debug_diagnostics_are_opt_in(self):
        result = PressureMapGenerator(debug=True).generate(
            {"C": 2.0, "R": 1.0, "T": -1.0, "L": 0.0, "B": 0.0}
        )
        self.assertIsNotNone(result.diagnostics)
        self.assertEqual(result.diagnostics["package_mode"], PRESSURE_PACKAGE_MODE_GENERAL_MULTI_SENSOR)
        self.assertIn("core_surface", result.diagnostics)
        self.assertTrue({
            "raw_sensor_values",
            "thresholded_sensor_values",
            "package_activity_confidence",
            "quadrant_corner_values",
            "quadrant_decay_origins",
            "natural_decay_factor",
            "boundary_guard_factor",
            "final_package_candidate",
        }.issubset(result.diagnostics))

    def test_supplied_geometry_is_authoritative_and_rejects_explicit_conflict(self):
        geometry = PressureMapGeometry(sensor_spacing_mm=1.0, package_center_spacing_mm=7.0)
        generator = PressureMapGenerator(geometry=geometry)
        self.assertEqual(generator.sensor_spacing_mm, 1.0)
        with self.assertRaisesRegex(ValueError, "conflicts"):
            PressureMapGenerator(geometry=geometry, sensor_spacing_mm=3.0)


if __name__ == "__main__":
    unittest.main()
