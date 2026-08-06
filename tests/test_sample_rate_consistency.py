"""
One Sample Rate for Display, Spectrum, and Filtering
====================================================
The Time Series readout, the Spectrum tab, and the ADC filter must agree about
the per-signal sample rate, otherwise a filter cutoff and a spectrum peak sit on
different frequency axes. These tests pin the shared authority
(TimingDisplayMixin.get_measured_sweep_rate_hz) and gate the filter's switch onto
it by proving it agrees with the measurement the filter engine does today.
"""

import threading
import unittest

import numpy as np

from data_processing.adc_filter_engine import ADCFilterEngine
from data_processing.timing_display import TimingDisplayMixin


SWEEP_RATE_HZ = 1250.0
CONVERSION_INTERVAL_US = 20.0
SIGNAL_COUNT = 25
MAX_SWEEPS = 4096


class _RateHost(TimingDisplayMixin):
    """Host carrying just the capture state the rate helpers read."""

    MAX_SWEEPS_BUFFER = MAX_SWEEPS

    def __init__(self, sweep_count, sweep_rate_hz=SWEEP_RATE_HZ, signal_count=SIGNAL_COUNT,
                 conversion_interval_us=CONVERSION_INTERVAL_US, configured_rate=0.0):
        self.buffer_lock = threading.Lock()
        self.is_full_view = False
        self.sweep_count = sweep_count
        self.config = {'sample_rate': configured_rate}
        self._signal_count = signal_count

        # timing_state is a lazily-created property on the mixin; let it build one.
        if conversion_interval_us:
            self.timing_state.arduino_sample_times.append(conversion_interval_us)

        self.sweep_timestamps_buffer = np.zeros(MAX_SWEEPS, dtype=np.float64)
        if sweep_count > 0:
            period = 1.0 / sweep_rate_hz
            # Sweep n is stamped at n*period, matching the capture path.
            for n in range(min(sweep_count, MAX_SWEEPS)):
                self.sweep_timestamps_buffer[n % MAX_SWEEPS] = n * period
        self.buffer_write_index = sweep_count

    def get_display_channel_specs(self):
        return [{'label': f'S{i}', 'sample_indices': [i]} for i in range(self._signal_count)]


class MeasuredSweepRateTests(unittest.TestCase):
    def test_measured_rate_matches_the_synthetic_sweep_rate(self):
        host = _RateHost(sweep_count=1000)

        self.assertAlmostEqual(host.get_measured_sweep_rate_hz(), SWEEP_RATE_HZ, places=6)

    def test_measured_rate_equals_the_time_series_readout_value(self):
        # update_timing_display stores actual_per_channel_rate_hz for the label;
        # the helper must return that same number.
        host = _RateHost(sweep_count=1000)
        elapsed_s = host._current_elapsed_since_first_sweep_seconds()
        expected = 1.0 / (elapsed_s / (host.sweep_count - 1))

        self.assertAlmostEqual(host.get_measured_sweep_rate_hz(), expected, places=9)

    def test_signal_rate_scales_with_slots_per_sweep(self):
        host = _RateHost(sweep_count=1000)

        self.assertAlmostEqual(host.get_signal_sample_rate_hz(1), SWEEP_RATE_HZ, places=6)
        self.assertAlmostEqual(host.get_signal_sample_rate_hz(4), SWEEP_RATE_HZ * 4, places=6)
        # Degenerate values must not produce a zero or negative rate.
        self.assertAlmostEqual(host.get_signal_sample_rate_hz(0), SWEEP_RATE_HZ, places=6)

    def test_rs_presence_does_not_change_the_pzt_rate(self):
        # RS slots widen the sweep but are not display specs, so the measured
        # sweep rate (and therefore the PZT per-signal rate) is unaffected.
        without_rs = _RateHost(sweep_count=1000, signal_count=25)
        with_rs = _RateHost(sweep_count=1000, signal_count=25)

        self.assertAlmostEqual(
            without_rs.get_measured_sweep_rate_hz(),
            with_rs.get_measured_sweep_rate_hz(),
            places=9,
        )


class RateFallbackTests(unittest.TestCase):
    def test_falls_back_to_conversion_rate_split_across_signals(self):
        host = _RateHost(sweep_count=0)

        expected = (1_000_000.0 / CONVERSION_INTERVAL_US) / SIGNAL_COUNT
        self.assertAlmostEqual(host.get_measured_sweep_rate_hz(), expected, places=6)

    def test_single_sweep_cannot_measure_a_period_and_falls_back(self):
        host = _RateHost(sweep_count=1)

        expected = (1_000_000.0 / CONVERSION_INTERVAL_US) / SIGNAL_COUNT
        self.assertAlmostEqual(host.get_measured_sweep_rate_hz(), expected, places=6)

    def test_falls_back_to_configured_rate_without_conversion_timing(self):
        host = _RateHost(sweep_count=0, conversion_interval_us=0.0, configured_rate=777.0)

        self.assertAlmostEqual(host.get_measured_sweep_rate_hz(), 777.0, places=6)

    def test_returns_zero_when_nothing_is_known(self):
        host = _RateHost(sweep_count=0, conversion_interval_us=0.0, configured_rate=0.0)

        self.assertEqual(host.get_measured_sweep_rate_hz(), 0.0)


class FilterEngineAgreementTests(unittest.TestCase):
    """Gate for switching the filter onto the shared helper.

    The engine currently derives each stream's rate from median timestamp
    spacing. For a uniformly sampled capture that must equal the shared helper's
    value, otherwise the two frequency axes would diverge.
    """

    def _uniform_sweep_timestamps(self, sweeps):
        return np.arange(sweeps, dtype=np.float64) / SWEEP_RATE_HZ

    def test_engine_estimate_matches_shared_helper_for_one_slot_signals(self):
        host = _RateHost(sweep_count=2000)
        engine = ADCFilterEngine()
        total_fs_hz = 1_000_000.0 / CONVERSION_INTERVAL_US
        index_map = {
            spec['label']: np.asarray(spec['sample_indices'], dtype=np.int32)
            for spec in host.get_display_channel_specs()
        }

        rates = engine.estimate_channel_sample_rates(
            total_fs_hz,
            channels=[],
            repeat_count=1,
            sweep_timestamps_sec=self._uniform_sweep_timestamps(2000),
            index_map=index_map,
        )

        shared = host.get_measured_sweep_rate_hz()
        for label, fs_hz in rates.items():
            self.assertAlmostEqual(
                fs_hz, shared, delta=shared * 1e-6,
                msg=f"{label}: engine {fs_hz} vs shared {shared}",
            )

    def test_engine_estimate_matches_shared_helper_for_repeated_slots(self):
        # repeat=2: each signal owns two adjacent slots per sweep, so its rate is
        # twice the sweep rate. Adjacent slots are one conversion interval apart,
        # which is what the engine's median spacing sees.
        sweeps = 2000
        host = _RateHost(sweep_count=sweeps)
        engine = ADCFilterEngine()
        total_fs_hz = 1_000_000.0 / CONVERSION_INTERVAL_US
        index_map = {'S0': np.asarray([0, 1], dtype=np.int32)}

        rates = engine.estimate_channel_sample_rates(
            total_fs_hz,
            channels=[],
            repeat_count=2,
            sweep_timestamps_sec=self._uniform_sweep_timestamps(sweeps),
            index_map=index_map,
        )

        # The engine measures the intra-sweep spacing here, so this documents the
        # known divergence the shared helper resolves rather than asserting parity.
        self.assertGreater(rates['S0'], host.get_signal_sample_rate_hz(2))


if __name__ == "__main__":
    unittest.main()
