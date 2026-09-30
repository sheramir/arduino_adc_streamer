import csv
import struct

import pytest

from Arduino_Sketches.TestBoard_7953.benchmarks.benchmark_common import (
    BinaryFrameParser,
    uint32_delta,
)
from Arduino_Sketches.TestBoard_7953.benchmarks.excel_report import (
    _summary_test_ids,
    write_benchmark_workbook,
    write_existing_session_report,
)
from Arduino_Sketches.TestBoard_7953.benchmarks.testboard_7953_benchmark import (
    CaptureResult,
    ChannelReference,
    Route,
    RouteSet,
    TestConfig as BenchmarkConfig,
    aggregate_result_rows,
    analyze_channels,
    build_complete_matrix,
    build_test_matrix,
    load_baselines_from_csv,
    load_route_manifest,
    measured_capture_after_warmup,
    parse_status,
    payload_order,
    validate_status,
    DEFAULT_ROUTES_PATH,
)


def make_frame(samples, *, average=7, started=100, ended=140):
    return (
        b"\xAA\x55"
        + struct.pack("<H", len(samples))
        + struct.pack(f"<{len(samples)}H", *samples)
        + struct.pack("<HII", average, started, ended)
    )


def test_binary_parser_handles_chunking_prefix_noise_and_timestamp_wrap():
    parser = BinaryFrameParser(expected_sample_count=3)
    raw = b"noise" + make_frame([2040, 2048, 2056], started=0xFFFFFFF0, ended=20)

    assert parser.feed(raw[:9], host_received_ns=10) == []
    frames = parser.feed(raw[9:], host_received_ns=20)

    assert len(frames) == 1
    assert frames[0].samples == (2040, 2048, 2056)
    assert frames[0].host_received_ns == 20
    assert frames[0].acquisition_duration_us == 36
    assert parser.discarded_bytes == 5
    assert parser.resync_events == 1
    assert uint32_delta(20, 0xFFFFFFF0) == 36


def test_binary_parser_rejects_wrong_route_count_and_incomplete_tail():
    parser = BinaryFrameParser(expected_sample_count=2)
    frames = parser.feed(make_frame([1]) + make_frame([2, 3])[:-1])

    assert frames == []
    assert parser.invalid_frames == 1
    assert parser.finish() == len(make_frame([2, 3])) - 1
    assert parser.invalid_frames == 2


def test_route_manifest_and_matrix_cover_required_modes():
    route_sets = load_route_manifest(DEFAULT_ROUTES_PATH)
    configs = build_test_matrix(route_sets)
    ids = {config.test_id for config in configs}

    assert len(ids) == len(configs)
    assert all(route.channel != 15 for route_set in route_sets.values() for route in route_set.routes)
    assert "one_adc_bus1__interleaved__manual__blocking__repeat1__vmidoff__spi10000000hz" in ids
    assert "all_four_full__interleaved__manual__dma__repeat3__vmidon__spi10000000hz" in ids
    assert "all_four_full__interleaved__auto1__lpspi__repeat1__vmidoff__spi10000000hz" in ids
    assert all(not config.vmid for config in configs if config.adcseq == "auto1")
    assert "all_four_full__array__manual__dma__repeat1__vmidoff__spi10000000hz" in ids
    assert "all_four_full__adc__manual__lpspi__repeat1__vmidoff__spi10000000hz" in ids

    multi_clock = build_test_matrix(route_sets, spi_clocks=(5_000_000, 10_000_000))
    assert len(multi_clock) == 2 * len(configs)
    assert {config.spi_clock_hz for config in multi_clock} == {5_000_000, 10_000_000}


def test_complete_matrix_can_focus_one_route_set_and_scan_order():
    route_sets = load_route_manifest(DEFAULT_ROUTES_PATH)
    configs = build_complete_matrix(
        route_sets, ("all_four_full",), ("adc",)
    )

    assert len(configs) == 21
    assert {config.route_set for config in configs} == {"all_four_full"}
    assert {config.scanorder for config in configs} == {"adc"}
    assert {config.spiengine for config in configs} == {
        "blocking", "dma", "lpspi"
    }
    manual = [config for config in configs if config.adcseq == "manual"]
    auto1 = [config for config in configs if config.adcseq == "auto1"]
    assert len(manual) == 18
    assert {(config.channelrepeat, config.vmid) for config in manual} == {
        (repeat, vmid) for repeat in (1, 2, 3) for vmid in (False, True)
    }
    assert len(auto1) == 3
    assert all(config.channelrepeat == 1 and not config.vmid for config in auto1)


