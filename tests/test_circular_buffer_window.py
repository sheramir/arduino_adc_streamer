"""
Circular Sweep-Buffer Windowing
===============================
Characterization tests for the trailing-window index math shared by the
plotting, heatmap, spectrum, and filter paths. These pin the behaviour of
ADCPlottingMixin._extract_recent_buffer_window (the reference implementation)
across the pre-wrap, wrapped, and exactly-full regimes.
"""

import unittest

import numpy as np

from data_processing.adc_plotting import ADCPlottingMixin
from data_processing.circular_buffer import recent_window_slices, take_recent


CAPACITY = 8
SAMPLES_PER_SWEEP = 2


class _WindowHost(ADCPlottingMixin):
    """Minimal host exposing the circular buffers the extractor reads."""

    MAX_SWEEPS_BUFFER = CAPACITY

    def __init__(self, sweep_timestamps_buffer):
        self.sweep_timestamps_buffer = sweep_timestamps_buffer


def _write_sweeps(total_sweeps):
    """Fill a circular buffer as the capture path does, returning it plus state."""
    data = np.zeros((CAPACITY, SAMPLES_PER_SWEEP), dtype=np.float32)
    timestamps = np.zeros(CAPACITY, dtype=np.float64)
    for sweep_index in range(total_sweeps):
        pos = sweep_index % CAPACITY
        data[pos, :] = float(sweep_index)
        timestamps[pos] = float(sweep_index)
    write_index = total_sweeps
    return data, timestamps, write_index


def _expected_tail(total_sweeps, count):
    """The sweep numbers a correct trailing window must return."""
    available = min(total_sweeps, CAPACITY)
    count = min(count, available)
    first = total_sweeps - count
    return [float(n) for n in range(first, total_sweeps)]


REGIMES = [
    ("empty", 0, 4),
    ("partial_smaller_window", 5, 3),
    ("partial_window_equals_available", 5, 5),
    ("partial_window_exceeds_available", 5, 99),
    ("exactly_full", CAPACITY, 4),
    ("exactly_full_whole_buffer", CAPACITY, CAPACITY),
    ("wrapped_no_split", CAPACITY + 2, 2),
    ("wrapped_split", CAPACITY + 3, 6),
    ("wrapped_whole_buffer", CAPACITY + 3, CAPACITY),
    ("wrapped_window_exceeds_capacity", CAPACITY + 3, CAPACITY + 5),
    ("wrapped_aligned", CAPACITY * 2, CAPACITY),
]


class ReferenceExtractorTests(unittest.TestCase):
    """Pin what the existing extractor returns, before any consolidation."""

    def test_reference_extractor_returns_expected_tail(self):
        for name, total_sweeps, window in REGIMES:
            with self.subTest(regime=name):
                data, timestamps, write_index = _write_sweeps(total_sweeps)
                host = _WindowHost(timestamps)
                actual_sweeps = min(total_sweeps, CAPACITY)

                result = host._extract_recent_buffer_window(
                    data, actual_sweeps, write_index, window
                )

                expected = _expected_tail(total_sweeps, window)
                if not expected:
                    self.assertIsNone(result)
                    continue

                self.assertIsNotNone(result)
                got_data, got_timestamps = result
                self.assertEqual(got_data[:, 0].tolist(), expected)
                self.assertEqual(got_timestamps.tolist(), expected)

    def test_reference_extractor_result_is_independent_of_the_buffer(self):
        data, timestamps, write_index = _write_sweeps(CAPACITY + 3)
        host = _WindowHost(timestamps)

        got_data, got_timestamps = host._extract_recent_buffer_window(
            data, CAPACITY, write_index, 4
        )
        before = got_data.copy(), got_timestamps.copy()
        data[:, :] = -1.0
        timestamps[:] = -1.0

        np.testing.assert_array_equal(got_data, before[0])
        np.testing.assert_array_equal(got_timestamps, before[1])


class RecentWindowSlicesTests(unittest.TestCase):
    """The shared helper must agree with the reference extractor everywhere."""

    def test_slices_match_reference_extractor(self):
        for name, total_sweeps, window in REGIMES:
            with self.subTest(regime=name):
                data, timestamps, write_index = _write_sweeps(total_sweeps)
                slices = recent_window_slices(total_sweeps, write_index, window, CAPACITY)

                expected = _expected_tail(total_sweeps, window)
                got = take_recent(data, slices)
                self.assertEqual(got[:, 0].tolist() if got.size else [], expected)
                self.assertEqual(take_recent(timestamps, slices).tolist(), expected)

    def test_no_slices_when_nothing_to_take(self):
        self.assertEqual(recent_window_slices(0, 0, 5, CAPACITY), [])
        self.assertEqual(recent_window_slices(10, 10, 0, CAPACITY), [])
        self.assertEqual(recent_window_slices(10, 10, -1, CAPACITY), [])

    def test_slices_never_exceed_capacity(self):
        for total_sweeps in range(0, CAPACITY * 3):
            for window in range(0, CAPACITY * 2):
                slices = recent_window_slices(total_sweeps, total_sweeps, window, CAPACITY)
                taken = sum(stop - start for start, stop in slices)
                self.assertLessEqual(taken, CAPACITY)
                self.assertEqual(taken, min(window, total_sweeps, CAPACITY))
                for start, stop in slices:
                    self.assertGreaterEqual(start, 0)
                    self.assertLessEqual(stop, CAPACITY)
                    self.assertLess(start, stop)

    def test_take_recent_copies_out_of_the_buffer(self):
        data, _timestamps, write_index = _write_sweeps(CAPACITY + 3)
        slices = recent_window_slices(CAPACITY + 3, write_index, 4, CAPACITY)

        taken = take_recent(data, slices)
        snapshot = taken.copy()
        data[:, :] = -1.0

        np.testing.assert_array_equal(taken, snapshot)


if __name__ == "__main__":
    unittest.main()
