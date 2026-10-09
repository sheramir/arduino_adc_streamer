"""Device timeline and common policy for missing received measurements."""
import numpy as np


class DeviceRestart(RuntimeError):
    pass


class DeviceTimeline:
    """Extend successive uint32 micros values, for any number of rollovers.

    A backward jump of less than half a cycle is a restart/out-of-order fault.
    More than 60 seconds between delivered timestamps is ambiguous in this
    high-rate protocol and interrupts the capture rather than splicing a restart.
    No host/device clock subtraction is used.
    """
    def __init__(self, max_interval_us=60_000_000):
        self.last = None
        self.elapsed_us = 0
        self.max_interval_us = max_interval_us

    def extend(self, starts):
        values = np.asarray(starts, dtype=np.int64)
        if not values.size:
            return np.empty(0, dtype=np.float64)
        previous = values[0] if self.last is None else self.last
        deltas = np.diff(np.concatenate(([previous], values))) & 0xFFFFFFFF
        if np.any(deltas > self.max_interval_us) or np.any(deltas[1:] == 0) or (self.last is not None and deltas[0] == 0):
            raise DeviceRestart("device timestamp restarted, moved backwards or has an ambiguous long gap; capture interrupted")
        extended = self.elapsed_us + np.cumsum(deltas, dtype=np.int64)
        self.elapsed_us = int(extended[-1])
        self.last = int(values[-1])
        return extended.astype(np.float64) / 1e6


def gap_indices(times, *, previous=None, nominal=None):
    """Reset/reject across intervals >3 normal periods (at least 10 us).

    Detection is based on received device times, not an assertion about sensor
    sampling. Callers may supply a capture's normal period for short windows.
    """
    times = np.asarray(times, dtype=np.float64)
    if not times.size:
        return np.empty(0, dtype=np.int64)
    deltas = np.diff(times, prepend=times[0] if previous is None else previous)
    positives = deltas[deltas > 0]
    if nominal is None:
        nominal = float(np.median(positives)) if positives.size else 0.0
    return np.flatnonzero(deltas > max(10e-6, 3 * nominal))


def peak_envelope(times, values, budget, *, nominal=None):
    """Pixel-budget min/max display reduction, with explicit NaN gap markers.

    Full-resolution samples are never changed. Extrema retain original times.
    Gap endpoints and markers have priority over the approximate point budget.
    """
    x, y = np.asarray(times), np.asarray(values)
    if not len(x):
        return x, y
    gaps = gap_indices(x, nominal=nominal)
    boundaries = np.concatenate(([0], gaps, [len(x)]))
    out_x, out_y = [], []
    for start, end in zip(boundaries[:-1], boundaries[1:]):
        count = end - start
        segment_budget = max(4, int(budget * count / len(x)))
        if count > segment_budget:
            bins = max(1, (segment_budget - 2) // 2)
            edges = np.linspace(start, end, bins + 1, dtype=int)
            # Repeat a bin's final value to fill short rows. Its original
            # occurrence wins argmin/argmax ties, preserving the exact extrema
            # and timestamps without thousands of Python calls per redraw.
            positions = np.minimum(edges[:-1, None] + np.arange(np.diff(edges).max()),
                                   edges[1:, None] - 1)
            values = y[positions]
            rows = np.arange(bins)
            minima = positions[rows, np.argmin(values, axis=1)]
            maxima = positions[rows, np.argmax(values, axis=1)]
            indices = np.unique(np.concatenate(([start, end - 1], minima, maxima)))
        else:
            indices = np.arange(start, end)
        if out_x:
            out_x.append(np.asarray([x[start]]))
            out_y.append(np.asarray([np.nan]))
        out_x.append(x[indices])
        out_y.append(y[indices])
    return np.concatenate(out_x), np.concatenate(out_y)