def test_payload_order_matches_all_three_firmware_orders():
    routes = (
        Route(2, 4), Route(1, 3), Route(4, 9),
        Route(3, 8), Route(2, 5), Route(4, 10),
    )

    assert payload_order(routes, "interleaved") == (
        Route(1, 3), Route(2, 4), Route(3, 8), Route(4, 9),
        Route(2, 5), Route(4, 10),
    )
    assert payload_order(routes, "array") == (
        Route(1, 3), Route(2, 4), Route(2, 5),
        Route(3, 8), Route(4, 9), Route(4, 10),
    )
    assert payload_order(routes, "adc") == (
        Route(1, 3), Route(2, 4), Route(2, 5),
        Route(3, 8), Route(4, 9), Route(4, 10),
    )
    with pytest.raises(ValueError, match="Unknown scanorder"):
        payload_order(routes, "invalid")


def test_status_parser_and_validator_require_effective_firmware_configuration():
    route_set = RouteSet(
        name="pair",
        array="both",
        routes=(Route(1, 0), Route(3, 0)),
        non_vmid_routes=frozenset(),
    )
    config = BenchmarkConfig("pair", "both", "interleaved", "auto1", "dma", 3, True)
    lines = [
        "# adcchannels=1:0,3:0", "# array=both", "# scanorder=interleaved",
        "# adcseq=auto1", "# spiengine=dma", "# spi_clock_hz=10000000",
        "# channelrepeat_requested=3",
        "# channelrepeat_effective=1", "# vmid_channel=15",
        "# vmid_between_channels_requested=true",
        "# vmid_between_channels_effective=false", "# vmid_parking=mandatory",
        "# route_count=2", "# vref=2.5", "# active_adcs=1,3",
        "# active_spi_buses=1,2", "#OK",
    ]
    status = parse_status(lines)

    validate_status(status, config, route_set)
    status["spiengine"] = "blocking"
    with pytest.raises(Exception, match="Status mismatch"):
        validate_status(status, config, route_set)


def test_channel_analysis_warns_for_vmid_offset_and_cross_mode_shift():
    raw = make_frame([2048, 2800])
    frame = BinaryFrameParser(expected_sample_count=2).feed(raw)[0]
    route_set = RouteSet(
        name="pair",
        array="1",
        routes=(Route(1, 0), Route(1, 1)),
        non_vmid_routes=frozenset(),
    )
    baselines = {
        (Route(1, 1), 10_000_000): ChannelReference(
            2048.0, 2.0, 3.0, "baseline"
        )
    }

    stats, counts, baseline_ids = analyze_channels(
        type("Capture", (), {"frames": [frame]})(),
        route_set.routes,
        route_set,
        baselines,
        test_id="candidate",
        vmid_nominal=2048,
        warning_tolerance=512,
        severe_tolerance=1024,
        cross_mode_floor=128,
        cross_mode_mad_multiplier=6.0,
        noise_floor=32,
        noise_mad_multiplier=3.0,
        spi_clock_hz=10_000_000,
    )

    assert stats[Route(1, 0)]["warnings"] == []
    assert "VMID_OFFSET_WARNING" in stats[Route(1, 1)]["warnings"]
    assert "CROSS_MODE_SHIFT" in stats[Route(1, 1)]["warnings"]
    assert counts["vmid_warning"] == 1
    assert counts["cross_mode"] == 1
    assert baseline_ids == {"baseline"}


def test_continuous_capture_discards_device_time_warmup_frames():
    frames = [
        BinaryFrameParser(expected_sample_count=1).feed(
            make_frame([2000 + index], started=index * 1000, ended=index * 1000 + 20)
        )[0]
        for index in range(6)
    ]
    capture = CaptureResult(frames, b"raw", 0, 0, 0, 0, 6_000_000, False)

    measured, discarded = measured_capture_after_warmup(capture, 2)

    assert discarded == 2
    assert [frame.samples[0] for frame in measured.frames] == [2002, 2003, 2004, 2005]


