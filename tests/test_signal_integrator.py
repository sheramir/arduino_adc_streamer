import unittest

import numpy as np

from config_constants import (
    DEFAULT_HPF_CUTOFF_HZ,
    DEFAULT_INTEGRATION_WINDOW_SAMPLES,
    SIGNAL_INTEGRATION_CHANNEL_COUNT,
    SIGNAL_INTEGRATION_DISABLED_HPF_CUTOFF_HZ,
)
from data_processing.signal_integrator import SignalIntegrator


class SignalIntegratorTests(unittest.TestCase):
    SAMPLE_RATE_HZ = 1000.0
    DC_BIAS_V = 1.65
    DC_SAMPLE_COUNT = 500
    FILTER_SETTLE_SAMPLES = 50
    SINE_FREQUENCY_HZ = 100.0
    SINE_SAMPLE_COUNT = 1000
    AC_MIN_RMS_RATIO = 0.85
    ZERO_TOLERANCE = 1e-6
    COMPARISON_TOLERANCE = 1e-9

    def _five_channel_batch(self, samples):
        return {
            channel_index: np.asarray(samples, dtype=np.float64)
            for channel_index in range(SIGNAL_INTEGRATION_CHANNEL_COUNT)
        }

    def test_dc_removal_rejects_constant_bias_after_filter_settles(self):
        integrator = SignalIntegrator(
            hpf_cutoff_hz=DEFAULT_HPF_CUTOFF_HZ,
            integration_window_samples=DEFAULT_INTEGRATION_WINDOW_SAMPLES,
            sample_rate_hz=self.SAMPLE_RATE_HZ,
        )
        samples = np.full(self.DC_SAMPLE_COUNT, self.DC_BIAS_V, dtype=np.float64)

        outputs = integrator.process(self._five_channel_batch(samples))

        for integrated in outputs.values():
            settled = integrated[self.FILTER_SETTLE_SAMPLES:]
            self.assertLess(float(np.max(np.abs(settled))), self.ZERO_TOLERANCE)

    def test_ac_signal_above_cutoff_is_preserved(self):
        times = np.arange(self.SINE_SAMPLE_COUNT, dtype=np.float64) / self.SAMPLE_RATE_HZ
        sine = np.sin(2.0 * np.pi * self.SINE_FREQUENCY_HZ * times)

        hpf_integrator = SignalIntegrator(
            hpf_cutoff_hz=DEFAULT_HPF_CUTOFF_HZ,
            integration_window_samples=1,
            sample_rate_hz=self.SAMPLE_RATE_HZ,
        )
        reference_integrator = SignalIntegrator(
            hpf_cutoff_hz=SIGNAL_INTEGRATION_DISABLED_HPF_CUTOFF_HZ,
            integration_window_samples=1,
            sample_rate_hz=self.SAMPLE_RATE_HZ,
        )

        hpf_output = hpf_integrator.process({0: sine + self.DC_BIAS_V})[0]
        reference_output = reference_integrator.process({0: sine})[0]

        hpf_settled = hpf_output[self.FILTER_SETTLE_SAMPLES:]
        reference_settled = reference_output[self.FILTER_SETTLE_SAMPLES:]
        rms_ratio = np.sqrt(np.mean(hpf_settled**2)) / np.sqrt(np.mean(reference_settled**2))

        self.assertGreater(float(rms_ratio), self.AC_MIN_RMS_RATIO)
        self.assertLess(abs(float(np.mean(hpf_settled))), DEFAULT_HPF_CUTOFF_HZ / self.SAMPLE_RATE_HZ)

    def test_integration_window_keeps_single_impulse_for_exact_window_length(self):
        samples = np.zeros(DEFAULT_INTEGRATION_WINDOW_SAMPLES * 2, dtype=np.float64)
        samples[0] = 1.0
        integrator = SignalIntegrator(
            hpf_cutoff_hz=SIGNAL_INTEGRATION_DISABLED_HPF_CUTOFF_HZ,
            integration_window_samples=DEFAULT_INTEGRATION_WINDOW_SAMPLES,
            sample_rate_hz=self.SAMPLE_RATE_HZ,
        )

        integrated = integrator.process({0: samples})[0]
        nonzero_indices = np.flatnonzero(np.abs(integrated) > self.ZERO_TOLERANCE)

        self.assertEqual(nonzero_indices.size, DEFAULT_INTEGRATION_WINDOW_SAMPLES)
        self.assertEqual(int(nonzero_indices[0]), 0)
        self.assertEqual(int(nonzero_indices[-1]), DEFAULT_INTEGRATION_WINDOW_SAMPLES - 1)
        self.assertTrue(np.allclose(integrated[DEFAULT_INTEGRATION_WINDOW_SAMPLES:], 0.0))

    def test_integration_value_stabilizes_to_amplitude_times_window(self):
        amplitude = 2.0
        samples = np.full(DEFAULT_INTEGRATION_WINDOW_SAMPLES * 2, amplitude, dtype=np.float64)
        integrator = SignalIntegrator(
            hpf_cutoff_hz=SIGNAL_INTEGRATION_DISABLED_HPF_CUTOFF_HZ,
            integration_window_samples=DEFAULT_INTEGRATION_WINDOW_SAMPLES,
            sample_rate_hz=self.SAMPLE_RATE_HZ,
        )

        integrated = integrator.process({0: samples})[0]

        self.assertAlmostEqual(
            float(integrated[-1]),
            amplitude * DEFAULT_INTEGRATION_WINDOW_SAMPLES,
            places=9,
        )

    def test_streaming_batches_match_single_call_output(self):
        samples = np.linspace(-1.0, 1.0, 200, dtype=np.float64)

        single_call = SignalIntegrator(
            hpf_cutoff_hz=SIGNAL_INTEGRATION_DISABLED_HPF_CUTOFF_HZ,
            integration_window_samples=DEFAULT_INTEGRATION_WINDOW_SAMPLES,
            sample_rate_hz=self.SAMPLE_RATE_HZ,
        )
        streaming = SignalIntegrator(
            hpf_cutoff_hz=SIGNAL_INTEGRATION_DISABLED_HPF_CUTOFF_HZ,
            integration_window_samples=DEFAULT_INTEGRATION_WINDOW_SAMPLES,
            sample_rate_hz=self.SAMPLE_RATE_HZ,
        )

        expected = single_call.process({0: samples})[0]
        first = streaming.process({0: samples[:100]})[0]
        second = streaming.process({0: samples[100:]})[0]

        np.testing.assert_allclose(
            np.concatenate([first, second]),
            expected,
            atol=self.COMPARISON_TOLERANCE,
        )

    def test_channel_map_routes_outputs_to_sensor_position_labels(self):
        channel_map = {0: "T", 1: "B", 2: "C", 3: "L", 4: "R"}
        integrator = SignalIntegrator(
            hpf_cutoff_hz=SIGNAL_INTEGRATION_DISABLED_HPF_CUTOFF_HZ,
            integration_window_samples=1,
            sample_rate_hz=self.SAMPLE_RATE_HZ,
            channel_map=channel_map,
        )

        outputs = integrator.process({
            channel_index: np.asarray([float(channel_index + 1)], dtype=np.float64)
            for channel_index in range(SIGNAL_INTEGRATION_CHANNEL_COUNT)
        })

        self.assertEqual(set(outputs), set(channel_map.values()))
        self.assertEqual(float(outputs["T"][0]), 1.0)
        self.assertEqual(float(outputs["R"][0]), 5.0)
        self.assertEqual(integrator.get_current_values()["C"], 3.0)

    def test_filter_state_persists_across_sequential_calls(self):
        times = np.arange(self.SINE_SAMPLE_COUNT, dtype=np.float64) / self.SAMPLE_RATE_HZ
        samples = self.DC_BIAS_V + np.sin(2.0 * np.pi * self.SINE_FREQUENCY_HZ * times)

        single_call = SignalIntegrator(
            hpf_cutoff_hz=DEFAULT_HPF_CUTOFF_HZ,
            integration_window_samples=DEFAULT_INTEGRATION_WINDOW_SAMPLES,
            sample_rate_hz=self.SAMPLE_RATE_HZ,
        )
        streaming = SignalIntegrator(
            hpf_cutoff_hz=DEFAULT_HPF_CUTOFF_HZ,
            integration_window_samples=DEFAULT_INTEGRATION_WINDOW_SAMPLES,
            sample_rate_hz=self.SAMPLE_RATE_HZ,
        )

        expected = single_call.process({0: samples})[0]
        first = streaming.process({0: samples[:400]})[0]
        second = streaming.process({0: samples[400:]})[0]

        np.testing.assert_allclose(
            np.concatenate([first, second]),
            expected,
            atol=self.COMPARISON_TOLERANCE,
        )

    def test_parameter_updates_rebuild_filter_and_resize_window(self):
        integrator = SignalIntegrator(
            hpf_cutoff_hz=DEFAULT_HPF_CUTOFF_HZ,
            integration_window_samples=DEFAULT_INTEGRATION_WINDOW_SAMPLES,
            sample_rate_hz=self.SAMPLE_RATE_HZ,
        )
        integrator.process({0: np.full(100, self.DC_BIAS_V, dtype=np.float64)})

        updated_window = DEFAULT_INTEGRATION_WINDOW_SAMPLES // 2
        integrator.update_parameters(
            hpf_cutoff_hz=DEFAULT_HPF_CUTOFF_HZ * 2.0,
            integration_window_samples=updated_window,
        )
        integrated = integrator.process({0: np.full(100, self.DC_BIAS_V, dtype=np.float64)})[0]

        self.assertEqual(integrator.integration_window_samples, updated_window)
        self.assertEqual(integrated.size, 100)

    def test_multi_channel_histories_are_independent(self):
        samples_0 = np.zeros(DEFAULT_INTEGRATION_WINDOW_SAMPLES * 2, dtype=np.float64)
        samples_0[0] = 1.0
        samples_1 = np.zeros_like(samples_0)
        integrator = SignalIntegrator(
            hpf_cutoff_hz=SIGNAL_INTEGRATION_DISABLED_HPF_CUTOFF_HZ,
            integration_window_samples=DEFAULT_INTEGRATION_WINDOW_SAMPLES,
            sample_rate_hz=self.SAMPLE_RATE_HZ,
        )

        outputs = integrator.process({0: samples_0, 1: samples_1})

        self.assertGreater(float(np.max(outputs[0])), 0.0)
        self.assertTrue(np.allclose(outputs[1], 0.0))


if __name__ == "__main__":
    unittest.main()
