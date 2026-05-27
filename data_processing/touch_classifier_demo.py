"""Demo material-classifier state engine for Pressure Map UI.

This is a GUI-only demonstration engine and does not perform real ML
inference. It emits fluctuating softmax-like scores that sum to 100.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
import time

from constants.touch_id import (
    TOUCH_CLASSIFIER_DOMINANT_MAX,
    TOUCH_CLASSIFIER_DOMINANT_MIN,
    TOUCH_CLASSIFIER_FLUCTUATION_STD,
    TOUCH_CLASSIFIER_HOLD_AFTER_NOISE_SEC,
    TOUCH_CLASSIFIER_REPEAT_WINDOW_SEC,
    TOUCH_CLASSIFIER_SCORE_MAX,
    TOUCH_CLASSIFIER_SCORE_MIN,
    TOUCH_CLASSIFIER_SMOOTHING_ALPHA,
    TOUCH_CLASSIFIER_TRIGGER_DELAY_SEC,
)


@dataclass(frozen=True, slots=True)
class TouchClassifierDisplayState:
    """Display state returned by the demo engine."""

    scores: tuple[float, ...]
    active_material_index: int | None


class TouchClassifierDemoEngine:
    """Generate deterministic demo scores for material classification UI."""

    def __init__(
        self,
        material_count: int,
        material_sequence: list[int] | tuple[int, ...],
        *,
        trigger_delay_sec: float = TOUCH_CLASSIFIER_TRIGGER_DELAY_SEC,
        repeat_window_sec: float = TOUCH_CLASSIFIER_REPEAT_WINDOW_SEC,
    ) -> None:
        self.material_count = max(1, int(material_count))
        self.sequence = self._normalize_sequence(material_sequence, self.material_count)
        self.trigger_delay_sec = max(0.0, float(trigger_delay_sec))
        self.repeat_window_sec = max(0.0, float(repeat_window_sec))
        self.hold_after_noise_sec = max(0.0, float(TOUCH_CLASSIFIER_HOLD_AFTER_NOISE_SEC))
        self._rng = random.Random(7321)

        self._sequence_pos = 0
        self._active_material_index: int | None = None
        self._last_displayed_material_index: int | None = None
        self._last_zero_time: float | None = None
        self._silence_started_time: float | None = None
        self._pending_material_index: int | None = None
        self._pending_sequence_pos: int | None = None
        self._pending_deadline: float | None = None
        self._scores: list[float] = [0.0 for _ in range(self.material_count)]

    def reset_scores(self) -> TouchClassifierDisplayState:
        self._scores = [0.0 for _ in range(self.material_count)]
        self._active_material_index = None
        self._last_displayed_material_index = None
        self._pending_material_index = None
        self._pending_sequence_pos = None
        self._pending_deadline = None
        self._last_zero_time = None
        self._silence_started_time = None
        return TouchClassifierDisplayState(tuple(self._scores), None)

    def update(
        self,
        *,
        signal_magnitude: float,
        noise_threshold: float,
        trigger_threshold: float,
        enabled: bool,
        now_monotonic: float | None = None,
    ) -> TouchClassifierDisplayState:
        now = time.monotonic() if now_monotonic is None else float(now_monotonic)

        if not enabled:
            return self.reset_scores()

        magnitude = abs(float(signal_magnitude))
        noise_floor = max(0.0, float(noise_threshold))
        trigger_floor = max(noise_floor, float(trigger_threshold))

        if self._active_material_index is not None and self._silence_started_time is not None:
            silence_elapsed = now - self._silence_started_time
            if silence_elapsed >= self.hold_after_noise_sec:
                self._last_zero_time = self._silence_started_time + self.hold_after_noise_sec
                self._active_material_index = None
                self._pending_material_index = None
                self._pending_sequence_pos = None
                self._pending_deadline = None
                self._scores = [0.0 for _ in range(self.material_count)]
            elif magnitude > noise_floor:
                self._silence_started_time = None

        if magnitude <= noise_floor:
            if self._active_material_index is not None:
                if self._silence_started_time is None:
                    self._silence_started_time = now
                silence_elapsed = now - self._silence_started_time
                if silence_elapsed < self.hold_after_noise_sec:
                    return TouchClassifierDisplayState(tuple(self._scores), self._active_material_index)

                self._last_zero_time = self._silence_started_time + self.hold_after_noise_sec
                self._active_material_index = None
                self._pending_material_index = None
                self._pending_sequence_pos = None
                self._pending_deadline = None
                self._scores = [0.0 for _ in range(self.material_count)]
                return TouchClassifierDisplayState(tuple(self._scores), None)

            if self._pending_material_index is not None:
                self._pending_material_index = None
                self._pending_sequence_pos = None
                self._pending_deadline = None
                self._scores = [0.0 for _ in range(self.material_count)]
                return TouchClassifierDisplayState(tuple(self._scores), None)

            self._scores = [0.0 for _ in range(self.material_count)]
            return TouchClassifierDisplayState(tuple(self._scores), None)

        if self._pending_material_index is not None and self._pending_deadline is not None:
            if now >= self._pending_deadline:
                self._active_material_index = self._pending_material_index
                if self._pending_sequence_pos is not None:
                    self._sequence_pos = self._pending_sequence_pos
                self._last_displayed_material_index = self._active_material_index
                self._pending_material_index = None
                self._pending_sequence_pos = None
                self._pending_deadline = None
                self._silence_started_time = None

        if self._active_material_index is None and self._pending_material_index is None and magnitude >= trigger_floor:
            selected, sequence_pos = self._select_material_for_trigger(now)
            self._pending_material_index = selected
            self._pending_sequence_pos = sequence_pos
            self._pending_deadline = now + self.trigger_delay_sec

        if self._active_material_index is None:
            return TouchClassifierDisplayState(tuple(self._scores), None)

        self._silence_started_time = None
        self._scores = self._generate_fluctuating_scores(self._active_material_index)
        return TouchClassifierDisplayState(tuple(self._scores), self._active_material_index)

    def _select_material_for_trigger(self, now: float) -> tuple[int, int]:
        if self._last_displayed_material_index is None:
            return self.sequence[0], 0

        reference_time = self._silence_started_time if self._silence_started_time is not None else self._last_zero_time
        if reference_time is not None:
            elapsed_since_zero = now - reference_time
            if elapsed_since_zero < self.repeat_window_sec:
                return self._last_displayed_material_index, self._sequence_pos

        next_pos = (self._sequence_pos + 1) % len(self.sequence)
        return self.sequence[next_pos], next_pos

    def _generate_fluctuating_scores(self, dominant_index: int) -> list[float]:
        dominant = self._rng.uniform(TOUCH_CLASSIFIER_DOMINANT_MIN, TOUCH_CLASSIFIER_DOMINANT_MAX)
        dominant += self._rng.gauss(0.0, TOUCH_CLASSIFIER_FLUCTUATION_STD)
        dominant = max(TOUCH_CLASSIFIER_DOMINANT_MIN, min(TOUCH_CLASSIFIER_DOMINANT_MAX, dominant))

        remainder = max(0.0, TOUCH_CLASSIFIER_SCORE_MAX - dominant)
        non_dominant_count = max(0, self.material_count - 1)

        if non_dominant_count == 0:
            target = [TOUCH_CLASSIFIER_SCORE_MAX]
        else:
            logits: list[float] = []
            for _ in range(non_dominant_count):
                logits.append(self._rng.uniform(-0.7, 0.7))
            max_logit = max(logits)
            exp_values = [math.exp(value - max_logit) for value in logits]
            exp_sum = sum(exp_values) or 1.0
            tail = [remainder * (value / exp_sum) for value in exp_values]

            target = []
            tail_index = 0
            for material_index in range(self.material_count):
                if material_index == dominant_index:
                    target.append(dominant)
                else:
                    target.append(tail[tail_index])
                    tail_index += 1

        alpha = max(0.0, min(1.0, TOUCH_CLASSIFIER_SMOOTHING_ALPHA))
        if sum(self._scores) <= 1e-9:
            smoothed = list(target)
        else:
            smoothed = [
                alpha * previous + (1.0 - alpha) * current
                for previous, current in zip(self._scores, target)
            ]

        total = sum(smoothed)
        if total <= 0.0:
            return [0.0 for _ in range(self.material_count)]

        normalized = [
            max(
                TOUCH_CLASSIFIER_SCORE_MIN,
                min(TOUCH_CLASSIFIER_SCORE_MAX, (value / total) * TOUCH_CLASSIFIER_SCORE_MAX),
            )
            for value in smoothed
        ]

        correction = TOUCH_CLASSIFIER_SCORE_MAX - sum(normalized)
        normalized[dominant_index] = max(
            TOUCH_CLASSIFIER_SCORE_MIN,
            min(TOUCH_CLASSIFIER_SCORE_MAX, normalized[dominant_index] + correction),
        )
        return normalized

    @staticmethod
    def _normalize_sequence(sequence: list[int] | tuple[int, ...], material_count: int) -> tuple[int, ...]:
        normalized: list[int] = []
        for entry in sequence:
            try:
                candidate = int(entry) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= candidate < material_count:
                normalized.append(candidate)

        if normalized:
            return tuple(normalized)

        return tuple(range(material_count))
