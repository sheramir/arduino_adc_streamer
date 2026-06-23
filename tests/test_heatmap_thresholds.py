import threading
import unittest

import numpy as np

from constants.heatmap import HEATMAP_COORD_EXTENT, HEATMAP_HEIGHT, HEATMAP_WIDTH, MAX_SENSOR_PACKAGES
from data_processing.heatmap_555_processor import Heatmap555ProcessorMixin
from data_processing.heatmap_piezo_processor import PiezoHeatmapProcessorMixin
from gui.heatmap_panel import HeatmapPanelMixin


class Dummy555Processor(Heatmap555ProcessorMixin):
    MAX_SWEEPS_BUFFER = 8

    def __init__(self):
        self.config = {
            "channels": [1, 2, 3, 4, 5],
            "repeat": 1,
            "selected_array_sensors": ["PZR2"],
        }
        self.buffer_lock = threading.Lock()
        self.samples_per_sweep = 5
        self.raw_data_buffer = np.zeros((self.MAX_SWEEPS_BUFFER, self.samples_per_sweep), dtype=np.float32)
        self.raw_data_buffer[0, :] = np.array([100.0, 100.0, 100.0, 100.0, 100.0], dtype=np.float32)
        self.raw_data_buffer[1, :] = np.array([112.0, 119.0, 132.0, 139.0, 156.0], dtype=np.float32)
        self.sweep_count = 2
        self.buffer_write_index = 2
        self.heatmap_x_grid = np.zeros((HEATMAP_HEIGHT, HEATMAP_WIDTH), dtype=np.float32)
        self.heatmap_y_grid = np.zeros((HEATMAP_HEIGHT, HEATMAP_WIDTH), dtype=np.float32)
        self.reset_555_heatmap_state()

    def is_array_sensor_selection_mode(self):
        return True


class StubSignalProcessor:
    def set_hpf_cutoff(self, cutoff_hz):
        self.cutoff_hz = cutoff_hz

    def compute_rms(self, channel_samples, dc_removal_mode, sample_rate_hz, window_end_time_sec):
        return [11.0, 19.0, 32.0, 39.0, 56.0], np.zeros(5, dtype=np.float64)

    def smooth_and_threshold(self, values, alpha, threshold):
        return list(values)


class MeanSignalProcessor:
    def set_hpf_cutoff(self, cutoff_hz):
        self.cutoff_hz = cutoff_hz

    def compute_rms(self, channel_samples, dc_removal_mode, sample_rate_hz, window_end_time_sec):
        values = []
        for samples in channel_samples:
            sample_array = np.asarray(samples, dtype=np.float64)
            values.append(float(np.mean(sample_array)) if sample_array.size else 0.0)
        return values, np.zeros(len(values), dtype=np.float64)

    def smooth_and_threshold(self, values, alpha, threshold):
        return list(values)


class DummyPiezoProcessor(PiezoHeatmapProcessorMixin):
    def __init__(self):
        self.config = {
            "channels": [1, 2, 3, 4, 5],
            "repeat": 1,
            "selected_array_sensors": ["PZT1"],
        }
        self.heatmap_signal_processors = [StubSignalProcessor()]

    def _extract_heatmap_window_data(self, window_ms):
        data_array = np.zeros((1, 5), dtype=np.float64)
        timestamps = np.array([2.0], dtype=np.float64)
        return data_array, timestamps, 1000.0

    def is_array_sensor_selection_mode(self):
        return True

    def get_array_selected_sensor_groups(self):
        return [{
            "sensor_id": "PZT1",
            "channels": [1, 2, 3, 4, 5],
            "positions": [0, 1, 2, 3, 4],
        }]

    def get_sensor_package_groups(self, required_channels, channels=None):
        return self.get_array_selected_sensor_groups()


