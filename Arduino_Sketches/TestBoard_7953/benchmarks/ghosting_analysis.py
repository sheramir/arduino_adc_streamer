"""Pure signal analysis and display reduction for the ghosting benchmark."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np


@dataclass(frozen=True)
class Calibration:
    baseline: float
    stdev: float
    noise_sigma: float
    sample_count: int


def calibrate(samples: np.ndarray, routes: Sequence[str]) -> dict[str, Calibration]:
    values = np.asarray(samples, dtype=float)
    if values.ndim != 2 or values.shape[1] != len(routes) or len(values) < 2:
        raise ValueError("Baseline requires at least two complete sweeps")
    if not np.isfinite(values).all() or (values < 0).any() or (values > 4095).any():
        raise ValueError("Baseline contains invalid ADC samples")
    medians = np.median(values, axis=0)
    deviations = np.std(values, axis=0, ddof=1)
    return {
        route: Calibration(float(medians[i]), float(deviations[i]),
                           max(1.0, float(deviations[i])), len(values))
        for i, route in enumerate(routes)
    }


def analyze_window(
    samples: np.ndarray, routes: Sequence[str], source: str,
    calibration: Mapping[str, Calibration], *, target_counts: float = 1,
    target_sigma: float = 3, correlation_min: float = 0.8,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    values = np.asarray(samples, dtype=float)
    if values.ndim != 2 or values.shape[1] != len(routes) or len(values) < 2:
        raise ValueError("Signal window requires at least two complete sweeps")
    if not np.isfinite(values).all() or (values < 0).any() or (values > 4095).any():
        raise ValueError("Signal window contains invalid ADC samples")
    source_index = routes.index(source)
    signals = values - np.array([calibration[r].baseline for r in routes])
    original = signals[:, source_index]
    source_peak = float(np.max(np.abs(original)))
    source_clipped = bool(((values[:, source_index] == 0) |
                           (values[:, source_index] == 4095)).any())
    if source_peak == 0:
        raise ValueError("Source has no measurable signal")
    centered_source = original - original.mean()
    source_norm = float(np.linalg.norm(centered_source))
    source_stdev = float(np.std(original, ddof=1))
    pairs: list[dict[str, Any]] = []
    for i, target in enumerate(routes):
        if target == source or target.split(":")[0] != source.split(":")[0]:
            continue
        signal = signals[:, i]
        peak = float(np.max(np.abs(signal)))
        centered_target = signal - signal.mean()
        target_stdev = float(np.std(signal, ddof=1))
        denominator = source_norm * float(np.linalg.norm(centered_target))
        correlation = (float(np.clip(np.dot(centered_source, centered_target) /
                                     denominator, -1, 1)) if denominator else None)
        clipped = bool(((values[:, i] == 0) | (values[:, i] == 4095)).any())
        threshold = max(target_counts, target_sigma * calibration[target].noise_sigma)
        inconclusive = source_clipped or clipped or correlation is None
        detected = not inconclusive and peak > threshold and correlation >= correlation_min
        pairs.append({
            "source": source, "target": target, "source_peak": source_peak,
            "target_peak": peak, "source_stdev": source_stdev, "target_stdev": target_stdev,
            "attenuation_pct": 100 * target_stdev / source_stdev if source_stdev > 0 else "",
            "correlation": correlation if correlation is not None else "",
            "target_threshold": threshold, "target_clipped": clipped,
            "ghosting_detected": detected,
            "status": "INCONCLUSIVE" if inconclusive else "GHOST" if detected else "NO_GHOST",
        })
    detected_targets = [p["target"] for p in pairs if p["ghosting_detected"]]
    return {
        "source": source, "source_peak": source_peak, "source_stdev": source_stdev,
        "source_clipped": source_clipped, "sample_count": len(values),
        "status": "CLIPPED" if source_clipped else "VALID",
        "ghosting_detected": bool(detected_targets),
        "ghost_targets": ", ".join(detected_targets),
        "inconclusive_pairs": sum(p["status"] == "INCONCLUSIVE" for p in pairs),
    }, pairs


def strongest_attempt(attempts: Sequence[Mapping[str, Any]], source: str) -> Any:
    valid = [a for a in attempts if a["source"] == source and a["status"] == "VALID"]
    # max retains the first attempt when peak amplitudes tie.
    return max(valid, key=lambda a: float(a["source_peak"]), default=None)


def summarize_attempts(routes: Sequence[str], attempts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for source in sorted(routes, key=lambda r: tuple(map(int, r.split(":")))):
        selected = strongest_attempt(attempts, source)
        history = [a for a in attempts if a["source"] == source]
        if selected is not None:
            rows.append({**selected, "selected_attempt": selected["attempt"]})
        else:
            rows.append({"source": source, "selected_attempt": "",
                         "status": history[-1]["status"] if history else "UNTESTED",
                         "notes": history[-1].get("notes", "") if history else ""})
    return rows


def chart_indices(signals: np.ndarray, limit: int = 5000) -> np.ndarray:
    """Shared time indices retaining each trace's bucket extrema."""
    values = np.asarray(signals)
    if values.ndim != 2 or not values.shape[1]:
        raise ValueError("Chart signals must be a nonempty-column matrix")
    count, channels = values.shape
    if count <= limit:
        return np.arange(count)
    buckets = (limit - 2) // (2 * channels)
    if buckets < 1:
        raise ValueError("Point limit cannot preserve all channel extrema")
    indices = {0, count - 1}
    edges = np.linspace(0, count, buckets + 1, dtype=int)
    for start, end in zip(edges[:-1], edges[1:]):
        chunk = values[start:end]
        indices.update((start + np.argmin(chunk, axis=0)).tolist())
        indices.update((start + np.argmax(chunk, axis=0)).tolist())
    return np.array(sorted(indices), dtype=int)


def chart_bounds(signals: np.ndarray) -> tuple[float, float]:
    lower, upper = float(np.min(signals)), float(np.max(signals))
    padding = max(1.0, 0.05 * (upper - lower))
    return lower - padding, upper + padding
