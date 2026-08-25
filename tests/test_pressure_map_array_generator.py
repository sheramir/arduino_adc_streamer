"""Tests for candidate-first Pressure Map array superposition."""

import unittest
import numpy as np

from data_processing.normal_force_calculator import NormalForceCalculator
from data_processing.pressure_map_array_generator import (
    PressureMapArrayGenerator,
    PressureMapArrayPackage,
    overlap_bounds_to_slice,
)
from data_processing.pressure_map_generator import PressureMapGenerator, evaluate_pressure_map_result_at


class PressureMapArrayGeneratorTests(unittest.TestCase):
    """Verify direct, diagonal, and multi-package fields superpose without cropping."""

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

    def _magnitude_grid_value(self, result, x_mm, y_mm):
        row = int(np.argmin(np.abs(result.y_coordinates_mm - y_mm)))
        col = int(np.argmin(np.abs(result.x_coordinates_mm - x_mm)))
        return float(result.magnitude_pressure_grid[row, col])

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
        self.assertEqual(result.structural_pairs, (("PZT3", "PZT6"),))
        self.assertEqual(result.adjacent_pairs, result.structural_pairs)
        self.assertEqual(result.active_overlap_pairs, ())
        self.assertEqual(result.overlap_pairs, result.active_overlap_pairs)

    def _contribution(self, result, package, x_mm, y_mm, *, generator=None):
        """Return one package's faded contribution at a world coordinate."""
        center_x, center_y = result.package_centers[package.sensor_id]
        confidence = float((generator or self._generator())._support_confidence(
            np.asarray(x_mm - center_x), np.asarray(y_mm - center_y)
        ))
        return confidence * self._candidate_value(result, package, x_mm, y_mm)

    def _assert_superposes(self, result, packages, x_mm, y_mm):
        generator = self._generator()
        values = [
            self._contribution(result, package, x_mm, y_mm, generator=generator)
            for package in packages
        ]
        self.assertAlmostEqual(self._grid_value(result, x_mm, y_mm), sum(values), places=8)
        self.assertAlmostEqual(
            self._magnitude_grid_value(result, x_mm, y_mm), abs(sum(values)), places=8
        )

    def test_horizontal_overlap_superposes_both_package_fields(self):
        first = self._package("A", (0, 0), {"C": 0.0, "L": 0.0, "R": 5.0, "T": 0.0, "B": 0.0})
        second = self._package("B", (0, 1), {"C": 0.0, "L": 2.0, "R": 0.0, "T": 0.0, "B": 0.0})
        result = self._generator().generate([first, second])

        for x_mm in (-2.0, -1.0, 0.0, 1.0, 2.0):
            self._assert_superposes(result, (first, second), x_mm, 0.0)
        self.assertEqual(result.structural_pairs, (("A", "B"),))
        self.assertEqual(result.active_overlap_pairs, (("A", "B"),))
        self.assertEqual(result.overlap_pairs, (("A", "B"),))

    def test_vertical_overlap_superposes_both_package_fields(self):
        top = self._package("TOP", (0, 0), {"C": 0.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 4.0})
        bottom = self._package("BOTTOM", (1, 0), {"C": 0.0, "L": 0.0, "R": 0.0, "T": 2.0, "B": 0.0})
        result = self._generator().generate([top, bottom])

        # y grows from the physical bottom package side to the top package side.
        for y_mm in (-2.0, -1.0, 0.0, 1.0, 2.0):
            self._assert_superposes(result, (top, bottom), 0.0, y_mm)

    def test_bottom_left_top_right_diagonal_superposes(self):
        bottom_left = self._package("BL", (1, 0), {"C": 0.0, "L": 0.0, "R": 4.0, "T": 4.0, "B": 0.0})
        top_right = self._package("TR", (0, 1), {"C": 0.0, "L": 3.0, "R": 0.0, "T": 0.0, "B": 3.0})
        result = self._generator().generate([bottom_left, top_right])
        self._assert_superposes(result, (bottom_left, top_right), -1.0, -1.0)

    def test_top_left_bottom_right_diagonal_superposes(self):
        top_left = self._package("TL", (0, 0), {"C": 0.0, "L": 0.0, "R": 4.0, "T": 0.0, "B": 4.0})
        bottom_right = self._package("BR", (1, 1), {"C": 0.0, "L": 3.0, "R": 0.0, "T": 3.0, "B": 0.0})
        result = self._generator().generate([top_left, bottom_right])
        self._assert_superposes(result, (top_left, bottom_right), -1.0, 1.0)

    def test_three_package_overlap_superposes_every_contribution(self):
        top_left = self._package("A", (0, 0), {"C": 0.0, "L": 0.0, "R": 5.0, "T": 0.0, "B": 4.0})
        top_right = self._package("B", (0, 1), {"C": 0.0, "L": 3.0, "R": 0.0, "T": 0.0, "B": 4.0})
        bottom_left = self._package("C", (1, 0), {"C": 0.0, "L": 0.0, "R": 5.0, "T": 3.0, "B": 0.0})
        result = self._generator().generate([top_left, top_right, bottom_left])
        self._assert_superposes(result, (top_left, top_right, bottom_left), 0.0, 0.0)

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

        first_value = self._candidate_value(result, first, 0.0, 0.0)
        self.assertGreater(abs(first_value), 0.0)
        # Superposition yields one field, and magnitude is that field's
        # magnitude.  Equal and opposite package fields therefore cancel here
        # rather than reading as the sum of their separate magnitudes.
        self.assertAlmostEqual(self._grid_value(result, 0.0, 0.0), 0.0, places=8)
        self.assertAlmostEqual(self._magnitude_grid_value(result, 0.0, 0.0), 0.0, places=8)
        np.testing.assert_allclose(
            result.magnitude_pressure_grid, np.abs(result.pressure_grid)
        )

    def test_magnitude_does_not_double_count_overlapping_packages(self):
        # Regression: accumulating sum |v| made every support overlap read
        # roughly twice as bright as either package measured.
        first = self._package("A", (0, 0), {"C": 0.0, "L": 0.0, "R": 5.0, "T": 0.0, "B": 0.0})
        second = self._package("B", (0, 1), {"C": 0.0, "L": 5.0, "R": 0.0, "T": 0.0, "B": 0.0})
        result = self._generator().generate([first, second])

        np.testing.assert_allclose(
            result.magnitude_pressure_grid, np.abs(result.pressure_grid)
        )
        for x_mm in (-2.0, -1.0, 0.0, 1.0, 2.0):
            contributions = [
                self._contribution(result, package, x_mm, 0.0) for package in (first, second)
            ]
            self.assertAlmostEqual(
                self._magnitude_grid_value(result, x_mm, 0.0), abs(sum(contributions)), places=8
            )

    def test_locally_absent_active_candidate_passes_through_present_neighbour(self):
        center_only = self._package(
            "CENTER", (0, 0), {"C": 5.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.0}
        )
        left_lobe = self._package(
            "LEFT", (0, 1), {"C": 0.0, "L": 5.0, "R": 0.0, "T": 0.0, "B": 0.0}
        )
        result = self._generator().generate([center_only, left_lobe])

        # At the overlap midpoint, the center-only field has already ended,
        # while the left-facing lobe remains nonzero.
        expected = self._candidate_value(result, left_lobe, 0.0, 0.0)
        self.assertGreater(abs(expected), 0.0)
        self.assertAlmostEqual(self._candidate_value(result, center_only, 0.0, 0.0), 0.0, places=12)
        self.assertAlmostEqual(self._grid_value(result, 0.0, 0.0), expected, places=10)
        self.assertAlmostEqual(self._magnitude_grid_value(result, 0.0, 0.0), abs(expected), places=10)

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
        self.assertIn("candidate_fields", result.diagnostics)
        self.assertIn("array_support_mask", result.diagnostics)
        self.assertIn("local_presence", result.diagnostics)
        self.assertIn("eligible_neighbor_pairs", result.diagnostics)
        self.assertIn("final_magnitude_array_field", result.diagnostics)
        self.assertEqual(result.diagnostics["structural_pairs"], result.structural_pairs)
        self.assertEqual(result.diagnostics["active_overlap_pairs"], result.active_overlap_pairs)

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
            self.assertAlmostEqual(self._magnitude_grid_value(result, world_x, 0.0), abs(expected), places=10)
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
        self.assertTrue(np.all(result.magnitude_pressure_grid[[0, -1], :] == 0.0))
        self.assertTrue(np.all(result.magnitude_pressure_grid[:, [0, -1]] == 0.0))

    def test_pair_prefilter_skips_away_facing_lobes_but_keeps_center_active_package(self):
        array_generator = self._generator()
        away_first = self._package("A", (0, 0), {"C": 0.0, "L": 3.0, "R": 0.0, "T": 0.0, "B": 0.0})
        away_second = self._package("B", (0, 1), {"C": 0.0, "L": 0.0, "R": 3.0, "T": 0.0, "B": 0.0})
        center = self._package("C", (0, 0), {"C": 3.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.0})
        centers = array_generator._package_centers([away_first, away_second])
        bounds = array_generator._candidate_support_bounds([away_first, away_second], centers)
        coordinates = array_generator._array_coordinates([away_first, away_second], centers, bounds)
        x_grid, y_grid = np.meshgrid(*coordinates)
        first_candidate = array_generator._evaluate_candidate(away_first, centers["A"], bounds["A"], x_grid, y_grid)
        second_candidate = array_generator._evaluate_candidate(away_second, centers["B"], bounds["B"], x_grid, y_grid)
        center_candidate = array_generator._evaluate_candidate(center, centers["A"], bounds["A"], x_grid, y_grid)

        self.assertFalse(array_generator._pair_is_sensor_relevant(first_candidate, second_candidate))
        self.assertTrue(array_generator._pair_is_sensor_relevant(center_candidate, second_candidate))

    def test_neighbor_enumeration_is_linear_for_regular_array(self):
        packages = [
            self._package(f"P{row}{col}", (row, col), {"C": 1.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.0})
            for row in range(3) for col in range(3)
        ]
        array_generator = self._generator()
        centers = array_generator._package_centers(packages)
        bounds = array_generator._candidate_support_bounds(packages, centers)
        coordinates = array_generator._array_coordinates(packages, centers, bounds)
        x_grid, y_grid = np.meshgrid(*coordinates)
        candidates = tuple(
            array_generator._evaluate_candidate(package, centers[package.sensor_id], bounds[package.sensor_id], x_grid, y_grid)
            for package in packages
        )
        pairs = array_generator._eligible_neighbor_pairs(candidates)

        self.assertEqual(len(pairs), 20)
        self.assertLessEqual(len(pairs), 4 * len(packages))
        for first, second in pairs:
            row_delta = abs(first.package.grid_position[0] - second.package.grid_position[0])
            col_delta = abs(first.package.grid_position[1] - second.package.grid_position[1])
            self.assertLessEqual(row_delta, 1)
            self.assertLessEqual(col_delta, 1)

    def test_active_overlap_pairs_use_the_shared_support_slice(self):
        first = self._package("A", (0, 0), {"C": 0.0, "L": 0.0, "R": 4.0, "T": 0.0, "B": 0.0})
        second = self._package("B", (0, 1), {"C": 0.0, "L": 4.0, "R": 0.0, "T": 0.0, "B": 0.0})
        array_generator = self._generator()
        centers = array_generator._package_centers([first, second])
        bounds = array_generator._candidate_support_bounds([first, second], centers)
        coordinates = array_generator._array_coordinates([first, second], centers, bounds)
        x_grid, y_grid = np.meshgrid(*coordinates)
        first_candidate = array_generator._evaluate_candidate(first, centers["A"], bounds["A"], x_grid, y_grid)
        second_candidate = array_generator._evaluate_candidate(second, centers["B"], bounds["B"], x_grid, y_grid)
        overlap = array_generator._support_overlap(first_candidate, second_candidate)
        y_slice, x_slice = overlap_bounds_to_slice(overlap, *coordinates)

        self.assertGreater(x_grid[y_slice, x_slice].size, 0)
        self.assertEqual(
            array_generator._active_overlap_pairs(
                ((first_candidate, second_candidate),), *coordinates
            ),
            (("A", "B"),),
        )

    def test_facing_lobes_add_instead_of_cropping_each_other(self):
        # Regression for a large lobe being cut flat where a small facing lobe
        # on the neighbouring package began.
        large = self._package("BOTTOM", (1, 0), {"C": 0.0, "L": 0.0, "R": 0.0, "T": 5.0, "B": 0.0})
        small = self._package("TOP", (0, 0), {"C": 0.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.5})
        quiet = self._package("TOP", (0, 0), {"C": 0.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.0})
        # The quiet neighbour keeps both runs on the same world raster.
        alone = self._generator().generate([large, quiet])
        combined = self._generator().generate([large, small])
        np.testing.assert_allclose(alone.y_coordinates_mm, combined.y_coordinates_mm)

        rose_above_alone = False
        for y_mm in np.arange(-3.0, 3.01, 0.1):
            alone_value = self._grid_value(alone, 0.0, float(y_mm))
            combined_value = self._grid_value(combined, 0.0, float(y_mm))
            # Same-sign neighbours may only add.
            self.assertGreaterEqual(combined_value, alone_value - 1e-12)
            rose_above_alone = rose_above_alone or combined_value > alone_value + 1e-9
        self.assertTrue(rose_above_alone)

    def test_composition_stays_continuous_across_a_neighbour_support_edge(self):
        # The removed presence test made a pixel jump as soon as a neighbour
        # field became nonzero.  A sum of continuous candidates cannot.
        first = self._package("BOTTOM", (1, 0), {"C": 0.0, "L": 0.0, "R": 0.0, "T": 5.0, "B": 0.0})
        second = self._package("TOP", (0, 0), {"C": 0.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.5})
        result = self._generator().generate([first, second])
        column = int(np.argmin(np.abs(result.x_coordinates_mm)))
        profile = result.pressure_grid[:, column]
        candidate_steps = max(
            float(np.max(np.abs(np.diff(
                np.asarray([
                    self._candidate_value(result, package, 0.0, float(y_mm))
                    for y_mm in result.y_coordinates_mm
                ])
            ))))
            for package in (first, second)
        )
        self.assertLessEqual(
            float(np.max(np.abs(np.diff(profile)))),
            2.0 * candidate_steps + 1e-12,
        )

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
