import unittest

import numpy as np

from data_processing.pzt_ghost_removal import PztGhostRemovalMixin


class PztGhostHarness(PztGhostRemovalMixin):
    def __init__(self, *, pzt_rs=False, channels=None, repeat=1):
        self.config = {
            'channels': list(channels or [0, 1, 2]),
            'repeat': repeat,
        }
        self._pzt_rs = pzt_rs
        self._init_pzt_ghost_removal_state()
        self.set_pzt_ghost_removal_settings(True, 0.5)

    def is_array_pzt1_mode(self):
        return not self._pzt_rs

    def is_array_pzt_rs_mode(self):
        return self._pzt_rs

    def get_channels_for_arduino_command(self):
        return self.config['channels']

    def get_array_selected_sensor_groups(self):
        if not self._pzt_rs:
            return []
        return [{'sensor_id': 'PZT1'}]


class PztGhostRemovalTests(unittest.TestCase):
    def test_attenuation_is_limited_to_a_fraction(self):
        harness = PztGhostHarness()

        harness.set_pzt_ghost_removal_settings(True, 2.0)

        self.assertEqual(harness.pzt_ghost_attenuation, 1.0)

    def test_paired_mux_paths_are_cleaned_independently(self):
        harness = PztGhostHarness(channels=[0, 1, 2])
        harness._pzt_ghost_baselines = np.full(6, 100.0, dtype=np.float32)

        cleaned = harness.prepare_pzt_ghost_block(np.array([[110, 105, 120, 107, 130, 109]], dtype=np.float32))

        # MUX 1: [10, 20, 30] -> [10, 15, 20]
        # MUX 2: [5, 7, 9] -> [5, 4.5, 5.5]
        np.testing.assert_allclose(cleaned, [[10, 5, 15, 4.5, 20, 5.5]])

    def test_first_signal_of_each_mux_sequence_has_no_ghost_subtraction(self):
        harness = PztGhostHarness(channels=[0, 1])
        harness._pzt_ghost_baselines = np.full(4, 50.0, dtype=np.float32)

        cleaned = harness.prepare_pzt_ghost_block(np.array([[53, 58, 55, 60]], dtype=np.float32))

        np.testing.assert_allclose(cleaned, [[3, 8, 3.5, 6]])

    def test_pzt_rs_corrects_only_five_pzt_slots_and_preserves_rs_slots(self):
        harness = PztGhostHarness(pzt_rs=True, channels=[0, 1, 2, 3, 4])
        harness._pzt_ghost_baselines = np.array([100, 100, 100, 100, 100, 0, 0], dtype=np.float32)

        cleaned = harness.prepare_pzt_ghost_block(
            np.array([[110, 120, 130, 140, 150, 12345, 23456]], dtype=np.float32)
        )

        np.testing.assert_allclose(cleaned, [[10, 15, 20, 25, 30, 12345, 23456]])

    def test_zero_signals_reconstruction_recovers_raw_equivalent_values(self):
        harness = PztGhostHarness(channels=[0, 1, 2])
        harness._pzt_ghost_baselines = np.full(6, 100.0, dtype=np.float32)
        raw = np.array([[110, 105, 120, 107, 130, 109]], dtype=np.float32)
        cleaned = harness.prepare_pzt_ghost_block(raw)

        recovered = harness.reconstruct_pzt_signal_for_baseline_capture(cleaned)

        np.testing.assert_allclose(recovered, raw)

    def test_plot_baselines_populate_each_physical_pzt_column(self):
        harness = PztGhostHarness(channels=[0, 1])
        harness.samples_per_sweep = 4
        harness.plot_baselines = {
            ('mux', 1, 0): 10.0,
            ('mux', 1, 1): 20.0,
            ('mux', 2, 0): 30.0,
            ('mux', 2, 1): 40.0,
        }
        harness.get_display_channel_specs = lambda: [
            {'key': ('mux', 1, 0), 'sample_indices': [0]},
            {'key': ('mux', 1, 1), 'sample_indices': [2]},
            {'key': ('mux', 2, 0), 'sample_indices': [1]},
            {'key': ('mux', 2, 1), 'sample_indices': [3]},
        ]
        harness._pzt_ghost_calibration_pending = False

        harness.on_plot_baselines_captured()

        np.testing.assert_allclose(harness._pzt_ghost_baselines, [10, 30, 20, 40])

    def test_calibration_captures_hidden_paired_mux_columns_from_same_window(self):
        harness = PztGhostHarness(channels=[0, 1])
        harness.samples_per_sweep = 4
        harness.get_display_channel_specs = lambda: [
            {'key': ('mux', 1, 0), 'sample_indices': [0]},
            {'key': ('mux', 1, 1), 'sample_indices': [2]},
        ]
        harness.plot_baselines = {('mux', 1, 0): 10.0, ('mux', 1, 1): 20.0}

        harness.on_plot_baselines_captured(np.array([
            [10, 30, 20, 40],
            [12, 32, 22, 42],
            [14, 34, 24, 44],
        ], dtype=np.float32))

        # Columns 1 and 3 are not displayed but are the second physical MUX
        # sequence and must still receive their calibration medians.
        np.testing.assert_allclose(harness._pzt_ghost_baselines, [12, 32, 22, 42])


if __name__ == '__main__':
    unittest.main()