class ArrayMuxPiezoProcessor(PiezoHeatmapProcessorMixin):
    def __init__(self):
        self.config = {
            "channels": [0, 1, 2, 3, 4],
            "repeat": 1,
            "selected_array_sensors": ["PZT3"],
            "channel_selection_source": "array",
        }
        self.heatmap_signal_processors = [MeanSignalProcessor()]

    def _extract_heatmap_window_data(self, window_ms):
        # Paired-MUX sample order for one sweep:
        # Ch0 M1, Ch0 M2, Ch1 M1, Ch1 M2, ...
        data_array = np.asarray(
            [[100.0, 10.0, 200.0, 20.0, 300.0, 30.0, 400.0, 40.0, 500.0, 50.0]],
            dtype=np.float64,
        )
        timestamps = np.asarray([1.0], dtype=np.float64)
        return data_array, timestamps, 1000.0

    def get_display_channel_specs(self):
        placements = ["T", "R", "C", "L", "B"]
        specs = []
        for local_index, placement in enumerate(placements):
            channel = self.config["channels"][local_index]
            specs.append({
                "key": ("sensor", "PZT3", placement, channel, 2),
                "label": f"PZT3_{placement}",
                "sample_indices": [(local_index * 2) + 1],
                "color_slot": local_index,
            })
        return specs

    def get_array_selected_sensor_groups(self):
        return [{
            "sensor_id": "PZT3",
            "mux": 2,
            "channels": [0, 1, 2, 3, 4],
            "positions": [0, 1, 2, 3, 4],
        }]

    def get_sensor_package_groups(self, required_channels, channels=None):
        return self.get_array_selected_sensor_groups()


class DirectPiezoHeatmapProcessor(PiezoHeatmapProcessorMixin):
    def __init__(self):
        self.smoothed_cop_x = [0.0]
        self.smoothed_cop_y = [0.0]
        self.smoothed_intensity = [0.0]
        self.heatmap_buffers = [
            np.zeros((HEATMAP_HEIGHT, HEATMAP_WIDTH), dtype=np.float32)
        ]
        y_coords = np.linspace(-HEATMAP_COORD_EXTENT, HEATMAP_COORD_EXTENT, HEATMAP_HEIGHT).reshape(-1, 1)
        x_coords = np.linspace(-HEATMAP_COORD_EXTENT, HEATMAP_COORD_EXTENT, HEATMAP_WIDTH).reshape(1, -1)
        self.heatmap_y_grid = np.tile(y_coords, (1, HEATMAP_WIDTH))
        self.heatmap_x_grid = np.tile(x_coords, (HEATMAP_HEIGHT, 1))


class FakeImageItem:
    def setImage(self, image, autoLevels=False, levels=None):
        self.image = image
        self.autoLevels = autoLevels
        self.levels = levels


class HeatmapLayoutHarness(HeatmapPanelMixin):
    def __init__(self):
        self.config = {
            "selected_array_sensors": ["PZT1", "PZT3", "PZT5", "PZT6", "PZT7"],
        }
        self.display_circle_diameter = 160.0
        self.display_heatmap_size = 160.0 * HEATMAP_COORD_EXTENT
        self.display_cell_spacing = 160.0

    def is_array_sensor_selection_mode(self):
        return True

    def _is_display_mirror_enabled(self):
        return False

    def get_active_sensor_configuration(self):
        return {
            "array_layout": {
                "cells": [
                    [None, "PZT7", None],
                    ["PZT1", "PZT6", "PZT5"],
                    [None, "PZT3", None],
                ]
            }
        }


