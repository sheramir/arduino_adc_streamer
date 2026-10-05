import csv
import io
import json
import struct
from types import SimpleNamespace

import pytest

from Arduino_Sketches.TestBoard_ADC124.benchmarks import testboard_adc124_benchmark as bench
from Arduino_Sketches.TestBoard_ADC124.benchmarks.benchmark_common import BinaryFrameParser


def test_wiring_population_pzt7_and_bias_resistors():
    manifest = bench.load_manifest(bench.DEFAULT_MANIFEST)
    assert len(manifest["full_array1"]) == len(manifest["full_array2"]) == 25
    assert len(manifest["both_full"]) == 50
    assert len(manifest["pzt7_both"]) == 10
    for array in (1, 2):
        pzt7 = [r for r in manifest["pzt7_both"] if r.array == array]
        assert [(r.mux, r.input, r.sensor_channel) for r in pzt7] == [
            (1, 5, 1), (2, 5, 2), (3, 5, 3), (4, 5, 4), (4, 6, 5)]
    assert [bench.Route(1, mux, 0).bias_ohms for mux in range(1, 5)] == [470000, 1000000, 470000, 1000000]
    assert [bench.Route(2, mux, 0).bias_ohms for mux in range(1, 5)] == [1000000, 470000, 1000000, 470000]
    assert {r.sensor for r in manifest["both_full"]} == {1, 3, 5, 6, 7}


@pytest.mark.parametrize("text", ["1:1:6", "1:4:7", "0:1:0", "3:1:0", "1:5:0", "1:1:-1", "1:0", "1:1:1.0", "1:1:0:0"])
def test_reserved_unknown_and_malformed_routes_rejected(text):
    with pytest.raises(ValueError):
        bench.Route.parse(text)


def test_manifest_cannot_silently_override_fixed_reference_or_bias(tmp_path):
    data = json.loads(bench.DEFAULT_MANIFEST.read_text())
    data["bias_resistors_ohms"]["1:1:0"] = 249000
    path = tmp_path / "routes.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="bias resistor"):
        bench.load_manifest(path)


def test_scan_orders_keep_identity_and_group_mux_addresses():
    routes = tuple(bench.Route.parse(r) for r in ("2:4:6", "1:3:0", "2:1:0", "1:1:0", "1:1:1"))
    assert tuple(map(str, bench.payload_order(routes, "mux"))) == (
        "1:1:0", "1:3:0", "1:1:1", "2:1:0", "2:4:6")
    assert tuple(map(str, bench.payload_order(routes, "channel"))) == (
        "1:1:0", "1:1:1", "1:3:0", "2:1:0", "2:4:6")
    assert tuple(map(str, bench.payload_order(routes, "interleaved"))) == (
        "1:1:0", "2:1:0", "1:3:0", "1:1:1", "2:4:6")


def test_default_matrix_and_smoke_cover_both_arrays_all_engines():
    routes = bench.load_manifest(bench.DEFAULT_MANIFEST)["both_full"]
    configs = bench.build_matrix(bench.parse_args(["--dry-run"]), routes)
    assert len(configs) == 36
    assert len({c.test_id for c in configs}) == len(configs)
    assert {c.array for c in configs} == {"1", "2", "both"}
    smoke = bench.build_matrix(bench.parse_args(["--smoke-only"]), routes)
    assert len(smoke) == 9
    assert {c.spiengine for c in smoke} == {"blocking", "dma", "lpspi"}


@pytest.mark.parametrize("args", [["--spi-clock-hz", "20000000"], ["--spi-clock-hz", "7999999"],
    ["--channel-repeat", "0"], ["--mux-settle-us", "1001"], ["--window-ms", "0"],
    ["--repetitions", "0"], ["--warm-up-ms", "3600000"], ["--noise-warn-counts", "nan"]])
def test_invalid_options_rejected(args):
    with pytest.raises(SystemExit):
        bench.parse_args(args)


