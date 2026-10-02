"""Continuous ghosting capture and immediate terminal key handling."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import struct
import sys
import time
from typing import Any, Callable, Optional, Sequence

import numpy as np

try:
    from .benchmark_common import BinaryFrame, BinaryFrameParser, uint32_delta
    from .ghosting_analysis import Calibration, calibrate
except ImportError:
    from benchmark_common import BinaryFrame, BinaryFrameParser, uint32_delta
    from ghosting_analysis import Calibration, calibrate


class GhostingCaptureError(RuntimeError):
    pass


class ConsoleKeys:
    """Read a single key without Enter; restore POSIX terminal state on exit."""

    def __enter__(self) -> "ConsoleKeys":
        if not sys.stdin.isatty():
            raise GhostingCaptureError("Ghosting acquisition requires an interactive terminal")
        self.saved = None
        if os.name == "nt":
            import msvcrt
            self.windows = msvcrt
        else:
            import termios
            import tty
            self.saved = termios.tcgetattr(sys.stdin.fileno())
            tty.setcbreak(sys.stdin.fileno())
        try:
            self.clear()
        except BaseException:
            self.__exit__()
            raise
        return self

    def poll(self) -> Optional[str]:
        if os.name == "nt":
            if not self.windows.kbhit():
                return None
            value = self.windows.getwch()
            if value in ("\x00", "\xe0"):
                if self.windows.kbhit():
                    self.windows.getwch()
                return ""
        else:
            import select
            if not select.select([sys.stdin], [], [], 0)[0]:
                return None
            value = os.read(sys.stdin.fileno(), 1).decode("utf-8", errors="replace")
        if value == "\x03":
            raise KeyboardInterrupt
        return value

    def clear(self) -> None:
        while self.poll() is not None:
            pass

    def __exit__(self, *_: Any) -> None:
        if self.saved is not None:
            import termios
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self.saved)


@dataclass
class GhostingCapture:
    warmup: list[BinaryFrame] = field(default_factory=list)
    baseline: list[BinaryFrame] = field(default_factory=list)
    window: list[BinaryFrame] = field(default_factory=list)
    calibration: dict[str, Calibration] = field(default_factory=dict)
    status: str = "INCOMPLETE"
    trigger_threshold: float = 0
    trigger_start_us: Optional[int] = None
    invalid_frames: int = 0
    resync_events: int = 0
    discarded_bytes: int = 0
    notes: str = ""


def stop_stream(protocol: Any, parser: BinaryFrameParser, timeout_s: float = 5) -> None:
    """Drain framed traffic before accepting a text ACK at a frame boundary.

    The parser's incomplete tail is transferred here. Never search for #OK
    inside a sample payload, which may itself contain those bytes.
    """
    protocol.log.write("> stop* (draining binary frames)")
    protocol.serial.write(b"stop*")
    protocol.serial.flush()
    pending = bytearray(parser.buffer)
    parser.buffer.clear()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        while pending:
            if pending.startswith(b"\xaa\x55"):
                if len(pending) < 4:
                    break
                count = struct.unpack_from("<H", pending, 2)[0]
                if count > parser.max_sample_count:
                    raise GhostingCaptureError("Invalid frame length while stopping stream")
                length = 14 + 2 * count
                if len(pending) < length:
                    break
                del pending[:length]
            elif pending[0] == 0xAA and len(pending) == 1:
                break
            elif pending.startswith(b"#"):
                if b"\n" not in pending:
                    break
                line, _, remaining = pending.partition(b"\n")
                pending = bytearray(remaining)
                decoded = line.rstrip(b"\r").decode("ascii", errors="replace")
                protocol.log.write(f"< {decoded}")
                if decoded == "#OK" or decoded.startswith("#OK "):
                    if pending:
                        raise GhostingCaptureError("Unexpected bytes after stop acknowledgment")
                    return
                if decoded.startswith("#NOT_OK"):
                    raise GhostingCaptureError(f"Stop rejected: {decoded}")
            else:
                raise GhostingCaptureError("Lost frame boundary while stopping stream")
        waiting = int(getattr(protocol.serial, "in_waiting", 0))
        pending.extend(protocol.serial.read(min(waiting, 65536) or 1))
    raise GhostingCaptureError("Timed out draining binary stream and waiting for stop ACK")


def capture_ghosting_attempt(
    protocol: Any, routes: Sequence[str], source: str, args: Any,
    keys: Any, result: GhostingCapture,
    notify: Callable[[str], None] = print,
) -> GhostingCapture:
    parser = BinaryFrameParser(expected_sample_count=len(routes))
    state = "warmup"
    first_start = baseline_start = previous_start = None
    source_index = routes.index(source)
    started = last_data = time.monotonic()
    calibration_deadline = started + (args.warm_up_ms + args.ghost_baseline_ms + args.grace_ms) / 1000
    window_deadline = None
    candidate_frames: list[BinaryFrame] = []
    candidate_direction = 0
    protocol.log.write("> run* (continuous ghosting capture)")
    protocol.serial.write(b"run*")
    protocol.serial.flush()
    primary_error = None
    try:
        while True:
            if state == "waiting":
                key = keys.poll()
                if key == " ":
                    result.status = "SKIPPED"
                    return result
                if key and key.lower() == "q":
                    result.status = "QUIT"
                    return result
            waiting = int(getattr(protocol.serial, "in_waiting", 0))
            data = protocol.serial.read(min(waiting, 65536) or 1)
            now = time.monotonic()
            if data:
                last_data = now
            elif now - last_data > (args.grace_ms if first_start is None else args.idle_ms) / 1000:
                raise GhostingCaptureError("ADC stream stopped or disconnected")
            if state in ("warmup", "baseline") and now > calibration_deadline:
                raise GhostingCaptureError("Device timestamps did not complete baseline calibration")
            if window_deadline is not None and now > window_deadline:
                raise GhostingCaptureError("Device timestamps did not complete the signal window")
            frames = parser.feed(data)
            if parser.invalid_frames or parser.discarded_bytes:
                raise GhostingCaptureError("Malformed frames or lost bytes in ghosting capture")
            for frame in frames:
                if any(sample > 4095 for sample in frame.samples):
                    raise GhostingCaptureError("ADC sample outside 0..4095")
                if previous_start is not None:
                    period = uint32_delta(frame.block_start_us, previous_start)
                    if period == 0 or period >= 0x80000000:
                        raise GhostingCaptureError("Device timestamps moved backwards or repeated")
                previous_start = frame.block_start_us
                if first_start is None:
                    first_start = frame.block_start_us
                if state == "warmup":
                    if uint32_delta(frame.block_start_us, first_start) < args.warm_up_ms * 1000:
                        if not getattr(args, "no_raw", False):
                            result.warmup.append(frame)
                        continue
                    state = "baseline"
                    baseline_start = frame.block_start_us
                if state == "baseline":
                    if uint32_delta(frame.block_start_us, baseline_start) < args.ghost_baseline_ms * 1000:
                        result.baseline.append(frame)
                        continue
                    result.calibration = calibrate(np.array([f.samples for f in result.baseline]), routes)
                    calibration = result.calibration[source]
                    if calibration.baseline in (0, 4095):
                        raise GhostingCaptureError("Source baseline is at an ADC rail; release or repair the sensor")
                    result.trigger_threshold = max(args.ghost_trigger_counts,
                                                   args.ghost_trigger_sigma * calibration.noise_sigma)
                    state = "waiting"
                    keys.clear()
                    adc, channel = source.split(":")
                    notify(f"Press ADC{adc}_CH{channel}; Space skips, Q quits. "
                           f"Trigger > {result.trigger_threshold:.2f} counts from "
                           f"baseline {calibration.baseline:.2f}; "
                           f"{args.ghost_trigger_samples} consecutive samples required.")
                if state == "waiting":
                    delta = frame.samples[source_index] - result.calibration[source].baseline
                    if abs(delta) <= result.trigger_threshold:
                        candidate_frames.clear()
                        candidate_direction = 0
                        continue
                    direction = 1 if delta > 0 else -1
                    if direction != candidate_direction:
                        candidate_frames.clear()
                        candidate_direction = direction
                    candidate_frames.append(frame)
                    if len(candidate_frames) < args.ghost_trigger_samples:
                        continue
                    result.trigger_start_us = candidate_frames[0].block_start_us
                    elapsed_s = uint32_delta(frame.block_start_us, result.trigger_start_us) / 1_000_000
                    if elapsed_s >= 2:
                        raise GhostingCaptureError("Trigger confirmation exceeds the two-second window; reduce --ghost-trigger-samples")
                    result.window.extend(candidate_frames[:-1])
                    candidate_frames.clear()
                    window_deadline = now + 2 - elapsed_s + args.grace_ms / 1000
                    state = "window"
                    notify("Triggered; capturing two seconds...")
                if state == "window":
                    if uint32_delta(frame.block_start_us, result.trigger_start_us) >= 2_000_000:
                        if len(result.window) < 2:
                            raise GhostingCaptureError("Too few complete sweeps in signal window")
                        result.status = "COMPLETE"
                        return result
                    result.window.append(frame)
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        result.invalid_frames = parser.invalid_frames
        result.resync_events = parser.resync_events
        result.discarded_bytes = parser.discarded_bytes
        try:
            stop_stream(protocol, parser)
        except Exception as exc:
            if primary_error is None:
                raise
            result.notes = f"Stop cleanup failed: {exc}"
            protocol.log.write(result.notes)
