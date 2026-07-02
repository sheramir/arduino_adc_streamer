"""Tests for array-level Pressure Map interpolation."""

import unittest
import warnings

import numpy as np

from data_processing.normal_force_calculator import NormalForceCalculator
from data_processing.pressure_map_array_generator import PressureMapArrayGenerator, PressureMapArrayPackage
from data_processing.pressure_map_generator import PressureMapGenerator


class PressureMapArrayGeneratorTests(unittest.TestCase):
    """Verify physical package spacing and adjacent gap interpolation."""

    def setUp(self):
        self.normal_calculator = NormalForceCalculator()
        self.package_generator = PressureMapGenerator(circle_diameter_mm=5.0, sensor_spacing_mm=1.0)
        self.zero_pressure_result = self.package_generator.generate({"C": 0.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.0})

    def _package(self, sensor_id, grid_position, calibrated_values):
        normal_result = self.normal_calculator.compute(calibrated_values)
        return PressureMapArrayPackage(
            sensor_id=sensor_id,
            grid_position=grid_position,
            normal_force_result=normal_result,
            pressure_result=self.zero_pressure_result,
            calibrated_values=dict(calibrated_values),
        )

    def _generate(self, packages, **kwargs):
        return PressureMapArrayGenerator(
            circle_diameter_mm=5.0,
            package_gap_mm=2.0,
            **kwargs,
        ).generate(packages)

    def _values_near(self, result, *, x_min, x_max, y_min, y_max):
        mask = (
            (result.x_grid_mm >= x_min)
            & (result.x_grid_mm <= x_max)
            & (result.y_grid_mm >= y_min)
            & (result.y_grid_mm <= y_max)
        )
        return result.pressure_grid[mask]

    def test_package_centers_use_circle_diameter_plus_gap(self):
        result = self._generate([
            self._package("PZT3", (0, 0), {"C": 0.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.0}),
            self._package("PZT6", (0, 1), {"C": 0.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.0}),
        ])

        first_x = result.package_centers["PZT3"][0]
        second_x = result.package_centers["PZT6"][0]

        self.assertAlmostEqual(second_x - first_x, 7.0)

    def test_horizontal_adjacent_facing_sensors_create_extrapolated_gap_peak(self):
        result = self._generate([
            self._package("PZT3", (0, 0), {"C": 0.0, "L": 0.0, "R": 5.0, "T": 0.0, "B": 0.0}),
            self._package("PZT6", (0, 1), {"C": 0.0, "L": 2.0, "R": 0.0, "T": 0.0, "B": 0.0}),
        ])
        values = self._values_near(result, x_min=-2.0, x_max=2.0, y_min=-0.2, y_max=0.2)

        self.assertGreater(float(np.max(values)), 5.5)
        self.assertEqual(result.adjacent_pairs, (("PZT3", "PZT6"),))

    def test_gap_contrast_gain_controls_extrapolated_peak_height(self):
        packages = [
            self._package("PZT3", (0, 0), {"C": 0.0, "L": 0.0, "R": 5.0, "T": 0.0, "B": 0.0}),
            self._package("PZT6", (0, 1), {"C": 0.0, "L": 2.0, "R": 0.0, "T": 0.0, "B": 0.0}),
        ]

        no_contrast = self._generate(packages, gap_contrast_gain=0.0)
        high_contrast = self._generate(packages, gap_contrast_gain=1.0)

        self.assertLess(float(np.max(no_contrast.pressure_grid)), float(np.max(high_contrast.pressure_grid)))

    def test_gap_fade_width_controls_lateral_spread(self):
        packages = [
            self._package("PZT3", (0, 0), {"C": 0.0, "L": 0.0, "R": 5.0, "T": 0.0, "B": 0.0}),
            self._package("PZT6", (0, 1), {"C": 0.0, "L": 2.0, "R": 0.0, "T": 0.0, "B": 0.0}),
        ]

        narrow = self._generate(packages, gap_fade_width_fraction=0.1)
        wide = self._generate(packages, gap_fade_width_fraction=1.0)

        self.assertLess(
            int(np.count_nonzero(narrow.pressure_grid > 0.0)),
            int(np.count_nonzero(wide.pressure_grid > 0.0)),
        )

    def test_vertical_adjacent_facing_sensors_create_gap_pressure(self):
        result = self._generate([
            self._package("PZT6", (0, 0), {"C": 0.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 2.0}),
            self._package("PZT3", (1, 0), {"C": 0.0, "L": 0.0, "R": 0.0, "T": 5.0, "B": 0.0}),
        ])
        values = self._values_near(result, x_min=-0.2, x_max=0.2, y_min=-2.0, y_max=2.0)

        self.assertGreater(float(np.max(values)), 5.5)
        self.assertEqual(result.adjacent_pairs, (("PZT6", "PZT3"),))

    def test_center_dominant_package_decays_without_new_gap_peak(self):
        result = self._generate([
            self._package("PZT3", (0, 0), {"C": 8.0, "L": 0.0, "R": 5.0, "T": 0.0, "B": 0.0}),
            self._package("PZT6", (0, 1), {"C": 0.0, "L": 2.0, "R": 0.0, "T": 0.0, "B": 0.0}),
        ])
        values = self._values_near(result, x_min=-2.0, x_max=2.0, y_min=-0.2, y_max=0.2)

        self.assertLessEqual(float(np.max(values)), 5.0)
        self.assertGreater(float(np.max(values)), 2.0)

    def test_gap_peak_moves_closer_to_stronger_facing_sensor(self):
        result = self._generate([
            self._package("PZT3", (0, 0), {"C": 0.0, "L": 0.0, "R": 5.0, "T": 0.0, "B": 0.0}),
            self._package("PZT6", (0, 1), {"C": 0.0, "L": 2.0, "R": 0.0, "T": 0.0, "B": 0.0}),
        ])
        row_index = int(np.argmin(np.abs(result.y_coordinates_mm)))
        values = result.pressure_grid[row_index]
        peak_x = float(result.x_coordinates_mm[int(np.argmax(values))])

        self.assertLess(peak_x, 0.0)

    def test_diagonal_packages_do_not_create_gap_bridge(self):
        result = self._generate([
            self._package("PZT3", (0, 0), {"C": 0.0, "L": 0.0, "R": 5.0, "T": 0.0, "B": 0.0}),
            self._package("PZT6", (1, 1), {"C": 0.0, "L": 2.0, "R": 0.0, "T": 0.0, "B": 0.0}),
        ])

        self.assertEqual(result.adjacent_pairs, ())
        self.assertEqual(float(np.max(result.pressure_grid)), 0.0)

    def test_opposite_sign_facing_sensors_interpolate_through_zero(self):
        result = self._generate(
            [
                self._package("PZT3", (0, 0), {"C": 0.0, "L": 0.0, "R": 5.0, "T": 0.0, "B": 0.0}),
                self._package("PZT6", (0, 1), {"C": 0.0, "L": -5.0, "R": 0.0, "T": 0.0, "B": 0.0}),
            ],
            show_negative=True,
        )
        values = self._values_near(result, x_min=-0.2, x_max=0.2, y_min=-0.2, y_max=0.2)

        self.assertLess(float(np.min(np.abs(values))), 0.5)

    def test_show_negative_false_clamps_negative_gap_values(self):
        result = self._generate([
            self._package("PZT3", (0, 0), {"C": 0.0, "L": 0.0, "R": -5.0, "T": 0.0, "B": 0.0}),
            self._package("PZT6", (0, 1), {"C": 0.0, "L": -2.0, "R": 0.0, "T": 0.0, "B": 0.0}),
        ])

        self.assertEqual(float(np.min(result.pressure_grid)), 0.0)
        self.assertEqual(float(np.max(result.pressure_grid)), 0.0)

    def test_one_sided_gap_peak_does_not_warn_on_zero_peak_denominator(self):
        packages = [
            self._package("PZT3", (0, 0), {"C": 0.0, "L": 0.0, "R": 5.0, "T": 0.0, "B": 0.0}),
            self._package("PZT6", (0, 1), {"C": 0.0, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.0}),
        ]

        with warnings.catch_warnings(record=True) as caught_warnings:
            warnings.simplefilter("always")
            result = self._generate(packages)

        warning_messages = [str(item.message) for item in caught_warnings]
        self.assertFalse(any("divide by zero" in message for message in warning_messages))
        self.assertGreater(float(np.max(result.pressure_grid)), 0.0)


if __name__ == "__main__":
    unittest.main()
