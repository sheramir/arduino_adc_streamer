#!/usr/bin/env python3
"""Benchmark this Teensy 4.1 + four-ADS7953 TestBoard firmware.

The runner owns the serial port, configures firmware modes without reflashing,
captures the binary stream, writes interpreted samples, and produces matched
timing comparisons. Use --list-tests and --dry-run before connecting hardware.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import time
from typing import Any, Iterable, Optional, Sequence

try:
    from .firmware_profile import save_profile
    from .benchmark_common import (
        BinaryFrame,
        BinaryFrameParser,
        median_absolute_deviation,
        numeric_summary,
        percentile,
        uint32_delta,
        stream_integrity_counts,
    )
    from .excel_report import write_benchmark_workbook, write_ghosting_workbook
    from .ghosting_analysis import analyze_window, chart_bounds, chart_indices, summarize_attempts, strongest_attempt
    from .ghosting_capture import ConsoleKeys, GhostingCapture, GhostingCaptureError, capture_ghosting_attempt
except ImportError:  # Direct execution from this directory.
    from firmware_profile import save_profile
    from benchmark_common import (  # type: ignore
        BinaryFrame,
        BinaryFrameParser,
        median_absolute_deviation,
        numeric_summary,
        percentile,
        uint32_delta,
        stream_integrity_counts,
    )
    from excel_report import write_benchmark_workbook, write_ghosting_workbook  # type: ignore
    from ghosting_analysis import analyze_window, chart_bounds, chart_indices, summarize_attempts, strongest_attempt
    from ghosting_capture import ConsoleKeys, GhostingCapture, GhostingCaptureError, capture_ghosting_attempt


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_ROUTES_PATH = SCRIPT_DIR / "testboard_7953_routes.json"
DEFAULT_BIAS_MAP_PATH = SCRIPT_DIR / "testboard_7953_bias_resistors.json"
DEFAULT_RESULTS_ROOT = SCRIPT_DIR / "results"
GLOSSARY_PATH = SCRIPT_DIR / "OUTPUT_GLOSSARY.md"
FIRMWARE_IDENTITY = "# TestBoard_7953"
RUNNER_VERSION = "2.5"
DEFAULT_SPI_CLOCK_HZ = 20_000_000
MIN_SPI_CLOCK_HZ = 100_000
MAX_SPI_CLOCK_HZ = 30_000_000
ERROR_COUNTERS = (
    "dma_start_errors",
    "lpspi_start_errors",
    "transfer_timeouts",
    "returned_channel_errors",
    "usb_write_errors",
)
LIVE_TRANSPORT_FIELDS = (
    "sampling_sweeps", "usb_frames_sent", "usb_frames_discarded",
    "sampling_period_max_us", "sampling_period_over_1ms",
)


class BenchmarkError(RuntimeError):
    """A recoverable or terminal benchmark protocol failure."""


@dataclass(frozen=True, order=True)
class Route:
    adc: int
    channel: int

    @classmethod
    def parse(cls, text: str) -> "Route":
        try:
            adc_text, channel_text = text.split(":", 1)
            route = cls(int(adc_text), int(channel_text))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid route {text!r}; expected ADC:channel") from exc
        if route.adc not in (1, 2, 3, 4):
            raise ValueError(f"ADC must be 1..4: {text!r}")
        if not 0 <= route.channel <= 14:
            raise ValueError(f"Channel must be 0..14; channel 15 is Vmid: {text!r}")
        return route

    def __str__(self) -> str:
        return f"{self.adc}:{self.channel}"


@dataclass(frozen=True)
class RouteSet:
    name: str
    array: str
    routes: tuple[Route, ...]
    non_vmid_routes: frozenset[Route]
    description: str = ""


@dataclass(frozen=True)
class TestConfig:
    route_set: str
    array: str
    scanorder: str
    adcseq: str
    spiengine: str
    channelrepeat: int
    vmid: bool
    spi_clock_hz: int = DEFAULT_SPI_CLOCK_HZ

    @property
    def test_id(self) -> str:
        vmid_name = "on" if self.vmid else "off"
        return (
            f"{self.route_set}__{self.scanorder}__{self.adcseq}__"
            f"{self.spiengine}__repeat{self.channelrepeat}__vmid{vmid_name}__"
            f"spi{self.spi_clock_hz}hz"
        )

    @property
    def comparison_key(self) -> tuple[Any, ...]:
        return (
            self.route_set,
            self.array,
            self.scanorder,
            self.adcseq,
            self.channelrepeat,
            self.vmid,
            self.spi_clock_hz,
        )


@dataclass(frozen=True)
class ScheduledTest:
    config: TestConfig
    test_id: str
    repetitions: int
    drift_phase: str = ""


@dataclass
class CaptureResult:
    frames: list[BinaryFrame]
    raw: bytes
    invalid_frames: int
    resync_events: int
    discarded_bytes: int
    trailing_bytes: int
    wall_duration_ns: int
    timed_out: bool
    stream_integrity: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelReference:
    median: float
    mad: float
    stdev: float
    test_id: str


SAMPLE_FIELDS = [
    "session_id", "test_id", "repetition", "attempt", "drift_phase",
    "frame_index", "host_received_ns", "block_start_us", "block_end_us",
    "acquisition_duration_us", "avg_dt_us", "sample_count",
    "payload_index", "array", "adc", "channel", "sample_raw",
    "offset_from_vmid", "route_warning",
]

WARMUP_SAMPLE_FIELDS = [
    "session_id", "test_id", "repetition", "attempt", "route_set",
    "array", "scanorder", "adcseq", "spiengine", "spi_clock_hz",
    "channelrepeat_requested", "vmid_requested", "adc", "channel",
    "bias_resistor_ohms", "warmup_frame_index", "elapsed_us",
    "block_start_us", "acquisition_duration_us", "sample_raw",
    "post_warmup_median_raw", "delta_from_post_warmup_median",
    "settling_frame_index", "settling_time_us",
]

CHANNEL_STAT_FIELDS = [
    "session_id", "test_id", "repetition", "attempt", "drift_phase",
    "route_set", "array", "scanorder", "adcseq", "spiengine",
    "spi_clock_hz", "channelrepeat_requested", "channelrepeat_effective",
    "vmid_requested", "vmid_effective", "adc", "channel", "sample_count",
    "sample_min_raw", "sample_mean_raw", "sample_median_raw",
    "sample_max_raw", "sample_stdev_raw", "sample_mad_raw",
    "sample_p1_raw", "sample_p5_raw", "sample_p95_raw", "sample_p99_raw",
    "startup_min_raw", "settling_frame_index", "settling_time_us",
    "settling_tolerance_counts", "settling_stable_frames",
    "settled_before_measurement",
    "median_offset_from_vmid", "route_warning",
]

RESULT_FIELDS = [
    "session_id", "test_id", "result_scope", "repetition", "attempt",
    "drift_phase", "route_set", "array", "route_list", "scanorder",
    "adcseq", "spiengine", "spi_clock_hz", "channelrepeat_requested",
    "channelrepeat_effective", "vmid_requested", "vmid_effective", "ref",
    "warm_up_ms", "window_ms", "captured_frames_total",
    "warmup_frames_discarded", "valid_frames", "invalid_frames", "resync_events",
    "discarded_bytes", "trailing_bytes", "capture_timed_out",
    "timestamp_regressions", "duplicate_frames", "invalid_timing_frames",
    "suspected_missing_frames",
    "usb_stream_policy", *LIVE_TRANSPORT_FIELDS,
    "total_samples", "startup_min_raw", "sample_min_raw", "sample_p1_raw",
    "sample_p5_raw", "sample_mean_raw", "sample_median_raw",
    "sample_p95_raw", "sample_p99_raw", "sample_max_raw", "sample_stdev_raw",
    "duration_min_us", "duration_mean_us",
    "duration_median_us", "duration_p5_us", "duration_p95_us",
    "duration_max_us", "duration_stdev_us",
    "payload_throughput_sps", "sweep_rate_hz",
    "block_period_median_us", "inter_block_gap_median_us",
    "host_arrival_period_median_us", "speedup_vs_blocking",
    "throughput_gain_pct", "dma_start_errors", "lpspi_start_errors",
    "transfer_timeouts", "returned_channel_errors", "vmid_warning_count",
    "usb_write_errors",
    "vmid_severe_count", "unstable_channel_count",
    "cross_mode_shift_count", "drift_warning_count",
    "settling_warning_count", "settling_max_frames", "settling_max_us",
    "settling_tolerance_counts", "settling_stable_frames",
    "timing_drift_pct",
    "drift_timing_tolerance_pct", "data_integrity_status", "overall_status",
    "vmid_nominal_code", "vmid_warning_tolerance",
    "vmid_severe_tolerance", "cross_mode_floor_counts",
    "cross_mode_mad_multiplier", "baseline_test_ids", "notes",
]


def load_route_manifest(path: Path) -> dict[str, RouteSet]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload:
        raise ValueError("Route manifest must be a non-empty JSON object")
    route_sets: dict[str, RouteSet] = {}
    for name, raw in payload.items():
        array = str(raw.get("array", "")).lower()
        if array not in ("1", "2", "both"):
            raise ValueError(f"{name}: array must be 1, 2, or both")
        routes = tuple(Route.parse(item) for item in raw.get("routes", []))
        if not routes or len(set(routes)) != len(routes):
            raise ValueError(f"{name}: routes must be non-empty and unique")
        allowed_adcs = {1, 2} if array == "1" else {3, 4} if array == "2" else {1, 2, 3, 4}
        if any(route.adc not in allowed_adcs for route in routes):
            raise ValueError(f"{name}: route does not belong to array {array}")
        non_vmid = frozenset(Route.parse(item) for item in raw.get("non_vmid_routes", []))
        if not non_vmid.issubset(set(routes)):
            raise ValueError(f"{name}: non_vmid_routes must be in routes")
        route_sets[name] = RouteSet(
            name=name,
            array=array,
            routes=routes,
            non_vmid_routes=non_vmid,
            description=str(raw.get("description", "")),
        )
    return route_sets


def load_bias_resistors(path: Path) -> dict[Route, float]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Bias-resistor map must be a JSON object")
    output: dict[Route, float] = {}
    for route_text, resistance in payload.items():
        route = Route.parse(route_text)
        value = float(resistance)
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"Bias resistance for {route} must be positive")
        output[route] = value
    return output


def payload_order(routes: Sequence[Route], scanorder: str) -> tuple[Route, ...]:
    """Mirror the firmware's canonical payload ordering."""

    if scanorder not in ("interleaved", "array", "adc"):
        raise ValueError(f"Unknown scanorder {scanorder!r}")

    if scanorder == "adc":
        return tuple(route for adc in range(1, 5) for route in routes if route.adc == adc)

    groups = ((1, 2), (3, 4)) if scanorder == "array" else ((1, 2, 3, 4),)
    ordered: list[Route] = []
    for group in groups:
        lanes = {adc: [route for route in routes if route.adc == adc] for adc in group}
        max_depth = max((len(lane) for lane in lanes.values()), default=0)
        for depth in range(max_depth):
            for adc in group:
                if depth < len(lanes[adc]):
                    ordered.append(lanes[adc][depth])
    if len(ordered) != len(routes):
        raise ValueError("Payload ordering lost one or more routes")
    return tuple(ordered)


def build_test_matrix(
    route_sets: dict[str, RouteSet],
    seed: int = 7953,
    spi_clocks: Sequence[int] = (DEFAULT_SPI_CLOCK_HZ,),
) -> list[TestConfig]:
    required = {
        "one_adc_bus1", "one_adc_bus2", "full_array1", "full_array2",
        "one_adc_each_bus", "all_four_full", "all_four_sparse_unbalanced",
    }
    missing = required.difference(route_sets)
    if missing:
        raise ValueError(f"Route manifest is missing: {', '.join(sorted(missing))}")

    configs: dict[tuple[Any, ...], TestConfig] = {}

    def add(route_name: str, scanorder: str, adcseq: str, engine: str,
            repeat: int, vmid: bool) -> None:
        # Auto mode always samples each channel once and never inserts Vmid
        # samples between channels. Do not schedule requested settings that
        # collapse to the same effective firmware configuration.
        if adcseq == "auto1":
            repeat = 1
            vmid = False
        route_set = route_sets[route_name]
        config = TestConfig(
            route_set=route_name,
            array=route_set.array,
            scanorder=scanorder,
            adcseq=adcseq,
            spiengine=engine,
            channelrepeat=repeat,
            vmid=vmid,
        )
        configs[config.comparison_key + (engine,)] = config

    engines = ("blocking", "dma", "lpspi")

    # Main 50-route engine/modifier comparison.
    for engine in engines:
        for repeat in (1, 2, 3):
            for vmid in (False, True):
                add("all_four_full", "interleaved", "manual", engine, repeat, vmid)
        add("all_four_full", "interleaved", "auto1", engine, 1, False)

    # Topology coverage for both acquisition modes.
    for route_name in route_sets:
        for engine in engines:
            add(route_name, "interleaved", "manual", engine, 1, False)
            add(route_name, "interleaved", "auto1", engine, 1, False)

    # Explicit same-bus and all-bus parking comparison.
    for route_name in ("full_array1", "full_array2", "all_four_full"):
        for engine in engines:
            for vmid in (False, True):
                add(route_name, "interleaved", "manual", engine, 1, vmid)

    # Payload-order equivalence.
    for scanorder in ("interleaved", "array", "adc"):
        for engine in engines:
            add("all_four_full", scanorder, "manual", engine, 1, False)

    base_configs = list(configs.values())
    expanded = [
        TestConfig(
            route_set=config.route_set,
            array=config.array,
            scanorder=config.scanorder,
            adcseq=config.adcseq,
            spiengine=config.spiengine,
            channelrepeat=config.channelrepeat,
            vmid=config.vmid,
            spi_clock_hz=clock_hz,
        )
        for clock_hz in spi_clocks
        for config in base_configs
    ]
    baseline = [
        config for config in expanded
        if config.spiengine == "blocking" and config.adcseq == "manual"
        and config.channelrepeat == 1 and not config.vmid
        and config.scanorder == "interleaved"
    ]
    baseline.sort(key=lambda item: item.route_set)
    baseline_ids = {item.test_id for item in baseline}
    remainder = [item for item in expanded if item.test_id not in baseline_ids]
    random.Random(seed).shuffle(remainder)
    return baseline + remainder