def status_for(config, routes, sweeps=0):
    return {"board": "TestBoard_ADC124", "protocol_version": "1", "mode": "PZT",
        "array": config.array, "scanorder": config.scanorder, "spiengine": config.spiengine,
        "spi_clock_hz": str(config.spi_clock_hz), "channelrepeat": str(config.channelrepeat),
        "mux_settle_us": str(config.mux_settle_us), "vmid_between_groups": str(config.vmid).lower(),
        "vmid_address": "7", "vmid_parking": "mandatory", "vref": "3.3", "vmid_volts": "1.65",
        "active_spi_buses": "1", "mux_enable_active_high": "true,false",
        "adcchannels": ",".join(map(str, routes)),
        "payload_routes": ",".join(map(str, bench.payload_order(bench.selected_routes(routes, config.array), config.scanorder))),
        "route_count": str(len(bench.selected_routes(routes, config.array))),
        "transfer_errors": "0", "data_errors": "0", "sweep_count": str(sweeps)}


@pytest.mark.parametrize("field,value", [("payload_routes", "1:1:0"), ("mux_enable_active_high", "true,true"),
    ("vref", "2.5"), ("active_spi_buses", "1,2"), ("data_errors", "missing")])
def test_status_rejects_wrong_board_assumptions(field, value):
    routes = bench.load_manifest(bench.DEFAULT_MANIFEST)["full_array1"]
    config = bench.BenchmarkConfig("1", "mux", "blocking", 16000000, 1, 5, False)
    status = status_for(config, routes)
    status[field] = value
    with pytest.raises(bench.BenchmarkError, match="Status mismatch"):
        bench.validate_status(status, config, routes)


