"""Hardware-free regression coverage for the interactive ghosting workflow."""

import csv
import json
import struct
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import pytest

from Arduino_Sketches.TestBoard_7953.benchmarks import testboard_7953_benchmark as runner
from Arduino_Sketches.TestBoard_7953.benchmarks.benchmark_common import BinaryFrameParser
from Arduino_Sketches.TestBoard_7953.benchmarks.excel_report import write_ghosting_workbook
from Arduino_Sketches.TestBoard_7953.benchmarks.ghosting_analysis import (
    analyze_window, calibrate, chart_bounds, chart_indices, strongest_attempt, summarize_attempts,
)
from Arduino_Sketches.TestBoard_7953.benchmarks.ghosting_capture import (
    GhostingCapture, GhostingCaptureError, capture_ghosting_attempt, stop_stream,
)


def frame(samples, started):
    return (b"\xaa\x55" + struct.pack("<H", len(samples)) + struct.pack(f"<{len(samples)}H", *samples)
            + struct.pack("<HII", 1, started & 0xFFFFFFFF, (started + 10) & 0xFFFFFFFF))


def ghost_args(*extra):
    return runner.parse_args(["--ghosting", "--ghost-adc", "1", *extra])


@pytest.mark.parametrize("adc,count,array", [(1, 10, "1"), (2, 15, "1"), (3, 10, "2"), (4, 15, "2")])
def test_populated_adc_selection_and_defaults(adc, count, array):
    args = runner.parse_args(["--ghosting", "--ghost-adc", str(adc), "--repetitions", "9", "--window-ms", "9000"])
    route_set, config = runner.select_ghosting_config(args, runner.load_route_manifest(runner.DEFAULT_ROUTES_PATH))
    assert len(route_set.routes) == count
    assert config.array == array
    assert {r.adc for r in route_set.routes} == {adc}
    assert config.scanorder == "adc" and config.spiengine == "lpspi"
    assert config.adcseq == "manual" and config.channelrepeat == 1 and not config.vmid
    assert args.window_ms == 2000 and args.repetitions == 1
    assert args.requested_window_ms == 9000 and args.requested_repetitions == 9
    assert args.ghost_trigger_sigma == 5 and args.ghost_target_sigma == 3
    assert args.ghost_trigger_counts == 100 and args.ghost_trigger_samples == 3


def test_array_fallback_and_acquisition_options(capsys):
    args = runner.parse_args(["--ghosting", "--route-set", "all_four_full", "--scan-order", "array",
                              "--vmid", "on", "--spi-engine", "dma", "--spi-clock-hz", "5000000"])
    route_set, config = runner.select_ghosting_config(args, runner.load_route_manifest(runner.DEFAULT_ROUTES_PATH))
    assert route_set.name == "full_array1" and len(route_set.routes) == 25
    assert "mapped to full_array1" in capsys.readouterr().out
    assert config.vmid and config.spiengine == "dma" and config.spi_clock_hz == 5000000


@pytest.mark.parametrize("flags", [
    ["--ghosting"], ["--ghost-adc", "1"],
    ["--ghosting", "--ghost-adc", "1", "--route-set", "full_array1"],
    ["--ghosting", "--route-set", "full_array1", "--route-set", "full_array2"],
    ["--ghosting", "--ghost-adc", "1", "--scan-order", "adc", "--scan-order", "array"],
    ["--ghosting", "--ghost-adc", "1", "--spi-clock-hz", "1000000", "--spi-clock-hz", "2000000"],
    ["--ghosting", "--ghost-adc", "1", "--resume", "--output", "unused"],
    ["--ghosting", "--ghost-adc", "1", "--smoke-only"],
    ["--ghosting", "--ghost-adc", "1", "--tests", "repeat3"],
    ["--ghosting", "--ghost-adc", "1", "--ghost-trigger-sigma", "2"],
    ["--ghosting", "--ghost-adc", "1", "--ghost-target-sigma", "0"],
    ["--ghosting", "--ghost-adc", "1", "--ghost-correlation-min", "1.1"],
    ["--ghosting", "--ghost-adc", "1", "--ghost-trigger-counts", "nan"],
    ["--ghosting", "--ghost-adc", "1", "--ghost-target-counts", "inf"],
    ["--vmid=on"], ["--spi-engine", "dma"],
    ["--ghosting", "--ghost-adc", "1", "--idle-ms", "0"],
    ["--ghosting", "--ghost-adc", "1", "--grace-ms", "0"],
    ["--ghosting", "--ghost-adc", "1", "--ghost-trigger-samples", "0"],
    ["--ghosting", "--ghost-adc", "1", "--ghost-trigger-samples", "65"],
    ["--ghost-trigger-samples", "3"],
])
def test_cli_rejects_incompatible_options(flags):
    with pytest.raises(SystemExit):
        runner.parse_args(flags)


