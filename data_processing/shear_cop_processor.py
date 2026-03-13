"""
Shear / CoP Processor
=====================
Real-time conditioning and shear / center-of-pressure estimation for the
5-channel MG-24 piezo package.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
from typing import Deque, Dict, Iterable, List, Tuple

import numpy as np


SHEAR_SENSOR_ORDER = ["C", "R", "B", "L", "T"]
SHEAR_SENSOR_COORDS = {
    "C": (0.0, 0.0),
    "R": (1.0, 0.0),
    "B": (0.0, -1.0),
    "L": (-1.0, 0.0),
    "T": (0.0, 1.0),
}


@dataclass
class ShearCoPResult:
    conditioned_values: Dict[str, float]
    integrated_values: Dict[str, float]
    signed_magnitudes: Dict[str, float]
    residual_values: Dict[str, float]
    cop_x: float
    cop_y: float
    shear_x: float
    shear_y: float
    shear_magnitude: float
    shear_angle_deg: float
    confidence: float
    total_weight: float


def condition_samples(
    samples: np.ndarray,
    baseline_value: float,
    smoothing_alpha: float,
) -> np.ndarray:
    """Remove DC/baseline and optionally apply a light EMA smoother."""
    centered = np.asarray(samples, dtype=np.float64) - float(baseline_value)
    if centered.size == 0 or smoothing_alpha <= 0.0:
        return centered

    alpha = min(max(float(smoothing_alpha), 0.0), 1.0)
    smoothed = np.empty_like(centered, dtype=np.float64)
    prev = centered[0]
    smoothed[0] = prev
    for idx in range(1, centered.size):
        prev = alpha * centered[idx] + (1.0 - alpha) * prev
        smoothed[idx] = prev
    return smoothed


def integrate_signed_signal(samples: np.ndarray, sample_rate_hz: float) -> float:
    """Integrate the signed signal over the current window."""
    if samples.size == 0 or sample_rate_hz <= 0:
        return 0.0
    dt = 1.0 / float(sample_rate_hz)
    return float(np.sum(samples) * dt)


def apply_signed_calibration(value: float, baseline: float, gain: float, deadband: float) -> float:
    """Apply signed deadband/noise-floor and gain while preserving sign."""
    net_deadband = max(float(baseline), float(deadband), 0.0)
    magnitude = max(0.0, abs(float(value)) - net_deadband)
    return math.copysign(magnitude * max(float(gain), 0.0), float(value)) if magnitude > 0.0 else 0.0


def extract_shear_pair(positive_sensor_value: float, negative_sensor_value: float) -> Tuple[float, float, float]:
    """
    Extract shear from an opposite-sign sensor pair.

    The pair order is the positive-axis sensor first:
    - X axis: (Right, Left)
    - Y axis: (Top, Bottom)
    """
    a = float(positive_sensor_value)
    b = float(negative_sensor_value)
    if a == 0.0 or b == 0.0 or (a > 0.0 and b > 0.0) or (a < 0.0 and b < 0.0):
        return 0.0, a, b

    extracted = min(abs(a), abs(b))
    residual_a = math.copysign(max(0.0, abs(a) - extracted), a)
    residual_b = math.copysign(max(0.0, abs(b) - extracted), b)

    # Opposite-sign patterns encode direction across the pair.
    if a > 0.0 and b < 0.0:
        signed_shear = extracted
    else:
        signed_shear = -extracted

    return signed_shear, residual_a, residual_b


def shift_residuals_to_positive(values: Dict[str, float]) -> Dict[str, float]:
    if not values:
        return {}
    min_value = min(float(v) for v in values.values())
    if min_value >= 0.0:
        return {key: float(val) for key, val in values.items()}
    offset = abs(min_value)
    return {key: float(val) + offset for key, val in values.items()}


def estimate_cop(values: Dict[str, float]) -> Tuple[float, float, float]:
    weights = shift_residuals_to_positive(values)
    total_weight = float(sum(weights.values()))
    if total_weight <= 1e-12:
        return 0.0, 0.0, 0.0

    cop_x = 0.0
    cop_y = 0.0
    for sensor_name in SHEAR_SENSOR_ORDER:
        weight = float(weights.get(sensor_name, 0.0))
        x_pos, y_pos = SHEAR_SENSOR_COORDS[sensor_name]
        cop_x += weight * x_pos
        cop_y += weight * y_pos

    return cop_x / total_weight, cop_y / total_weight, total_weight


def angle_from_shear_vector(shear_x: float, shear_y: float) -> float:
    # 0 deg = +Y, +90 deg = +X
    return math.degrees(math.atan2(float(shear_x), float(shear_y)))


def generate_gaussian_blob(
    x_grid: np.ndarray,
    y_grid: np.ndarray,
    center_x: float,
    center_y: float,
    sigma_x: float,
    sigma_y: float,
    amplitude: float,
) -> np.ndarray:
    sigma_x = max(float(sigma_x), 1e-6)
    sigma_y = max(float(sigma_y), 1e-6)
    dx = np.asarray(x_grid, dtype=np.float64) - float(center_x)
    dy = np.asarray(y_grid, dtype=np.float64) - float(center_y)
    gaussian = np.exp(-(dx ** 2 / (2.0 * sigma_x ** 2) + dy ** 2 / (2.0 * sigma_y ** 2)))
    return gaussian * max(float(amplitude), 0.0)


class ShearCoPProcessor:
    """Stateful shear / CoP processor for live updates."""

    def __init__(self, sensor_order: Iterable[str] | None = None) -> None:
        self.sensor_order = list(sensor_order or SHEAR_SENSOR_ORDER)
        self.reset()

    def reset(self) -> None:
        self.baseline_tracker = {name: 0.0 for name in self.sensor_order}
        self.baseline_initialized = {name: False for name in self.sensor_order}
        self.shear_history: Deque[np.ndarray] = deque(maxlen=12)
        self.magnitude_history: Deque[float] = deque(maxlen=12)

    def _update_baseline(self, sensor_name: str, samples: np.ndarray, baseline_alpha: float) -> float:
        if samples.size == 0:
            return self.baseline_tracker[sensor_name]

        sample_mean = float(np.mean(samples))
        alpha = min(max(float(baseline_alpha), 0.0), 1.0)
        if alpha <= 0.0:
            return self.baseline_tracker[sensor_name]
        if not self.baseline_initialized[sensor_name]:
            self.baseline_tracker[sensor_name] = sample_mean
            self.baseline_initialized[sensor_name] = True
        else:
            prev = self.baseline_tracker[sensor_name]
            self.baseline_tracker[sensor_name] = alpha * sample_mean + (1.0 - alpha) * prev
        return self.baseline_tracker[sensor_name]

    def _compute_temporal_stability(self, shear_x: float, shear_y: float, magnitude: float) -> float:
        current_vec = np.array([float(shear_x), float(shear_y)], dtype=np.float64)

        if magnitude > 1e-9:
            norm_current = current_vec / magnitude
            self.shear_history.append(norm_current)
            self.magnitude_history.append(float(magnitude))
        else:
            self.shear_history.append(np.zeros(2, dtype=np.float64))
            self.magnitude_history.append(0.0)

        if len(self.shear_history) < 2:
            return 1.0

        hist = np.array(self.shear_history, dtype=np.float64)
        mag_hist = np.array(self.magnitude_history, dtype=np.float64)
        active = mag_hist > 1e-9

        if not np.any(active):
            return 1.0

        active_hist = hist[active]
        mean_vec = np.mean(active_hist, axis=0)
        mean_norm = float(np.linalg.norm(mean_vec))
        if mean_norm <= 1e-9 or magnitude <= 1e-9:
            alignment = 1.0
        else:
            mean_dir = mean_vec / mean_norm
            alignment = float(np.clip((np.dot(current_vec / magnitude, mean_dir) + 1.0) * 0.5, 0.0, 1.0))

        mean_mag = float(np.mean(mag_hist[active]))
        if mean_mag <= 1e-9:
            magnitude_stability = 1.0
        else:
            magnitude_std = float(np.std(mag_hist[active]))
            magnitude_stability = float(np.clip(1.0 - (magnitude_std / (mean_mag + 1e-9)), 0.0, 1.0))

        return 0.6 * alignment + 0.4 * magnitude_stability

    def _compute_confidence(
        self,
        signed_magnitudes: Dict[str, float],
        shear_x: float,
        shear_y: float,
        shear_magnitude: float,
        total_weight: float,
        signal_strength_ref: float,
    ) -> float:
        total_signal = float(sum(abs(v) for v in signed_magnitudes.values()))
        strength = float(np.clip(total_signal / max(float(signal_strength_ref), 1e-9), 0.0, 1.0))
        dominance = float(np.clip(shear_magnitude / max(total_signal, 1e-9), 0.0, 1.0))
        weight_quality = float(np.clip(total_weight / max(float(signal_strength_ref), 1e-9), 0.0, 1.0))
        stability = self._compute_temporal_stability(shear_x, shear_y, shear_magnitude)
        return float(np.clip((0.5 * strength + 0.2 * weight_quality + 0.3 * dominance) * stability, 0.0, 1.0))

    def process(
        self,
        sensor_samples: Dict[str, np.ndarray],
        sample_rate_hz: float,
        settings: Dict[str, object],
    ) -> ShearCoPResult:
        integration_window_ms = float(settings.get("integration_window_ms", 16.0))
        samples_in_window = max(1, int(round(sample_rate_hz * integration_window_ms / 1000.0)))
        smoothing_alpha = float(settings.get("conditioning_alpha", 0.25))
        baseline_alpha = float(settings.get("baseline_alpha", 0.05))
        deadband = float(settings.get("deadband_threshold", 0.0))
        gains = settings.get("sensor_gains", {})
        baselines = settings.get("sensor_baselines", {})

        conditioned_values: Dict[str, float] = {}
        integrated_values: Dict[str, float] = {}
        signed_magnitudes: Dict[str, float] = {}

        for sensor_name in self.sensor_order:
            samples = np.asarray(sensor_samples.get(sensor_name, np.array([], dtype=np.float64)), dtype=np.float64)
            if samples.size > samples_in_window:
                samples = samples[-samples_in_window:]

            tracked_baseline = self._update_baseline(sensor_name, samples, baseline_alpha)
            conditioned = condition_samples(samples, tracked_baseline, smoothing_alpha)
            integrated = integrate_signed_signal(conditioned, sample_rate_hz)
            signed_mag = apply_signed_calibration(
                integrated,
                float(baselines.get(sensor_name, 0.0)),
                float(gains.get(sensor_name, 1.0)),
                deadband,
            )

            conditioned_values[sensor_name] = float(conditioned[-1]) if conditioned.size else 0.0
            integrated_values[sensor_name] = integrated
            signed_magnitudes[sensor_name] = signed_mag

        shear_x, residual_r, residual_l = extract_shear_pair(
            signed_magnitudes.get("R", 0.0),
            signed_magnitudes.get("L", 0.0),
        )
        shear_y, residual_t, residual_b = extract_shear_pair(
            signed_magnitudes.get("T", 0.0),
            signed_magnitudes.get("B", 0.0),
        )

        residuals = dict(signed_magnitudes)
        residuals["R"] = residual_r
        residuals["L"] = residual_l
        residuals["T"] = residual_t
        residuals["B"] = residual_b

        cop_x, cop_y, total_weight = estimate_cop(residuals)
        shear_magnitude = math.hypot(shear_x, shear_y)
        shear_angle_deg = angle_from_shear_vector(shear_x, shear_y)
        confidence = self._compute_confidence(
            signed_magnitudes,
            shear_x,
            shear_y,
            shear_magnitude,
            total_weight,
            float(settings.get("confidence_signal_ref", 1.0)),
        )

        return ShearCoPResult(
            conditioned_values=conditioned_values,
            integrated_values=integrated_values,
            signed_magnitudes=signed_magnitudes,
            residual_values=residuals,
            cop_x=cop_x,
            cop_y=cop_y,
            shear_x=shear_x,
            shear_y=shear_y,
            shear_magnitude=shear_magnitude,
            shear_angle_deg=shear_angle_deg,
            confidence=confidence,
            total_weight=total_weight,
        )


def run_shear_debug_cases() -> List[Dict[str, object]]:
    """Synthetic extraction/debug cases requested for the new shear pipeline."""
    cases = []

    x1, r1, l1 = extract_shear_pair(-3.0, 4.0)
    cases.append({
        "name": "R=-3, L=+4",
        "shear": x1,
        "residual": {"R": r1, "L": l1},
    })

    x2, r2, l2 = extract_shear_pair(2.0, -3.0)
    cases.append({
        "name": "R=+2, L=-3",
        "shear": x2,
        "residual": {"R": r2, "L": l2},
    })

    x3, r3, l3 = extract_shear_pair(2.0, 5.0)
    cases.append({
        "name": "Same-sign pair",
        "shear": x3,
        "residual": {"R": r3, "L": l3},
    })

    processor = ShearCoPProcessor()
    diag_samples = {
        "C": np.zeros(16, dtype=np.float64),
        "R": np.full(16, 2.0),
        "L": np.full(16, -3.0),
        "T": np.full(16, 4.0),
        "B": np.full(16, -5.0),
    }
    diag_result = processor.process(
        diag_samples,
        sample_rate_hz=1000.0,
        settings={
            "integration_window_ms": 16.0,
            "conditioning_alpha": 0.0,
            "baseline_alpha": 0.0,
            "deadband_threshold": 0.0,
            "sensor_gains": {name: 1.0 for name in SHEAR_SENSOR_ORDER},
            "sensor_baselines": {name: 0.0 for name in SHEAR_SENSOR_ORDER},
            "confidence_signal_ref": 1.0,
        },
    )
    cases.append({
        "name": "Diagonal XY",
        "shear_vector": (diag_result.shear_x, diag_result.shear_y),
        "angle_deg": diag_result.shear_angle_deg,
    })

    quiet_processor = ShearCoPProcessor()
    quiet_samples = {name: np.zeros(16, dtype=np.float64) for name in SHEAR_SENSOR_ORDER}
    quiet_result = quiet_processor.process(
        quiet_samples,
        sample_rate_hz=1000.0,
        settings={
            "integration_window_ms": 16.0,
            "conditioning_alpha": 0.0,
            "baseline_alpha": 0.0,
            "deadband_threshold": 0.01,
            "sensor_gains": {name: 1.0 for name in SHEAR_SENSOR_ORDER},
            "sensor_baselines": {name: 0.0 for name in SHEAR_SENSOR_ORDER},
            "confidence_signal_ref": 1.0,
        },
    )
    cases.append({
        "name": "Near-zero",
        "shear_vector": (quiet_result.shear_x, quiet_result.shear_y),
        "confidence": quiet_result.confidence,
    })

    return cases
