"""
Spectrum Channel Sourcing
=========================
The spectrum must show the five channels of exactly one sensor package. It used
to group by raw ADC pin number, which merged packages that share pins across
different MUXes (PZT1 and PZT5 both sit on pins 0-4 in Array_PCB1.7) and dropped
every package whose pins fell outside the first five unique values.
"""

import threading
import unittest

import numpy as np

from data_processing.spectrum_processor import SpectrumProcessorMixin
from data_processing.timing_display import TimingDisplayMixin


SWEEP_RATE_HZ = 1250.0
CONVERSION_INTERVAL_US = 20.0
MAX_SWEEPS = 4096

# Array_PCB1.7 layout: five packages, and ADC pins deliberately repeat across
# MUXes so a pin-number grouping would merge PZT1 with PZT5 and PZT3 with PZT7.
PACKAGE_PINS = {
    "PZT1": [0, 1, 2, 3, 4],
    "PZT3": [5, 6, 7, 8, 9],
    "PZT5": [0, 1, 2, 3, 4],
    "PZT6": [10, 11, 12, 13, 14],
    "PZT7": [5, 6, 7, 8, 9],
}
PLACEMENTS = ["T", "B", "R", "L", "C"]
SWEEP_WIDTH = 25


def _array_display_specs():
    """One spec per sensor channel, as get_display_channel_specs() returns."""
    specs = []
    column = 0
    for sensor_id, pins in PACKAGE_PINS.items():
        for local_index, pin in enumerate(pins):
            specs.append({
                "key": ("sensor", sensor_id, PLACEMENTS[local_index], pin),
                "label": f"{sensor_id}_{PLACEMENTS[local_index]}",
                "sample_indices": [column],
                "color_slot": column,
            })
            column += 1
    return specs


def _manual_display_specs(count=8):
    return [
        {"key": ("adc", ch), "label": f"Ch {ch}", "sample_indices": [ch], "color_slot": ch}
        for ch in range(count)
    ]


class _SpectrumHost(SpectrumProcessorMixin, TimingDisplayMixin):
    """Host exposing the capture state and config the payload builder reads."""

    MAX_SWEEPS_BUFFER = MAX_SWEEPS

    def __init__(self, specs, *, array_mode=True, sweeps=512, selected_package=None):
        self.buffer_lock = threading.Lock()
        self.is_full_view = False
        self._specs = specs
        self._array_mode = array_mode
        self.spectrum_selected_package = selected_package
        self.samples_per_sweep = SWEEP_WIDTH
        self.sweep_count = sweeps
        self.buffer_write_index = sweeps
        self.config = {"channels": list(range(SWEEP_WIDTH)), "repeat": 1, "sample_rate": 0}

        # Each column carries a distinct constant so a mixed-up channel is obvious.
        self.raw_data_buffer = np.zeros((MAX_SWEEPS, SWEEP_WIDTH), dtype=np.float32)
        for column in range(SWEEP_WIDTH):
            self.raw_data_buffer[:, column] = float(column)
        self.processed_data_buffer = None
        self.sweep_timestamps_buffer = np.arange(MAX_SWEEPS, dtype=np.float64) / SWEEP_RATE_HZ
        self.timing_state.arduino_sample_times.append(CONVERSION_INTERVAL_US)

    def get_display_channel_specs(self, channels=None, repeat_count=None):
        return list(self._specs)

    def is_array_sensor_selection_mode(self):
        return self._array_mode

    def get_active_data_buffer(self):
        return self.raw_data_buffer


def _settings():
    return {
        "mode": "fft", "nfft_mode": "auto", "nfft_value": 4096, "window": "hann",
        "remove_dc": True, "welch_segment": 256, "welch_overlap": 50.0,
        "window_ms": 200, "band_f1": 50.0, "band_f2": 500.0,
    }


class PackageGroupingTests(unittest.TestCase):
    def test_payload_exposes_one_package_of_five_channels(self):
        host = _SpectrumHost(_array_display_specs())

        payload, error = host._build_spectrum_payload(_settings())

        self.assertIsNone(error)
        self.assertEqual(len(payload["channels"]), 5)

    def test_defaults_to_the_first_package(self):
        host = _SpectrumHost(_array_display_specs())

        payload, _ = host._build_spectrum_payload(_settings())

        self.assertEqual(
            [entry["label"] for entry in payload["channels"]],
            [f"PZT1_{p}" for p in PLACEMENTS],
        )

    def test_selecting_a_later_package_returns_only_that_package(self):
        host = _SpectrumHost(_array_display_specs(), selected_package="PZT6")

        payload, _ = host._build_spectrum_payload(_settings())

        self.assertEqual(
            [entry["label"] for entry in payload["channels"]],
            [f"PZT6_{p}" for p in PLACEMENTS],
        )

    def test_stale_package_selection_falls_back_to_the_first(self):
        host = _SpectrumHost(_array_display_specs(), selected_package="PZT_REMOVED")

        payload, _ = host._build_spectrum_payload(_settings())

        self.assertEqual(payload["channels"][0]["label"], "PZT1_T")

    def test_available_packages_are_listed_in_selection_order(self):
        host = _SpectrumHost(_array_display_specs())

        self.assertEqual(host.get_spectrum_available_packages(), list(PACKAGE_PINS))