def test_channel_analysis_reports_startup_settling_and_percentiles():
    startup_values = [700, 1500, 1900, 2040, 2045, 2047, 2046]
    frames = [
        BinaryFrameParser(expected_sample_count=1).feed(
            make_frame([value], started=index * 1000, ended=index * 1000 + 20)
        )[0]
        for index, value in enumerate(startup_values)
    ]
    full_capture = CaptureResult(frames, b"", 0, 0, 0, 0, 7_000_000, False)
    measured_capture = CaptureResult(frames[3:], b"", 0, 0, 0, 0, 4_000_000, False)
    route = Route(1, 0)
    route_set = RouteSet("single", "1", (route,), frozenset())

    stats, counts, _ = analyze_channels(
        measured_capture, (route,), route_set, {}, test_id="settling",
        vmid_nominal=2048, warning_tolerance=512, severe_tolerance=1024,
        cross_mode_floor=128, cross_mode_mad_multiplier=6.0,
        noise_floor=32, noise_mad_multiplier=3.0, spi_clock_hz=10_000_000,
        settling_capture=full_capture, warm_up_us=3_000,
        settling_tolerance_counts=64, settling_stable_frames=3,
    )

    assert stats[route]["startup_min"] == 700
    assert stats[route]["settling_frame_index"] == 3
    assert stats[route]["settling_time_us"] == 3000
    assert stats[route]["settled_before_measurement"] is True
    assert stats[route]["p1"] >= 2040
    assert counts["settling"] == 0


def test_resume_baselines_are_restored_from_sample_csv(tmp_path):
    samples = tmp_path / "samples.csv"
    with samples.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=["test_id", "adc", "channel", "sample_raw"])
        writer.writeheader()
        writer.writerows([
            {"test_id": "base", "adc": 1, "channel": 0, "sample_raw": 2040},
            {"test_id": "base", "adc": 1, "channel": 0, "sample_raw": 2050},
            {"test_id": "other", "adc": 1, "channel": 0, "sample_raw": 3000},
        ])
    results = [{
        "test_id": "base", "result_scope": "repetition", "overall_status": "PASS",
        "scanorder": "interleaved", "adcseq": "manual", "spiengine": "blocking",
        "channelrepeat_requested": "1", "vmid_requested": "false",
    }]

    restored = load_baselines_from_csv(samples, results)

    assert restored[(Route(1, 0), 10_000_000)].median == 2045
    assert restored[(Route(1, 0), 10_000_000)].mad == 5
    assert restored[(Route(1, 0), 10_000_000)].test_id == "base"


def test_aggregate_reports_matched_speedup_against_blocking():
    common = {
        "result_scope": "repetition", "overall_status": "PASS",
        "route_set": "pair", "array": "both", "scanorder": "interleaved",
        "adcseq": "manual", "channelrepeat_requested": "1",
        "spi_clock_hz": "10000000",
        "vmid_requested": "false", "ref": "2.5", "valid_frames": "10",
        "invalid_frames": "0", "total_samples": "20", "sweep_rate_hz": "1000",
        "block_period_median_us": "1000", "inter_block_gap_median_us": "10",
        "host_arrival_period_median_us": "1000", "vmid_warning_count": "0",
        "vmid_severe_count": "0", "unstable_channel_count": "0",
        "cross_mode_shift_count": "0",
        "drift_warning_count": "0", "drift_timing_tolerance_pct": "10",
        "data_integrity_status": "PASS", "drift_phase": "",
    }
    rows = [
        {**common, "test_id": "blocking", "spiengine": "blocking",
         "duration_median_us": "200", "payload_throughput_sps": "100000"},
        {**common, "test_id": "dma", "spiengine": "dma",
         "duration_median_us": "100", "payload_throughput_sps": "200000"},
    ]

    aggregates = {row["test_id"]: row for row in aggregate_result_rows(rows)}

    assert aggregates["dma"]["speedup_vs_blocking"] == 2.0
    assert aggregates["dma"]["throughput_gain_pct"] == 100.0


