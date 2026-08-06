"""
RS Columns Must Bypass the ADC Filter
=====================================
RS values are produced by 555 timing, not ADC sampling, so they are resistance
readings rather than sampled waveforms. Running them through the ADC filter
chain distorts them (a high-pass, for example, strips the DC level that *is*
the measurement). These tests pin RS out of the filter path.
"""

import unittest

import numpy as np

from data_processing.adc_filter_engine import (
    ADCFilterEngine,
    SCIPY_FILTERS_AVAILABLE,
    build_default_filter_settings,
)
from data_processing.filter_processor import FilterProcessorMixin


# Two PZT sensors in PZT_RS layout: 7 outputs each (5 PZT + 2 RS), repeat 1.
PZT_COLUMNS = {
    "PZT1_T": [0], "PZT1_B": [1], "PZT1_R": [2], "PZT1_L": [3], "PZT1_C": [4],
    "PZT3_T": [7], "PZT3_B": [8], "PZT3_R": [9], "PZT3_L": [10], "PZT3_C": [11],
}
RS_COLUMNS = {
    "PZT1_RS1": [5], "PZT1_RS2": [6],
    "PZT3_RS1": [12], "PZT3_RS2": [13],
}
SWEEP_WIDTH = 14


def _specs(columns, stream):
    return [
        {"key": (stream, label), "label": label, "sample_indices": list(indices)}
        for label, indices in columns.items()
    ]


class _StreamMapHarness(FilterProcessorMixin):
    """Minimal host exposing only what _build_filter_stream_map reads."""

    def __init__(self, *, pzt_rs_mode=True):
        self._pzt_rs_mode = pzt_rs_mode

    def is_array_pzt1_mode(self):
        return False

    def is_array_pzt_rs_mode(self):
        return self._pzt_rs_mode

    def is_array_sensor_selection_mode(self):
        return True

    def get_display_channel_specs(self):
        return _specs(PZT_COLUMNS, "sensor")

    def get_rosette_display_channel_specs(self):
        return _specs(RS_COLUMNS, "rs") if self._pzt_rs_mode else []


def _highpass_settings():
    settings = build_default_filter_settings()
    settings["enabled"] = True
    settings["main_type"] = "highpass"
    settings["high_cutoff_hz"] = 20.0
    settings["order"] = 2
    for notch in settings["notches"]:
        notch["enabled"] = False
    return settings


def _make_block(sweeps=64):
    """Block where every column carries a distinct constant-plus-ramp signal."""
    block = np.zeros((sweeps, SWEEP_WIDTH), dtype=np.float32)
    for column in range(SWEEP_WIDTH):
        block[:, column] = 1000.0 + column * 100.0 + np.arange(sweeps, dtype=np.float32)
    return block


class FilterStreamMapTests(unittest.TestCase):
    def test_stream_map_contains_only_pzt_signals(self):
        harness = _StreamMapHarness()

        stream_map = harness._build_filter_stream_map()

        self.assertIsNotNone(stream_map)
        self.assertEqual(set(stream_map), set(PZT_COLUMNS))

    def test_stream_map_excludes_every_rs_signal(self):
        harness = _StreamMapHarness()

        stream_map = harness._build_filter_stream_map()

        for rs_label in RS_COLUMNS:
            self.assertNotIn(rs_label, stream_map)

    def test_no_rs_column_index_is_claimed_by_any_stream(self):
        harness = _StreamMapHarness()
        rs_indices = {index for indices in RS_COLUMNS.values() for index in indices}

        stream_map = harness._build_filter_stream_map()

        claimed = {int(i) for indices in stream_map.values() for i in np.asarray(indices).reshape(-1)}
        self.assertEqual(claimed & rs_indices, set())


@unittest.skipUnless(SCIPY_FILTERS_AVAILABLE, "SciPy required for filtering")
class FilterBlockLeavesRsUntouchedTests(unittest.TestCase):
    def test_rs_columns_are_bit_identical_after_filtering(self):
        harness = _StreamMapHarness()
        engine = ADCFilterEngine()
        stream_map = harness._build_filter_stream_map()
        runtime = engine.build_runtime_plan(
            _highpass_settings(),
            1000.0,
            channels=[],
            repeat_count=1,
            channel_fs_by_channel={label: 1000.0 for label in stream_map},
            index_map=stream_map,
        )

        block = _make_block()
        original = block.copy()
        filtered = engine.filter_block(runtime, block.copy())

        for label, indices in RS_COLUMNS.items():
            for index in indices:
                np.testing.assert_array_equal(
                    filtered[:, index], original[:, index],
                    err_msg=f"{label} (column {index}) was modified by the ADC filter",
                )

    def test_pzt_columns_are_actually_filtered(self):
        # Guards the test above: if nothing were filtered it would pass vacuously.
        harness = _StreamMapHarness()
        engine = ADCFilterEngine()
        stream_map = harness._build_filter_stream_map()
        runtime = engine.build_runtime_plan(
            _highpass_settings(),
            1000.0,
            channels=[],
            repeat_count=1,
            channel_fs_by_channel={label: 1000.0 for label in stream_map},
            index_map=stream_map,
        )

        block = _make_block()
        original = block.copy()
        filtered = engine.filter_block(runtime, block.copy())

        for label, indices in PZT_COLUMNS.items():
            for index in indices:
                self.assertFalse(
                    np.array_equal(filtered[:, index], original[:, index]),
                    f"{label} (column {index}) should have been filtered",
                )


if __name__ == "__main__":
    unittest.main()