def build_complete_matrix(
    route_sets: dict[str, RouteSet],
    route_names: Sequence[str],
    scan_orders: Sequence[str],
    seed: int = 7953,
    spi_clocks: Sequence[int] = (DEFAULT_SPI_CLOCK_HZ,),
) -> list[TestConfig]:
    """Build every engine/manual modifier plus Auto1 for selected topology/order."""
    unknown_routes = set(route_names).difference(route_sets)
    if unknown_routes:
        raise ValueError(
            f"Unknown route set(s): {', '.join(sorted(unknown_routes))}"
        )
    unknown_orders = set(scan_orders).difference(("interleaved", "array", "adc"))
    if unknown_orders:
        raise ValueError(
            f"Unknown scan order(s): {', '.join(sorted(unknown_orders))}"
        )

    configs: list[TestConfig] = []
    for clock_hz in spi_clocks:
        for route_name in route_names:
            route_set = route_sets[route_name]
            for scan_order in scan_orders:
                for engine in ("blocking", "dma", "lpspi"):
                    for repeat in (1, 2, 3):
                        for vmid in (False, True):
                            configs.append(TestConfig(
                                route_name, route_set.array, scan_order,
                                "manual", engine, repeat, vmid, clock_hz,
                            ))
                    configs.append(TestConfig(
                        route_name, route_set.array, scan_order,
                        "auto1", engine, 1, False, clock_hz,
                    ))
    random.Random(seed).shuffle(configs)
    return configs


def smoke_configs(
    route_sets: dict[str, RouteSet], spi_clock_hz: int
) -> tuple[TestConfig, TestConfig]:
    return tuple(
        TestConfig(
            name, route_sets[name].array, "interleaved", "manual",
            "blocking", 1, False, spi_clock_hz,
        )
        for name in ("one_adc_bus1", "all_four_full")
    )  # type: ignore[return-value]


def parse_status(lines: Sequence[str]) -> dict[str, str]:
    status: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped[1:].split("=", 1)
        status[key.strip()] = value.strip()
    return status


def counter_value(status: dict[str, str], key: str) -> int:
    try:
        return int(status.get(key, "0"))
    except ValueError:
        return 0


def counter_deltas(before: dict[str, str], after: dict[str, str]) -> dict[str, int]:
    return {
        key: counter_value(after, key) - counter_value(before, key)
        for key in ERROR_COUNTERS
    }