def test_aggregate_does_not_claim_single_bus_speedup_and_flags_timing_drift():
    common = {
        "result_scope": "repetition", "overall_status": "PASS",
        "data_integrity_status": "PASS", "route_set": "reference",
        "array": "1", "scanorder": "interleaved", "adcseq": "manual",
        "spi_clock_hz": "10000000",
        "channelrepeat_requested": "1", "vmid_requested": "false", "ref": "2.5",
        "spiengine": "blocking", "valid_frames": "10", "invalid_frames": "0",
        "total_samples": "100", "payload_throughput_sps": "100000",
        "speedup_vs_blocking": "", "throughput_gain_pct": "",
        "sweep_rate_hz": "1000", "block_period_median_us": "1000",
        "inter_block_gap_median_us": "10", "host_arrival_period_median_us": "1000",
        "vmid_warning_count": "0", "vmid_severe_count": "0",
        "unstable_channel_count": "0", "cross_mode_shift_count": "0",
        "drift_warning_count": "0", "drift_timing_tolerance_pct": "10",
    }
    rows = [
        {**common, "test_id": "regular", "drift_phase": "",
         "duration_median_us": "200"},
        {**common, "test_id": "begin", "drift_phase": "begin",
         "duration_median_us": "200"},
        {**common, "test_id": "end", "drift_phase": "end",
         "duration_median_us": "230"},
    ]

    aggregates = {row["test_id"]: row for row in aggregate_result_rows(rows)}

    assert aggregates["regular"]["speedup_vs_blocking"] == ""
    assert aggregates["end"]["timing_drift_pct"] == pytest.approx(15.0)
    assert aggregates["end"]["overall_status"] == "WARN"
    assert "DRIFT_WARNING" in aggregates["end"]["notes"]


def test_excel_report_contains_tables_and_native_charts(tmp_path):
    results = tmp_path / "benchmark_results.csv"
    channels = tmp_path / "benchmark_channel_stats.csv"
    warmup = tmp_path / "benchmark_warmup_samples.csv"
    metadata = tmp_path / "session_metadata.json"
    glossary = tmp_path / "OUTPUT_GLOSSARY.md"
    output = tmp_path / "benchmark_report.xlsx"

    with results.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=[
            "test_id", "result_scope", "drift_phase", "route_set",
            "spiengine", "adcseq", "spi_clock_hz",
            "channelrepeat_requested", "vmid_requested",
            "duration_median_us", "block_period_median_us",
            "payload_throughput_sps", "sweep_rate_hz", "sample_min_raw",
            "sample_median_raw", "sample_max_raw", "sample_stdev_raw",
            "speedup_vs_blocking", "overall_status",
        ])
        writer.writeheader()
        writer.writerow({
            "test_id": "sample", "result_scope": "aggregate",
            "drift_phase": "", "route_set": "all_four_full",
            "spiengine": "dma", "adcseq": "manual",
            "spi_clock_hz": 10_000_000, "channelrepeat_requested": 1,
            "vmid_requested": "false", "duration_median_us": 100,
            "block_period_median_us": 120, "payload_throughput_sps": 500_000,
            "sweep_rate_hz": 8_333, "sample_min_raw": 1900,
            "sample_median_raw": 2048, "sample_max_raw": 2200,
            "sample_stdev_raw": 20, "speedup_vs_blocking": 1.5,
            "overall_status": "PASS",
        })
    with channels.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=[
            "test_id", "adc", "channel", "sample_median_raw"
        ])
        writer.writeheader()
        writer.writerow({"test_id": "sample", "adc": 1, "channel": 0,
                         "sample_median_raw": 2048})
    with warmup.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=[
            "test_id", "adc", "channel", "warmup_frame_index",
            "elapsed_us", "sample_raw", "post_warmup_median_raw",
            "bias_resistor_ohms",
        ])
        writer.writeheader()
        writer.writerow({
            "test_id": "sample", "adc": 1, "channel": 0,
            "warmup_frame_index": 0, "elapsed_us": 0, "sample_raw": 1000,
            "post_warmup_median_raw": 2048,
            "bias_resistor_ohms": 100000,
        })
    metadata.write_text('{"session_id":"test"}', encoding="utf-8")
    glossary.write_text(
        "| Field | File | Meaning |\n| --- | --- | --- |\n"
        "| test_id | Results | Test identifier. |\n",
        encoding="utf-8",
    )

    write_benchmark_workbook(output, results, channels, warmup, metadata, glossary)

    import zipfile
    with zipfile.ZipFile(output) as archive:
        members = set(archive.namelist())
        shared_strings = archive.read("xl/sharedStrings.xml").decode("utf-8")
        workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
        chart_xml = "\n".join(
            archive.read(name).decode("utf-8")
            for name in members if name.startswith("xl/charts/chart")
        )
    assert "xl/workbook.xml" in members
    assert any(name.startswith("xl/charts/chart") for name in members)
    assert "Warmup Samples" in workbook_xml
    assert "Warmup Channel" in workbook_xml
    assert "Warmup Curves" in workbook_xml
    assert 'plotVisOnly val="1"' in chart_xml
    for header in (
        "Test ID", "Measured runs", "Route set", "Array", "Scan order", "Vmid",
        "Channel repeat",
    ):
        assert header in shared_strings


