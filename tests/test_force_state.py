import collections
import unittest

from data_processing.force_state import (
    ForceRuntimeState,
    build_default_force_runtime_state,
    get_force_runtime_state,
)


class LegacyForceHarness:
    def __init__(self):
        self.force_data = collections.deque(maxlen=4)
        self.force_start_time = None
        self.force_calibration_offset = {"x": 0.0, "z": 0.0}
        self.force_calibrating = False
        self.calibration_samples = {"x": [], "z": []}
        self._force_disconnect_in_progress = False
        self._force_raw_samples_seen = 0
        self._force_selected_port_text = None


class ForceStateTests(unittest.TestCase):
    def test_default_force_runtime_state_has_expected_defaults(self):
        state = build_default_force_runtime_state()

        self.assertIsInstance(state, ForceRuntimeState)
        self.assertIsInstance(state.data, collections.deque)
        self.assertIsNone(state.start_time)
        self.assertEqual(state.calibration_offset, {"x": 0.0, "z": 0.0})
        self.assertFalse(state.calibrating)
        self.assertEqual(state.calibration_samples, {"x": [], "z": []})
        self.assertIsInstance(state.recent_raw_samples, collections.deque)
        self.assertFalse(state.disconnect_in_progress)
        self.assertEqual(state.raw_samples_seen, 0)
        self.assertIsNone(state.selected_port_text)

    def test_legacy_force_runtime_adapter_reads_and_writes_legacy_fields(self):
        harness = LegacyForceHarness()
        state = get_force_runtime_state(harness)

        state.start_time = 1.25
        state.calibration_offset["x"] = 2.0
        state.calibrating = True
        state.calibration_samples["z"].append(3.5)
        state.recent_raw_samples.append((4.5, 5.5))
        state.disconnect_in_progress = True
        state.raw_samples_seen = 7
        state.selected_port_text = "COM20 - USB Serial Device"
        state.data.append((0.1, 1.0, 2.0))

        self.assertEqual(harness.force_start_time, 1.25)
        self.assertEqual(harness.force_calibration_offset["x"], 2.0)
        self.assertTrue(harness.force_calibrating)
        self.assertEqual(harness.calibration_samples["z"], [3.5])
        self.assertEqual(list(harness._force_recent_raw_samples), [(4.5, 5.5)])
        self.assertTrue(harness._force_disconnect_in_progress)
        self.assertEqual(harness._force_raw_samples_seen, 7)
        self.assertEqual(harness._force_selected_port_text, "COM20 - USB Serial Device")
        self.assertEqual(list(harness.force_data), [(0.1, 1.0, 2.0)])


if __name__ == "__main__":
    unittest.main()