class SessionLog:
    def __init__(self, path: Path) -> None:
        self._file = path.open("a", encoding="utf-8", newline="\n")

    def write(self, message: str) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        self._file.write(f"{timestamp} {message}\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


class SerialProtocol:
    def __init__(self, serial_port: Any, session_log: SessionLog) -> None:
        self.serial = serial_port
        self.log = session_log

    def drain_until_idle(self, idle_s: float = 0.15, limit_s: float = 2.0) -> bytes:
        collected = bytearray()
        deadline = time.monotonic() + limit_s
        idle_deadline = time.monotonic() + idle_s
        while time.monotonic() < deadline:
            waiting = int(getattr(self.serial, "in_waiting", 0))
            data = self.serial.read(waiting or 1)
            if data:
                collected.extend(data)
                idle_deadline = time.monotonic() + idle_s
            elif time.monotonic() >= idle_deadline:
                break
        if collected:
            self.log.write(f"DRAIN {len(collected)} stale bytes")
        return bytes(collected)

    def send_command(self, command: str, timeout_s: float = 3.0) -> list[str]:
        wire = command if command.endswith("*") else f"{command}*"
        self.log.write(f"> {wire}")
        self.serial.write(wire.encode("ascii"))
        self.serial.flush()
        deadline = time.monotonic() + timeout_s
        pending = bytearray()
        lines: list[str] = []
        while time.monotonic() < deadline:
            waiting = int(getattr(self.serial, "in_waiting", 0))
            data = self.serial.read(waiting or 1)
            if not data:
                continue
            pending.extend(data)
            while b"\n" in pending:
                raw_line, _, remainder = pending.partition(b"\n")
                pending = bytearray(remainder)
                line = raw_line.rstrip(b"\r").decode("ascii", errors="replace")
                if not line:
                    continue
                self.log.write(f"< {line}")
                lines.append(line)
                if line.startswith("#NOT_OK"):
                    raise BenchmarkError(f"Command {wire!r} failed: {line}")
                if line.startswith("#OK"):
                    return lines
        preview = bytes(pending[:80]).decode("ascii", errors="replace")
        raise BenchmarkError(f"Timed out waiting for ACK to {wire!r}; pending={preview!r}")

    def send_run(self, duration_ms: int) -> None:
        wire = f"run {duration_ms}*"
        self.log.write(f"> {wire} (binary response)")
        self.serial.write(wire.encode("ascii"))
        self.serial.flush()

    def capture_timed(self, duration_ms: int, expected_samples: int,
                      grace_ms: int, idle_ms: int, *, reader_pause_ms: int = 0,
                      reader_pause_at_ms: int = 2000,
                      defer_parsing: bool = False) -> CaptureResult:
        parser = BinaryFrameParser(expected_sample_count=expected_samples)
        raw = bytearray()
        frames: list[BinaryFrame] = []
        started_ns = time.monotonic_ns()
        minimum_end_ns = started_ns + duration_ms * 1_000_000
        deadline_ns = minimum_end_ns + grace_ms * 1_000_000
        idle_ns = idle_ms * 1_000_000
        last_data_ns = started_ns
        paused = False
        chunks: list[tuple[bytes, int]] = []

        self.send_run(duration_ms)
        timed_out = True
        while time.monotonic_ns() < deadline_ns:
            if (reader_pause_ms and not paused and
                    time.monotonic_ns() >= started_ns + reader_pause_at_ms * 1_000_000):
                self.log.write(f"READER_PAUSE {reader_pause_ms} ms (Windows may buffer data)")
                time.sleep(reader_pause_ms / 1000)
                paused = True
            waiting = int(getattr(self.serial, "in_waiting", 0))
            data = self.serial.read(waiting or 1)
            now_ns = time.monotonic_ns()
            if data:
                raw.extend(data)
                last_data_ns = now_ns
                if defer_parsing:
                    chunks.append((data, now_ns))
                else:
                    frames.extend(parser.feed(data, now_ns))
            elif now_ns >= minimum_end_ns and now_ns - last_data_ns >= idle_ns:
                timed_out = False
                break

        capture_finished_ns = time.monotonic_ns()
        if defer_parsing:
            for data, received_ns in chunks:
                frames.extend(parser.feed(data, received_ns))
        trailing = parser.finish()
        integrity = stream_integrity_counts(frames)
        wall_ns = capture_finished_ns - started_ns
        self.log.write(
            "CAPTURE "
            f"duration_ms={duration_ms} frames={len(frames)} raw={len(raw)} "
            f"invalid={parser.invalid_frames} resync={parser.resync_events} "
            f"trailing={trailing} integrity={integrity}"
        )
        return CaptureResult(
            frames=frames,
            raw=bytes(raw),
            invalid_frames=parser.invalid_frames,
            resync_events=parser.resync_events,
            discarded_bytes=parser.discarded_bytes,
            trailing_bytes=trailing,
            wall_duration_ns=wall_ns,
            timed_out=timed_out,
            stream_integrity=integrity,
        )


def validate_status(status: dict[str, str], config: TestConfig,
                    route_set: RouteSet) -> None:
    expected_repeat = "1" if config.adcseq == "auto1" else str(config.channelrepeat)
    expected_vmid_effective = "true" if config.adcseq == "manual" and config.vmid else "false"
    expected_adcs = ",".join(str(value) for value in sorted({route.adc for route in route_set.routes}))
    expected_buses_values = []
    if any(route.adc <= 2 for route in route_set.routes):
        expected_buses_values.append("1")
    if any(route.adc >= 3 for route in route_set.routes):
        expected_buses_values.append("2")
    expected = {
        "adcchannels": ",".join(str(route) for route in route_set.routes),
        "array": config.array,
        "scanorder": config.scanorder,
        "adcseq": config.adcseq,
        "spiengine": config.spiengine,
        "spi_clock_hz": str(config.spi_clock_hz),
        "channelrepeat_requested": str(config.channelrepeat),
        "channelrepeat_effective": expected_repeat,
        "vmid_between_channels_requested": "true" if config.vmid else "false",
        "vmid_between_channels_effective": expected_vmid_effective,
        "vmid_channel": "15",
        "vmid_parking": "mandatory",
        "route_count": str(len(route_set.routes)),
        "vref": "2.5",
        "active_adcs": expected_adcs,
        "active_spi_buses": ",".join(expected_buses_values),
    }
    mismatches = [
        f"{key}: expected {value!r}, got {status.get(key)!r}"
        for key, value in expected.items() if status.get(key) != value
    ]
    if mismatches:
        raise BenchmarkError("Status mismatch: " + "; ".join(mismatches))


def configure_test(protocol: SerialProtocol, config: TestConfig,
                   route_set: RouteSet) -> dict[str, str]:
    protocol.send_command("stop")
    commands = (
        f"array {config.array}",
        f"scanorder {config.scanorder}",
        "adcchannels " + ",".join(str(route) for route in route_set.routes),
        "ref 2.5",
        f"adcseq {config.adcseq}",
        f"spiengine {config.spiengine}",
        f"spiclock {config.spi_clock_hz}",
        f"channelrepeat {config.channelrepeat}",
        f"vmid {'true' if config.vmid else 'false'}",
    )
    for command in commands:
        protocol.send_command(command)
    lines = protocol.send_command("status")
    status = parse_status(lines)
    validate_status(status, config, route_set)
    return status


def stop_after_capture(protocol: SerialProtocol) -> dict[str, str]:
    protocol.send_command("stop", timeout_s=5.0)
    return parse_status(protocol.send_command("status"))


def configure_profile(protocol: SerialProtocol, initial_status: dict[str, str],
                      requested: str) -> dict[str, str]:
    if initial_status.get("profile_available") != "true":
        if requested == "on":
            raise BenchmarkError("Profiling requires a teensy41_profile firmware build")
        return initial_status
    protocol.send_command(f"profile {requested}")
    status = parse_status(protocol.send_command("status"))
    if status.get("profile_enabled") != ("true" if requested == "on" else "false"):
        raise BenchmarkError("Firmware did not accept the requested profiling mode")
    return status


def measured_capture_after_warmup(
    capture: CaptureResult, warm_up_ms: int
) -> tuple[CaptureResult, int]:
    """Return frames beginning after a continuous device-time warm-up."""

    if not capture.frames:
        return capture, 0
    first_start = capture.frames[0].block_start_us
    cutoff_us = warm_up_ms * 1000
    discarded = 0
    for frame in capture.frames:
        if uint32_delta(frame.block_start_us, first_start) >= cutoff_us:
            break
        discarded += 1
    measured = CaptureResult(
        frames=capture.frames[discarded:],
        raw=capture.raw,
        invalid_frames=capture.invalid_frames,
        resync_events=capture.resync_events,
        discarded_bytes=capture.discarded_bytes,
        trailing_bytes=capture.trailing_bytes,
        wall_duration_ns=capture.wall_duration_ns,
        timed_out=capture.timed_out,
        stream_integrity=capture.stream_integrity or stream_integrity_counts(capture.frames),
    )
    return measured, discarded


def frame_metrics(capture: CaptureResult) -> dict[str, Any]:
    frames = capture.frames
    durations = [frame.acquisition_duration_us for frame in frames]
    duration_summary = numeric_summary(durations)
    throughputs = [
        frame.sample_count * 1_000_000.0 / frame.acquisition_duration_us
        for frame in frames if frame.acquisition_duration_us > 0
    ]
    block_periods = [
        uint32_delta(current.block_start_us, previous.block_start_us)
        for previous, current in zip(frames, frames[1:])
    ]
    gaps = [
        uint32_delta(current.block_start_us, previous.block_end_us)
        for previous, current in zip(frames, frames[1:])
    ]
    host_periods = [
        (current.host_received_ns - previous.host_received_ns) / 1000.0
        for previous, current in zip(frames, frames[1:])
    ]
    period_median = statistics.median(block_periods) if block_periods else math.nan
    suspected_missing = 0
    if block_periods and period_median > 0:
        for period in block_periods:
            if period > 1.75 * period_median:
                suspected_missing += max(0, round(period / period_median) - 1)
    sweep_rate = 1_000_000.0 / period_median if period_median and not math.isnan(period_median) else math.nan
    return {
        "duration": duration_summary,
        "payload_throughput_sps": statistics.median(throughputs) if throughputs else math.nan,
        "sweep_rate_hz": sweep_rate,
        "block_period_median_us": statistics.median(block_periods) if block_periods else math.nan,
        "inter_block_gap_median_us": statistics.median(gaps) if gaps else math.nan,
        "host_arrival_period_median_us": statistics.median(host_periods) if host_periods else math.nan,
        "suspected_missing_frames": suspected_missing,
    }


def analyze_channels(
    capture: CaptureResult,
    ordered_routes: Sequence[Route],
    route_set: RouteSet,
    baselines: dict[tuple[Route, int], ChannelReference],
    *,
    test_id: str,
    vmid_nominal: int,
    warning_tolerance: int,
    severe_tolerance: int,
    cross_mode_floor: int,
    cross_mode_mad_multiplier: float,
    noise_floor: int,
    noise_mad_multiplier: float,
    spi_clock_hz: int,
    settling_capture: Optional[CaptureResult] = None,
    warm_up_us: int = 0,
    settling_tolerance_counts: int = 64,
    settling_stable_frames: int = 5,
) -> tuple[dict[Route, dict[str, Any]], dict[str, int], set[str]]:
    values: dict[Route, list[int]] = {route: [] for route in ordered_routes}
    impossible = False
    for frame in capture.frames:
        if len(frame.samples) != len(ordered_routes):
            impossible = True
            continue
        for route, sample in zip(ordered_routes, frame.samples):
            values[route].append(sample)
            if not 0 <= sample <= 4095:
                impossible = True

    channel_stats: dict[Route, dict[str, Any]] = {}
    baseline_ids: set[str] = set()
    counts = {
        "vmid_warning": 0,
        "vmid_severe": 0,
        "unstable": 0,
        "cross_mode": 0,
        "drift": 0,
        "settling": 0,
        "integrity_failure": int(impossible),
    }
    startup_frames = (
        settling_capture.frames if settling_capture is not None else capture.frames
    )
    startup_values: dict[Route, list[int]] = {
        route: [] for route in ordered_routes
    }
    for frame in startup_frames:
        if len(frame.samples) != len(ordered_routes):
            continue
        for route, sample in zip(ordered_routes, frame.samples):
            startup_values[route].append(sample)

    for route, route_values in values.items():
        summary = numeric_summary(route_values)
        median = float(summary["median"])
        mad = median_absolute_deviation(route_values)
        warnings: list[str] = []
        route_startup_values = startup_values[route]
        tolerance = max(
            settling_tolerance_counts,
            int(math.ceil(6.0 * max(float(mad), 1.0))),
        )
        settling_frame_index: Any = ""
        settling_time_us: Any = ""
        stable_frames = max(1, settling_stable_frames)
        if route_startup_values and route_values:
            for index in range(0, len(route_startup_values) - stable_frames + 1):
                window = route_startup_values[index:index + stable_frames]
                if all(abs(value - median) <= tolerance for value in window):
                    settling_frame_index = index
                    settling_time_us = uint32_delta(
                        startup_frames[index].block_start_us,
                        startup_frames[0].block_start_us,
                    )
                    break
        settled_before_measurement = (
            settling_time_us != "" and int(settling_time_us) <= warm_up_us
        )
        if settling_capture is not None and not settled_before_measurement:
            warnings.append("SETTLING_EXCEEDS_WARMUP")
            counts["settling"] += 1
        if route not in route_set.non_vmid_routes and route_values:
            offset = abs(median - vmid_nominal)
            if offset > severe_tolerance:
                warnings.append("VMID_OFFSET_SEVERE")
                counts["vmid_severe"] += 1
            elif offset > warning_tolerance:
                warnings.append("VMID_OFFSET_WARNING")
                counts["vmid_warning"] += 1

        baseline = baselines.get((route, spi_clock_hz))
        if baseline is not None and route_values:
            baseline_ids.add(baseline.test_id)
            if mad > max(noise_floor, noise_mad_multiplier * max(baseline.mad, 1.0)):
                warnings.append("UNSTABLE_CHANNEL")
                counts["unstable"] += 1
            shift_limit = max(
                cross_mode_floor,
                cross_mode_mad_multiplier * max(baseline.mad, mad, 1.0),
            )
            if abs(median - baseline.median) > shift_limit:
                if "__drift_" in test_id:
                    warnings.append("DRIFT_WARNING")
                    counts["drift"] += 1
                else:
                    warnings.append("CROSS_MODE_SHIFT")
                    counts["cross_mode"] += 1

        channel_stats[route] = {
            **summary,
            "mad": mad,
            "p1": percentile(route_values, 0.01),
            "p5": percentile(route_values, 0.05),
            "p95": percentile(route_values, 0.95),
            "p99": percentile(route_values, 0.99),
            "startup_min": min(route_startup_values) if route_startup_values else "",
            "settling_frame_index": settling_frame_index,
            "settling_time_us": settling_time_us,
            "settling_tolerance_counts": tolerance,
            "settling_stable_frames": stable_frames,
            "settled_before_measurement": settled_before_measurement,
            "warnings": warnings,
        }
    return channel_stats, counts, baseline_ids


def is_baseline_config(config: TestConfig) -> bool:
    return (
        config.scanorder == "interleaved"
        and config.adcseq == "manual"
        and config.spiengine == "blocking"
        and config.channelrepeat == 1
        and not config.vmid
    )


def update_baselines(
    baselines: dict[tuple[Route, int], ChannelReference],
    channel_stats: dict[Route, dict[str, Any]],
    test_id: str,
    spi_clock_hz: int,
) -> None:
    for route, stats in channel_stats.items():
        key = (route, spi_clock_hz)
        if int(stats["count"]) == 0 or key in baselines:
            continue
        baselines[key] = ChannelReference(
            median=float(stats["median"]),
            mad=float(stats["mad"]),
            stdev=float(stats["stdev"]),
            test_id=test_id,
        )


def finite_or_blank(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return ""
    return value


class CsvAppender:
    def __init__(self, path: Path, fieldnames: Sequence[str]) -> None:
        self.path = path
        self.fieldnames = list(fieldnames)
        existed = path.exists() and path.stat().st_size > 0
        if existed:
            with path.open("r", encoding="utf-8", newline="") as source:
                existing_fields = next(csv.reader(source), [])
            if existing_fields != self.fieldnames:
                raise BenchmarkError(
                    f"CSV schema differs from runner {RUNNER_VERSION}: {path}. "
                    "Start a new session directory instead of resuming."
                )
        self.file = path.open("a", encoding="utf-8", newline="")
        self.writer = csv.DictWriter(self.file, fieldnames=self.fieldnames, extrasaction="ignore")
        if not existed:
            self.writer.writeheader()
            self.flush()

    def rows(self, rows: Iterable[dict[str, Any]]) -> None:
        for row in rows:
            self.writer.writerow({key: finite_or_blank(row.get(key, "")) for key in self.fieldnames})
        self.flush()

    def flush(self) -> None:
        self.file.flush()
        os.fsync(self.file.fileno())

    def close(self) -> None:
        self.file.close()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def git_revision() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=SCRIPT_DIR.parents[2],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return completed.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def load_existing_results(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def load_baselines_from_csv(
    samples_path: Path,
    result_rows: Sequence[dict[str, str]],
) -> dict[tuple[Route, int], ChannelReference]:
    """Restore blocking/manual references when a session is resumed."""

    baseline_test_clocks = {
        row.get("test_id", ""): int(
            row.get("spi_clock_hz") or DEFAULT_SPI_CLOCK_HZ
        )
        for row in result_rows
        if row.get("result_scope") == "repetition"
        and row.get("overall_status") in ("PASS", "WARN")
        and row.get("scanorder") == "interleaved"
        and row.get("adcseq") == "manual"
        and row.get("spiengine") == "blocking"
        and row.get("channelrepeat_requested") == "1"
        and row.get("vmid_requested", "").lower() == "false"
    }
    if not baseline_test_clocks or not samples_path.exists():
        return {}

    grouped: dict[tuple[str, Route], list[int]] = {}
    with samples_path.open("r", encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            test_id = row.get("test_id", "")
            if test_id not in baseline_test_clocks:
                continue
            try:
                route = Route(int(row["adc"]), int(row["channel"]))
                value = int(row["sample_raw"])
            except (KeyError, TypeError, ValueError):
                continue
            grouped.setdefault((test_id, route), []).append(value)

    baselines: dict[tuple[Route, int], ChannelReference] = {}
    for (test_id, route), values in grouped.items():
        key = (route, baseline_test_clocks[test_id])
        if key in baselines or not values:
            continue
        baselines[key] = ChannelReference(
            median=float(statistics.median(values)),
            mad=median_absolute_deviation(values),
            stdev=statistics.stdev(values) if len(values) > 1 else 0.0,
            test_id=test_id,
        )
    return baselines


def load_warmup_exported_routes(path: Path) -> set[Route]:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    routes: set[Route] = set()
    with path.open("r", encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            try:
                routes.add(Route(int(row["adc"]), int(row["channel"])))
            except (KeyError, TypeError, ValueError):
                continue
    return routes


def completed_repetitions(rows: Sequence[dict[str, str]]) -> set[tuple[str, int]]:
    completed: set[tuple[str, int]] = set()
    for row in rows:
        if row.get("result_scope") != "repetition":
            continue
        if row.get("overall_status") not in ("PASS", "WARN"):
            continue
        try:
            completed.add((row["test_id"], int(row["repetition"])))
        except (KeyError, ValueError):
            continue
    return completed


def result_row_for_capture(
    *,
    session_id: str,
    scheduled: ScheduledTest,
    repetition: int,
    attempt: int,
    route_set: RouteSet,
    capture: CaptureResult,
    before_status: dict[str, str],
    after_status: dict[str, str],
    channel_counts: dict[str, int],
    sample_summary: dict[str, Any],
    settling_summary: dict[str, Any],
    baseline_ids: set[str],
    metrics: dict[str, Any],
    args: argparse.Namespace,
    notes: str = "",
) -> dict[str, Any]:
    config = scheduled.config
    deltas = counter_deltas(before_status, after_status)
    integrity = capture.stream_integrity or stream_integrity_counts(capture.frames)
    duration = metrics["duration"]
    hard_failure = (
        capture.timed_out
        or capture.invalid_frames > 0
        or capture.resync_events > 0
        or capture.discarded_bytes > 0
        or any(integrity.values())
        or capture.trailing_bytes > 0
        or not capture.frames
        or channel_counts["integrity_failure"] > 0
        or any(deltas.values())
    )
    warning = any(
        channel_counts[key] > 0
        for key in (
            "vmid_warning", "vmid_severe", "unstable", "cross_mode", "drift",
            "settling",
        )
    )
    overall = "FAIL" if hard_failure else "WARN" if warning else "PASS"
    if after_status.get("usb_stream_policy") == "discard_if_busy" and int(after_status.get("usb_frames_discarded", "0")):
        notes = (f"{notes}; LIVE_OMISSIONS: {after_status['usb_frames_discarded']} acquired sweeps discarded; "
                 "received gaps are not proof of sensor pauses").lstrip("; ")
    if any(integrity.values()) or capture.discarded_bytes or capture.resync_events:
        notes = f"{notes}; STREAM_INTEGRITY: {integrity}, discarded_bytes={capture.discarded_bytes}, resync_events={capture.resync_events}".lstrip("; ")
    return {
        "session_id": session_id,
        "test_id": scheduled.test_id,
        "result_scope": "repetition",
        "repetition": repetition,
        "attempt": attempt,
        "drift_phase": scheduled.drift_phase,
        "route_set": config.route_set,
        "array": config.array,
        "route_list": ",".join(str(route) for route in route_set.routes),
        "scanorder": config.scanorder,
        "adcseq": config.adcseq,
        "spiengine": config.spiengine,
        "spi_clock_hz": config.spi_clock_hz,
        "channelrepeat_requested": config.channelrepeat,
        "channelrepeat_effective": after_status.get("channelrepeat_effective", ""),
        "vmid_requested": str(config.vmid).lower(),
        "vmid_effective": after_status.get("vmid_between_channels_effective", ""),
        "ref": 2.5,
        "warm_up_ms": args.warm_up_ms,
        "window_ms": args.window_ms,
        "captured_frames_total": settling_summary["captured_frames_total"],
        "warmup_frames_discarded": settling_summary["warmup_frames_discarded"],
        "valid_frames": len(capture.frames),
        "invalid_frames": capture.invalid_frames,
        "resync_events": capture.resync_events,
        "discarded_bytes": capture.discarded_bytes,
        "trailing_bytes": capture.trailing_bytes,
        "capture_timed_out": str(capture.timed_out).lower(),
        **integrity,
        "suspected_missing_frames": metrics["suspected_missing_frames"],
        "usb_stream_policy": after_status.get("usb_stream_policy", "legacy_blocking"),
        **{key: after_status.get(key, "") for key in LIVE_TRANSPORT_FIELDS},
        "total_samples": sum(frame.sample_count for frame in capture.frames),
        "startup_min_raw": settling_summary["startup_min_raw"],
        "sample_min_raw": sample_summary["min"],
        "sample_p1_raw": sample_summary["p1"],
        "sample_p5_raw": sample_summary["p5"],
        "sample_mean_raw": sample_summary["mean"],
        "sample_median_raw": sample_summary["median"],
        "sample_p95_raw": sample_summary["p95"],
        "sample_p99_raw": sample_summary["p99"],
        "sample_max_raw": sample_summary["max"],
        "sample_stdev_raw": sample_summary["stdev"],
        "duration_min_us": duration["min"],
        "duration_mean_us": duration["mean"],
        "duration_median_us": duration["median"],
        "duration_p5_us": duration["p5"],
        "duration_p95_us": duration["p95"],
        "duration_max_us": duration["max"],
        "duration_stdev_us": duration["stdev"],
        "payload_throughput_sps": metrics["payload_throughput_sps"],
        "sweep_rate_hz": metrics["sweep_rate_hz"],
        "block_period_median_us": metrics["block_period_median_us"],
        "inter_block_gap_median_us": metrics["inter_block_gap_median_us"],
        "host_arrival_period_median_us": metrics["host_arrival_period_median_us"],
        "speedup_vs_blocking": "",
        "throughput_gain_pct": "",
        **deltas,
        "vmid_warning_count": channel_counts["vmid_warning"],
        "vmid_severe_count": channel_counts["vmid_severe"],
        "unstable_channel_count": channel_counts["unstable"],
        "cross_mode_shift_count": channel_counts["cross_mode"],
        "drift_warning_count": channel_counts["drift"],
        "settling_warning_count": channel_counts["settling"],
        "settling_max_frames": settling_summary["settling_max_frames"],
        "settling_max_us": settling_summary["settling_max_us"],
        "settling_tolerance_counts": args.settling_tolerance_counts,
        "settling_stable_frames": args.settling_stable_frames,
        "timing_drift_pct": "",
        "drift_timing_tolerance_pct": args.drift_timing_tolerance_pct,
        "data_integrity_status": "FAIL" if hard_failure else "WARN" if warning else "PASS",
        "overall_status": overall,
        "vmid_nominal_code": args.vmid_code,
        "vmid_warning_tolerance": args.vmid_warning_tolerance,
        "vmid_severe_tolerance": args.vmid_severe_tolerance,
        "cross_mode_floor_counts": args.cross_mode_floor,
        "cross_mode_mad_multiplier": args.cross_mode_mad_multiplier,
        "baseline_test_ids": ";".join(sorted(baseline_ids)),
        "notes": notes,
    }


def validate_live_transport(status: dict[str, str], received_frames: int) -> None:
    """Reconcile whole-run sent/discarded counts, independent of profiling."""
    if status.get("usb_stream_policy") != "discard_if_busy":
        return  # Older firmware has no live counters.
    try:
        values = {key: int(status[key]) for key in LIVE_TRANSPORT_FIELDS}
    except (KeyError, ValueError) as exc:
        raise BenchmarkError("Missing/invalid live transport counters") from exc
    if any(value < 0 for value in values.values()):
        raise BenchmarkError("Negative live transport counters")
    if values["sampling_sweeps"] != values["usb_frames_sent"] + values["usb_frames_discarded"]:
        raise BenchmarkError("Acquired/sent/discarded sweep count mismatch")
    if values["usb_frames_sent"] != received_frames:
        raise BenchmarkError("USB sent/received whole-capture frame count mismatch")


def sample_rows_for_capture(
    *,
    session_id: str,
    scheduled: ScheduledTest,
    repetition: int,
    attempt: int,
    route_set: RouteSet,
    ordered_routes: Sequence[Route],
    capture: CaptureResult,
    channel_stats: dict[Route, dict[str, Any]],
    vmid_code: int,
) -> Iterable[dict[str, Any]]:
    warnings = {
        route: ";".join(stats["warnings"])
        for route, stats in channel_stats.items()
    }
    for frame_index, frame in enumerate(capture.frames):
        for payload_index, (route, sample) in enumerate(zip(ordered_routes, frame.samples)):
            yield {
                "session_id": session_id,
                "test_id": scheduled.test_id,
                "repetition": repetition,
                "attempt": attempt,
                "drift_phase": scheduled.drift_phase,
                "frame_index": frame_index,
                "host_received_ns": frame.host_received_ns,
                "block_start_us": frame.block_start_us,
                "block_end_us": frame.block_end_us,
                "acquisition_duration_us": frame.acquisition_duration_us,
                "avg_dt_us": frame.avg_dt_us,
                "sample_count": frame.sample_count,
                "payload_index": payload_index,
                "array": scheduled.config.array,
                "adc": route.adc,
                "channel": route.channel,
                "sample_raw": sample,
                "offset_from_vmid": sample - vmid_code,
                "route_warning": warnings.get(route, ""),
            }


def channel_stat_rows_for_capture(
    *,
    session_id: str,
    scheduled: ScheduledTest,
    repetition: int,
    attempt: int,
    route_set: RouteSet,
    channel_stats: dict[Route, dict[str, Any]],
    after_status: dict[str, str],
    vmid_code: int,
) -> Iterable[dict[str, Any]]:
    config = scheduled.config
    for route in payload_order(route_set.routes, config.scanorder):
        stats = channel_stats[route]
        yield {
            "session_id": session_id,
            "test_id": scheduled.test_id,
            "repetition": repetition,
            "attempt": attempt,
            "drift_phase": scheduled.drift_phase,
            "route_set": config.route_set,
            "array": config.array,
            "scanorder": config.scanorder,
            "adcseq": config.adcseq,
            "spiengine": config.spiengine,
            "spi_clock_hz": config.spi_clock_hz,
            "channelrepeat_requested": config.channelrepeat,
            "channelrepeat_effective": after_status.get(
                "channelrepeat_effective", ""
            ),
            "vmid_requested": str(config.vmid).lower(),
            "vmid_effective": after_status.get(
                "vmid_between_channels_effective", ""
            ),
            "adc": route.adc,
            "channel": route.channel,
            "sample_count": stats["count"],
            "sample_min_raw": stats["min"],
            "sample_mean_raw": stats["mean"],
            "sample_median_raw": stats["median"],
            "sample_max_raw": stats["max"],
            "sample_stdev_raw": stats["stdev"],
            "sample_mad_raw": stats["mad"],
            "sample_p1_raw": stats["p1"],
            "sample_p5_raw": stats["p5"],
            "sample_p95_raw": stats["p95"],
            "sample_p99_raw": stats["p99"],
            "startup_min_raw": stats["startup_min"],
            "settling_frame_index": stats["settling_frame_index"],
            "settling_time_us": stats["settling_time_us"],
            "settling_tolerance_counts": stats["settling_tolerance_counts"],
            "settling_stable_frames": stats["settling_stable_frames"],
            "settled_before_measurement": str(
                stats["settled_before_measurement"]
            ).lower(),
            "median_offset_from_vmid": float(stats["median"]) - vmid_code,
            "route_warning": ";".join(stats["warnings"]),
        }


def warmup_sample_rows_for_capture(
    *,
    session_id: str,
    scheduled: ScheduledTest,
    repetition: int,
    attempt: int,
    route_set: RouteSet,
    ordered_routes: Sequence[Route],
    full_capture: CaptureResult,
    warmup_frames_discarded: int,
    channel_stats: dict[Route, dict[str, Any]],
    routes_to_export: set[Route],
    bias_resistors: dict[Route, float],
    frame_limit: int,
) -> Iterable[dict[str, Any]]:
    if not full_capture.frames:
        return
    first_start = full_capture.frames[0].block_start_us
    export_frames = full_capture.frames[:min(warmup_frames_discarded, frame_limit)]
    config = scheduled.config
    for payload_index, route in enumerate(ordered_routes):
        if route not in routes_to_export:
            continue
        for frame_index, frame in enumerate(export_frames):
            elapsed_us = uint32_delta(frame.block_start_us, first_start)
            sample = frame.samples[payload_index]
            stats = channel_stats[route]
            median = float(stats["median"])
            yield {
                "session_id": session_id,
                "test_id": scheduled.test_id,
                "repetition": repetition,
                "attempt": attempt,
                "route_set": config.route_set,
                "array": config.array,
                "scanorder": config.scanorder,
                "adcseq": config.adcseq,
                "spiengine": config.spiengine,
                "spi_clock_hz": config.spi_clock_hz,
                "channelrepeat_requested": config.channelrepeat,
                "vmid_requested": str(config.vmid).lower(),
                "adc": route.adc,
                "channel": route.channel,
                "bias_resistor_ohms": bias_resistors.get(route, ""),
                "warmup_frame_index": frame_index,
                "elapsed_us": elapsed_us,
                "block_start_us": frame.block_start_us,
                "acquisition_duration_us": frame.acquisition_duration_us,
                "sample_raw": sample,
                "post_warmup_median_raw": median,
                "delta_from_post_warmup_median": sample - median,
                "settling_frame_index": stats["settling_frame_index"],
                "settling_time_us": stats["settling_time_us"],
            }


def aggregate_result_rows(rows: Sequence[dict[str, str]]) -> list[dict[str, Any]]:
    valid_rows = [
        row for row in rows
        if row.get("result_scope") == "repetition"
        and row.get("overall_status") in ("PASS", "WARN")
    ]
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in valid_rows:
        grouped.setdefault(row["test_id"], []).append(row)

    aggregates: list[dict[str, Any]] = []
    for test_id, group in grouped.items():
        first = group[0]

        def numbers(field: str) -> list[float]:
            output = []
            for row in group:
                try:
                    output.append(float(row[field]))
                except (KeyError, TypeError, ValueError):
                    pass
            return output

        duration_values = numbers("duration_median_us")
        throughput_values = numbers("payload_throughput_sps")
        duration_summary = numeric_summary(duration_values)
        aggregate = dict(first)
        aggregate.update({
            "result_scope": "aggregate",
            "repetition": "",
            "attempt": "",
            "valid_frames": sum(int(row.get("valid_frames", 0)) for row in group),
            "captured_frames_total": sum(int(row.get("captured_frames_total", 0)) for row in group),
            "warmup_frames_discarded": sum(int(row.get("warmup_frames_discarded", 0)) for row in group),
            "invalid_frames": sum(int(row.get("invalid_frames", 0)) for row in group),
            **{key: sum(int(row.get(key, 0)) for row in group) for key in (
                "resync_events", "discarded_bytes", "trailing_bytes",
                "timestamp_regressions", "duplicate_frames", "invalid_timing_frames",
                *ERROR_COUNTERS,
            )},
            "total_samples": sum(int(row.get("total_samples", 0)) for row in group),
            "startup_min_raw": min(numbers("startup_min_raw"), default=""),
            "sample_min_raw": min(numbers("sample_min_raw"), default=""),
            "sample_p1_raw": statistics.median(numbers("sample_p1_raw")) if numbers("sample_p1_raw") else "",
            "sample_p5_raw": statistics.median(numbers("sample_p5_raw")) if numbers("sample_p5_raw") else "",
            "sample_mean_raw": statistics.median(numbers("sample_mean_raw")) if numbers("sample_mean_raw") else "",
            "sample_median_raw": statistics.median(numbers("sample_median_raw")) if numbers("sample_median_raw") else "",
            "sample_p95_raw": statistics.median(numbers("sample_p95_raw")) if numbers("sample_p95_raw") else "",
            "sample_p99_raw": statistics.median(numbers("sample_p99_raw")) if numbers("sample_p99_raw") else "",
            "sample_max_raw": max(numbers("sample_max_raw"), default=""),
            "sample_stdev_raw": statistics.median(numbers("sample_stdev_raw")) if numbers("sample_stdev_raw") else "",
            "duration_min_us": duration_summary["min"],
            "duration_mean_us": duration_summary["mean"],
            "duration_median_us": duration_summary["median"],
            "duration_p5_us": duration_summary["p5"],
            "duration_p95_us": duration_summary["p95"],
            "duration_max_us": duration_summary["max"],
            "duration_stdev_us": duration_summary["stdev"],
            "payload_throughput_sps": statistics.median(throughput_values) if throughput_values else "",
            "sweep_rate_hz": statistics.median(numbers("sweep_rate_hz")) if numbers("sweep_rate_hz") else "",
            "block_period_median_us": statistics.median(numbers("block_period_median_us")) if numbers("block_period_median_us") else "",
            "inter_block_gap_median_us": statistics.median(numbers("inter_block_gap_median_us")) if numbers("inter_block_gap_median_us") else "",
            "host_arrival_period_median_us": statistics.median(numbers("host_arrival_period_median_us")) if numbers("host_arrival_period_median_us") else "",
            "vmid_warning_count": sum(int(row.get("vmid_warning_count", 0)) for row in group),
            "vmid_severe_count": sum(int(row.get("vmid_severe_count", 0)) for row in group),
            "unstable_channel_count": sum(int(row.get("unstable_channel_count", 0)) for row in group),
            "cross_mode_shift_count": sum(int(row.get("cross_mode_shift_count", 0)) for row in group),
            "drift_warning_count": sum(int(row.get("drift_warning_count", 0)) for row in group),
            "settling_warning_count": sum(int(row.get("settling_warning_count", 0)) for row in group),
            "settling_max_frames": max(numbers("settling_max_frames"), default=""),
            "settling_max_us": max(numbers("settling_max_us"), default=""),
            "data_integrity_status": (
                "WARN"
                if any(row.get("data_integrity_status") == "WARN" for row in group)
                else "PASS"
            ),
            "overall_status": "WARN" if any(row.get("overall_status") == "WARN" for row in group) else "PASS",
            "notes": f"Aggregate of {len(group)} valid repetitions",
        })
        for key in LIVE_TRANSPORT_FIELDS:
            values = numbers(key)
            aggregate[key] = (max(values) if key == "sampling_period_max_us" else sum(values)) if values else ""
        aggregates.append(aggregate)

    by_comparison: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in aggregates:
        key = (
            row["route_set"], row["array"], row["scanorder"], row["adcseq"],
            row["spi_clock_hz"], row["channelrepeat_requested"],
            row["vmid_requested"], row["ref"],
        )
        if (
            row["spiengine"] == "blocking"
            and row.get("drift_phase", "") == ""
            and row["array"] == "both"
        ):
            by_comparison[key] = row
    for row in aggregates:
        if row["array"] != "both" or row.get("drift_phase", ""):
            continue
        key = (
            row["route_set"], row["array"], row["scanorder"], row["adcseq"],
            row["spi_clock_hz"], row["channelrepeat_requested"],
            row["vmid_requested"], row["ref"],
        )
        baseline = by_comparison.get(key)
        if baseline is None:
            continue
        try:
            baseline_duration = float(baseline["duration_median_us"])
            tested_duration = float(row["duration_median_us"])
            baseline_throughput = float(baseline["payload_throughput_sps"])
            tested_throughput = float(row["payload_throughput_sps"])
            row["speedup_vs_blocking"] = baseline_duration / tested_duration
            row["throughput_gain_pct"] = 100.0 * (
                tested_throughput / baseline_throughput - 1.0
            )
        except (TypeError, ValueError, ZeroDivisionError):
            pass

    drift_begin = next(
        (row for row in aggregates if row.get("drift_phase") == "begin"),
        None,
    )
    if drift_begin is not None:
        try:
            begin_duration = float(drift_begin["duration_median_us"])
        except (TypeError, ValueError):
            begin_duration = 0.0
        for row in aggregates:
            if row.get("drift_phase") not in ("middle", "end") or begin_duration <= 0:
                continue
            try:
                drift_pct = 100.0 * (
                    float(row["duration_median_us"]) / begin_duration - 1.0
                )
                tolerance = float(row.get("drift_timing_tolerance_pct", 10.0))
            except (TypeError, ValueError, ZeroDivisionError):
                continue
            row["timing_drift_pct"] = drift_pct
            if abs(drift_pct) > tolerance:
                row["drift_warning_count"] = int(
                    row.get("drift_warning_count", 0)
                ) + 1
                row["data_integrity_status"] = "WARN"
                row["overall_status"] = "WARN"
                row["notes"] = (
                    f"{row.get('notes', '')}; DRIFT_WARNING: acquisition duration "
                    f"changed {drift_pct:.2f}% from beginning control"
                ).lstrip("; ")
    return aggregates


def rewrite_results_with_aggregates(path: Path) -> None:
    rows = load_existing_results(path)
    repetitions = [row for row in rows if row.get("result_scope") == "repetition"]
    aggregates = aggregate_result_rows(repetitions)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=RESULT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in repetitions + aggregates:
            writer.writerow({key: finite_or_blank(row.get(key, "")) for key in RESULT_FIELDS})
    os.replace(temporary, path)


def write_failure_row(
    appender: CsvAppender, *, session_id: str, scheduled: ScheduledTest,
    repetition: int, attempt: int, route_set: RouteSet, args: argparse.Namespace,
    message: str,
) -> None:
    appender.rows([{
        "session_id": session_id,
        "test_id": scheduled.test_id,
        "result_scope": "repetition",
        "repetition": repetition,
        "attempt": attempt,
        "drift_phase": scheduled.drift_phase,
        "route_set": scheduled.config.route_set,
        "array": scheduled.config.array,
        "route_list": ",".join(str(route) for route in route_set.routes),
        "scanorder": scheduled.config.scanorder,
        "adcseq": scheduled.config.adcseq,
        "spiengine": scheduled.config.spiengine,
        "spi_clock_hz": scheduled.config.spi_clock_hz,
        "channelrepeat_requested": scheduled.config.channelrepeat,
        "vmid_requested": str(scheduled.config.vmid).lower(),
        "ref": 2.5,
        "window_ms": args.window_ms,
        "data_integrity_status": "FAIL",
        "overall_status": "FAIL",
        "vmid_nominal_code": args.vmid_code,
        "vmid_warning_tolerance": args.vmid_warning_tolerance,
        "vmid_severe_tolerance": args.vmid_severe_tolerance,
        "cross_mode_floor_counts": args.cross_mode_floor,
        "cross_mode_mad_multiplier": args.cross_mode_mad_multiplier,
        "drift_timing_tolerance_pct": args.drift_timing_tolerance_pct,
        "notes": message,
    }])


def recover_with_smoke(
    protocol: SerialProtocol,
    route_set: RouteSet,
    args: argparse.Namespace,
    spi_clock_hz: int,
) -> None:
    recovery = TestConfig(
        route_set=route_set.name,
        array=route_set.array,
        scanorder="interleaved",
        adcseq="manual",
        spiengine="blocking",
        channelrepeat=1,
        vmid=False,
        spi_clock_hz=spi_clock_hz,
    )
    before = configure_test(protocol, recovery, route_set)
    capture = protocol.capture_timed(
        min(500, args.warm_up_ms), len(route_set.routes),
        args.grace_ms, args.idle_ms,
    )
    after = stop_after_capture(protocol)
    if (not capture.frames or capture.invalid_frames or capture.timed_out
            or capture.trailing_bytes or capture.discarded_bytes or capture.resync_events
            or any((capture.stream_integrity or stream_integrity_counts(capture.frames)).values())):
        raise BenchmarkError("Blocking recovery smoke capture failed")
    deltas = counter_deltas(before, after)
    if any(deltas.values()):
        raise BenchmarkError(
            f"Blocking recovery smoke changed firmware counters: {deltas}"
        )


def run_measured_repetition(
    *,
    protocol: SerialProtocol,
    session_id: str,
    scheduled: ScheduledTest,
    repetition: int,
    attempt: int,
    route_set: RouteSet,
    args: argparse.Namespace,
    samples_csv: CsvAppender,
    warmup_samples_csv: CsvAppender,
    channel_stats_csv: CsvAppender,
    results_csv: CsvAppender,
    raw_dir: Path,
    baselines: dict[tuple[Route, int], ChannelReference],
    warmup_exported_routes: set[Route],
    bias_resistors: dict[Route, float],
) -> dict[str, Any]:
    before_status = configure_test(protocol, scheduled.config, route_set)
    full_capture = protocol.capture_timed(
        args.warm_up_ms + args.window_ms,
        len(route_set.routes), args.grace_ms, args.idle_ms,
        reader_pause_ms=args.reader_pause_ms,
        reader_pause_at_ms=args.reader_pause_at_ms,
        defer_parsing=args.defer_parsing,
    )
    raw_path = raw_dir / (
        f"{scheduled.test_id}__r{repetition}__attempt{attempt}.bin"
    )
    if not args.no_raw:
        raw_path.write_bytes(full_capture.raw)
    after_status = stop_after_capture(protocol)
    (raw_dir.parent / f"{scheduled.test_id}__r{repetition}__attempt{attempt}__status.json").write_text(
        json.dumps(after_status, indent=2), encoding="utf-8")
    validate_live_transport(after_status, len(full_capture.frames))

    try:
        save_profile(raw_dir.parent / "firmware_profile.jsonl", after_status,
                     received_frames=len(full_capture.frames), requested=args.profile,
                     session_id=session_id, test_id=scheduled.test_id,
                     repetition=repetition, attempt=attempt)
    except ValueError as exc:
        raise BenchmarkError(f"Firmware profile failed: {exc}") from exc

    if not full_capture.frames:
        preview = full_capture.raw[:120].decode("ascii", errors="replace")
        raise BenchmarkError(f"No valid binary frames; raw preview={preview!r}")
    capture, warmup_frames_discarded = measured_capture_after_warmup(
        full_capture, args.warm_up_ms
    )
    if not capture.frames:
        raise BenchmarkError(
            "Continuous capture ended before any post-warm-up frames were decoded"
        )

    ordered_routes = payload_order(route_set.routes, scheduled.config.scanorder)
    channel_stats, channel_counts, baseline_ids = analyze_channels(
        capture,
        ordered_routes,
        route_set,
        baselines,
        test_id=scheduled.test_id,
        vmid_nominal=args.vmid_code,
        warning_tolerance=args.vmid_warning_tolerance,
        severe_tolerance=args.vmid_severe_tolerance,
        cross_mode_floor=args.cross_mode_floor,
        cross_mode_mad_multiplier=args.cross_mode_mad_multiplier,
        noise_floor=args.noise_floor,
        noise_mad_multiplier=args.noise_mad_multiplier,
        spi_clock_hz=scheduled.config.spi_clock_hz,
        settling_capture=full_capture,
        warm_up_us=args.warm_up_ms * 1000,
        settling_tolerance_counts=args.settling_tolerance_counts,
        settling_stable_frames=args.settling_stable_frames,
    )
    metrics = frame_metrics(capture)
    sample_values = [
        sample for frame in capture.frames for sample in frame.samples
    ]
    sample_summary = numeric_summary(sample_values)
    sample_summary.update({
        "p1": percentile(sample_values, 0.01),
        "p99": percentile(sample_values, 0.99),
    })
    settling_frames = [
        int(stats["settling_frame_index"])
        for stats in channel_stats.values()
        if stats["settling_frame_index"] != ""
    ]
    settling_times = [
        int(stats["settling_time_us"])
        for stats in channel_stats.values()
        if stats["settling_time_us"] != ""
    ]
    settling_summary = {
        "captured_frames_total": len(full_capture.frames),
        "warmup_frames_discarded": warmup_frames_discarded,
        "startup_min_raw": min(
            sample for frame in full_capture.frames for sample in frame.samples
        ),
        "settling_max_frames": max(settling_frames, default=""),
        "settling_max_us": max(settling_times, default=""),
    }
    row = result_row_for_capture(
        session_id=session_id,
        scheduled=scheduled,
        repetition=repetition,
        attempt=attempt,
        route_set=route_set,
        capture=capture,
        before_status=before_status,
        after_status=after_status,
        channel_counts=channel_counts,
        sample_summary=sample_summary,
        settling_summary=settling_summary,
        baseline_ids=baseline_ids,
        metrics=metrics,
        args=args,
    )
    samples_csv.rows(sample_rows_for_capture(
        session_id=session_id,
        scheduled=scheduled,
        repetition=repetition,
        attempt=attempt,
        route_set=route_set,
        ordered_routes=ordered_routes,
        capture=capture,
        channel_stats=channel_stats,
        vmid_code=args.vmid_code,
    ))
    channel_stats_csv.rows(channel_stat_rows_for_capture(
        session_id=session_id,
        scheduled=scheduled,
        repetition=repetition,
        attempt=attempt,
        route_set=route_set,
        channel_stats=channel_stats,
        after_status=after_status,
        vmid_code=args.vmid_code,
    ))
    results_csv.rows([row])

    deltas = counter_deltas(before_status, after_status)
    if any(deltas.values()):
        raise BenchmarkError(f"Firmware error counters increased: {deltas}")
    if row["overall_status"] == "FAIL":
        raise BenchmarkError("Data-integrity checks failed")
    routes_to_export = set(ordered_routes) - warmup_exported_routes
    if routes_to_export:
        warmup_samples_csv.rows(warmup_sample_rows_for_capture(
            session_id=session_id,
            scheduled=scheduled,
            repetition=repetition,
            attempt=attempt,
            route_set=route_set,
            ordered_routes=ordered_routes,
            full_capture=full_capture,
            warmup_frames_discarded=warmup_frames_discarded,
            channel_stats=channel_stats,
            routes_to_export=routes_to_export,
            bias_resistors=bias_resistors,
            frame_limit=args.warmup_export_frames,
        ))
        warmup_exported_routes.update(routes_to_export)
    if is_baseline_config(scheduled.config):
        update_baselines(
            baselines,
            channel_stats,
            scheduled.test_id,
            scheduled.config.spi_clock_hz,
        )
    return row


def run_smoke(protocol: SerialProtocol, config: TestConfig, route_set: RouteSet,
              args: argparse.Namespace) -> None:
    before = configure_test(protocol, config, route_set)
    capture = protocol.capture_timed(
        min(750, args.window_ms), len(route_set.routes),
        args.grace_ms, args.idle_ms,
    )
    after = stop_after_capture(protocol)
    impossible_value = any(
        sample > 4095 for frame in capture.frames for sample in frame.samples
    )
    if (
        not capture.frames
        or capture.invalid_frames
        or capture.discarded_bytes or capture.resync_events
        or any((capture.stream_integrity or stream_integrity_counts(capture.frames)).values())
        or capture.trailing_bytes
        or capture.timed_out
        or impossible_value
    ):
        raise BenchmarkError(
            f"Smoke capture failed for {config.route_set}: "
            f"frames={len(capture.frames)} invalid={capture.invalid_frames}"
        )
    deltas = counter_deltas(before, after)
    if any(deltas.values()):
        raise BenchmarkError(f"Smoke capture changed firmware counters: {deltas}")


def make_schedule(configs: Sequence[TestConfig], repetitions: int,
                  include_drift: bool = True) -> list[ScheduledTest]:
    regular = [ScheduledTest(config, config.test_id, repetitions) for config in configs]
    if not include_drift:
        return regular
    reference = next(
        (item for item in configs if item.route_set == "all_four_full" and is_baseline_config(item)),
        None,
    )
    if reference is None:
        reference = next(
            (
                item for item in configs
                if item.route_set == "all_four_full"
                and item.spiengine == "blocking"
                and item.adcseq == "manual"
                and item.channelrepeat == 1
                and not item.vmid
            ),
            None,
        )
    if reference is None:
        return regular
    midpoint = len(regular) // 2
    controls = {
        "begin": ScheduledTest(reference, reference.test_id + "__drift_begin", 1, "begin"),
        "middle": ScheduledTest(reference, reference.test_id + "__drift_middle", 1, "middle"),
        "end": ScheduledTest(reference, reference.test_id + "__drift_end", 1, "end"),
    }
    return [controls["begin"]] + regular[:midpoint] + [controls["middle"]] + regular[midpoint:] + [controls["end"]]


def print_route_sets(route_sets: dict[str, RouteSet]) -> None:
    print("Route sets:")
    for route_set in route_sets.values():
        print(
            f"  {route_set.name:28} array={route_set.array:4} "
            f"routes={len(route_set.routes):2}  {route_set.description}"
        )


def print_tests(schedule: Sequence[ScheduledTest]) -> None:
    print(f"Tests: {len(schedule)} scheduled configurations")
    for index, scheduled in enumerate(schedule, 1):
        print(f"  {index:03}: {scheduled.test_id} x{scheduled.repetitions}")


def list_serial_ports() -> int:
    try:
        from serial.tools import list_ports
    except ImportError:
        print("pyserial is not installed; run: uv sync", file=sys.stderr)
        return 2
    ports = list(list_ports.comports())
    if not ports:
        print("No serial ports found")
        return 1
    for port in ports:
        print(f"{port.device}\t{port.description}\t{port.hwid}")
    return 0


def open_serial_port(port: str, baud: int) -> Any:
    try:
        import serial
    except ImportError as exc:
        raise BenchmarkError("pyserial is not installed; run: uv sync") from exc
    return serial.Serial(
        port=port,
        baudrate=baud,
        timeout=0.02,
        write_timeout=2.0,
    )


def select_configs(configs: Sequence[TestConfig], selectors: Sequence[str],
                   smoke_only: bool) -> list[TestConfig]:
    if smoke_only:
        return [
            config for config in configs
            if config.route_set in ("one_adc_bus1", "all_four_full")
            and is_baseline_config(config)
        ]
    if not selectors:
        return list(configs)
    selected = [
        config for config in configs
        if any(selector.lower() in config.test_id.lower() for selector in selectors)
    ]
    if not selected:
        raise ValueError("No tests matched --tests selectors")
    return selected


GHOST_ATTEMPT_FIELDS = [
    "session_id", "source", "attempt", "status", "source_peak", "source_stdev", "source_clipped",
    "sample_count", "trigger_threshold", "ghosting_detected", "ghost_targets",
    "inconclusive_pairs", "invalid_frames", "resync_events", "discarded_bytes", "notes",
]
GHOST_SUMMARY_FIELDS = ["selected_attempt", *GHOST_ATTEMPT_FIELDS]
GHOST_PAIR_FIELDS = [
    "session_id", "source", "attempt", "target", "source_peak", "target_peak",
    "source_stdev", "target_stdev", "attenuation_pct", "correlation", "target_threshold", "target_clipped", "ghosting_detected", "status",
]
GHOST_SAMPLE_FIELDS = [
    "session_id", "source", "attempt", "phase", "frame_index", "block_start_us",
    "block_end_us", "elapsed_us", "adc", "channel", "sample_raw", "baseline",
    "baseline_stdev", "noise_sigma", "baseline_relative",
]


def select_ghosting_config(args: argparse.Namespace, route_sets: dict[str, RouteSet]) -> tuple[RouteSet, TestConfig]:
    if args.ghost_adc is not None:
        array = "1" if args.ghost_adc <= 2 else "2"
        parent = route_sets.get(f"full_array{array}")
        if parent is None:
            raise ValueError(f"Route manifest requires full_array{array} for --ghost-adc")
        routes = tuple(route for route in parent.routes if route.adc == args.ghost_adc)
        route_set = RouteSet(f"ghost_adc{args.ghost_adc}", array, routes, frozenset())
    else:
        name = args.route_set_filters[0]
        if name == "all_four_full":
            print("Ghosting tests one array: all_four_full is mapped to full_array1 (array 1).")
            name = "full_array1"
        if name not in route_sets:
            raise ValueError(f"Unknown ghosting route set: {name}")
        route_set = route_sets[name]
    if route_set.array == "both":
        raise ValueError("Ghosting cannot test two arrays; choose one ADC or one array")
    if not route_set.routes:
        raise ValueError("Ghosting selection has no sensor routes")
    if any(route.channel >= (10 if route.adc in (1, 3) else 15) for route in route_set.routes):
        raise ValueError("Ghosting routes must use populated sensor channels")
    config = TestConfig(route_set.name, route_set.array, args.scan_order_filters[0],
                        "manual", args.spi_engine, 1, args.vmid == "on", args.spi_clocks_hz[0])
    return route_set, config


def write_ghosting_csv(path: Path, fields: Sequence[str], rows: Sequence[dict[str, Any]]) -> None:
    temporary = path.with_suffix(".csv.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: finite_or_blank(row.get(field, "")) for field in fields})
        destination.flush()
        os.fsync(destination.fileno())
    os.replace(temporary, path)


def ghosting_sample_rows(capture: GhostingCapture, routes: Sequence[Route],
                         session_id: str, source: str, attempt: int) -> Iterable[dict[str, Any]]:
    for phase, frames in (("baseline", capture.baseline), ("window", capture.window)):
        if not frames:
            continue
        origin = capture.trigger_start_us if phase == "window" else frames[0].block_start_us
        for index, frame in enumerate(frames):
            for route, sample in zip(routes, frame.samples):
                reference = capture.calibration.get(str(route))
                yield {
                    "session_id": session_id, "source": source, "attempt": attempt,
                    "phase": phase, "frame_index": index, "adc": route.adc, "channel": route.channel,
                    "block_start_us": frame.block_start_us, "block_end_us": frame.block_end_us,
                    "elapsed_us": uint32_delta(frame.block_start_us, origin),
                    "sample_raw": sample, "baseline": reference.baseline if reference else "",
                    "baseline_stdev": reference.stdev if reference else "",
                    "noise_sigma": reference.noise_sigma if reference else "",
                    "baseline_relative": sample - reference.baseline if reference else "",
                }


def print_ghosting_result(row: dict[str, Any], pairs: Sequence[dict[str, Any]]) -> None:
    print(f"  {row['status']}: source peak={row.get('source_peak', 'n/a')} counts, "
          f"std={row.get('source_stdev', 'n/a')} counts")
    if row.get("notes"):
        print(f"  {row['notes']}")
    for pair in pairs:
        correlation = pair["correlation"]
        displayed = f"{correlation:.3f}" if isinstance(correlation, (int, float)) else "undefined"
        attenuation = pair["attenuation_pct"]
        attenuation_display = f"{attenuation:.2f}%" if isinstance(attenuation, (int, float)) else "undefined"
        print(f"    {pair['target']}: peak={pair['target_peak']:.2f} counts, "
              f"std={pair['target_stdev']:.2f} counts, "
              f"attenuation={attenuation_display}, r={displayed}, {pair['status']}")


def ghosting_next_action() -> str:
    while True:
        answer = input("Continue [Enter/C], Redo [R], or Quit [Q]: ").strip().lower()
        if answer in ("", "c", "continue"):
            return "continue"
        if answer in ("r", "redo"):
            return "redo"
        if answer in ("q", "quit"):
            return "quit"


def run_ghosting_session(args: argparse.Namespace, route_sets: dict[str, RouteSet]) -> int:
    import numpy as np

    route_set, config = select_ghosting_config(args, route_sets)
    ordered = payload_order(route_set.routes, config.scanorder)
    route_names = tuple(map(str, ordered))
    print(f"Ghosting: {config.test_id}; {len(ordered)} sources; two-second windows; "
          "channelrepeat=1, repetitions=1.")
    if args.requested_window_ms != 2000 or args.requested_repetitions != 1:
        print(f"Requested window={args.requested_window_ms} ms, repetitions={args.requested_repetitions}; "
              "ghosting overrides these to 2000 ms and 1.")
    if args.dry_run or args.list_tests:
        print("Sources: " + ", ".join(str(route) for route in sorted(ordered)))
        print(f"Source trigger: max({args.ghost_trigger_counts:g} counts, "
              f"{args.ghost_trigger_sigma:g} * noise sigma), "
              f"{args.ghost_trigger_samples} consecutive same-polarity samples.")
        print(f"Target detection: max({args.ghost_target_counts:g} counts, "
              f"{args.ghost_target_sigma:g} * noise sigma); positive correlation >= "
              f"{args.ghost_correlation_min:g}.")
        print("Dry run only; no serial port was opened.")
        return 0
    if not args.port:
        raise SystemExit("--port is required for ghosting acquisition")
    if not sys.stdin.isatty():
        raise SystemExit("Ghosting acquisition requires an interactive terminal for immediate Space handling")
    now = datetime.now(timezone.utc)
    output = (args.output or DEFAULT_RESULTS_ROOT / now.strftime("%Y%m%dT%H%M%SZ-ghosting")).resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"Output directory is not empty: {output}; choose a new ghosting directory")
    output.mkdir(parents=True, exist_ok=True)
    if not args.no_raw:
        (output / "raw").mkdir(exist_ok=True)
    session_id = now.strftime("testboard7953-ghosting-%Y%m%dT%H%M%SZ")
    metadata: dict[str, Any] = {
        "session_id": session_id, "mode": "ghosting", "schema_version": 2,
        "runner_version": RUNNER_VERSION, "runner_path": str(Path(__file__).resolve()),
        "git_revision": git_revision(), "started_utc": now.isoformat(), "status": "running",
        "port": args.port, "baud": args.baud,
        "route_manifest": str(args.routes.resolve()),
        "requested_selection": f"ADC{args.ghost_adc}" if args.ghost_adc else args.route_set_filters[0],
        "effective_route_set": route_set.name, "array": config.array, "routes": list(route_names),
        "scan_order": config.scanorder, "spi_engine": config.spiengine,
        "spi_clock_hz": config.spi_clock_hz, "vmid": args.vmid, "adcseq": "manual",
        "channelrepeat": 1, "repetitions": 1, "window_ms": 2000,
        "requested_window_ms": args.requested_window_ms, "requested_repetitions": args.requested_repetitions,
        "warm_up_ms": args.warm_up_ms, "baseline_ms": args.ghost_baseline_ms,
        "trigger_counts": args.ghost_trigger_counts, "target_counts": args.ghost_target_counts,
        "trigger_samples": args.ghost_trigger_samples,
        "trigger_sigma": args.ghost_trigger_sigma, "target_sigma": args.ghost_target_sigma,
        "correlation_min": args.ghost_correlation_min, "calibrations": [],
        "detection_coverage": "all_other_channels_on_same_adc", "graph_coverage": "all_measured_channels",
        "selection_policy": "strongest_valid_source_peak; ties retain earlier attempt",
        "attenuation_method": "100 * target_sample_stdev / source_sample_stdev; ddof=1",
        "attenuation_window": "full-resolution shared two-second signal window",
    }
    attempts: list[dict[str, Any]] = []
    all_pairs: list[dict[str, Any]] = []
    graphs: dict[str, dict[str, Any]] = {}
    log = SessionLog(output / "session_commands.log")
    samples = CsvAppender(output / "ghosting_samples.csv", GHOST_SAMPLE_FIELDS)
    serial_port = None
    protocol = None
    exit_code = 0
    active_capture = None
    active_row = None

    def persist() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        summary = summarize_attempts(route_names, attempts)
        selected = {(r["source"], r["selected_attempt"]) for r in summary if r["selected_attempt"] != ""}
        pairs = [p for p in all_pairs if (p["source"], p["attempt"]) in selected]
        write_ghosting_csv(output / "ghosting_summary.csv", GHOST_SUMMARY_FIELDS, summary)
        write_ghosting_csv(output / "ghosting_pairs.csv", GHOST_PAIR_FIELDS, pairs)
        write_ghosting_csv(output / "ghosting_attempts.csv", GHOST_ATTEMPT_FIELDS, attempts)
        atomic_write_json(output / "session_metadata.json", metadata)
        return summary, pairs

    def save_capture(capture: GhostingCapture, row: dict[str, Any]) -> None:
        samples.rows(ghosting_sample_rows(capture, ordered, session_id, row["source"], row["attempt"]))
        if not args.no_raw:
            for phase, frames in (("warmup", capture.warmup), ("baseline", capture.baseline), ("window", capture.window)):
                if frames:
                    destination = output / "raw" / f"adc{row['source'].replace(':', '_ch')}__attempt{row['attempt']}__{phase}.bin"
                    with destination.open("wb") as raw_file:
                        for frame in frames:
                            raw_file.write(frame.raw)
        metadata["calibrations"].append({
            "source": row["source"], "attempt": row["attempt"],
            "channels": {r: {"baseline": c.baseline, "stdev": c.stdev,
                             "noise_sigma": c.noise_sigma, "sample_count": c.sample_count}
                         for r, c in capture.calibration.items()},
        })

    try:
        persist()
        serial_port = open_serial_port(args.port, args.baud)
        protocol = SerialProtocol(serial_port, log)
        protocol.drain_until_idle()
        protocol.send_command("stop")
        if FIRMWARE_IDENTITY not in protocol.send_command("mcu"):
            raise BenchmarkError(f"Expected firmware {FIRMWARE_IDENTITY}")
        protocol.send_command("mode PZT")
        initial = parse_status(protocol.send_command("status"))
        initial = configure_profile(protocol, initial, "off")
        metadata["firmware_status_initial"] = initial
        nonzero = {key: counter_value(initial, key) for key in ERROR_COUNTERS if counter_value(initial, key)}
        if nonzero and not args.allow_existing_errors:
            raise BenchmarkError(f"Firmware has existing errors: {nonzero}; investigate or use --allow-existing-errors")
        if nonzero:
            log.write(f"WARNING pre-existing counters: {nonzero}")
        quitting = False
        for route in sorted(ordered):
            source = str(route)
            number = 0
            while True:
                answer = input(f"Release all sensors before ADC{route.adc}_CH{route.channel}; "
                               "Enter when ready, Q to quit: ").strip().lower()
                if answer == "q":
                    quitting = True
                    break
                number += 1
                active_capture = GhostingCapture()
                active_row = {"session_id": session_id, "source": source, "attempt": number,
                              "status": "INCOMPLETE", "notes": ""}
                pairs = []
                candidate_graph = None
                try:
                    protocol.drain_until_idle()
                    before = configure_test(protocol, config, route_set)
                    metadata["firmware_status_effective"] = before
                    with ConsoleKeys() as keys:
                        capture_ghosting_attempt(protocol, route_names, source, args, keys,
                                                active_capture, notify=lambda message: print(message, flush=True))
                    after = parse_status(protocol.send_command("status"))
                    deltas = counter_deltas(before, after)
                    if any(deltas.values()):
                        raise BenchmarkError(f"Firmware counters increased: {deltas}")
                    if active_capture.status == "COMPLETE":
                        values = np.array([frame.samples for frame in active_capture.window])
                        metrics, pairs = analyze_window(values, route_names, source, active_capture.calibration,
                                                        target_counts=args.ghost_target_counts,
                                                        target_sigma=args.ghost_target_sigma,
                                                        correlation_min=args.ghost_correlation_min)
                        active_row.update(metrics)
                        if metrics["source_clipped"]:
                            active_row["notes"] = "Source reached 0 or 4095; excluded from strongest-valid selection. Redo with a lighter press."
                        previous = strongest_attempt(attempts, source)
                        if metrics["status"] == "VALID" and (previous is None or metrics["source_peak"] > previous["source_peak"]):
                            signals = values - np.array([active_capture.calibration[r].baseline for r in route_names])
                            indices = chart_indices(signals)
                            candidate_graph = {
                                "attempt": number, "routes": list(route_names),
                                "times_s": np.array([uint32_delta(active_capture.window[int(i)].block_start_us,
                                                                  active_capture.trigger_start_us) / 1_000_000 for i in indices]),
                                "signals": signals[indices], "bounds": chart_bounds(signals),
                                "full_sample_count": len(values),
                            }
                    else:
                        active_row["status"] = "INCOMPLETE" if active_capture.status == "QUIT" else active_capture.status
                except (BenchmarkError, GhostingCaptureError, ValueError, OSError) as exc:
                    active_row.update(status="FAILED", notes=str(exc))
                    log.write(f"GHOSTING ATTEMPT FAILED {source} attempt={number}: {exc}")
                active_row.update(trigger_threshold=active_capture.trigger_threshold,
                                  sample_count=len(active_capture.window),
                                  invalid_frames=active_capture.invalid_frames,
                                  resync_events=active_capture.resync_events,
                                  discarded_bytes=active_capture.discarded_bytes)
                save_capture(active_capture, active_row)
                attempts.append(active_row)
                all_pairs.extend({"session_id": session_id, "attempt": number, **pair} for pair in pairs)
                if candidate_graph is not None:
                    graphs[source] = candidate_graph
                print_ghosting_result(active_row, pairs)
                quitting = active_capture.status == "QUIT"
                skipped = active_capture.status == "SKIPPED"
                active_capture = None
                active_row = None
                persist()
                action = "quit" if quitting else "continue" if skipped else ghosting_next_action()
                if action == "quit":
                    quitting = True
                    break
                if action == "continue":
                    break
            if quitting:
                break
        metadata["status"] = "partial" if quitting else "complete"
    except (KeyboardInterrupt, EOFError):
        exit_code = 130
        metadata["status"] = "interrupted"
        print("Ghosting interrupted; completed and partial attempts are preserved.", file=sys.stderr)
    except (BenchmarkError, GhostingCaptureError, OSError, ValueError) as exc:
        exit_code = 1
        metadata.update(status="failed", failure=str(exc))
        log.write(f"GHOSTING SESSION FAILED {exc}")
        print(f"Ghosting failed: {exc}", file=sys.stderr)
    finally:
        if active_capture is not None and active_row is not None and active_row not in attempts:
            if active_row["status"] != "FAILED":
                active_row.update(status="INCOMPLETE", notes=metadata.get("failure", "Session interrupted during attempt"))
            active_row.update(sample_count=len(active_capture.window),
                              trigger_threshold=active_capture.trigger_threshold,
                              invalid_frames=active_capture.invalid_frames,
                              resync_events=active_capture.resync_events,
                              discarded_bytes=active_capture.discarded_bytes)
            save_capture(active_capture, active_row)
            attempts.append(active_row)
        if protocol is not None:
            try:
                protocol.send_command("stop", timeout_s=2)
            except Exception as exc:
                log.write(f"CLEANUP stop: {exc}")
        if serial_port is not None:
            serial_port.close()
        samples.close()
        metadata["ended_utc"] = datetime.now(timezone.utc).isoformat()
        summary, pairs = persist()
        try:
            if not args.no_excel:
                write_ghosting_workbook(output / "ghosting_report.xlsx", summary, pairs,
                                       attempts, metadata, graphs, GLOSSARY_PATH)
        except (OSError, RuntimeError, ValueError) as exc:
            metadata["report_error"] = str(exc)
            atomic_write_json(output / "session_metadata.json", metadata)
            print(f"Excel report failed; CSVs preserved: {exc}", file=sys.stderr)
            exit_code = exit_code or 1
        log.close()
    print(f"Ghosting {metadata['status']}: {output}")
    return exit_code


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="Teensy serial port, for example COM7")
    parser.add_argument("--baud", type=int, default=460800)
    parser.add_argument(
        "--spi-clock-hz",
        action="append",
        type=int,
        dest="spi_clocks_hz",
        help=(
            "SPI clock in Hz; repeat this option to benchmark several clocks "
            f"(default: {DEFAULT_SPI_CLOCK_HZ})."
        ),
    )
    parser.add_argument("--routes", type=Path, default=DEFAULT_ROUTES_PATH)
    parser.add_argument("--bias-map", type=Path, default=DEFAULT_BIAS_MAP_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--window-ms", type=int, default=5000)
    parser.add_argument("--warm-up-ms", type=int, default=1000)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--profile", choices=("off", "on"), default="off",
                        help="Collect firmware phase profiling (on requires teensy41_profile build)")
    parser.add_argument("--reader-pause-ms", type=int, default=0,
                        help="Pause host reads once during each timing capture; Windows may buffer the pause")
    parser.add_argument("--reader-pause-at-ms", type=int, default=2000,
                        help="Elapsed time at which the host-read pause begins")
    parser.add_argument("--defer-parsing", action="store_true",
                        help="Drain raw bytes during capture and parse afterward to compare reader overhead")
    parser.add_argument("--grace-ms", type=int, default=3000)
    parser.add_argument("--idle-ms", type=int, default=250)
    parser.add_argument("--tests", action="append", default=[],
                        help="Run test IDs containing this text; repeatable")
    parser.add_argument(
        "--route-set", action="append", dest="route_set_filters", default=[],
        help=("Build a complete matrix for this route-set name; repeatable. "
              "Use with --scan-order for a focused complete benchmark."),
    )
    parser.add_argument(
        "--scan-order", action="append", dest="scan_order_filters", default=[],
        choices=("interleaved", "array", "adc"),
        help=("Build a complete matrix for this payload scan order; repeatable. "
              "Use with --route-set for a focused complete benchmark."),
    )
    parser.add_argument("--smoke-only", action="store_true")
    parser.add_argument("--list-tests", action="store_true")
    parser.add_argument("--list-ports", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--allow-existing-errors",
        action="store_true",
        help=(
            "Allow nonzero cumulative firmware counters at startup; each test "
            "still fails if any counter changes."
        ),
    )
    parser.add_argument("--no-raw", action="store_true")
    parser.add_argument("--no-excel", action="store_true")
    parser.add_argument("--no-drift-controls", action="store_true")
    parser.add_argument("--seed", type=int, default=7953)
    parser.add_argument("--vmid-code", type=int, default=2048)
    parser.add_argument("--vmid-warning-tolerance", type=int, default=512)
    parser.add_argument("--vmid-severe-tolerance", type=int, default=1024)
    parser.add_argument("--cross-mode-floor", type=int, default=128)
    parser.add_argument("--cross-mode-mad-multiplier", type=float, default=6.0)
    parser.add_argument("--noise-floor", type=int, default=32)
    parser.add_argument("--noise-mad-multiplier", type=float, default=3.0)
    parser.add_argument("--settling-tolerance-counts", type=int, default=64)
    parser.add_argument("--settling-stable-frames", type=int, default=5)
    parser.add_argument("--warmup-export-frames", type=int, default=250)
    parser.add_argument("--drift-timing-tolerance-pct", type=float, default=10.0)
    ghost = parser.add_argument_group("interactive ghosting test")
    ghost.add_argument("--ghosting", action="store_true", help="Test manually pressed sensor channels for ghosting")
    ghost.add_argument("--ghost-adc", type=int, choices=(1, 2, 3, 4), help="Test one populated ADC; alternatively choose one --route-set")
    ghost.add_argument("--spi-engine", choices=("blocking", "dma", "lpspi"), default="lpspi", help="Ghosting engine (default: lpspi)")
    ghost.add_argument("--vmid", choices=("on", "off"), default="off", help="Ghosting between-channel Vmid conversions (default: off)")
    ghost.add_argument("--ghost-baseline-ms", type=int, default=1000, help="Quiet calibration after warm-up (default: 1000 ms)")
    ghost.add_argument("--ghost-trigger-counts", type=float, default=100, help="Source-trigger count floor (default: 100); effective threshold is also at least source sigma multiplier times noise")
    ghost.add_argument("--ghost-trigger-samples", type=int, default=3, help="Consecutive same-polarity source samples above threshold (default: 3; range: 1..64)")
    ghost.add_argument("--ghost-target-counts", type=float, default=1, help="Target peak count floor; also requires the target noise threshold")
    ghost.add_argument("--ghost-trigger-sigma", type=float, default=5, help="Source noise multiplier (default: 5; minimum: 3)")
    ghost.add_argument("--ghost-target-sigma", type=float, default=3, help="Target noise multiplier (default: 3)")
    ghost.add_argument("--ghost-correlation-min", type=float, default=0.8, help="Minimum positive Pearson correlation (default: 0.8)")
    tokens = list(argv) if argv is not None else sys.argv[1:]
    args = parser.parse_args(tokens)
    if args.ghosting and args.profile != "off":
        parser.error("--profile on is for the timing benchmark, not interactive ghosting")
    ghost_only = ("--ghost-adc", "--spi-engine", "--vmid", "--ghost-baseline-ms",
                  "--ghost-trigger-counts", "--ghost-trigger-samples", "--ghost-target-counts", "--ghost-trigger-sigma",
                  "--ghost-target-sigma", "--ghost-correlation-min")
    if not args.ghosting and any(token.split("=", 1)[0] in ghost_only for token in tokens):
        parser.error("interactive ghosting options require --ghosting")
    if args.ghosting:
        if args.idle_ms <= 0 or args.grace_ms <= 0:
            parser.error("ghosting idle and grace durations must be positive")
        if bool(args.ghost_adc) == bool(args.route_set_filters):
            parser.error("ghosting requires either --ghost-adc or one --route-set")
        if len(args.route_set_filters) > 1 or len(args.scan_order_filters) > 1:
            parser.error("ghosting uses one route set and one scan order")
        if args.tests or args.smoke_only or args.resume:
            parser.error("ghosting does not support --tests, --smoke-only, or --resume")
        if args.ghost_baseline_ms <= 0:
            parser.error("ghost baseline duration must be positive")
        if not 1 <= args.ghost_trigger_samples <= 64:
            parser.error("ghost trigger confirmation must be 1..64 consecutive samples")
        numeric = (args.ghost_trigger_counts, args.ghost_target_counts,
                   args.ghost_trigger_sigma, args.ghost_target_sigma, args.ghost_correlation_min)
        if not all(math.isfinite(value) for value in numeric):
            parser.error("ghosting thresholds must be finite")
        if args.ghost_trigger_counts <= 0 or args.ghost_target_counts <= 0 or args.ghost_target_sigma <= 0:
            parser.error("ghosting count floors and target sigma must be positive")
        if args.ghost_trigger_sigma < 3 or not 0 <= args.ghost_correlation_min <= 1:
            parser.error("source sigma must be at least 3 and correlation must be 0..1")
        args.requested_window_ms = args.window_ms
        args.requested_repetitions = args.repetitions
        args.window_ms = 2000
        args.repetitions = 1
        if not args.scan_order_filters:
            args.scan_order_filters = ["adc"]
    if args.spi_clocks_hz is None:
        args.spi_clocks_hz = [DEFAULT_SPI_CLOCK_HZ]
    args.spi_clocks_hz = list(dict.fromkeys(args.spi_clocks_hz))
    if args.ghosting and len(args.spi_clocks_hz) != 1:
        parser.error("ghosting uses one SPI speed per session")
    if any(
        clock < MIN_SPI_CLOCK_HZ or clock > MAX_SPI_CLOCK_HZ
        for clock in args.spi_clocks_hz
    ):
        parser.error(
            f"SPI clocks must be {MIN_SPI_CLOCK_HZ}..{MAX_SPI_CLOCK_HZ} Hz"
        )
    if args.window_ms <= 0 or args.warm_up_ms <= 0 or args.repetitions <= 0:
        parser.error("window, warm-up, and repetitions must be positive")
    if args.reader_pause_ms < 0 or args.reader_pause_at_ms < 0:
        parser.error("reader pause durations must be nonnegative")
    if args.reader_pause_ms and args.reader_pause_at_ms + args.reader_pause_ms >= args.warm_up_ms + args.window_ms:
        parser.error("reader pause must finish before the timed run ends")
    if args.ghosting and (args.reader_pause_ms or args.defer_parsing):
        parser.error("reader stress options are for the timing benchmark only")
    if args.settling_tolerance_counts <= 0 or args.settling_stable_frames <= 0:
        parser.error("settling tolerance and stable-frame count must be positive")
    if args.warmup_export_frames <= 0:
        parser.error("warm-up export frame count must be positive")
    if args.resume and args.output is None:
        parser.error("--resume requires --output pointing to an existing session")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.list_ports:
        return list_serial_ports()

    route_sets = load_route_manifest(args.routes)
    if args.ghosting:
        try:
            return run_ghosting_session(args, route_sets)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    bias_resistors = load_bias_resistors(args.bias_map)
    if args.route_set_filters or args.scan_order_filters:
        matrix = build_complete_matrix(
            route_sets,
            args.route_set_filters or tuple(route_sets),
            args.scan_order_filters or ("interleaved",),
            seed=args.seed,
            spi_clocks=args.spi_clocks_hz,
        )
    else:
        matrix = build_test_matrix(
            route_sets, seed=args.seed, spi_clocks=args.spi_clocks_hz
        )
    configs = select_configs(
        matrix,
        args.tests,
        args.smoke_only,
    )
    schedule = make_schedule(
        configs,
        args.repetitions,
        include_drift=not args.no_drift_controls and not args.smoke_only,
    )
    if args.list_tests or args.dry_run:
        print_route_sets(route_sets)
        print_tests(schedule)
        if args.dry_run:
            print("Dry run only; no serial port was opened.")
        return 0
    if not args.port:
        raise SystemExit("--port is required unless --list-tests, --dry-run, or --list-ports is used")

    now = datetime.now(timezone.utc)
    default_output = DEFAULT_RESULTS_ROOT / now.strftime("%Y%m%dT%H%M%SZ")
    output_dir = (args.output or default_output).resolve()
    if args.resume and not output_dir.exists():
        raise SystemExit(f"Resume directory does not exist: {output_dir}")
    if output_dir.exists() and not args.resume and any(output_dir.iterdir()):
        raise SystemExit(f"Output directory is not empty: {output_dir}; use --resume")
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(exist_ok=True)
    results_path = output_dir / "benchmark_results.csv"
    samples_path = output_dir / "benchmark_samples.csv"
    warmup_samples_path = output_dir / "benchmark_warmup_samples.csv"
    channel_stats_path = output_dir / "benchmark_channel_stats.csv"
    metadata_path = output_dir / "session_metadata.json"
    excel_path = output_dir / "benchmark_report.xlsx"
    if args.resume and not metadata_path.exists():
        raise SystemExit(f"Resume metadata does not exist: {metadata_path}")
    previous_metadata = None
    if args.resume:
        previous_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if previous_metadata.get("firmware_profile_mode", "off") != args.profile:
            raise SystemExit("Cannot resume with a different profiling mode; use a fresh output directory")
        for key, value in (("reader_pause_ms", args.reader_pause_ms),
                           ("reader_pause_at_ms", args.reader_pause_at_ms),
                           ("defer_parsing", args.defer_parsing)):
            if previous_metadata.get(key, False if key == "defer_parsing" else (2000 if key == "reader_pause_at_ms" else 0)) != value:
                raise SystemExit("Cannot resume with different reader stress settings; use a fresh output directory")
    log = SessionLog(output_dir / "session_commands.log")

    existing_rows = load_existing_results(results_path)
    completed = completed_repetitions(existing_rows)
    if previous_metadata is not None:
        session_id = previous_metadata["session_id"]
    else:
        session_id = now.strftime("testboard7953-%Y%m%dT%H%M%SZ")

    metadata = {
        "session_id": session_id,
        "firmware_profile_mode": args.profile,
        "reader_pause_ms": args.reader_pause_ms,
        "reader_pause_at_ms": args.reader_pause_at_ms,
        "defer_parsing": args.defer_parsing,
        "runner_version": RUNNER_VERSION,
        "runner_path": str(Path(__file__).resolve()),
        "git_revision": git_revision(),
        "host_platform": platform.platform(),
        "python_version": sys.version,
        "started_utc": now.isoformat(),
        "port": args.port,
        "baud": args.baud,
        "spi_clocks_hz": args.spi_clocks_hz,
        "route_set_filters": args.route_set_filters,
        "scan_order_filters": args.scan_order_filters,
        "route_manifest": str(args.routes.resolve()),
        "bias_resistor_map": str(args.bias_map.resolve()),
        "bias_resistor_routes": len(bias_resistors),
        "window_ms": args.window_ms,
        "warm_up_ms": args.warm_up_ms,
        "repetitions": args.repetitions,
        "vmid_code": args.vmid_code,
        "vmid_warning_tolerance": args.vmid_warning_tolerance,
        "vmid_severe_tolerance": args.vmid_severe_tolerance,
        "cross_mode_floor": args.cross_mode_floor,
        "cross_mode_mad_multiplier": args.cross_mode_mad_multiplier,
        "noise_floor": args.noise_floor,
        "noise_mad_multiplier": args.noise_mad_multiplier,
        "settling_tolerance_counts": args.settling_tolerance_counts,
        "settling_stable_frames": args.settling_stable_frames,
        "warmup_export_frames": args.warmup_export_frames,
        "drift_timing_tolerance_pct": args.drift_timing_tolerance_pct,
        "test_ids": [item.test_id for item in schedule],
        "status": "running",
    }
    atomic_write_json(metadata_path, metadata)

    samples_csv = CsvAppender(samples_path, SAMPLE_FIELDS)
    warmup_samples_csv = CsvAppender(warmup_samples_path, WARMUP_SAMPLE_FIELDS)
    channel_stats_csv: Optional[CsvAppender] = CsvAppender(
        channel_stats_path, CHANNEL_STAT_FIELDS
    )
    results_csv = CsvAppender(results_path, RESULT_FIELDS)
    baselines = load_baselines_from_csv(samples_path, existing_rows)
    warmup_exported_routes = load_warmup_exported_routes(warmup_samples_path)
    serial_port = None
    exit_code = 0
    try:
        serial_port = open_serial_port(args.port, args.baud)
        metadata["serial_port_info"] = {
            "name": getattr(serial_port, "name", args.port),
            "baudrate": getattr(serial_port, "baudrate", args.baud),
            "timeout": getattr(serial_port, "timeout", None),
            "write_timeout": getattr(serial_port, "write_timeout", None),
        }
        protocol = SerialProtocol(serial_port, log)
        protocol.drain_until_idle()
        protocol.send_command("stop")
        identity_lines = protocol.send_command("mcu")
        if FIRMWARE_IDENTITY not in identity_lines:
            raise BenchmarkError(
                f"Expected {FIRMWARE_IDENTITY!r}; received {identity_lines!r}"
            )
        initial_status = parse_status(protocol.send_command("status"))
        initial_status = configure_profile(protocol, initial_status, args.profile)
        metadata["firmware_status_initial"] = initial_status
        atomic_write_json(metadata_path, metadata)
        nonzero_initial = {
            key: counter_value(initial_status, key)
            for key in ERROR_COUNTERS if counter_value(initial_status, key)
        }
        if nonzero_initial:
            if not args.allow_existing_errors:
                raise BenchmarkError(
                    "Firmware started with non-zero error counters; power-cycle "
                    "or pass --allow-existing-errors after investigating: "
                    f"{nonzero_initial}"
                )
            log.write(
                "WARNING continuing with pre-existing cumulative counters: "
                f"{nonzero_initial}"
            )
        if baselines:
            log.write(f"RESTORED {len(baselines)} channel baselines from CSV")

        for spi_clock_hz in args.spi_clocks_hz:
            for smoke in smoke_configs(route_sets, spi_clock_hz):
                log.write(f"SMOKE START {smoke.test_id}")
                run_smoke(protocol, smoke, route_sets[smoke.route_set], args)
                log.write(f"SMOKE PASS {smoke.test_id}")

        total_runs = sum(item.repetitions for item in schedule)
        run_number = 0
        for scheduled in schedule:
            route_set = route_sets[scheduled.config.route_set]
            for repetition in range(1, scheduled.repetitions + 1):
                run_number += 1
                if (scheduled.test_id, repetition) in completed:
                    print(f"[{run_number}/{total_runs}] SKIP {scheduled.test_id} r{repetition}")
                    continue
                print(f"[{run_number}/{total_runs}] RUN  {scheduled.test_id} r{repetition}")
                success = False
                for attempt in (1, 2):
                    try:
                        row = run_measured_repetition(
                            protocol=protocol,
                            session_id=session_id,
                            scheduled=scheduled,
                            repetition=repetition,
                            attempt=attempt,
                            route_set=route_set,
                            args=args,
                            samples_csv=samples_csv,
                            warmup_samples_csv=warmup_samples_csv,
                            channel_stats_csv=channel_stats_csv,
                            results_csv=results_csv,
                            raw_dir=raw_dir,
                            baselines=baselines,
                            warmup_exported_routes=warmup_exported_routes,
                            bias_resistors=bias_resistors,
                        )
                        print(
                            f"    {row['overall_status']} "
                            f"median={float(row['duration_median_us']):.1f} us "
                            f"frames={row['valid_frames']}"
                        )
                        success = True
                        break
                    except BenchmarkError as exc:
                        log.write(
                            f"ATTEMPT FAIL test={scheduled.test_id} "
                            f"repetition={repetition} attempt={attempt}: {exc}"
                        )
                        if attempt == 1:
                            print(f"    attempt 1 failed; recovering: {exc}")
                            recover_with_smoke(
                                protocol,
                                route_set,
                                args,
                                scheduled.config.spi_clock_hz,
                            )
                        else:
                            write_failure_row(
                                results_csv,
                                session_id=session_id,
                                scheduled=scheduled,
                                repetition=repetition,
                                attempt=attempt,
                                route_set=route_set,
                                args=args,
                                message=str(exc),
                            )
                            print(f"    FAIL after retry: {exc}")
                if not success:
                    exit_code = 1
                    raise BenchmarkError(
                        f"Stopping after repeated failure in {scheduled.test_id} r{repetition}"
                    )

        results_csv.close()
        results_csv = None
        rewrite_results_with_aggregates(results_path)
        assert channel_stats_csv is not None
        channel_stats_csv.close()
        channel_stats_csv = None
        metadata["status"] = "complete"
        metadata["completed_utc"] = datetime.now(timezone.utc).isoformat()
        atomic_write_json(metadata_path, metadata)
        if not args.no_excel:
            write_benchmark_workbook(
                excel_path,
                results_path,
                channel_stats_path,
                warmup_samples_path,
                metadata_path,
                GLOSSARY_PATH,
            )
        print(f"Benchmark complete: {output_dir}")
    except (BenchmarkError, OSError, ValueError) as exc:
        exit_code = 1
        metadata["status"] = "failed"
        metadata["failure"] = str(exc)
        metadata["ended_utc"] = datetime.now(timezone.utc).isoformat()
        log.write(f"SESSION FAIL {exc}")
        print(f"Benchmark failed: {exc}", file=sys.stderr)
    except KeyboardInterrupt:
        exit_code = 130
        metadata["status"] = "interrupted"
        metadata["ended_utc"] = datetime.now(timezone.utc).isoformat()
        log.write("SESSION INTERRUPTED")
        print("Benchmark interrupted; completed CSV rows are preserved.", file=sys.stderr)
    finally:
        if serial_port is not None:
            try:
                SerialProtocol(serial_port, log).send_command("stop", timeout_s=2.0)
            except Exception:
                pass
            serial_port.close()
        samples_csv.close()
        warmup_samples_csv.close()
        if channel_stats_csv is not None:
            channel_stats_csv.close()
        if results_csv is not None:
            results_csv.close()
        atomic_write_json(metadata_path, metadata)
        log.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
