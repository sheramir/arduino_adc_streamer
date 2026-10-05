"""Configure, measure and compare TestBoard_ADC124 firmware without the GUI.

Raw bytes and every decoded sample are streamed to disk; memory stays bounded.
Use --dry-run before a hardware session. No serial port is opened in dry-run.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import itertools
import json
import math
from pathlib import Path
import time
from typing import Any, Optional, Sequence

if __package__:
    from .benchmark_common import BinaryFrameParser, uint32_delta
else:
    from benchmark_common import BinaryFrameParser, uint32_delta

HERE = Path(__file__).resolve().parent
DEFAULT_MANIFEST = HERE / "testboard_adc124_routes.json"
REFERENCE_VOLTS = 3.3
COUNTERS = ("transfer_errors", "data_errors")


class BenchmarkError(RuntimeError):
    pass


@dataclass(frozen=True, order=True)
class Route:
    array: int
    mux: int
    input: int

    def __post_init__(self):
        if (self.array not in (1, 2) or self.mux not in (1, 2, 3, 4)
                or self.input not in range(7)
                or (self.input == 6 and self.mux != 4)):
            raise ValueError(f"Not a populated sensor route: {self}")

    @classmethod
    def parse(cls, text: str) -> Route:
        parts = text.split(":")
        if len(parts) != 3 or any(not p.isascii() or not p.isdecimal() for p in parts):
            raise ValueError(f"Expected array:mux:input, got {text!r}")
        return cls(*(int(p) for p in parts))

    def __str__(self):
        return f"{self.array}:{self.mux}:{self.input}"

    @property
    def sensor(self):
        return 7 if self.input >= 5 else (1, 3, 5, 6)[self.mux - 1]

    @property
    def sensor_channel(self):
        return (self.mux if self.input == 5 else 5) if self.sensor == 7 else self.input + 1

    @property
    def bias_ohms(self):
        return ((470000, 1000000, 470000, 1000000),
                (1000000, 470000, 1000000, 470000))[self.array - 1][self.mux - 1]

    @property
    def mux_type(self):
        return "TMUX1108" if self.array == 1 else "TMUX1308A"


def load_manifest(path: Path) -> dict[str, tuple[Route, ...]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("board") != "TestBoard_ADC124" or data.get("schema_version") != 1:
        raise ValueError("Expected TestBoard_ADC124 route manifest schema 1")
    if data.get("reference_volts") != 3.3 or data.get("vmid_volts") != 1.65:
        raise ValueError("Board has fixed 3.3 V reference and 1.65 V Vmid")
    result = {}
    for name, values in data["route_sets"].items():
        routes = tuple(Route.parse(v) for v in values)
        if not routes or len(routes) > 50 or len(set(routes)) != len(routes):
            raise ValueError(f"Empty, oversized or duplicate route set: {name}")
        result[name] = routes
        for route in routes:
            if data.get("bias_resistors_ohms", {}).get(str(route)) != route.bias_ohms:
                raise ValueError(f"Missing or incorrect board bias resistor: {route}")
    return result


def payload_order(routes: Sequence[Route], scanorder: str) -> tuple[Route, ...]:
    keys = {
        "mux": lambda r: (r.array, r.input, r.mux),
        "channel": lambda r: (r.array, r.mux, r.input),
        "interleaved": lambda r: (r.input, r.mux, r.array),
    }
    return tuple(sorted(routes, key=keys[scanorder]))


@dataclass(frozen=True)
class BenchmarkConfig:
    array: str
    scanorder: str
    spiengine: str
    spi_clock_hz: int
    channelrepeat: int
    mux_settle_us: int
    vmid: bool

    @property
    def test_id(self):
        return (f"array{self.array}__{self.scanorder}__{self.spiengine}__"
                f"spi{self.spi_clock_hz}__repeat{self.channelrepeat}__"
                f"settle{self.mux_settle_us}__vmid{'on' if self.vmid else 'off'}")

    @property
    def comparison_key(self):
        return (self.array, self.scanorder, self.spi_clock_hz,
                self.channelrepeat, self.mux_settle_us, self.vmid)


def selected_routes(routes: Sequence[Route], array: str) -> tuple[Route, ...]:
    return tuple(r for r in routes if array == "both" or r.array == int(array))


def build_matrix(args, routes: Sequence[Route]) -> list[BenchmarkConfig]:
    available = sorted({str(r.array) for r in routes})
    arrays = args.arrays or (available + ["both"] if len(available) == 2 else available)
    result = []
    for array, order, clock, settle, repeat, vmid, engine in itertools.product(
            arrays, args.scan_order, args.spi_clock_hz, args.mux_settle_us,
            args.channel_repeat, args.vmid, args.spi_engine):
        if not selected_routes(routes, array):
            raise ValueError(f"Array {array} has no selected routes")
        config = BenchmarkConfig(array, order, engine, clock, repeat, settle, vmid == "on")
        if config not in result:
            result.append(config)
    return result


def parse_status(lines: Sequence[str]) -> dict[str, str]:
    result = {}
    for line in lines:
        if line.startswith("# ") and "=" in line:
            key, value = line[2:].split("=", 1)
            result[key] = value.strip()
    return result


def validate_status(status, config: BenchmarkConfig, routes: Sequence[Route]):
    active = selected_routes(routes, config.array)
    expected = {
        "board": "TestBoard_ADC124", "protocol_version": "1", "mode": "PZT",
        "array": config.array, "scanorder": config.scanorder,
        "spiengine": config.spiengine, "spi_clock_hz": str(config.spi_clock_hz),
        "channelrepeat": str(config.channelrepeat), "mux_settle_us": str(config.mux_settle_us),
        "vmid_between_groups": str(config.vmid).lower(), "vmid_address": "7",
        "vmid_parking": "mandatory", "vref": "3.3", "vmid_volts": "1.65",
        "active_spi_buses": "1", "mux_enable_active_high": "true,false",
        "adcchannels": ",".join(map(str, routes)),
        "payload_routes": ",".join(map(str, payload_order(active, config.scanorder))),
        "route_count": str(len(active)),
    }
    mismatches = [f"{key}: expected {value!r}, got {status.get(key)!r}"
                  for key, value in expected.items() if status.get(key) != value]
    for key in (*COUNTERS, "sweep_count"):
        if not status.get(key, "").isascii() or not status.get(key, "").isdecimal():
            mismatches.append(f"missing/invalid counter {key}")
    if mismatches:
        raise BenchmarkError("Status mismatch: " + "; ".join(mismatches))


class SerialProtocol:
    def __init__(self, serial_port, log):
        self.serial = serial_port
        self.log = log

    def log_line(self, text):
        self.log.write(f"{datetime.now(timezone.utc).isoformat()} {text}\n")
        self.log.flush()

    def drain(self, idle_s=0.15, limit_s=3.0):
        deadline = time.monotonic() + limit_s
        idle = time.monotonic() + idle_s
        while time.monotonic() < deadline:
            if self.serial.read(min(self.serial.in_waiting, 65536) or 1):
                idle = time.monotonic() + idle_s
            elif time.monotonic() >= idle:
                return
        raise BenchmarkError("Serial stream did not become idle")

    def command(self, command, timeout_s=3.0):
        self.log_line("> " + command + "*")
        self.serial.write((command + "*").encode("ascii"))
        self.serial.flush()
        deadline = time.monotonic() + timeout_s
        pending = bytearray()
        lines = []
        while time.monotonic() < deadline:
            data = self.serial.read(min(self.serial.in_waiting, 65536) or 1)
            pending.extend(data)
            if len(pending) > 16384:
                raise BenchmarkError("Oversized command response")
            while b"\n" in pending:
                line, _, pending = pending.partition(b"\n")
                line = line.rstrip(b"\r").decode("ascii", errors="replace")
                self.log_line("< " + line)
                lines.append(line)
                if line == "#NOT_OK" or line.startswith("#NOT_OK "):
                    raise BenchmarkError(f"Firmware rejected {command!r}: {lines}")
                if line == "#OK" or line.startswith("#OK "):
                    return lines
        raise BenchmarkError(f"Timed out waiting for ACK: {command}")

    def stop_and_drain(self):
        # Stop may arrive while binary data are queued. Consume it before
        # asking a text command to decode its own ACK.
        self.serial.write(b"stop*")
        self.serial.flush()
        self.drain()


def configure(protocol: SerialProtocol, config: BenchmarkConfig, routes):
    protocol.command("stop")
    for command in ("mode PZT", f"array {config.array}",
                    "adcchannels " + ",".join(map(str, routes)),
                    f"scanorder {config.scanorder}", "ref 3.3",
                    f"spiengine {config.spiengine}", f"spiclock {config.spi_clock_hz}",
                    f"channelrepeat {config.channelrepeat}", f"muxsettle {config.mux_settle_us}",
                    "vmid " + str(config.vmid).lower()):
        protocol.command(command)
    status = parse_status(protocol.command("status"))
    validate_status(status, config, routes)
    if any(int(status[k]) for k in COUNTERS):
        raise BenchmarkError("Firmware has existing error counters; reset the Teensy")
    return status


@dataclass
class OnlineStats:
    count: int = 0
    mean: float = 0.0
    m2: float = 0.0
    minimum: float = math.inf
    maximum: float = -math.inf

    def add(self, value):
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        self.m2 += delta * (value - self.mean)
        self.minimum = min(self.minimum, value)
        self.maximum = max(self.maximum, value)

    @property
    def stdev(self):
        return math.sqrt(max(0, self.m2 / (self.count - 1))) if self.count > 1 else 0.0


SAMPLE_FIELDS = ("phase", "sweep", "device_start_us", "device_end_us", "device_elapsed_us",
                 "host_received_ns", "payload_index", "route", "array", "adc_input", "mux",
                 "mux_type", "mux_input", "sensor", "sensor_channel", "bias_resistor_ohms",
                 "code", "volts")
CHANNEL_FIELDS = ("test_id", "repetition", "route", "array", "mux_type", "mux", "mux_input",
                  "sensor", "sensor_channel", "bias_resistor_ohms", "count", "mean_code",
                  "stdev_code", "min_code", "max_code", "mean_volts", "vmid_offset_code", "clipped_samples")
RESULT_FIELDS = ("test_id", "repetition", "result", "reason", "array", "scanorder", "spiengine",
                 "spi_clock_hz", "channelrepeat", "mux_settle_us", "vmid", "route_count",
                 "measured_frames", "warmup_frames", "device_span_us", "sweeps_per_second",
                 "samples_per_second", "mean_acquisition_us", "mean_sweep_period_us",
                 "min_sweep_period_us", "max_sweep_period_us", "invalid_frames", "discarded_bytes",
                 "resync_events", "trailing_bytes", "timed_out", "transfer_errors", "data_errors",
                 "firmware_sweeps", "received_frames")


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def capture(protocol, config, routes, args, directory):
    """Stream one continuous warm-up + measured run to per-run artifacts."""
    before = configure(protocol, config, routes)
    order = payload_order(selected_routes(routes, config.array), config.scanorder)
    parser = BinaryFrameParser(expected_sample_count=len(order), max_sample_count=50)
    stats = {r: OnlineStats() for r in order}
    clipped = {r: 0 for r in order}
    durations, periods = OnlineStats(), OnlineStats()
    first_start = last_start = measured_first = measured_end = None
    elapsed_us = warmup_frames = measured_frames = received_frames = 0
    out_of_range = False
    total_ms = args.warm_up_ms + args.window_ms
    now = time.monotonic()
    minimum_end = now + total_ms / 1000
    deadline = minimum_end + args.grace_ms / 1000
    last_data = now
    timed_out = True
    directory.mkdir()
    raw_file = None
    try:
        if not args.no_raw:
            raw_file = (directory / "capture.bin").open("wb")
        with (directory / "samples.csv").open("w", encoding="utf-8", newline="") as sample_file:
            writer = csv.DictWriter(sample_file, fieldnames=SAMPLE_FIELDS)
            writer.writeheader()
            protocol.log_line(f"> run {total_ms}* (binary)")
            protocol.serial.write(f"run {total_ms}*".encode("ascii"))
            protocol.serial.flush()
            while time.monotonic() < deadline:
                data = protocol.serial.read(min(protocol.serial.in_waiting, 65536) or 1)
                now = time.monotonic()
                if not data:
                    if now >= minimum_end and now - last_data >= args.idle_ms / 1000:
                        timed_out = False
                        break
                    continue
                last_data = now
                if raw_file:
                    raw_file.write(data)
                for frame in parser.feed(data, time.monotonic_ns()):
                    if first_start is None:
                        first_start = frame.block_start_us
                    if last_start is not None:
                        elapsed_us += uint32_delta(frame.block_start_us, last_start)
                    measured = elapsed_us >= args.warm_up_ms * 1000
                    received_frames += 1
                    if measured:
                        if measured_first is None:
                            measured_first = frame.block_start_us
                        elif last_start is not None:
                            periods.add(uint32_delta(frame.block_start_us, last_start))
                        measured_end = frame.block_end_us
                        durations.add(frame.acquisition_duration_us)
                        measured_frames += 1
                    else:
                        warmup_frames += 1
                    for index, (route, code) in enumerate(zip(order, frame.samples)):
                        out_of_range |= code > 4095
                        if measured:
                            stats[route].add(code)
                            clipped[route] += code in (0, 4095)
                        writer.writerow({
                            "phase": "measurement" if measured else "warmup",
                            "sweep": received_frames - 1, "device_start_us": frame.block_start_us,
                            "device_end_us": frame.block_end_us, "device_elapsed_us": elapsed_us,
                            "host_received_ns": frame.host_received_ns, "payload_index": index,
                            "route": str(route), "array": route.array, "adc_input": route.mux - 1,
                            "mux": route.mux, "mux_type": route.mux_type, "mux_input": route.input,
                            "sensor": f"PZT{route.sensor}", "sensor_channel": route.sensor_channel,
                            "bias_resistor_ohms": route.bias_ohms,
                            "code": code, "volts": code * REFERENCE_VOLTS / 4096,
                        })
                    last_start = frame.block_start_us
    finally:
        if raw_file:
            raw_file.close()
        protocol.stop_and_drain()
    trailing = parser.finish()
    after = parse_status(protocol.command("status"))
    validate_status(after, config, routes)
    errors = {k: uint32_delta(int(after[k]), int(before[k])) for k in COUNTERS}
    firmware_sweeps = uint32_delta(int(after["sweep_count"]), int(before["sweep_count"]))
    failures = []
    warnings = []
    if timed_out: failures.append("capture did not become idle before deadline")
    if parser.invalid_frames or parser.discarded_bytes or trailing:
        failures.append("malformed or incomplete binary stream")
    if out_of_range: failures.append("ADC code exceeds 4095")
    if any(errors.values()): failures.append("new firmware errors")
    if received_frames != firmware_sweeps: failures.append("received/firmware sweep count mismatch")
    if measured_frames < 2: failures.append("fewer than two measured frames")
    span = uint32_delta(measured_end, measured_first) if measured_end is not None else 0
    if span < args.window_ms * 1000 * 0.8:
        failures.append("measured device duration below 80% of requested window")
    channel_rows = []
    for route, stat in stats.items():
        if not stat.count:
            continue
        if abs(stat.mean - 2048) > args.vmid_warn_counts:
            warnings.append(f"{route}: Vmid offset")
        if stat.stdev > args.noise_warn_counts:
            warnings.append(f"{route}: noise")
        if clipped[route]: warnings.append(f"{route}: clipping")
        channel_rows.append({"route": str(route), "array": route.array, "mux_type": route.mux_type,
            "mux": route.mux, "mux_input": route.input, "sensor": f"PZT{route.sensor}",
            "sensor_channel": route.sensor_channel, "bias_resistor_ohms": route.bias_ohms,
            "count": stat.count, "mean_code": stat.mean, "stdev_code": stat.stdev,
            "min_code": stat.minimum, "max_code": stat.maximum,
            "mean_volts": stat.mean * REFERENCE_VOLTS / 4096,
            "vmid_offset_code": stat.mean - 2048, "clipped_samples": clipped[route]})
    rate = 1e6 / periods.mean if periods.count and periods.mean else 0
    result = {**asdict(config), "test_id": config.test_id,
        "result": "FAIL" if failures else "WARN" if warnings else "PASS",
        "reason": "; ".join(failures + warnings), "route_count": len(order),
        "measured_frames": measured_frames, "warmup_frames": warmup_frames, "device_span_us": span,
        "sweeps_per_second": rate, "samples_per_second": rate * len(order),
        "mean_acquisition_us": durations.mean, "mean_sweep_period_us": periods.mean,
        "min_sweep_period_us": periods.minimum if periods.count else "",
        "max_sweep_period_us": periods.maximum if periods.count else "",
        "invalid_frames": parser.invalid_frames, "discarded_bytes": parser.discarded_bytes,
        "resync_events": parser.resync_events, "trailing_bytes": trailing, "timed_out": timed_out,
        **errors, "firmware_sweeps": firmware_sweeps, "received_frames": received_frames}
    write_json(directory / "status.json", {"before": before, "after": after})
    return result, channel_rows


COMPARISON_FIELDS = ("test_id", "repetition", "baseline_test_id", "route", "result",
                     "mean_shift_code", "noise_ratio", "throughput_ratio")


def comparisons(results, channels, configs, threshold):
    by_id = {c.test_id: c for c in configs}
    baselines = {(by_id[r["test_id"]].comparison_key, r["repetition"]): r
                 for r in results if r["spiengine"] == "blocking" and r["result"] != "FAIL"}
    channel_map = {(r["test_id"], r["repetition"], r["route"]): r for r in channels}
    rows = []
    for result in results:
        if result["spiengine"] == "blocking" or result["result"] == "FAIL":
            continue
        baseline = baselines.get((by_id[result["test_id"]].comparison_key, result["repetition"]))
        if not baseline:
            continue
        for key, channel in channel_map.items():
            if key[:2] != (result["test_id"], result["repetition"]):
                continue
            reference = channel_map[(baseline["test_id"], baseline["repetition"], key[2])]
            shift = channel["mean_code"] - reference["mean_code"]
            rows.append({"test_id": result["test_id"], "repetition": result["repetition"],
                "baseline_test_id": baseline["test_id"], "route": key[2],
                "result": "WARN" if abs(shift) > threshold else "PASS", "mean_shift_code": shift,
                "noise_ratio": channel["stdev_code"] / reference["stdev_code"] if reference["stdev_code"] else "",
                "throughput_ratio": result["sweeps_per_second"] / baseline["sweeps_per_second"]
                    if baseline["sweeps_per_second"] else ""})
    return rows


def write_workbook(output, results, channels, comparison_rows):
    import xlsxwriter
    with xlsxwriter.Workbook(str(output / "benchmark_report.xlsx"),
                            {"strings_to_formulas": False, "strings_to_urls": False}) as workbook:
        header = workbook.add_format({"bold": True, "bg_color": "#DCE6F1"})
        for name, fields, rows in (("Results", RESULT_FIELDS, results),
                                  ("Channels", CHANNEL_FIELDS, channels),
                                  ("Engine comparisons", COMPARISON_FIELDS, comparison_rows)):
            sheet = workbook.add_worksheet(name)
            sheet.freeze_panes(1, 2)
            sheet.set_column(0, 0, 85)
            sheet.set_column(1, len(fields) - 1, 20)
            sheet.write_row(0, 0, fields, header)
            for index, row in enumerate(rows, 1):
                sheet.write_row(index, 0, [row.get(field, "") for field in fields])
            sheet.autofilter(0, 0, len(rows), len(fields) - 1)
        notes = workbook.add_worksheet("Notes")
        notes.set_column(0, 0, 120)
        for index, line in enumerate((
                "TestBoard_ADC124: 3.3 V fixed reference, 1.65 V Vmid, codes 0..4095.",
                "Voltage = code * 3.3 / 4096; numbered sensor channels 1..5 have no assumed spatial orientation.",
                "Rate uses device sweep-start timestamps; the ADCs transfer sequentially on one SPI bus.",
                "Engine comparisons match all settings and repetition to a passing/warning blocking run.",
                "WARN is an analog offset/noise/clipping or engine mean-shift advisory, not proof of channel identity.",
                "Missing comparisons mean no matching successful blocking baseline was captured.",
                "Requested SCLK is not a measurement; verify actual SCLK and analog settling on hardware.")):
            notes.write(index, 0, line)


def parse_args(argv: Optional[Sequence[str]] = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port")
    parser.add_argument("--list-ports", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--smoke-only", action="store_true")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--route-set", default="both_full")
    parser.add_argument("--sensors", nargs="+", type=int, choices=(1, 3, 5, 6, 7))
    parser.add_argument("--routes", help="Explicit comma-separated array:mux:input sensor routes")
    parser.add_argument("--arrays", nargs="+", choices=("1", "2", "both"))
    parser.add_argument("--scan-order", nargs="+", choices=("mux", "channel", "interleaved"), default=["mux", "channel"])
    parser.add_argument("--spi-engine", nargs="+", choices=("blocking", "dma", "lpspi"), default=["blocking", "dma", "lpspi"])
    parser.add_argument("--spi-clock-hz", nargs="+", type=int, default=[16000000])
    parser.add_argument("--channel-repeat", nargs="+", type=int, default=[1])
    parser.add_argument("--mux-settle-us", nargs="+", type=int, default=[2, 5])
    parser.add_argument("--vmid", nargs="+", choices=("off", "on"), default=["off"])
    parser.add_argument("--warm-up-ms", type=int, default=1000)
    parser.add_argument("--window-ms", type=int, default=5000)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--idle-ms", type=int, default=150)
    parser.add_argument("--grace-ms", type=int, default=3000)
    parser.add_argument("--vmid-warn-counts", type=float, default=100)
    parser.add_argument("--noise-warn-counts", type=float, default=10)
    parser.add_argument("--shift-warn-counts", type=float, default=5)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-raw", action="store_true")
    parser.add_argument("--no-excel", action="store_true")
    args = parser.parse_args(argv)
    for values, minimum, maximum, label in (
            (args.spi_clock_hz, 8000000, 16000000, "SPI clock"),
            (args.channel_repeat, 1, 3, "channel repeat"),
            (args.mux_settle_us, 0, 1000, "MUX settling delay")):
        if any(v < minimum or v > maximum for v in values):
            parser.error(f"{label} must be in {minimum}..{maximum}")
    if (args.warm_up_ms < 0 or args.window_ms < 1 or args.repetitions < 1
            or args.warm_up_ms + args.window_ms > 3600000
            or args.idle_ms < 1 or args.grace_ms <= args.idle_ms):
        parser.error("Invalid duration/repetitions; total run <= 3600000 ms; grace > idle > 0")
    if any(not math.isfinite(v) or v < 0 for v in
           (args.vmid_warn_counts, args.noise_warn_counts, args.shift_warn_counts)):
        parser.error("Warning thresholds must be finite and nonnegative")
    if args.smoke_only:
        args.scan_order = ["mux"]
        args.mux_settle_us = [5]
        args.channel_repeat = [1]
        args.vmid = ["off"]
        args.repetitions = 1
        args.window_ms = min(args.window_ms, 1000)
    return args


def main(argv: Optional[Sequence[str]] = None):
    args = parse_args(argv)
    if args.list_ports:
        from serial.tools import list_ports
        for port in list_ports.comports():
            print(f"{port.device}: {port.description}")
        return 0
    manifest = load_manifest(args.manifest)
    if args.route_set not in manifest:
        raise ValueError(f"Unknown route set {args.route_set!r}; choose {', '.join(manifest)}")
    routes = tuple(Route.parse(r.strip()) for r in args.routes.split(",")) if args.routes else manifest[args.route_set]
    if args.sensors:
        routes = tuple(r for r in routes if r.sensor in args.sensors)
    if not routes or len(routes) > 50 or len(set(routes)) != len(routes):
        raise ValueError("Select 1..50 distinct populated routes")
    configs = build_matrix(args, routes)
    for config in configs:
        print(f"{config.test_id} ({len(selected_routes(routes, config.array))} samples/frame)")
    print(f"{len(configs)} configurations x {args.repetitions} repetitions; "
          f"{args.warm_up_ms} ms warm-up + {args.window_ms} ms measured per run")
    if args.dry_run:
        return 0
    if not args.port:
        raise ValueError("--port is required unless using --dry-run or --list-ports")
    output = args.output or HERE / "results" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    output.mkdir(parents=True, exist_ok=False)
    metadata = {"schema_version": 1, "board": "TestBoard_ADC124", "created_utc": datetime.now(timezone.utc).isoformat(),
        "reference_volts": REFERENCE_VOLTS, "vmid_volts": 1.65,
        "arguments": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
        "manifest": json.loads(args.manifest.read_text(encoding="utf-8")),
        "routes": [str(r) for r in routes], "configs": [asdict(c) for c in configs], "state": "running"}
    write_json(output / "session.json", metadata)
    results, channels, comparison_rows = [], [], []
    serial_port = protocol = None
    exit_code = 0
    try:
        import serial
        with (output / "commands.log").open("w", encoding="utf-8") as log:
            serial_port = serial.Serial(args.port, baudrate=460800, timeout=0.02, write_timeout=3)
            protocol = SerialProtocol(serial_port, log)
            try:
                protocol.stop_and_drain()
                identity = protocol.command("mcu")
                if "# TestBoard_ADC124" not in identity:
                    raise BenchmarkError(f"Wrong firmware: {identity}")
                for config in configs:
                    for repetition in range(1, args.repetitions + 1):
                        print(f"Capture {config.test_id} repetition {repetition}", flush=True)
                        directory = output / f"{config.test_id}__rep{repetition}"
                        try:
                            result, channel_rows = capture(protocol, config, routes, args, directory)
                        except (BenchmarkError, OSError, ValueError) as error:
                            result = {**asdict(config), "test_id": config.test_id,
                                      "result": "FAIL", "reason": str(error)}
                            channel_rows = []
                        result["repetition"] = repetition
                        for row in channel_rows:
                            row.update(test_id=config.test_id, repetition=repetition)
                        results.append(result)
                        channels.extend(channel_rows)
                        write_csv(output / "results.csv", RESULT_FIELDS, results)
                        write_csv(output / "channel_stats.csv", CHANNEL_FIELDS, channels)
                        comparison_rows = comparisons(results, channels, configs, args.shift_warn_counts)
                        write_csv(output / "comparisons.csv", COMPARISON_FIELDS, comparison_rows)
                        print(f"{result['result']}: {result.get('reason') or 'stream validated'}", flush=True)
                        if result["result"] == "FAIL":
                            # Fail fast: preserve artifacts and require investigation/reset.
                            raise BenchmarkError(result["reason"])
                metadata["state"] = "complete"
            finally:
                if protocol:
                    try:
                        protocol.stop_and_drain()
                    except (BenchmarkError, OSError) as error:
                        metadata["cleanup_error"] = str(error)
                        if metadata["state"] == "complete":
                            raise
    except KeyboardInterrupt:
        metadata["state"] = "interrupted"
        exit_code = 130
    except (BenchmarkError, OSError, ValueError) as error:
        metadata["state"] = "failed"
        metadata["error"] = str(error)
        print(f"FAIL: {error}")
        exit_code = 1
    finally:
        if serial_port:
            serial_port.close()
        write_json(output / "session.json", metadata)
        if not args.no_excel and results:
            try:
                write_workbook(output, results, channels, comparison_rows)
            except (ImportError, OSError) as error:
                print(f"Workbook export failed; CSV artifacts are saved: {error}")
                exit_code = exit_code or 1
    print(f"Artifacts: {output}")
    return exit_code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BenchmarkError, ValueError, OSError) as error:
        raise SystemExit(str(error))