class PinSharingRegressionTests(unittest.TestCase):
    """PZT1 and PZT5 share ADC pins 0-4; they must never be merged."""

    def test_selected_package_columns_belong_to_that_package_only(self):
        host = _SpectrumHost(_array_display_specs(), selected_package="PZT5")
        pzt5_columns = {
            spec["sample_indices"][0]
            for spec in _array_display_specs()
            if spec["key"][1] == "PZT5"
        }

        payload, _ = host._build_spectrum_payload(_settings())

        # Each column was filled with its own index, so the sample values
        # identify exactly which sweep columns were read.
        for entry in payload["channels"]:
            observed = set(np.unique(entry["samples"]).astype(int).tolist())
            self.assertTrue(
                observed <= pzt5_columns,
                f"{entry['label']} read columns {observed}, outside PZT5 {pzt5_columns}",
            )

    def test_no_channel_mixes_two_packages(self):
        host = _SpectrumHost(_array_display_specs(), selected_package="PZT1")

        payload, _ = host._build_spectrum_payload(_settings())

        for entry in payload["channels"]:
            self.assertEqual(
                len(np.unique(entry["samples"])), 1,
                f"{entry['label']} contains samples from more than one sweep column",
            )

    def test_every_package_is_reachable(self):
        # The old first-five-unique-pins rule made PZT3, PZT6 and PZT7 unreachable.
        for sensor_id in PACKAGE_PINS:
            with self.subTest(package=sensor_id):
                host = _SpectrumHost(_array_display_specs(), selected_package=sensor_id)
                payload, _ = host._build_spectrum_payload(_settings())
                self.assertEqual(payload["channels"][0]["label"], f"{sensor_id}_T")


class SampleRateTests(unittest.TestCase):
    def test_channel_rate_is_the_measured_sweep_rate(self):
        host = _SpectrumHost(_array_display_specs())

        payload, _ = host._build_spectrum_payload(_settings())

        for entry in payload["channels"]:
            self.assertAlmostEqual(entry["fs_hz"], SWEEP_RATE_HZ, delta=SWEEP_RATE_HZ * 1e-6)

    def test_channel_rate_matches_the_shared_helper(self):
        host = _SpectrumHost(_array_display_specs())
        expected = host.get_measured_sweep_rate_hz()

        payload, _ = host._build_spectrum_payload(_settings())

        for entry in payload["channels"]:
            self.assertAlmostEqual(entry["fs_hz"], expected, delta=expected * 1e-9)


class ManualModeTests(unittest.TestCase):
    def test_manual_mode_keeps_first_five_channels(self):
        host = _SpectrumHost(_manual_display_specs(), array_mode=False)

        payload, _ = host._build_spectrum_payload(_settings())

        self.assertEqual(len(payload["channels"]), 5)

    def test_manual_mode_uses_underscore_channel_labels(self):
        host = _SpectrumHost(_manual_display_specs(), array_mode=False)

        payload, _ = host._build_spectrum_payload(_settings())

        self.assertEqual(
            [entry["label"] for entry in payload["channels"]],
            [f"Ch_{n}" for n in range(5)],
        )

    def test_manual_mode_reports_no_packages(self):
        host = _SpectrumHost(_manual_display_specs(), array_mode=False)

        self.assertEqual(host.get_spectrum_available_packages(), [])


class RsExclusionTests(unittest.TestCase):
    def test_rs_specs_are_never_consulted(self):
        host = _SpectrumHost(_array_display_specs())
        host.get_rosette_display_channel_specs = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("spectrum must not read RS specs: RS is 555-derived, not ADC")
        )

        payload, error = host._build_spectrum_payload(_settings())

        self.assertIsNone(error)
        self.assertTrue(all("RS" not in entry["label"] for entry in payload["channels"]))


if __name__ == "__main__":
    unittest.main()