def make_frame(samples, start, duration=100):
    return b"\xaa\x55" + struct.pack("<H", len(samples)) + struct.pack(f"<{len(samples)}H", *samples) + struct.pack(
        "<HII", duration // len(samples), start & 0xffffffff, (start + duration) & 0xffffffff)


def test_parser_chunking_timestamps_wrong_width_and_incomplete_tail():
    raw = make_frame((123, 2048), 0xfffffff0)
    parser = BinaryFrameParser(expected_sample_count=2, max_sample_count=50)
    frames = []
    for byte in raw:
        frames.extend(parser.feed(bytes([byte])))
    assert frames[0].samples == (123, 2048)
    assert frames[0].acquisition_duration_us == 100
    assert parser.feed(make_frame((5,), 100)) == []
    assert parser.invalid_frames == 1
    parser.feed(raw[:-1])
    assert parser.finish() == len(raw) - 1


class FakeClock:
    value = 0.0

    def monotonic(self):
        return self.value

    def monotonic_ns(self):
        return int(self.value * 1e9)


class FakeSerial:
    """A fragmented mixed text/binary USB stream with one-frame captures."""
    def __init__(self, clock, config, routes, *, corrupt=False, drop=False):
        self.clock, self.config, self.routes = clock, config, routes
        self.pending = bytearray()
        self.writes = []
        self.sweeps = 0
        self.corrupt, self.drop = corrupt, drop

    @property
    def in_waiting(self):
        return len(self.pending)

    def read(self, count):
        self.clock.value += 0.0001 if self.pending else 0.001
        count = min(count, 19)  # deliberately split headers, samples, ACKs
        value = bytes(self.pending[:count])
        del self.pending[:count]
        return value

    def write(self, data):
        self.writes.append(data)
        command = data.decode().rstrip("*")
        if command.startswith("run "):
            for index in range(5):
                samples = (2000 + index, 2100 + index)
                if self.corrupt and index == 2:
                    samples = (65535, 2048)
                if not (self.drop and index == 2):
                    self.pending.extend(make_frame(samples, 0xfffffff0 + index * 1000))
            self.sweeps += 5
            return len(data)
        if command == "status":
            status = status_for(self.config, self.routes, self.sweeps)
            self.pending.extend("".join(f"# {k}={v}\n" for k, v in status.items()).encode())
        elif command == "mcu":
            self.pending.extend(b"# TestBoard_ADC124\n")
        self.pending.extend(b"#OK\n")
        return len(data)

    def flush(self):
        pass

    def close(self):
        pass


@pytest.mark.parametrize("corrupt,drop,expected", [(False, False, "PASS"), (True, False, "FAIL"), (False, True, "FAIL")])
def test_capture_streams_warmup_samples_and_detects_dropped_or_invalid_frames(tmp_path, monkeypatch, corrupt, drop, expected):
    clock = FakeClock()
    monkeypatch.setattr(bench, "time", clock)
    routes = (bench.Route(1, 1, 0), bench.Route(1, 4, 6))
    config = bench.BenchmarkConfig("1", "mux", "blocking", 16000000, 1, 5, False)
    serial = FakeSerial(clock, config, routes, corrupt=corrupt, drop=drop)
    protocol = bench.SerialProtocol(serial, io.StringIO())
    args = bench.parse_args(["--warm-up-ms", "1", "--window-ms", "3", "--idle-ms", "1", "--grace-ms", "100"])
    result, channels = bench.capture(protocol, config, routes, args, tmp_path / "run")
    assert result["result"] == expected
    assert result["warmup_frames"] == 1
    assert result["firmware_sweeps"] == 5
    assert result["received_frames"] == (4 if drop else 5)
    assert serial.writes[-2:] == [b"stop*", b"status*"]
    rows = list(csv.DictReader((tmp_path / "run" / "samples.csv").open()))
    assert rows[0]["phase"] == "warmup"
    assert rows[0]["volts"] == str(2000 * 3.3 / 4096)
    assert rows[1]["sensor"] == "PZT7"
    assert rows[1]["sensor_channel"] == "5"
    assert rows[1]["bias_resistor_ohms"] == "1000000"
    assert rows[2]["device_elapsed_us"] == "1000"
    if not corrupt and not drop:
        assert result["sweeps_per_second"] == 1000
        assert channels[0]["mean_code"] == 2002.5
    assert (tmp_path / "run" / "capture.bin").stat().st_size > 0


def test_command_rejection_and_no_ack_timeout(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(bench, "time", clock)
    serial = FakeSerial(clock, None, ())
    serial.pending.extend(b"#NOT_OK\n")
    protocol = bench.SerialProtocol(serial, io.StringIO())
    with pytest.raises(bench.BenchmarkError, match="rejected"):
        protocol.command("mode PZR")
    serial.pending.clear()
    serial.write = lambda data: len(data)
    with pytest.raises(bench.BenchmarkError, match="Timed out"):
        protocol.command("status", timeout_s=0.01)


def test_comparisons_match_routes_settings_and_repetition():
    base = bench.BenchmarkConfig("both", "mux", "blocking", 16000000, 1, 5, False)
    dma = bench.BenchmarkConfig("both", "mux", "dma", 16000000, 1, 5, False)
    results = [{**bench.asdict(c), "test_id": c.test_id, "repetition": 1,
                "result": "PASS", "sweeps_per_second": rate}
               for c, rate in ((base, 1000), (dma, 500))]
    channels = [{"test_id": c.test_id, "repetition": 1, "route": "2:4:6", "mean_code": mean, "stdev_code": 2}
                for c, mean in ((base, 2048), (dma, 2060))]
    rows = bench.comparisons(results, channels, [base, dma], 5)
    assert len(rows) == 1
    assert rows[0]["mean_shift_code"] == 12
    assert rows[0]["throughput_ratio"] == 0.5
    assert rows[0]["result"] == "WARN"
    results[0]["result"] = "FAIL"
    assert bench.comparisons(results, channels, [base, dma], 5) == []


def test_dry_run_does_not_create_output_or_open_serial(tmp_path):
    output = tmp_path / "unused"
    assert bench.main(["--dry-run", "--output", str(output), "--routes", "1:4:6", "--sensors", "7"]) == 0
    assert not output.exists()


def test_main_fake_session_writes_reviewable_csv_json_workbook(tmp_path, monkeypatch):
    import serial
    clock = FakeClock()
    monkeypatch.setattr(bench, "time", clock)
    routes = (bench.Route(1, 1, 0), bench.Route(1, 4, 6))
    config = bench.BenchmarkConfig("1", "mux", "blocking", 16000000, 1, 5, False)
    device = FakeSerial(clock, config, routes)
    monkeypatch.setattr(serial, "Serial", lambda *a, **k: device)
    output = tmp_path / "session"
    assert bench.main(["--port", "FAKE", "--output", str(output), "--routes", "1:1:0,1:4:6",
        "--scan-order", "mux", "--spi-engine", "blocking", "--mux-settle-us", "5",
        "--warm-up-ms", "1", "--window-ms", "3", "--repetitions", "1",
        "--idle-ms", "1", "--grace-ms", "100"]) == 0
    assert json.loads((output / "session.json").read_text())["state"] == "complete"
    assert (output / "benchmark_report.xlsx").stat().st_size > 0
    rows = list(csv.DictReader((output / "results.csv").open()))
    assert rows[0]["result"] == "PASS"
    assert len(list(csv.DictReader((output / "channel_stats.csv").open()))) == 2
    assert device.writes[-1] == b"stop*"
