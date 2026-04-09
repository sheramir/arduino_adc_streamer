import unittest

import numpy as np

from data_processing.adc_plotting import ADCPlottingMixin


class ADCPlottingHarness(ADCPlottingMixin):
    MAX_SWEEPS_BUFFER = 5

    def __init__(self):
        self.sweep_timestamps_buffer = np.array([10.0, 11.0, 12.0, 13.0, 14.0], dtype=np.float64)


class ADCPlottingTests(unittest.TestCase):
    def test_extract_recent_buffer_window_without_wrap(self):
        harness = ADCPlottingHarness()
        data = np.array(
            [
                [100, 101],
                [110, 111],
                [120, 121],
                [130, 131],
                [140, 141],
            ],
            dtype=np.float32,
        )

        window_data, window_timestamps = harness._extract_recent_buffer_window(
            data,
            actual_sweeps=3,
            current_write_index=3,
            window_sweeps=2,
        )

        np.testing.assert_array_equal(window_data, np.array([[110, 111], [120, 121]], dtype=np.float32))
        np.testing.assert_array_equal(window_timestamps, np.array([11.0, 12.0], dtype=np.float64))

    def test_extract_recent_buffer_window_with_wrap(self):
        harness = ADCPlottingHarness()
        harness.sweep_timestamps_buffer = np.array([13.0, 14.0, 10.0, 11.0, 12.0], dtype=np.float64)
        data = np.array(
            [
                [300, 301],
                [400, 401],
                [100, 101],
                [200, 201],
                [0, 1],
            ],
            dtype=np.float32,
        )

        window_data, window_timestamps = harness._extract_recent_buffer_window(
            data,
            actual_sweeps=5,
            current_write_index=2,
            window_sweeps=3,
        )

        np.testing.assert_array_equal(
            window_data,
            np.array([[0, 1], [300, 301], [400, 401]], dtype=np.float32),
        )
        np.testing.assert_array_equal(window_timestamps, np.array([12.0, 13.0, 14.0], dtype=np.float64))


if __name__ == "__main__":
    unittest.main()
