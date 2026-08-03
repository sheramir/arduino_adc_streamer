"""Tests for candidate-first Pressure Map array overlap blending."""

import unittest
import numpy as np

from data_processing.normal_force_calculator import NormalForceCalculator
from data_processing.pressure_map_array_generator import PressureMapArrayGenerator, PressureMapArrayPackage
from data_processing.pressure_map_generator import PressureMapGenerator, evaluate_pressure_map_result_at


class PressureMapArrayGeneratorTests(unittest.TestCase):
    """Verify direct, diagonal, and multi-package blends are geometric and signed."""

    def setUp(self):
        self.normal_calculator = NormalForceCalculator(sensor_spacing_mm=1.0)
        self.package_generator = PressureMapGenerator(
            sensor_spacing_mm=1.0,
            package_center_spacing_mm=7.0,
            outer_boundary_reach_mm=2.0,
            pixels_per_mm=10.0,
        )

    def _package(self, sensor_id, grid_position, values, *, generator=None):
        active_generator = generator or self.package_generator
        return PressureMapArrayPackage(
            sensor_id=sensor_id,
            grid_position=grid_position,
            normal_force_result=self.normal_calculator.compute(values),
            pressure_result=active_generator.generate(values),
        )

    def _generator(self, **kwargs):
        return PressureMapArrayGenerator(
            sensor_spacing_mm=1.0,
            package_center_spacing_mm=7.0,
            outer_boundary_reach_mm=2.0,
            **kwargs,
        )

    def _grid_value(self, result, x_mm, y_mm):
        row = int(np.argmin(np.abs(result.y_coordinates_mm - y_mm)))
        col = int(np.argmin(np.abs(result.x_coordinates_mm - x_mm)))
        return float(result.pressure_grid[row, col])

    def _candidate_value(self, result, package, x_mm, y_mm):
        center_x, center_y = result.package_centers[package.sensor_id]
        return float(evaluate_pressure_map_result_at(
            package.pressure_result,
            np.asarray([x_mm - center_x]),
            np.asarray([y_mm - center_y]),
            support_bounds_mm=result.candidate_support_bounds_mm[package.sensor_id],
        )[0])

    def test_package_centers_use_configured_center_spacing(self):
        empty = {"C": 0.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.0}
        result = self._generator().generate([
            self._package("PZT3", (0, 0), empty),
            self._package("PZT6", (0, 1), empty),
        ])
        self.assertAlmostEqual(result.package_centers["PZT6"][0] - result.package_centers["PZT3"][0], 7.0)

    def test_horizontal_overlap_uses_0_50_100_linear_weights(self):
        first = self._package("A", (0, 0), {"C": 0.0, "L": 0.0, "R": 5.0, "T": 0.0, "B": 0.0})
        second = self._package("B", (0, 1), {"C": 0.0, "L": 2.0, "R": 0.0, "T": 0.0, "B": 0.0})
        result = self._generator().generate([first, second])

        for x_mm, first_weight in ((-2.0, 1.0), (0.0, 0.5), (2.0, 0.0)):
            first_value = self._candidate_value(result, first, x_mm, 0.0)
            second_value = self._candidate_value(result, second, x_mm, 0.0)
            expected = first_weight * first_value + (1.0 - first_weight) * second_value
            self.assertAlmostEqual(self._grid_value(result, x_mm, 0.0), expected, places=8)
        self.assertEqual(result.overlap_pairs, (("A", "B"),))

    def test_vertical_overlap_uses_0_50_100_linear_weights(self):
        top = self._package("TOP", (0, 0), {"C": 0.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 4.0})
        bottom = self._package("BOTTOM", (1, 0), {"C": 0.0, "L": 0.0, "R": 0.0, "T": 2.0, "B": 0.0})
        result = self._generator().generate([top, bottom])

        # y grows from the physical bottom package side to the top package side.
        for y_mm, top_weight in ((-2.0, 0.0), (0.0, 0.5), (2.0, 1.0)):
            top_value = self._candidate_value(result, top, 0.0, y_mm)
            bottom_value = self._candidate_value(result, bottom, 0.0, y_mm)
            expected = top_weight * top_value + (1.0 - top_weight) * bottom_value
            self.assertAlmostEqual(self._grid_value(result, 0.0, y_mm), expected, places=8)

    def test_bottom_left_top_right_diagonal_uses_area_ratio_weights(self):
        bottom_left = self._package("BL", (1, 0), {"C": 0.0, "L": 0.0, "R": 4.0, "T": 4.0, "B": 0.0})
        top_right = self._package("TR", (0, 1), {"C": 0.0, "L": 3.0, "R": 0.0, "T": 0.0, "B": 3.0})
        result = self._generator().generate([bottom_left, top_right])
        x_mm, y_mm = -1.0, -1.0
        u = v = 0.25
        raw_bl, raw_tr = (1.0 - u) * (1.0 - v), u * v
        first_value = self._candidate_value(result, bottom_left, x_mm, y_mm)
        second_value = self._candidate_value(result, top_right, x_mm, y_mm)
        expected = (raw_bl * first_value + raw_tr * second_value) / (raw_bl + raw_tr)
        self.assertAlmostEqual(self._grid_value(result, x_mm, y_mm), expected, places=8)

    def test_top_left_bottom_right_diagonal_uses_area_ratio_weights(self):
        top_left = self._package("TL", (0, 0), {"C": 0.0, "L": 0.0, "R": 4.0, "T": 0.0, "B": 4.0})
        bottom_right = self._package("BR", (1, 1), {"C": 0.0, "L": 3.0, "R": 0.0, "T": 3.0, "B": 0.0})
        result = self._generator().generate([top_left, bottom_right])
        x_mm, y_mm = -1.0, 1.0
        u, v = 0.25, 0.75
        raw_tl, raw_br = (1.0 - u) * v, u * (1.0 - v)
        first_value = self._candidate_value(result, top_left, x_mm, y_mm)
        second_value = self._candidate_value(result, bottom_right, x_mm, y_mm)
        expected = (raw_tl * first_value + raw_br * second_value) / (raw_tl + raw_br)
        self.assertAlmostEqual(self._grid_value(result, x_mm, y_mm), expected, places=8)

    def test_three_package_overlap_averages_original_pair_blends(self):
        top_left = self._package("A", (0, 0), {"C": 0.0, "L": 0.0, "R": 5.0, "T": 0.0, "B": 4.0})
        top_right = self._package("B", (0, 1), {"C": 0.0, "L": 3.0, "R": 0.0, "T": 0.0, "B": 4.0})
        bottom_left = self._package("C", (1, 0), {"C": 0.0, "L": 0.0, "R": 5.0, "T": 3.0, "B": 0.0})
        result = self._generator().generate([top_left, top_right, bottom_left])
        x_mm, y_mm = 0.0, 0.0
        a = self._candidate_value(result, top_left, x_mm, y_mm)
        b = self._candidate_value(result, top_right, x_mm, y_mm)
        c = self._candidate_value(result, bottom_left, x_mm, y_mm)
        # At the common overlap midpoint every direct pair is 50/50 and the
        # diagonal raw areas are equal, so each pair blend is the mean.
        expected = (((a + b) / 2.0) + ((a + c) / 2.0) + ((b + c) / 2.0)) / 3.0
        self.assertAlmostEqual(self._grid_value(result, x_mm, y_mm), expected, places=8)

    def test_signed_candidates_cross_zero_without_overshoot(self):
        signed_generator = PressureMapGenerator(
            sensor_spacing_mm=1.0,
            package_center_spacing_mm=7.0,
            outer_boundary_reach_mm=2.0,
            pixels_per_mm=10.0,
            show_negative=True,
        )
        first = self._package("A", (0, 0), {"C": 0.0, "L": 0.0, "R": 5.0, "T": 0.0, "B": 0.0}, generator=signed_generator)
        second = self._package("B", (0, 1), {"C": 0.0, "L": -5.0, "R": 0.0, "T": 0.0, "B": 0.0}, generator=signed_generator)
        result = self._generator().generate([first, second])
        self.assertAlmostEqual(self._grid_value(result, 0.0, 0.0), 0.0, places=8)

        for x_mm in (-1.0, -0.5, 0.0, 0.5, 1.0):
            candidates = (self._candidate_value(result, first, x_mm, 0.0), self._candidate_value(result, second, x_mm, 0.0))
            value = self._grid_value(result, x_mm, 0.0)
            self.assertGreaterEqual(value, min(candidates) - 1e-12)
            self.assertLessEqual(value, max(candidates) + 1e-12)

    def test_output_is_independent_of_package_input_order(self):
        packages = [
            self._package("A", (0, 0), {"C": 0.0, "L": 0.0, "R": 4.0, "T": 0.0, "B": 4.0}),
            self._package("B", (0, 1), {"C": 0.0, "L": 3.0, "R": 0.0, "T": 0.0, "B": 4.0}),
            self._package("C", (1, 0), {"C": 0.0, "L": 0.0, "R": 4.0, "T": 3.0, "B": 0.0}),
        ]
        forward = self._generator().generate(packages)
        reverse = self._generator().generate(list(reversed(packages)))
        np.testing.assert_allclose(forward.x_coordinates_mm, reverse.x_coordinates_mm)
        np.testing.assert_allclose(forward.y_coordinates_mm, reverse.y_coordinates_mm)
        np.testing.assert_allclose(forward.pressure_grid, reverse.pressure_grid, rtol=1e-12, atol=1e-12)

    def test_every_package_uses_the_same_fixed_outer_support_square(self):
        packages = [
            self._package("A", (0, 0), {"C": 0.0, "L": 0.0, "R": 5.0, "T": 0.0, "B": 0.0}),
            self._package("B", (0, 2), {"C": 0.0, "L": 2.0, "R": 0.0, "T": 0.0, "B": 0.0}),
        ]
        result = self._generator().generate(packages)
        expected = (-5.5, 5.5, -5.5, 5.5)
        self.assertEqual(result.candidate_support_bounds_mm["A"], expected)
        self.assertEqual(result.candidate_support_bounds_mm["B"], expected)

    def test_candidates_are_zero_at_their_outer_support_boundaries(self):
        first = self._package("A", (0, 0), {"C": 0.0, "L": 0.0, "R": 5.0, "T": 0.0, "B": 0.0})
        second = self._package("B", (0, 1), {"C": 0.0, "L": 2.0, "R": 0.0, "T": 0.0, "B": 0.0})
        result = self._generator().generate([first, second])
        for package in (first, second):
            left, right, bottom, top = result.candidate_support_bounds_mm[package.sensor_id]
            for local_x, local_y in ((left, 0.0), (right, 0.0), (0.0, bottom), (0.0, top)):
                value = evaluate_pressure_map_result_at(
                    package.pressure_result,
                    np.asarray([local_x]),
                    np.asarray([local_y]),
                    support_bounds_mm=(left, right, bottom, top),
                )[0]
                self.assertAlmostEqual(float(value), 0.0, places=10)

    def test_four_package_overlap_uses_confidence_weighted_pair_aggregation(self):
        values = {"C": 1.0, "L": 1.0, "R": 1.0, "T": 1.0, "B": 1.0}
        packages = [
            self._package("A", (0, 0), values), self._package("B", (0, 1), values),
            self._package("C", (1, 0), values), self._package("D", (1, 1), values),
        ]
        result = self._generator().generate(packages)
        self.assertTrue(np.isfinite(result.pressure_grid).all())

    def test_support_confidence_is_smooth_from_mid_to_outer_boundary(self):
        generator = self._generator()
        radius = np.asarray([
            generator.mid_boundary_half_width_mm,
            (generator.mid_boundary_half_width_mm + generator.outer_boundary_half_width_mm) / 2.0,
            generator.outer_boundary_half_width_mm,
        ])
        confidence = generator._support_confidence(radius, np.zeros_like(radius))
        np.testing.assert_allclose(confidence, [1.0, 0.5, 0.0], atol=1e-12)

    def test_diagonal_weights_are_finite_and_continuous_at_former_singular_corner(self):
        first = self._package("A", (1, 0), {"C": 0.0, "L": 0.0, "R": 4.0, "T": 4.0, "B": 0.0})
        second = self._package("B", (0, 1), {"C": 0.0, "L": 3.0, "R": 0.0, "T": 0.0, "B": 3.0})
        result = self._generator().generate([first, second])
        corner = (-2.0, -2.0)
        nearby = (-1.999, -2.0)
        corner_value = self._grid_value(result, *corner)
        nearby_value = self._grid_value(result, *nearby)
        self.assertTrue(np.isfinite(corner_value))
        self.assertTrue(np.isfinite(nearby_value))
        self.assertLess(abs(corner_value - nearby_value), 0.1)

    def test_debug_array_diagnostics_are_opt_in(self):
        package = self._package("A", (0, 0), {"C": 0.0, "L": 0.0, "R": 1.0, "T": 0.0, "B": 0.0})
        result = self._generator(debug=True).generate([package])
        self.assertIsNotNone(result.diagnostics)
        self.assertIn("support_confidence", result.diagnostics)
        self.assertIn("pair_confidence_denominator", result.diagnostics)
        self.assertIn("candidate_fallback_denominator", result.diagnostics)
        self.assertIn("effective_pair_weights", result.diagnostics)
        self.assertIn("array_support_mask", result.diagnostics)

    def test_rejects_duplicate_ids_positions_nonfinite_data_and_geometry_mismatch(self):
        values = {"C": 0.0, "L": 0.0, "R": 1.0, "T": 0.0, "B": 0.0}
        first = self._package("A", (0, 0), values)
        duplicate_id = self._package("A", (0, 1), values)
        duplicate_position = self._package("B", (0, 0), values)
        with self.assertRaisesRegex(ValueError, "sensor_id"):
            self._generator().generate([first, duplicate_id])
        with self.assertRaisesRegex(ValueError, "grid_position"):
            self._generator().generate([first, duplicate_position])

        nonfinite = self._package("C", (0, 1), values)
        nonfinite.pressure_result.pressure_grid[0, 0] = np.nan
        with self.assertRaisesRegex(ValueError, "finite"):
            self._generator().generate([first, nonfinite])

        different_density = PressureMapGenerator(
            sensor_spacing_mm=1.0, package_center_spacing_mm=7.0,
            outer_boundary_reach_mm=2.0, pixels_per_mm=8.0,
        )
        incompatible = self._package("D", (0, 1), values, generator=different_density)
        with self.assertRaisesRegex(ValueError, "incompatible"):
            self._generator().generate([first, incompatible])

    def test_coordinate_metadata_uses_actual_linspace_spacing(self):
        values = {"C": 0.0, "L": 0.0, "R": 1.0, "T": 0.0, "B": 0.0}
        result = self._generator().generate([
            self._package("A", (0, 0), values),
            self._package("B", (0, 1), values),
        ])
        self.assertEqual(result.cell_size_x_mm, result.x_coordinates_mm[1] - result.x_coordinates_mm[0])
        self.assertEqual(result.cell_size_y_mm, result.y_coordinates_mm[1] - result.y_coordinates_mm[0])

    def test_inactive_neighbour_cannot_attenuate_an_active_candidate(self):
        active_values = {"C": 5.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.0}
        inactive_values = {"C": 0.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.0}
        inactive = self._package("ZERO", (0, 0), inactive_values)
        active = self._package("ACTIVE", (0, 1), active_values)
        result = self._generator().generate([inactive, active])

        for world_x in (0.5, 1.5, 2.5, 3.5):
            expected = self._candidate_value(result, active, world_x, 0.0)
            self.assertAlmostEqual(self._grid_value(result, world_x, 0.0), expected, places=10)
        self.assertEqual(inactive.pressure_result.package_activity_confidence, 0.0)

    def test_array_field_is_zero_at_and_outside_every_outer_boundary(self):
        first = self._package("A", (0, 0), {"C": 5.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.0})
        result = self._generator().generate([first])
        center_x, center_y = result.package_centers["A"]
        _left, right, _bottom, top = result.candidate_support_bounds_mm["A"]
        for world_x, world_y in ((center_x + right, center_y), (center_x + right + 0.1, center_y), (center_x, center_y + top)):
            actual = evaluate_pressure_map_result_at(
                first.pressure_result,
                np.asarray([world_x - center_x]),
                np.asarray([world_y - center_y]),
                support_bounds_mm=result.candidate_support_bounds_mm["A"],
            )[0]
            self.assertEqual(float(actual), 0.0)
        self.assertTrue(np.all(result.pressure_grid[[0, -1], :] == 0.0))
        self.assertTrue(np.all(result.pressure_grid[:, [0, -1]] == 0.0))

    def test_activity_confidence_is_smooth_between_threshold_and_full_participation(self):
        generator = PressureMapGenerator(
            sensor_spacing_mm=1.0,
            package_center_spacing_mm=7.0,
            outer_boundary_reach_mm=2.0,
            signal_activity_threshold=1.0,
            decay_amplitude_reference=5.0,
        )
        low = generator.generate({"C": 1.01, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.0})
        mid = generator.generate({"C": 1.5, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.0})
        high = generator.generate({"C": 2.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.0})
        self.assertGreater(low.package_activity_confidence, 0.0)
        self.assertGreater(mid.package_activity_confidence, low.package_activity_confidence)
        self.assertEqual(high.package_activity_confidence, 1.0)


if __name__ == "__main__":
    unittest.main()
