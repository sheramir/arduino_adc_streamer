"""
Circular Sweep-Buffer Windowing
===============================
Index math for reading the most recent sweeps out of the fixed-size circular
buffers used by capture. Several processing paths (plotting, heatmap, spectrum,
filtering) need the same trailing window, so the wrap-around arithmetic lives
here once rather than being re-derived at each call site.
"""

from __future__ import annotations

import numpy as np


def recent_window_slices(
    total_sweeps: int,
    write_index: int,
    count: int,
    capacity: int,
) -> list[tuple[int, int]]:
    """Return buffer ``(start, stop)`` ranges covering the most recent ``count`` sweeps.

    Ranges are returned in chronological order and may be one or two entries:
    two when the requested window wraps past the end of the buffer. An empty
    list means there is nothing to read.

    Handles both regimes: before the buffer has wrapped it is filled linearly
    from index 0, and afterwards it is a true ring written at
    ``write_index % capacity``.
    """
    if capacity <= 0:
        return []

    available = min(int(total_sweeps), capacity)
    count = min(int(count), available)
    if count <= 0:
        return []

    # Not yet wrapped: sweeps sit contiguously at the front of the buffer.
    if available < capacity:
        return [(available - count, available)]

    write_pos = int(write_index) % capacity
    start_pos = (write_pos - count) % capacity

    # A full-capacity window starting at the write head reads the whole ring.
    if count == capacity and write_pos == 0:
        return [(0, capacity)]

    if start_pos < write_pos:
        return [(start_pos, write_pos)]

    tail = (start_pos, capacity)
    head = (0, write_pos)
    return [tail, head] if write_pos > 0 else [tail]


def take_recent(buffer: np.ndarray, slices: list[tuple[int, int]]) -> np.ndarray:
    """Copy the given ranges out of ``buffer`` as one contiguous array.

    The result never aliases ``buffer``, so callers may release the buffer lock
    immediately afterwards.
    """
    if not slices:
        empty_shape = (0,) + buffer.shape[1:]
        return np.empty(empty_shape, dtype=buffer.dtype)
    if len(slices) == 1:
        start, stop = slices[0]
        return buffer[start:stop].copy()
    return np.concatenate([buffer[start:stop] for start, stop in slices])