def test_other_two_array_route_sets_rejected():
    args = runner.parse_args(["--ghosting", "--route-set", "one_adc_each_bus"])
    with pytest.raises(ValueError, match="two arrays"):
        runner.select_ghosting_config(args, runner.load_route_manifest(runner.DEFAULT_ROUTES_PATH))


def test_dry_run_never_opens_port_or_creates_output(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(runner, "open_serial_port", lambda *_: pytest.fail("Port opened"))
    destination = tmp_path / "unused"
    assert runner.main(["--ghosting", "--ghost-adc", "4", "--dry-run", "--output", str(destination)]) == 0
    assert not destination.exists()
    assert "15 sources" in capsys.readouterr().out


def test_noise_calibration_and_count_floor():
    routes = ("1:0", "1:1")
    calibrated = calibrate(np.array([[1000, 2000], [1002, 2000], [1004, 2000]]), routes)
    assert calibrated["1:0"].baseline == 1002
    assert calibrated["1:0"].stdev == 2
    assert calibrated["1:1"].stdev == 0 and calibrated["1:1"].noise_sigma == 1
    with pytest.raises(ValueError, match="two complete"):
        calibrate(np.array([[1000, 2000]]), routes)


def test_twenty_percent_ghost_all_same_adc_channels_and_no_cross_adc_classification():
    routes = ("1:0", "1:1", "1:2", "1:3", "2:0")
    reference = calibrate(np.full((10, 5), 2000), routes)
    source = np.array([0, 50, 100, 200, 100, 50, 0, -50])
    values = 2000 + np.column_stack([source, source * .2, -source * .2,
                                    [0, 3, -2, 1, -3, 0, 2, -1], source * .5])
    summary, pairs = analyze_window(values, routes, "1:1", reference)
    assert {p["target"] for p in pairs} == {"1:0", "1:2", "1:3"}
    summary, pairs = analyze_window(values, routes, "1:0", reference)
    assert summary["ghost_targets"] == "1:1"
    assert pairs[0]["attenuation_pct"] == pytest.approx(20)
    assert pairs[1]["attenuation_pct"] == pytest.approx(20)
    assert pairs[0]["correlation"] == pytest.approx(1)
    assert pairs[1]["correlation"] == pytest.approx(-1) and not pairs[1]["ghosting_detected"]
    assert not pairs[2]["ghosting_detected"]


def test_attenuation_uses_window_standard_deviations_despite_an_isolated_target_spike():
    routes = ("1:0", "1:1")
    reference = calibrate(np.full((10, 2), 2000), routes)
    source = np.tile([0., 100., 0., -100.], 2500)
    target = .2 * source
    target[0] += 150
    values = 2000 + np.column_stack([source, target])
    summary, pairs = analyze_window(values, routes, routes[0], reference)
    pair = pairs[0]
    assert pair["source_peak"] == 100 and pair["target_peak"] == 150
    assert pair["source_stdev"] == pytest.approx(np.std(source, ddof=1))
    assert pair["target_stdev"] == pytest.approx(np.std(target, ddof=1))
    assert summary["source_stdev"] == pair["source_stdev"]
    assert pair["attenuation_pct"] == pytest.approx(100 * np.std(target, ddof=1) / np.std(source, ddof=1))
    assert abs(pair["attenuation_pct"] - 20) < .2
    assert "gain_pct" not in pair
    _, shifted_pairs = analyze_window(values + [100, -200], routes, routes[0], reference)
    assert shifted_pairs[0]["attenuation_pct"] == pytest.approx(pair["attenuation_pct"])


def test_zero_variance_source_has_undefined_attenuation():
    routes = ("1:0", "1:1")
    reference = calibrate(np.full((3, 2), 2000), routes)
    _, pairs = analyze_window(np.array([[2100, 2000], [2100, 2020], [2100, 2000]]),
                              routes, routes[0], reference)
    assert pairs[0]["source_stdev"] == 0
    assert pairs[0]["attenuation_pct"] == "" and pairs[0]["correlation"] == ""
    assert pairs[0]["status"] == "INCONCLUSIVE"


def test_console_reports_attenuation_and_undefined_ratio(capsys):
    routes = ("1:0", "1:1")
    reference = calibrate(np.full((3, 2), 2000), routes)
    summary, pairs = analyze_window(np.array([[2000, 2000], [2100, 2020], [2000, 2000]]),
                                    routes, routes[0], reference)
    runner.print_ghosting_result(summary, pairs)
    text = capsys.readouterr().out
    assert "attenuation=20.00%" in text and "std=" in text and "gain=" not in text
    summary, pairs = analyze_window(np.array([[2100, 2000], [2100, 2020], [2100, 2000]]),
                                    routes, routes[0], reference)
    runner.print_ghosting_result(summary, pairs)
    assert "attenuation=undefined" in capsys.readouterr().out


def test_target_threshold_strict_boundary_and_source_clipping():
    routes = ("1:0", "1:1", "1:2")
    reference = calibrate(np.full((4, 3), 2000), routes)
    values = np.array([[2000, 2000, 2000], [2100, 2003, 2004], [2050, 2001.5, 2002], [2000, 2000, 2000]])
    _, pairs = analyze_window(values, routes, routes[0], reference)
    assert not pairs[0]["ghosting_detected"] and pairs[1]["ghosting_detected"]
    values[1, 0] = 4095
    summary, pairs = analyze_window(values, routes, routes[0], reference)
    assert summary["status"] == "CLIPPED" and all(p["status"] == "INCONCLUSIVE" for p in pairs)


def test_target_clipping_and_undefined_correlation_are_inconclusive():
    routes = ("1:0", "1:1", "1:2")
    reference = calibrate(np.full((3, 3), 2000), routes)
    values = np.array([[2100, 2000, 2000], [2200, 4095, 2000], [2100, 2000, 2000]])
    summary, pairs = analyze_window(values, routes, routes[0], reference)
    assert summary["status"] == "VALID"
    assert summary["inconclusive_pairs"] == 2
    assert pairs[0]["target_clipped"] and pairs[1]["correlation"] == ""
    assert pairs[1]["target_stdev"] == 0 and pairs[1]["attenuation_pct"] == 0


def test_strongest_attempt_skipped_redo_tie_and_invalid_larger_peak():
    attempts = [
        {"source": "1:0", "attempt": 1, "status": "VALID", "source_peak": 100},
        {"source": "1:0", "attempt": 2, "status": "VALID", "source_peak": 200},
        {"source": "1:0", "attempt": 3, "status": "VALID", "source_peak": 200},
        {"source": "1:0", "attempt": 4, "status": "CLIPPED", "source_peak": 2000},
        {"source": "1:0", "attempt": 5, "status": "SKIPPED"},
        {"source": "1:1", "attempt": 1, "status": "SKIPPED"},
    ]
    assert strongest_attempt(attempts, "1:0")["attempt"] == 2
    summary = summarize_attempts(("1:0", "1:1", "1:2"), attempts)
    assert summary[0]["selected_attempt"] == 2
    assert summary[1]["status"] == "SKIPPED" and summary[2]["status"] == "UNTESTED"


class FakeSerial:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.writes = []
        self.stopping = False
        self.closed = False

    @property
    def in_waiting(self):
        return len(self.chunks[0]) if self.chunks else 0

    def read(self, count):
        if self.chunks:
            data = self.chunks.pop(0)
            if len(data) > count:
                self.chunks.insert(0, data[count:])
            return data[:count]
        return b""

    def write(self, data):
        self.writes.append(data)
        if data == b"stop*":
            self.stopping = True
            self.chunks.append(b"#OK\r\n")

    def flush(self):
        pass

    def close(self):
        self.closed = True


class FakeKeys:
    def __init__(self, values=()):
        self.values = list(values)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def clear(self):
        pass

    def poll(self):
        return self.values.pop(0) if self.values else None


def protocol_for(chunks):
    return SimpleNamespace(serial=FakeSerial(chunks), log=SimpleNamespace(write=lambda _: None))


def capture_args():
    return ghost_args("--warm-up-ms", "1", "--ghost-baseline-ms", "1",
                      "--ghost-trigger-counts", "1", "--ghost-trigger-samples", "1")


def baseline_chunks(offset=0):
    return [frame([100, 100], offset), frame([3000, 3000], offset + 500),
            frame([2000, 2000], offset + 1000), frame([2000, 2000], offset + 1500)]


@pytest.mark.parametrize("offset,sign", [(0, 1), (0xFFFFF000, -1)])
def test_continuous_capture_warmup_trigger_boundary_window_and_rollover(offset, sign):
    chunks = baseline_chunks(offset) + [frame([2005, 2000], offset + 2000),
        frame([2000 + sign * 6, 2001], offset + 2500),
        frame([2000 + sign * 100, 2020], offset + 1_000_000),
        frame([2000, 2000], offset + 2_002_499),
        frame([2000, 2000], offset + 2_002_500)]
    protocol = protocol_for(chunks)
    result = capture_ghosting_attempt(protocol, ("1:0", "1:1"), "1:0", capture_args(),
                                      FakeKeys(), GhostingCapture(), notify=lambda _: None)
    assert result.status == "COMPLETE"
    assert len(result.warmup) == 2 and len(result.baseline) == 2 and len(result.window) == 3
    assert result.calibration["1:0"].baseline == 2000
    assert result.trigger_threshold == 5
    assert result.trigger_start_us == (offset + 2500) & 0xFFFFFFFF
    assert protocol.serial.writes == [b"run*", b"stop*"]


@pytest.mark.parametrize("key,status", [(" ", "SKIPPED"), ("q", "QUIT")])
def test_immediate_space_and_quit_drain_stream(key, status):
    protocol = protocol_for(baseline_chunks() + [frame([2000, 2000], 2000), frame([2000, 2000], 2500)])
    result = capture_ghosting_attempt(protocol, ("1:0", "1:1"), "1:0", capture_args(),
                                      FakeKeys([key]), GhostingCapture(), notify=lambda _: None)
    assert result.status == status and not result.window
    assert protocol.serial.stopping


def test_fresh_baselines_are_used_for_each_attempt():
    for baseline in (1900, 2200):
        chunks = [frame([baseline] * 2, t) for t in (0, 500, 1000, 1500, 2000)]
        result = capture_ghosting_attempt(protocol_for(chunks), ("1:0", "1:1"), "1:0", capture_args(),
                                          FakeKeys([" "]), GhostingCapture(), notify=lambda _: None)
        assert result.calibration["1:0"].baseline == baseline


def test_default_trigger_rejects_observed_unpressed_excursions():
    # Representative of the user's run: sub-count calibration noise followed
    # by a 58-count source excursion and larger simultaneous target excursions.
    chunks = baseline_chunks() + [frame([2000, 2000], 2000),
                                 frame([1942, 1917], 2500),
                                 frame([1972, 1957], 3000),
                                 frame([2001, 2000], 3500)]
    args = ghost_args("--warm-up-ms", "1", "--ghost-baseline-ms", "1")
    result = capture_ghosting_attempt(protocol_for(chunks), ("1:0", "1:1"), "1:0", args,
                                      FakeKeys([None, None, None, " "]), GhostingCapture(), notify=lambda _: None)
    assert result.status == "SKIPPED"
    assert result.trigger_threshold == 100 and result.trigger_start_us is None
    assert not result.window


@pytest.mark.parametrize("sign", [1, -1])
def test_trigger_confirmation_rejects_isolated_and_alternating_spikes_keeps_first_crossing(sign):
    chunks = baseline_chunks() + [frame([2100, 2000], 2000)]  # equal to threshold does not trigger
    for time_us, delta in ((2500, 112), (3000, 0), (3500, 150), (4000, -150),
                           (4500, 150), (5000, 200), (5500, 250), (1_000_000, 100), (2_004_500, 0)):
        chunks.append(frame([2000 + sign * delta, 2000], time_us))
    args = ghost_args("--warm-up-ms", "1", "--ghost-baseline-ms", "1")
    result = capture_ghosting_attempt(protocol_for(chunks), ("1:0", "1:1"), "1:0", args,
                                      FakeKeys(), GhostingCapture(), notify=lambda _: None)
    assert result.status == "COMPLETE"
    assert result.trigger_start_us == 4500
    assert [f.block_start_us for f in result.window] == [4500, 5000, 5500, 1_000_000]
    assert result.window[0].samples[0] == 2000 + sign * 150


def test_source_threshold_floor_remains_overridable():
    args = ghost_args("--warm-up-ms", "1", "--ghost-baseline-ms", "1", "--ghost-trigger-counts", "20")
    result = capture_ghosting_attempt(protocol_for(baseline_chunks() + [frame([2000, 2000], 2000)]),
                                      ("1:0", "1:1"), "1:0", args, FakeKeys([" "]),
                                      GhostingCapture(), notify=lambda _: None)
    assert result.trigger_threshold == 20 and result.status == "SKIPPED"


def test_stop_ack_is_not_recognized_inside_binary_payload_and_chunked_tail():
    payload = bytearray(frame([2000] * 10, 100))
    payload[7:12] = b"#OK\r\n"
    parser = BinaryFrameParser(expected_sample_count=10)
    parser.feed(bytes(payload[:8]))
    protocol = protocol_for([bytes(payload[8:13]), bytes(payload[13:])])
    stop_stream(protocol, parser)
    assert not protocol.serial.chunks and not parser.buffer


def test_interruption_still_stops_stream():
    class InterruptedKeys(FakeKeys):
        def poll(self):
            raise KeyboardInterrupt
    protocol = protocol_for(baseline_chunks() + [frame([2000, 2000], 2000)])
    with pytest.raises(KeyboardInterrupt):
        capture_ghosting_attempt(protocol, ("1:0", "1:1"), "1:0", capture_args(),
                                 InterruptedKeys(), GhostingCapture(), notify=lambda _: None)
    assert protocol.serial.stopping


def test_malformed_frame_fails_and_stops():
    protocol = protocol_for([frame([2000], 0)])
    with pytest.raises(GhostingCaptureError, match="Malformed"):
        capture_ghosting_attempt(protocol, ("1:0", "1:1"), "1:0", capture_args(),
                                 FakeKeys(), GhostingCapture(), notify=lambda _: None)
    assert protocol.serial.stopping


def test_disconnect_fails_and_stops(monkeypatch):
    from Arduino_Sketches.TestBoard_7953.benchmarks import ghosting_capture
    ticks = iter([0, 10, 11, 12, 13])
    monkeypatch.setattr(ghosting_capture.time, "monotonic", lambda: next(ticks))
    protocol = protocol_for([])
    with pytest.raises(GhostingCaptureError, match="disconnected"):
        capture_ghosting_attempt(protocol, ("1:0", "1:1"), "1:0", capture_args(),
                                 FakeKeys(), GhostingCapture(), notify=lambda _: None)
    assert protocol.serial.stopping


def test_timestamp_reset_is_not_mistaken_for_window_completion():
    protocol = protocol_for(baseline_chunks() + [frame([2010, 2002], 2000), frame([2050, 2010], 500)])
    with pytest.raises(GhostingCaptureError, match="timestamps moved backwards"):
        capture_ghosting_attempt(protocol, ("1:0", "1:1"), "1:0", capture_args(),
                                 FakeKeys(), GhostingCapture(), notify=lambda _: None)


def test_stop_cleanup_failure_preserves_original_interruption(monkeypatch):
    from Arduino_Sketches.TestBoard_7953.benchmarks import ghosting_capture
    class InterruptedKeys(FakeKeys):
        def poll(self):
            raise KeyboardInterrupt
    def failed_stop(*_):
        raise OSError("disconnected")
    monkeypatch.setattr(ghosting_capture, "stop_stream", failed_stop)
    result = GhostingCapture()
    protocol = protocol_for(baseline_chunks() + [frame([2000, 2000], 2000)])
    with pytest.raises(KeyboardInterrupt):
        capture_ghosting_attempt(protocol, ("1:0", "1:1"), "1:0", capture_args(),
                                 InterruptedKeys(), result, notify=lambda _: None)
    assert "Stop cleanup failed" in result.notes


def test_chart_reduction_retains_all_channel_extrema_and_common_time_indices():
    rng = np.random.default_rng(123)
    signals = rng.normal(size=(30_000, 25))
    indices = chart_indices(signals)
    assert len(indices) <= 5000 and indices[0] == 0 and indices[-1] == len(signals) - 1
    assert np.all(np.diff(indices) > 0)
    assert set(np.argmin(signals, axis=0)).issubset(indices)
    assert set(np.argmax(signals, axis=0)).issubset(indices)
    np.testing.assert_allclose(signals[indices].min(axis=0), signals.min(axis=0))
    np.testing.assert_allclose(signals[indices].max(axis=0), signals.max(axis=0))
    assert chart_bounds(np.array([[0, -100], [200, 0]])) == (-115, 215)
    assert chart_bounds(np.zeros((5, 2))) == (-1, 1)


@pytest.mark.parametrize("count", [10, 15, 25])
def test_workbook_graph_count_all_traces_hidden_data_axis_bounds_and_attempts(tmp_path, count):
    routes = [f"1:{i}" for i in range(10)] + [f"2:{i}" for i in range(15)]
    routes = routes[:count] if count != 15 else [f"2:{i}" for i in range(15)]
    summary = [{"source": r, "selected_attempt": 2, "status": "VALID", "source_peak": 100} for r in routes]
    graphs = {r: {"attempt": 2, "routes": routes, "times_s": np.array([0, .5, 1.9]),
                  "signals": np.tile([0, 100, -10], (count, 1)).T, "bounds": (-15.5, 105.5),
                  "full_sample_count": 30_000} for r in routes}
    destination = tmp_path / "report.xlsx"
    write_ghosting_workbook(destination, summary, [], summary, {"status": "complete"}, graphs, runner.GLOSSARY_PATH)
    with zipfile.ZipFile(destination) as archive:
        workbook = archive.read("xl/workbook.xml").decode()
        assert 'name="Signal Graphs"' in workbook and 'name="Chart Data"' in workbook and 'state="hidden"' in workbook
        charts = [name for name in archive.namelist() if name.startswith("xl/charts/chart") and name.endswith(".xml")]
        assert len(charts) == count
        ns = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart"}
        for name in charts:
            root = ET.fromstring(archive.read(name))
            assert len(root.findall(".//c:ser", ns)) == count
            assert root.find(".//c:scatterChart", ns) is not None
            visible_only = root.find(".//c:plotVisOnly", ns)
            assert visible_only is None or visible_only.attrib["val"] == "0"
            xml = archive.read(name).decode()
            assert 'min val="-15.5"' in xml and 'max val="105.5"' in xml
            assert 'max val="2"' in xml and "attempt 2" in xml and "display reduced" in xml


def test_partial_workbook_has_status_placeholders(tmp_path):
    output = tmp_path / "partial.xlsx"
    rows = [{"source": "1:0", "selected_attempt": "", "status": "SKIPPED"},
            {"source": "1:1", "selected_attempt": "", "status": "UNTESTED"}]
    write_ghosting_workbook(output, rows, [], [], {"status": "partial"}, {}, runner.GLOSSARY_PATH)
    with zipfile.ZipFile(output) as archive:
        assert not any(name.startswith("xl/charts/chart") for name in archive.namelist())
        strings = archive.read("xl/sharedStrings.xml").decode()
        assert "No valid signal graph: SKIPPED" in strings and "No valid signal graph: UNTESTED" in strings


def test_session_redo_skip_strongest_selection_and_partial_export(monkeypatch, tmp_path):
    args = ghost_args("--port", "FAKE", "--output", str(tmp_path), "--no-raw")
    serial = FakeSerial([])
    protocol = SimpleNamespace(serial=serial, log=SimpleNamespace(write=lambda _: None),
                               drain_until_idle=lambda: None,
                               send_command=lambda command, **_: [runner.FIRMWARE_IDENTITY, "#OK"] if command == "mcu" else ["#OK"])
    monkeypatch.setattr(runner.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(runner, "open_serial_port", lambda *_: serial)
    monkeypatch.setattr(runner, "SerialProtocol", lambda *_: protocol)
    monkeypatch.setattr(runner, "configure_test", lambda *_: {})
    monkeypatch.setattr(runner, "ConsoleKeys", FakeKeys)
    responses = iter(["", "r", "", "r", "", "q"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    peaks = iter([50, 100, None])

    def capture(_, routes, source, __, keys, result, notify):
        peak = next(peaks)
        parser = BinaryFrameParser(expected_sample_count=len(routes))
        result.baseline = parser.feed(frame([2000] * len(routes), 0) + frame([2000] * len(routes), 500))
        result.calibration = calibrate(np.array([f.samples for f in result.baseline]), routes)
        result.trigger_threshold = 5
        if peak is None:
            result.status = "SKIPPED"
        else:
            result.status = "COMPLETE"
            result.trigger_start_us = 1000
            samples = [2000 + peak, 2000 + peak // 5] + [2000] * (len(routes) - 2)
            result.window = parser.feed(frame(samples, 1000) + frame([2000] * len(routes), 1_001_000))
        return result

    monkeypatch.setattr(runner, "capture_ghosting_attempt", capture)
    assert runner.run_ghosting_session(args, runner.load_route_manifest(runner.DEFAULT_ROUTES_PATH)) == 0
    assert serial.closed
    with (tmp_path / "ghosting_summary.csv").open() as src:
        summary = list(csv.DictReader(src))
    assert summary[0]["selected_attempt"] == "2" and float(summary[0]["source_peak"]) == 100
    assert summary[1]["status"] == "UNTESTED"
    with (tmp_path / "ghosting_attempts.csv").open() as src:
        assert [r["status"] for r in csv.DictReader(src)] == ["VALID", "VALID", "SKIPPED"]
    with (tmp_path / "ghosting_pairs.csv").open() as src:
        reader = csv.DictReader(src)
        pairs = list(reader)
        assert {r["attempt"] for r in pairs} == {"2"}
        assert "gain_pct" not in reader.fieldnames
        assert {"attenuation_pct", "source_stdev", "target_stdev"}.issubset(reader.fieldnames)
        assert float(pairs[0]["attenuation_pct"]) == pytest.approx(20)
    metadata = json.loads((tmp_path / "session_metadata.json").read_text())
    assert metadata["status"] == "partial" and metadata["schema_version"] == 2
    assert "ddof=1" in metadata["attenuation_method"]
    assert (tmp_path / "ghosting_report.xlsx").exists()
    with zipfile.ZipFile(tmp_path / "ghosting_report.xlsx") as archive:
        namespace = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        strings_xml = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        strings = [element.text for element in strings_xml.findall(".//s:t", namespace)]
        assert "attenuation_pct" in strings and "gain_pct" not in strings
        pairs_xml = ET.fromstring(archive.read("xl/worksheets/sheet2.xml"))
        headers = pairs_xml.find("s:sheetData/s:row", namespace)
        attenuation_header = next(cell for cell in headers
                                  if cell.attrib.get("t") == "s" and
                                  strings[int(cell.find("s:v", namespace).text)] == "attenuation_pct")
        column = attenuation_header.attrib["r"].rstrip("0123456789")
        cell = pairs_xml.find(f"s:sheetData/s:row/s:c[@r='{column}2']", namespace)
        assert cell.attrib.get("t") != "s"
        assert float(cell.find("s:v", namespace).text) == pytest.approx(20)


@pytest.mark.parametrize("failure,expected_status,expected_exit", [
    ("interrupt", "interrupted", 130), ("capture_error", "partial", 0), ("counter_error", "partial", 0),
])
def test_session_failure_and_interruption_preserve_samples_raw_and_partial_report(
    monkeypatch, tmp_path, failure, expected_status, expected_exit,
):
    args = ghost_args("--port", "FAKE", "--output", str(tmp_path))
    serial = FakeSerial([])
    status_calls = 0

    def command(command, **_):
        nonlocal status_calls
        if command == "mcu":
            return [runner.FIRMWARE_IDENTITY, "#OK"]
        if command == "status":
            status_calls += 1
            return [f"# returned_channel_errors={int(failure == 'counter_error' and status_calls > 1)}", "#OK"]
        return ["#OK"]

    protocol = SimpleNamespace(serial=serial, log=SimpleNamespace(write=lambda _: None),
                               drain_until_idle=lambda: None, send_command=command)
    monkeypatch.setattr(runner.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(runner, "open_serial_port", lambda *_: serial)
    monkeypatch.setattr(runner, "SerialProtocol", lambda *_: protocol)
    monkeypatch.setattr(runner, "configure_test", lambda *_: {})
    monkeypatch.setattr(runner, "ConsoleKeys", FakeKeys)
    responses = iter(["", "q"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    def capture(_, routes, source, __, keys, result, notify):
        parser = BinaryFrameParser(expected_sample_count=len(routes))
        result.baseline = parser.feed(frame([2000] * len(routes), 0) + frame([2000] * len(routes), 500))
        result.calibration = calibrate(np.array([f.samples for f in result.baseline]), routes)
        result.trigger_threshold = 5
        result.trigger_start_us = 1000
        result.window = parser.feed(frame([2100] + [2000] * (len(routes) - 1), 1000))
        if failure == "interrupt":
            raise KeyboardInterrupt
        if failure == "capture_error":
            raise GhostingCaptureError("stream disconnected during window")
        result.status = "COMPLETE"
        return result

    monkeypatch.setattr(runner, "capture_ghosting_attempt", capture)
    assert runner.run_ghosting_session(args, runner.load_route_manifest(runner.DEFAULT_ROUTES_PATH)) == expected_exit
    assert serial.closed
    metadata = json.loads((tmp_path / "session_metadata.json").read_text())
    assert metadata["status"] == expected_status
    with (tmp_path / "ghosting_attempts.csv").open() as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 1
    assert rows[0]["status"] == ("INCOMPLETE" if failure == "interrupt" else "FAILED")
    assert rows[0]["sample_count"] == "1"
    with (tmp_path / "ghosting_samples.csv").open() as source:
        samples = list(csv.DictReader(source))
    assert len(samples) == 30 and {s["phase"] for s in samples} == {"baseline", "window"}
    assert all(s["baseline"] == "2000.0" for s in samples)
    raw_files = list((tmp_path / "raw").glob("*.bin"))
    assert len(raw_files) == 2
    for path in raw_files:
        parser = BinaryFrameParser(expected_sample_count=10)
        assert parser.feed(path.read_bytes())
        assert not parser.buffer and not parser.invalid_frames
    assert (tmp_path / "ghosting_report.xlsx").exists()
