"""
Heatmap Signal Processing
=========================
Per-channel signal conditioning for heatmap magnitude calculation.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

import numpy as np


class HeatmapSignalProcessor:
    """Process per-channel samples into bias-removed RMS magnitudes."""

    def __init__(
        self,
        channel_count: int,
        bias_duration_sec: float,
        hpf_cutoff_hz: float,
    ) -> None:
        self.channel_count = channel_count
        self.bias_duration_sec = bias_duration_sec
        self.hpf_cutoff_hz = hpf_cutoff_hz
        self.reset()

    def reset(self) -> None:
        self.bias_sums = np.zeros(self.channel_count, dtype=np.float64)
        self.bias_counts = np.zeros(self.channel_count, dtype=np.float64)
        self.bias_values = np.zeros(self.channel_count, dtype=np.float64)
        self.bias_ready = False
        self.bias_start_time = None
        self.hpf_prev_x = np.zeros(self.channel_count, dtype=np.float64)
        self.hpf_prev_y = np.zeros(self.channel_count, dtype=np.float64)
        self.ema_values = np.zeros(self.channel_count, dtype=np.float64)
        self.ema_initialized = False

    def update_channel_count(self, channel_count: int) -> None:
        if channel_count != self.channel_count:
            self.channel_count = channel_count
            self.reset()

    def set_hpf_cutoff(self, cutoff_hz: float) -> None:
        self.hpf_cutoff_hz = cutoff_hz

    def _update_bias(self, channel_samples: List[np.ndarray], window_end_time_sec: Optional[float]) -> None:
        if self.bias_ready:
            return

        for idx, samples in enumerate(channel_samples):
            if samples.size == 0:
                continue
            self.bias_sums[idx] += float(np.sum(samples))
            self.bias_counts[idx] += float(samples.size)

        counts = np.maximum(self.bias_counts, 1.0)
        self.bias_values = self.bias_sums / counts

        if window_end_time_sec is not None and window_end_time_sec >= self.bias_duration_sec:
            self.bias_ready = True

    def _high_pass_filter(self, samples: np.ndarray, sample_rate_hz: float, idx: int) -> np.ndarray:
        if samples.size == 0:
            return samples

        if sample_rate_hz <= 0 or self.hpf_cutoff_hz <= 0:
            return samples - float(np.mean(samples))

        dt = 1.0 / sample_rate_hz
        rc = 1.0 / (2.0 * np.pi * self.hpf_cutoff_hz)
        alpha = rc / (rc + dt)

        y = np.empty_like(samples, dtype=np.float64)
        prev_x = self.hpf_prev_x[idx]
        prev_y = self.hpf_prev_y[idx]

        for i in range(samples.size):
            x = samples[i]
            prev_y = alpha * (prev_y + x - prev_x)
            y[i] = prev_y
            prev_x = x

        self.hpf_prev_x[idx] = prev_x
        self.hpf_prev_y[idx] = prev_y
        return y

    def compute_rms(
        self,
        channel_samples: List[np.ndarray],
        dc_removal_mode: str,
        sample_rate_hz: float,
        window_end_time_sec: Optional[float],
    ) -> Tuple[List[float], np.ndarray]:
        self.update_channel_count(len(channel_samples))

        if dc_removal_mode == "bias":
            self._update_bias(channel_samples, window_end_time_sec)
            rms_values = []
            for idx, samples in enumerate(channel_samples):
                if samples.size == 0:
                    rms_values.append(0.0)
                    continue
                centered = samples - self.bias_values[idx]
                rms_values.append(float(np.sqrt(np.mean(centered ** 2))))
            return rms_values, self.bias_values.copy()

        rms_values = []
        for idx, samples in enumerate(channel_samples):
            filtered = self._high_pass_filter(samples, sample_rate_hz, idx)
            if filtered.size == 0:
                rms_values.append(0.0)
                continue
            rms_values.append(float(np.sqrt(np.mean(filtered ** 2))))

        return rms_values, self.bias_values.copy()

    def smooth_and_threshold(
        self,
        values: List[float],
        alpha: float,
        threshold: float,
    ) -> List[float]:
        if not values:
            return []

        self.update_channel_count(len(values))
        values_array = np.array(values, dtype=np.float64)

        if alpha <= 0.0:
            smoothed = values_array
        elif alpha >= 1.0:
            smoothed = values_array
            self.ema_values = values_array
            self.ema_initialized = True
        else:
            if not self.ema_initialized:
                self.ema_values = values_array
                self.ema_initialized = True
            else:
                self.ema_values = alpha * values_array + (1.0 - alpha) * self.ema_values
            smoothed = self.ema_values

        if threshold > 0.0:
            smoothed = np.where(smoothed < threshold, 0.0, smoothed)

        return smoothed.tolist()