def test_summary_short_ids_map_repetitions_and_aggregate_to_same_test():
    rows = [
        {"test_id": "config_a", "result_scope": "repetition", "repetition": 1,
         "drift_phase": ""},
        {"test_id": "config_a", "result_scope": "repetition", "repetition": 2,
         "drift_phase": ""},
        {"test_id": "config_a", "result_scope": "aggregate", "drift_phase": ""},
        {"test_id": "control", "result_scope": "aggregate", "drift_phase": "begin"},
        {"test_id": "config_b", "result_scope": "aggregate", "drift_phase": ""},
    ]

    assert _summary_test_ids(rows) == {"config_a": "T001", "config_b": "T002"}


def test_existing_session_report_backfills_pre_v2_sample_statistics(tmp_path):
    results = tmp_path / "benchmark_results.csv"
    samples = tmp_path / "benchmark_samples.csv"
    metadata = tmp_path / "session_metadata.json"
    glossary = tmp_path / "OUTPUT_GLOSSARY.md"

    result_fields = [
        "session_id", "test_id", "result_scope", "repetition", "attempt",
        "route_set", "array", "scanorder", "adcseq", "spiengine",
        "channelrepeat_requested", "channelrepeat_effective",
        "vmid_requested", "vmid_effective", "duration_median_us",
        "block_period_median_us", "payload_throughput_sps", "sweep_rate_hz",
        "overall_status",
    ]
    with results.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=result_fields)
        writer.writeheader()
        common = {
            "session_id": "legacy", "test_id": "blocking", "route_set": "one_adc",
            "array": "1", "scanorder": "grouped", "adcseq": "manual",
            "spiengine": "blocking", "channelrepeat_requested": 1,
            "channelrepeat_effective": 1, "vmid_requested": "false",
            "vmid_effective": "park-only", "duration_median_us": 31,
            "block_period_median_us": 36, "payload_throughput_sps": 322581,
            "sweep_rate_hz": 27778, "overall_status": "PASS",
        }
        writer.writerow({**common, "result_scope": "repetition", "repetition": 1,
                         "attempt": 1})
        writer.writerow({**common, "result_scope": "aggregate", "repetition": "",
                         "attempt": ""})
    with samples.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=[
            "test_id", "repetition", "attempt", "adc", "channel",
            "sample_raw", "route_warning",
        ])
        writer.writeheader()
        for value in (2000, 2048, 2100):
            writer.writerow({
                "test_id": "blocking", "repetition": 1, "attempt": 1,
                "adc": 1, "channel": 0, "sample_raw": value,
                "route_warning": "",
            })
    metadata.write_text('{"session_id":"legacy"}', encoding="utf-8")
    glossary.write_text(
        "| Field | File | Meaning |\n| --- | --- | --- |\n"
        "| sample_median_raw | Results | Median sample. |\n",
        encoding="utf-8",
    )

    output = write_existing_session_report(tmp_path, glossary)

    import zipfile
    with zipfile.ZipFile(output) as archive:
        shared_strings = archive.read("xl/sharedStrings.xml").decode("utf-8")
        workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
        assert "sample_median_raw" in shared_strings
        assert "Channel Stats" in workbook_xml
