"""Shared helpers for the TestBoard 7953 firmware benchmark runner.

The active ADC streamer firmware families use the same binary envelope:

    AA 55 | sample_count:u16 | samples:u16[] |
    avg_dt_us:u16 | block_start_us:u32 | block_end_us:u32

This module deliberately has no serial-port dependency, which makes the parser
and timing calculations testable without connected hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import statistics
import struct
import time
from typing import Dict, Iterable, List, Optional, Sequence, Union


MAGIC = b"\xAA\x55"
HEADER_BYTES = 4
TRAILER_BYTES = 10
UINT32_MODULUS = 1 << 32


def uint32_delta(later: int, earlier: int) -> int:
    """Return a wraparound-safe unsigned 32-bit timestamp difference."""

    return (int(later) - int(earlier)) & 0xFFFFFFFF


@dataclass(frozen=True)
class BinaryFrame:
    samples: tuple[int, ...]
    avg_dt_us: int
    block_start_us: int
    block_end_us: int
    host_received_ns: int
    raw: bytes

    @property
    def sample_count(self) -> int:
        return len(self.samples)

    @property
    def acquisition_duration_us(self) -> int:
        return uint32_delta(self.block_end_us, self.block_start_us)


class BinaryFrameParser:
    """Incrementally decode framed ADC blocks and recover after bad bytes."""

    def __init__(self, *, expected_sample_count: Optional[int] = None,
                 max_sample_count: int = 4096) -> None:
        self.expected_sample_count = expected_sample_count
        self.max_sample_count = max_sample_count
        self.buffer = bytearray()
        self.discarded_bytes = 0
        self.resync_events = 0
        self.invalid_frames = 0

    def feed(
        self, data: bytes, host_received_ns: Optional[int] = None
    ) -> List[BinaryFrame]:
        if data:
            self.buffer.extend(data)
        completed_ns = host_received_ns if host_received_ns is not None else time.monotonic_ns()
        frames: List[BinaryFrame] = []

        while True:
            if len(self.buffer) < HEADER_BYTES:
                break

            magic_index = self.buffer.find(MAGIC)
            if magic_index < 0:
                # Keep a trailing 0xAA because it may be the first byte of a
                # header split across serial reads.
                keep = 1 if self.buffer[-1] == MAGIC[0] else 0
                removed = len(self.buffer) - keep
                if removed:
                    del self.buffer[:removed]
                    self.discarded_bytes += removed
                    self.resync_events += 1
                break
            if magic_index:
                del self.buffer[:magic_index]
                self.discarded_bytes += magic_index
                self.resync_events += 1
            if len(self.buffer) < HEADER_BYTES:
                break

            sample_count = struct.unpack_from("<H", self.buffer, 2)[0]
            if sample_count > self.max_sample_count:
                del self.buffer[0]
                self.discarded_bytes += 1
                self.invalid_frames += 1
                self.resync_events += 1
                continue

            frame_bytes = HEADER_BYTES + sample_count * 2 + TRAILER_BYTES
            if len(self.buffer) < frame_bytes:
                break

            raw = bytes(self.buffer[:frame_bytes])
            del self.buffer[:frame_bytes]
            if (self.expected_sample_count is not None and
                    sample_count != self.expected_sample_count):
                self.invalid_frames += 1
                continue

            samples_offset = HEADER_BYTES
            samples = struct.unpack_from(f"<{sample_count}H", raw, samples_offset)
            trailer_offset = samples_offset + sample_count * 2
            avg_dt_us, block_start_us, block_end_us = struct.unpack_from(
                "<HII", raw, trailer_offset
            )
            frames.append(
                BinaryFrame(
                    samples=tuple(samples),
                    avg_dt_us=avg_dt_us,
                    block_start_us=block_start_us,
                    block_end_us=block_end_us,
                    host_received_ns=completed_ns,
                    raw=raw,
                )
            )

        return frames

    def finish(self) -> int:
        """Mark and discard an incomplete trailing frame; return byte count."""

        trailing = len(self.buffer)
        if trailing:
            self.invalid_frames += 1
            self.discarded_bytes += trailing
            self.buffer.clear()
        return trailing


def percentile(values: Sequence[float], probability: float) -> float:
    """Linear-interpolated percentile for probability in the range 0..1."""

    if not values:
        return math.nan
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(1.0, probability)) * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def numeric_summary(values: Iterable[float]) -> Dict[str, Union[float, int]]:
    data = [float(value) for value in values]
    if not data:
        return {
            "count": 0,
            "min": math.nan,
            "max": math.nan,
            "mean": math.nan,
            "median": math.nan,
            "stdev": math.nan,
            "p5": math.nan,
            "p95": math.nan,
        }
    return {
        "count": len(data),
        "min": min(data),
        "max": max(data),
        "mean": statistics.fmean(data),
        "median": statistics.median(data),
        "stdev": statistics.stdev(data) if len(data) > 1 else 0.0,
        "p5": percentile(data, 0.05),
        "p95": percentile(data, 0.95),
    }


def median_absolute_deviation(values: Iterable[float]) -> float:
    data = [float(value) for value in values]
    if not data:
        return math.nan
    center = statistics.median(data)
    return statistics.median(abs(value - center) for value in data)
