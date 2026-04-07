import threading
import unittest

import numpy as np

from config_constants import HEATMAP_HEIGHT, HEATMAP_WIDTH
from data_processing.heatmap_555_processor import Heatmap555ProcessorMixin
from data_processing.heatmap_piezo_processor import PiezoHeatmapProcessorMixin


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


class HeatmapThresholdTests(unittest.TestCase):
    def test_555_thresholds_use_package_sensor_id_and_per_channel_totals(self):
        processor = Dummy555Processor()
        settings = {
            "channel_sensor_map": ["T", "B", "R", "L", "C"],
            "global_channel_thresholds": [10.0, 20.0, 30.0, 40.0, 50.0],
            "global_channel_release_thresholds": [10.0, 20.0, 30.0, 40.0, 50.0],
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
        self.assertEqual(display_values, [6.0, 0.0, 0.0, 0.0, 28.0])
        self.assertEqual(intensity, 34.0)

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
            "global_channel_thresholds": [10.0, 20.0, 30.0, 40.0, 50.0],
            "sensor_calibration_dict": {
                "PZT1": {
                    "thresholds": [1.0, 2.0, 3.0, 4.0, 5.0],
                    "gains": [1.0, 1.0, 1.0, 1.0, 1.0],
                }
            },
            "smooth_alpha": 1.0,
        }

        values = processor.compute_channel_intensities(settings)

        self.assertEqual(values, [[11.0, 0.0, 0.0, 0.0, 56.0]])

    def test_555_cop_respects_configured_channel_placement(self):
        processor = Dummy555Processor()
        processor.raw_data_buffer[0, :] = np.array([100.0, 100.0, 100.0, 100.0, 100.0], dtype=np.float32)
        processor.raw_data_buffer[1, :] = np.array([140.0, 100.0, 100.0, 100.0, 145.0], dtype=np.float32)
        processor.sweep_count = 2
        processor.buffer_write_index = 2
        processor.reset_555_heatmap_state()

        settings = {
            "channel_sensor_map": ["L", "B", "C", "R", "T"],
            "global_channel_thresholds": [0.0, 0.0, 0.0, 0.0, 0.0],
            "global_channel_release_thresholds": [0.0, 0.0, 0.0, 0.0, 0.0],
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
            "global_channel_thresholds": [0.0, 0.0, 0.0, 0.0, 0.0],
            "global_channel_release_thresholds": [0.0, 0.0, 0.0, 0.0, 0.0],
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
