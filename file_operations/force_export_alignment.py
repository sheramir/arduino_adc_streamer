"""
Force Export Alignment Helpers
==============================
Helpers for aligning captured force samples to exported ADC sweep rows.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class ForceExportSeries:
    """Sorted force samples ready for nearest-timestamp lookup."""

    timestamps_s: np.ndarray
    x_force: np.ndarray
    z_force: np.ndarray


def build_force_export_series(force_samples) -> ForceExportSeries | None:
    """Return a sorted force-sample view for export alignment."""
    if not force_samples:
        return None

    force_array = np.asarray(force_samples, dtype=np.float64)
    if force_array.ndim != 2 or force_array.shape[1] < 3 or len(force_array) == 0:
        return None

    sort_order = np.argsort(force_array[:, 0], kind="stable")
    force_array = force_array[sort_order]
    return ForceExportSeries(
        timestamps_s=force_array[:, 0],
        x_force=force_array[:, 1],
        z_force=force_array[:, 2],
    )


def build_export_row_timestamps(
    *,
    selected_timestamps,
    saved_total: int,
    capture_duration_s: float | None,
):
    """Return row timestamps for export using measured sweep times when available."""
    if selected_timestamps is not None and len(selected_timestamps) >= saved_total:
        return np.asarray(selected_timestamps[:saved_total], dtype=np.float64)

    if capture_duration_s is None or saved_total <= 1:
        return None

    return np.linspace(0.0, float(capture_duration_s), num=saved_total, dtype=np.float64)


def get_nearest_force_values(
    force_series: ForceExportSeries | None,
    sweep_time_s: float | None,
) -> tuple[float, float]:
    """Return the nearest calibrated force sample for one exported sweep row."""
    if force_series is None or sweep_time_s is None or len(force_series.timestamps_s) == 0:
        return (0.0, 0.0)

    timestamps = force_series.timestamps_s
    insert_at = int(np.searchsorted(timestamps, float(sweep_time_s), side="left"))

    if insert_at <= 0:
        closest_index = 0
    elif insert_at >= len(timestamps):
        closest_index = len(timestamps) - 1
    else:
        prev_index = insert_at - 1
        next_index = insert_at
        prev_diff = abs(float(sweep_time_s) - float(timestamps[prev_index]))
        next_diff = abs(float(timestamps[next_index]) - float(sweep_time_s))
        closest_index = prev_index if prev_diff <= (next_diff + 1e-12) else next_index

    return (
        float(force_series.x_force[closest_index]),
        float(force_series.z_force[closest_index]),
    )