class HeatmapThresholdTests(unittest.TestCase):
    def _peak_row_col(self, heatmap):
        return np.unravel_index(int(np.argmax(heatmap)), heatmap.shape)

    def test_piezo_heatmap_blob_uses_columns_for_left_right_motion(self):
        settings = {
            "smooth_alpha": 1.0,
            "intensity_scale": 1.0,
            "blob_sigma_x": 0.08,
            "blob_sigma_y": 0.08,
        }

        processor = DirectPiezoHeatmapProcessor()
        right_heatmap, right_x, right_y, *_ = processor.process_sensor_data_for_heatmap(
            [0.0, 0.0, 10.0, 0.0, 0.0],
            settings,
        )
        right_row, right_col = self._peak_row_col(right_heatmap)

        processor = DirectPiezoHeatmapProcessor()
        left_heatmap, left_x, left_y, *_ = processor.process_sensor_data_for_heatmap(
            [0.0, 0.0, 0.0, 10.0, 0.0],
            settings,
        )
        left_row, left_col = self._peak_row_col(left_heatmap)

        center_row = HEATMAP_HEIGHT // 2
        self.assertGreater(right_x, 0.9)
        self.assertAlmostEqual(right_y, 0.0, places=5)
        self.assertGreater(right_col, int(HEATMAP_WIDTH * 0.75))
        self.assertLess(right_col, int(HEATMAP_WIDTH * 0.95))
        self.assertLess(abs(right_row - center_row), int(HEATMAP_HEIGHT * 0.1))
        self.assertLess(left_x, -0.9)
        self.assertAlmostEqual(left_y, 0.0, places=5)
        self.assertGreater(left_col, int(HEATMAP_WIDTH * 0.05))
        self.assertLess(left_col, int(HEATMAP_WIDTH * 0.25))
        self.assertLess(abs(left_row - center_row), int(HEATMAP_HEIGHT * 0.1))

    def test_heatmap_panel_uses_row_major_images_without_transpose(self):
        panel = HeatmapPanelMixin.__new__(HeatmapPanelMixin)
        image_item = panel._create_heatmap_image_item()
        self.assertEqual(image_item.axisOrder, "row-major")

        fake_item = FakeImageItem()
        heatmap = np.arange(12, dtype=np.float32).reshape(3, 4)

        panel._set_heatmap_image(fake_item, heatmap)

        self.assertIs(fake_item.image, heatmap)
        self.assertEqual(fake_item.image.shape, (3, 4))
        self.assertFalse(fake_item.autoLevels)
        self.assertEqual(fake_item.levels, (0, 1))

    def test_heatmap_array_package_centers_follow_sensor_layout(self):
        panel = HeatmapLayoutHarness()

        centers = panel._get_display_package_centers(5)

        self.assertGreaterEqual(MAX_SENSOR_PACKAGES, 5)
        self.assertEqual(
            centers,
            [
                (-160.0, 0.0),
                (0.0, 160.0),
                (160.0, 0.0),
                (0.0, 0.0),
                (0.0, -160.0),
            ],
        )

    def test_heatmap_display_bounds_expand_to_viewport_aspect(self):
        panel = HeatmapLayoutHarness()

        x_min, x_max, y_min, y_max = panel._aspect_correct_display_bounds(
            -217.6,
            217.6,
            -297.6,
            297.6,
            viewport_width=966.0,
            viewport_height=307.0,
        )

        self.assertAlmostEqual((x_max - x_min) / (y_max - y_min), 966.0 / 307.0)
        self.assertLessEqual(x_min, -217.6)
        self.assertGreaterEqual(x_max, 217.6)
        self.assertEqual((y_min, y_max), (-297.6, 297.6))

    def test_555_thresholds_use_package_sensor_id_and_per_channel_totals(self):
        processor = Dummy555Processor()
        settings = {
            "channel_sensor_map": ["T", "B", "R", "L", "C"],
            "global_noise_threshold": 20.0,
            "global_channel_release_thresholds": [1000.0, 1000.0, 1000.0, 1000.0, 1000.0],
            "sensor_calibration_dict": {
                "PZR2": {
                    "thresholds": [1.0, 2.0, 3.0, 4.0, 5.0],
                    "gains": [1.0, 1.0, 1.0, 1.0, 1.0],
                }
            },
            "sensor_calibration": [1.0, 1.0, 1.0, 1.0, 1.0],
            "sensor_pos_x": [0.0, 0.0, 0.0, 0.0, 0.0],
            "sensor_pos_y": [0.0, 0.0, 0.0, 0.0, 0.0],
            "cop_smooth_alpha": 1.0,
            "map_smooth_alpha": 1.0,
            "intensity_scale": 1.0,
            "intensity_min": 0.0,
            "intensity_max": 1.0,
            "blob_sigma_x": 1.0,
            "blob_sigma_y": 1.0,
            "axis_adapt_strength": 0.0,
        }

        result = processor.process_555_displacement_heatmap(settings)

        self.assertEqual(len(result), 1)
        _, _, _, intensity, _, display_values = result[0]
        self.assertEqual(display_values, [0.0, 0.0, 16.0, 19.5, 28.0])
        self.assertAlmostEqual(intensity, 63.5)

    def test_piezo_thresholds_use_global_plus_package_channel_thresholds(self):
        processor = DummyPiezoProcessor()
        settings = {
            "rms_window_ms": 50.0,
            "dc_removal_mode": "bias",
            "hpf_cutoff_hz": 0.0,
            "channel_sensor_map": ["T", "B", "R", "L", "C"],
            "channel_to_baseline": {},
            "sensor_noise_floor": [0.0, 0.0, 0.0, 0.0, 0.0],
            "sensor_calibration": [1.0, 1.0, 1.0, 1.0, 1.0],
            "global_noise_threshold": 20.0,
            "sensor_calibration_dict": {
                "PZT1": {
                    "thresholds": [1.0, 2.0, 3.0, 4.0, 5.0],
                    "gains": [1.0, 1.0, 1.0, 1.0, 1.0],
                }
            },
            "smooth_alpha": 1.0,
        }

        values = processor.compute_channel_intensities(settings)

        self.assertEqual(values, [[0.0, 0.0, 32.0, 39.0, 56.0]])

    def test_piezo_array_mux_mode_uses_display_spec_sample_indices(self):
        processor = ArrayMuxPiezoProcessor()
        settings = {
            "rms_window_ms": 50.0,
            "dc_removal_mode": "bias",
            "hpf_cutoff_hz": 0.0,
            "channel_sensor_map": ["T", "R", "C", "L", "B"],
            "channel_to_baseline": {},
            "sensor_noise_floor": [0.0, 0.0, 0.0, 0.0, 0.0],
            "sensor_calibration": [1.0, 1.0, 1.0, 1.0, 1.0],
            "global_noise_threshold": 0.0,
            "sensor_calibration_dict": {},
            "smooth_alpha": 1.0,
        }

        values = processor.compute_channel_intensities(settings)

        self.assertEqual(values, [[10.0, 50.0, 20.0, 40.0, 30.0]])

    def test_555_cop_respects_configured_channel_placement(self):
        processor = Dummy555Processor()
        processor.raw_data_buffer[0, :] = np.array([100.0, 100.0, 100.0, 100.0, 100.0], dtype=np.float32)
        processor.raw_data_buffer[1, :] = np.array([140.0, 100.0, 100.0, 100.0, 145.0], dtype=np.float32)
        processor.sweep_count = 2
        processor.buffer_write_index = 2
        processor.reset_555_heatmap_state()

        settings = {
            "channel_sensor_map": ["L", "B", "C", "R", "T"],
            "global_noise_threshold": 0.0,
            "sensor_calibration_dict": {
                "PZR2": {
                    "thresholds": [0.0, 0.0, 0.0, 0.0, 0.0],
                    "gains": [1.0, 1.0, 1.0, 1.0, 1.0],
                }
            },
            "sensor_calibration": [1.0, 1.0, 1.0, 1.0, 1.0],
            "cop_smooth_alpha": 1.0,
            "map_smooth_alpha": 1.0,
            "intensity_scale": 1.0,
            "intensity_min": 0.0,
            "intensity_max": 1.0,
            "blob_sigma_x": 1.0,
            "blob_sigma_y": 1.0,
            "axis_adapt_strength": 0.0,
        }

        result = processor.process_555_displacement_heatmap(settings)

        self.assertEqual(len(result), 1)
        _, cop_x, cop_y, _, _, _ = result[0]
        self.assertLess(cop_x, 0.0)
        self.assertLess(cop_y, 0.0)

    def test_555_uses_channel_baselines_for_heatmap_calculation(self):
        processor = Dummy555Processor()
        processor.raw_data_buffer[0, :] = np.array([112.0, 119.0, 132.0, 139.0, 156.0], dtype=np.float32)
        processor.raw_data_buffer[1, :] = np.array([112.0, 119.0, 132.0, 139.0, 156.0], dtype=np.float32)
        processor.sweep_count = 2
        processor.buffer_write_index = 2
        processor.reset_555_heatmap_state()
        settings = {
            "channel_sensor_map": ["T", "B", "R", "L", "C"],
            "global_noise_threshold": 0.0,
            "channel_to_baseline": {1: 112.0, 2: 119.0, 3: 132.0, 4: 139.0, 5: 156.0},
            "sensor_calibration_dict": {
                "PZR2": {
                    "thresholds": [0.0, 0.0, 0.0, 0.0, 0.0],
                    "gains": [1.0, 1.0, 1.0, 1.0, 1.0],
                }
            },
            "sensor_calibration": [1.0, 1.0, 1.0, 1.0, 1.0],
            "cop_smooth_alpha": 1.0,
            "map_smooth_alpha": 1.0,
            "intensity_scale": 1.0,
            "intensity_min": 0.0,
            "intensity_max": 1.0,
            "blob_sigma_x": 1.0,
            "blob_sigma_y": 1.0,
            "axis_adapt_strength": 0.0,
        }

        result = processor.process_555_displacement_heatmap(settings)

        self.assertEqual(len(result), 1)
        _, _, _, intensity, _, display_values = result[0]
        self.assertEqual(display_values, [0.0, 0.0, 0.0, 0.0, 0.0])
        self.assertEqual(intensity, 0.0)


if __name__ == "__main__":
    unittest.main()
