"""Tests for the Pressure Map touch-classifier demo engine."""

import unittest

from data_processing.touch_classifier_demo import TouchClassifierDemoEngine


class TouchClassifierDemoEngineTests(unittest.TestCase):
    def test_trigger_delay_and_first_material(self):
        engine = TouchClassifierDemoEngine(material_count=5, material_sequence=(1, 2, 3, 4, 5))

        initial = engine.update(
            signal_magnitude=0.8,
            noise_threshold=0.1,
            trigger_threshold=0.5,
            enabled=True,
            now_monotonic=0.0,
        )
        self.assertIsNone(initial.active_material_index)
        self.assertEqual(sum(initial.scores), 0.0)

        delayed = engine.update(
            signal_magnitude=0.8,
            noise_threshold=0.1,
            trigger_threshold=0.5,
            enabled=True,
            now_monotonic=0.6,
        )
        self.assertEqual(delayed.active_material_index, 0)
        self.assertGreaterEqual(delayed.scores[0], 70.0)
        self.assertLessEqual(delayed.scores[0], 95.0)

    def test_under_two_seconds_repeats_same_material(self):
        engine = TouchClassifierDemoEngine(material_count=5, material_sequence=(1, 2, 3, 4, 5))

        engine.update(signal_magnitude=0.8, noise_threshold=0.1, trigger_threshold=0.5, enabled=True, now_monotonic=0.0)
        first_active = engine.update(signal_magnitude=0.8, noise_threshold=0.1, trigger_threshold=0.5, enabled=True, now_monotonic=0.6)
        self.assertEqual(first_active.active_material_index, 0)

        engine.update(signal_magnitude=0.0, noise_threshold=0.1, trigger_threshold=0.5, enabled=True, now_monotonic=1.0)
        engine.update(signal_magnitude=0.8, noise_threshold=0.1, trigger_threshold=0.5, enabled=True, now_monotonic=2.0)
        repeated = engine.update(signal_magnitude=0.8, noise_threshold=0.1, trigger_threshold=0.5, enabled=True, now_monotonic=2.6)
        self.assertEqual(repeated.active_material_index, 0)

    def test_over_two_seconds_advances_sequence(self):
        engine = TouchClassifierDemoEngine(material_count=5, material_sequence=(1, 2, 3, 4, 5))

        engine.update(signal_magnitude=0.8, noise_threshold=0.1, trigger_threshold=0.5, enabled=True, now_monotonic=0.0)
        engine.update(signal_magnitude=0.8, noise_threshold=0.1, trigger_threshold=0.5, enabled=True, now_monotonic=0.6)

        engine.update(signal_magnitude=0.0, noise_threshold=0.1, trigger_threshold=0.5, enabled=True, now_monotonic=1.0)
        engine.update(signal_magnitude=0.8, noise_threshold=0.1, trigger_threshold=0.5, enabled=True, now_monotonic=3.4)
        advanced = engine.update(signal_magnitude=0.8, noise_threshold=0.1, trigger_threshold=0.5, enabled=True, now_monotonic=4.0)
        self.assertEqual(advanced.active_material_index, 1)

    def test_uses_custom_sequence_with_repeats(self):
        engine = TouchClassifierDemoEngine(material_count=5, material_sequence=(1, 2, 3, 4, 5, 3, 2, 4))

        sequence_seen = []
        current_time = 0.0
        for _ in range(8):
            engine.update(signal_magnitude=0.9, noise_threshold=0.1, trigger_threshold=0.5, enabled=True, now_monotonic=current_time)
            current_time += 0.6
            active = engine.update(signal_magnitude=0.9, noise_threshold=0.1, trigger_threshold=0.5, enabled=True, now_monotonic=current_time)
            sequence_seen.append(active.active_material_index)
            current_time += 0.1
            engine.update(signal_magnitude=0.0, noise_threshold=0.1, trigger_threshold=0.5, enabled=True, now_monotonic=current_time)
            current_time += 2.5

        self.assertEqual(sequence_seen, [0, 1, 2, 3, 4, 2, 1, 3])

    def test_bars_remain_visible_for_half_second_after_noise_drop(self):
        engine = TouchClassifierDemoEngine(material_count=5, material_sequence=(1, 2, 3, 4, 5))

        engine.update(signal_magnitude=0.8, noise_threshold=0.1, trigger_threshold=0.5, enabled=True, now_monotonic=0.0)
        active = engine.update(signal_magnitude=0.8, noise_threshold=0.1, trigger_threshold=0.5, enabled=True, now_monotonic=0.6)
        self.assertEqual(active.active_material_index, 0)

        held = engine.update(signal_magnitude=0.0, noise_threshold=0.1, trigger_threshold=0.5, enabled=True, now_monotonic=1.2)
        self.assertEqual(held.active_material_index, 0)
        self.assertGreater(sum(held.scores), 0.0)

        cleared = engine.update(signal_magnitude=0.0, noise_threshold=0.1, trigger_threshold=0.5, enabled=True, now_monotonic=1.8)
        self.assertIsNone(cleared.active_material_index)
        self.assertEqual(sum(cleared.scores), 0.0)


if __name__ == "__main__":
    unittest.main()
