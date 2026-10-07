"""Create a compact Excel report from TestBoard 7953 benchmark CSV files."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import statistics
import tempfile
from typing import Any, Iterable, Mapping, Optional, Sequence


NUMERIC_FIELDS = {
    "repetition", "attempt", "spi_clock_hz", "channelrepeat_requested",
    "channelrepeat_effective", "ref", "warm_up_ms", "window_ms",
    "captured_frames_total", "warmup_frames_discarded", "valid_frames",
    "invalid_frames", "resync_events", "discarded_bytes", "trailing_bytes",
    "timestamp_regressions", "duplicate_frames", "invalid_timing_frames", "usb_write_errors",
    "suspected_missing_frames", "total_samples", "sample_count", "adc",
    "sampling_sweeps", "usb_frames_sent", "usb_frames_discarded",
    "sampling_period_max_us", "sampling_period_over_1ms",
    "channel", "startup_min_raw", "sample_min_raw", "sample_p1_raw",
    "sample_p5_raw", "sample_mean_raw", "sample_median_raw",
    "sample_p95_raw", "sample_p99_raw", "sample_max_raw",
    "sample_stdev_raw", "sample_mad_raw", "settling_frame_index",
    "settling_time_us", "settling_tolerance_counts", "settling_stable_frames",
    "median_offset_from_vmid", "duration_min_us", "duration_mean_us",
    "duration_median_us", "duration_p5_us", "duration_p95_us",
    "duration_max_us", "duration_stdev_us", "payload_throughput_sps",
    "sweep_rate_hz", "block_period_median_us", "inter_block_gap_median_us",
    "host_arrival_period_median_us", "speedup_vs_blocking",
    "throughput_gain_pct", "dma_start_errors", "lpspi_start_errors",
    "transfer_timeouts", "returned_channel_errors", "vmid_warning_count",
    "vmid_severe_count", "unstable_channel_count", "cross_mode_shift_count",
    "drift_warning_count", "settling_warning_count", "settling_max_frames",
    "settling_max_us", "timing_drift_pct", "drift_timing_tolerance_pct",
    "vmid_nominal_code", "vmid_warning_tolerance", "vmid_severe_tolerance",
    "cross_mode_floor_counts", "cross_mode_mad_multiplier",
    "bias_resistor_ohms", "warmup_frame_index", "elapsed_us",
    "block_start_us", "acquisition_duration_us", "sample_raw",
    "post_warmup_median_raw", "delta_from_post_warmup_median",
}


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    if not path.exists() or path.stat().st_size == 0:
        return [], []
    with path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        fields = list(reader.fieldnames or [])
        rows = []
        for raw in reader:
            row: dict[str, Any] = {}
            for field in fields:
                value = raw.get(field, "")
                if field in NUMERIC_FIELDS and value not in (None, ""):
                    try:
                        number = float(value)
                        row[field] = int(number) if number.is_integer() else number
                        continue
                    except ValueError:
                        pass
                row[field] = value or ""
            rows.append(row)
    return fields, rows


def flatten_metadata(value: Any, prefix: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            yield from flatten_metadata(child, child_prefix)
    elif isinstance(value, list):
        yield prefix, ", ".join(str(item) for item in value)
    else:
        yield prefix, value


def read_glossary(path: Path) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        if len(cells) != 3 or cells[0] in ("Field", "---"):
            continue
        rows.append((cells[0], cells[1], cells[2]))
    return rows


def _write_table_sheet(
    workbook: Any,
    name: str,
    fields: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    table_name: str,
    field_formats: Optional[Mapping[str, Any]] = None,
) -> None:
    worksheet = workbook.add_worksheet(name)
    worksheet.hide_gridlines(2)
    worksheet.freeze_panes(1, 2)
    header = workbook.add_format({
        "bold": True, "font_color": "#FFFFFF", "bg_color": "#1F4E78",
        "align": "center", "valign": "vcenter", "border": 0,
    })
    number = workbook.add_format({"num_format": "0.00"})
    integer = workbook.add_format({"num_format": "0"})
    text = workbook.add_format({"valign": "vcenter"})
    for col, field in enumerate(fields):
        worksheet.write(0, col, field, header)
    for row_index, row in enumerate(rows, 1):
        for col, field in enumerate(fields):
            value = row.get(field, "")
            if isinstance(value, int):
                worksheet.write_number(row_index, col, value, integer)
            elif isinstance(value, float):
                worksheet.write_number(row_index, col, value, (field_formats or {}).get(field, number))
            else:
                worksheet.write(row_index, col, value, text)
    if fields and rows:
        worksheet.add_table(
            0, 0, len(rows), len(fields) - 1,
            {
                "name": table_name,
                "style": "Table Style Medium 2",
                "columns": [{"header": field} for field in fields],
            },
        )
    for col, field in enumerate(fields):
        width = min(42, max(11, len(field) + 2))
        if field in ("test_id", "route_list", "notes", "baseline_test_ids"):
            width = 38
        worksheet.set_column(col, col, width)
    if "overall_status" in fields and rows:
        status_col = fields.index("overall_status")
        worksheet.conditional_format(
            1, status_col, len(rows), status_col,
            {"type": "text", "criteria": "containing", "value": "WARN",
             "format": workbook.add_format({"bg_color": "#FFF2CC", "font_color": "#9C6500"})},
        )
        worksheet.conditional_format(
            1, status_col, len(rows), status_col,
            {"type": "text", "criteria": "containing", "value": "FAIL",
             "format": workbook.add_format({"bg_color": "#F4CCCC", "font_color": "#9C0006"})},
        )


def _summary_label(row: Mapping[str, Any]) -> str:
    clock_mhz = float(row.get("spi_clock_hz") or 20_000_000) / 1_000_000.0
    return (
        f"{row.get('route_set', '')} | {row.get('scanorder', '')} | "
        f"{row.get('spiengine', '')} | {row.get('adcseq', '')} | "
        f"r{row.get('channelrepeat_requested', '')} | "
        f"vmid {row.get('vmid_requested', '')} | {clock_mhz:g} MHz"
    )


def _summary_test_ids(
    result_rows: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    """Match the short Summary labels to their underlying configuration IDs."""
    aggregate_test_ids = [
        str(row.get("test_id", ""))
        for row in result_rows
        if row.get("result_scope") == "aggregate"
        and not row.get("drift_phase")
    ]
    return {
        test_id: f"T{index:03d}"
        for index, test_id in enumerate(aggregate_test_ids, 1)
    }


def _write_summary(workbook: Any, result_rows: Sequence[Mapping[str, Any]]) -> None:
    aggregates = [
        row for row in result_rows
        if row.get("result_scope") == "aggregate" and not row.get("drift_phase")
    ]
    measured_runs: dict[str, set[Any]] = {}
    for row in result_rows:
        if row.get("result_scope") != "repetition" or row.get("drift_phase"):
            continue
        measured_runs.setdefault(str(row.get("test_id", "")), set()).add(
            row.get("repetition", "")
        )
    worksheet = workbook.add_worksheet("Summary")
    worksheet.hide_gridlines(2)
    title = workbook.add_format({"bold": True, "font_size": 15, "font_color": "#1F1F1F"})
    note = workbook.add_format({"italic": True, "font_color": "#595959"})
    header = workbook.add_format({
        "bold": True, "font_color": "#FFFFFF", "bg_color": "#1F4E78",
        "align": "center", "valign": "vcenter",
    })
    worksheet.write("A2", "TestBoard 7953 benchmark summary", title)
    worksheet.write(
        "A3",
        "Aggregate rows only. Raw decoded samples remain in benchmark_samples.csv because Excel has a row limit.",
        note,
    )
    fields = [
        "Test", "Test ID", "Measured runs", "Route set", "Array", "Scan order", "Vmid",
        "Channel repeat", "Configuration", "SPI clock (MHz)", "Engine", "Sequence",
        "Duration median (us)", "Block period median (us)",
        "Payload throughput (samples/s)", "Sweep rate (Hz)",
        "Post-warm-up min", "Sample p1", "Sample median", "Sample p99",
        "Sample max", "Sample std-dev", "Settling max (us)",
        "Speedup vs blocking", "Status",
    ]
    worksheet.write_row(4, 0, fields, header)
    summary_test_ids = _summary_test_ids(result_rows)
    for index, row in enumerate(aggregates, 5):
        worksheet.write_row(index, 0, [
            summary_test_ids[str(row.get("test_id", ""))],
            row.get("test_id", ""),
            len(measured_runs.get(str(row.get("test_id", "")), set())),
            row.get("route_set", ""), row.get("array", ""),
            row.get("scanorder", ""),
            row.get("vmid_requested", ""),
            row.get("channelrepeat_requested", ""),
            _summary_label(row),
            float(row.get("spi_clock_hz") or 20_000_000) / 1_000_000.0,
            row.get("spiengine", ""), row.get("adcseq", ""),
            row.get("duration_median_us", ""), row.get("block_period_median_us", ""),
            row.get("payload_throughput_sps", ""), row.get("sweep_rate_hz", ""),
            row.get("sample_min_raw", ""), row.get("sample_p1_raw", ""),
            row.get("sample_median_raw", ""), row.get("sample_p99_raw", ""),
            row.get("sample_max_raw", ""), row.get("sample_stdev_raw", ""),
            row.get("settling_max_us", ""),
            row.get("speedup_vs_blocking", ""), row.get("overall_status", ""),
        ])
    if aggregates:
        worksheet.add_table(
            4, 0, 4 + len(aggregates), len(fields) - 1,
            {"name": "BenchmarkSummary", "style": "Table Style Medium 2",
             "columns": [{"header": field} for field in fields]},
        )
    worksheet.freeze_panes(5, 8)
    worksheet.set_column("A:A", 10)
    worksheet.set_column("B:B", 42)
    worksheet.set_column("C:C", 15)
    worksheet.set_column("D:D", 28)
    worksheet.set_column("E:H", 15)
    worksheet.set_column("I:I", 68)
    worksheet.set_column("J:Y", 18)
    worksheet.set_row(2, 22)

    if not aggregates:
        return
    first_row = 5
    last_row = 4 + len(aggregates)
    categories = ["Summary", first_row, 0, last_row, 0]
    chart_start_row = 7 + len(aggregates)

    timing = workbook.add_chart({"type": "column"})
    timing.add_series({
        "name": "Duration median (us)", "categories": categories,
        "values": ["Summary", first_row, 12, last_row, 12],
        "fill": {"color": "#4472C4"},
    })
    timing.add_series({
        "name": "Block period median (us)", "categories": categories,
        "values": ["Summary", first_row, 13, last_row, 13],
        "fill": {"color": "#A5A5A5"},
    })
    timing.set_title({"name": "Sweep duration and block period"})
    timing.set_y_axis({"name": "Microseconds", "min": 0})
    timing.set_legend({"position": "top"})
    timing.set_size({"width": 1050, "height": 420})
    worksheet.insert_chart(chart_start_row, 0, timing)

    rates = workbook.add_chart({"type": "column"})
    rates.add_series({
        "name": "Sweep rate (Hz)", "categories": categories,
        "values": ["Summary", first_row, 15, last_row, 15],
        "fill": {"color": "#70AD47"},
    })
    rates.set_title({"name": "Sweep rate"})
    rates.set_y_axis({"name": "Sweeps per second", "min": 0})
    rates.set_legend({"none": True})
    rates.set_size({"width": 1050, "height": 420})
    worksheet.insert_chart(chart_start_row + 22, 0, rates)

    samples = workbook.add_chart({"type": "line"})
    for column, name, color in (
        (17, "Sample p1", "#5B9BD5"),
        (18, "Sample median", "#70AD47"),
        (19, "Sample p99", "#ED7D31"),
    ):
        samples.add_series({
            "name": name, "categories": categories,
            "values": ["Summary", first_row, column, last_row, column],
            "line": {"color": color, "width": 2},
        })
    samples.set_title({"name": "Measured ADC values"})
    samples.set_y_axis({"name": "Raw ADC counts", "min": 0, "max": 4095})
    samples.set_legend({"position": "top"})
    samples.set_size({"width": 1050, "height": 420})
    worksheet.insert_chart(chart_start_row + 44, 0, samples)


def _format_resistance(value: Any) -> str:
    if value in (None, ""):
        return ""
    resistance = float(value)
    if resistance >= 1_000_000:
        return f"{resistance / 1_000_000:g} MΩ"
    if resistance >= 1_000:
        return f"{resistance / 1_000:g} kΩ"
    return f"{resistance:g} Ω"


def _write_warmup_curves(
    workbook: Any,
    fields: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
) -> None:
    if not fields or not rows:
        return
    elapsed_col = fields.index("elapsed_us")
    sample_col = fields.index("sample_raw")
    grouped: dict[tuple[int, int], list[int]] = {}
    resistance_by_route: dict[tuple[int, int], Any] = {}
    for excel_row, row in enumerate(rows, 1):
        route = (int(row["adc"]), int(row["channel"]))
        grouped.setdefault(route, []).append(excel_row)
        resistance_by_route[route] = row.get("bias_resistor_ohms", "")

    worksheet = workbook.add_worksheet("Warmup Curves")
    worksheet.hide_gridlines(2)
    worksheet.write(
        "A1",
        "First exported warm-up trace for each physical channel. "
        "Elapsed time is the Teensy device timestamp delta.",
    )
    placements = {1: "A3", 2: "J3", 3: "A22", 4: "J22"}
    colors = (
        "#4472C4", "#ED7D31", "#70AD47", "#A5A5A5", "#FFC000",
        "#5B9BD5", "#C55A11", "#548235", "#7F6000", "#7030A0",
        "#00B0F0", "#FF0000", "#76933C", "#8064A2", "#4BACC6",
    )
    for adc in range(1, 5):
        routes = sorted(route for route in grouped if route[0] == adc)
        if not routes:
            continue
        chart = workbook.add_chart({"type": "line"})
        for series_index, route in enumerate(routes):
            indices = grouped[route]
            first_row, last_row = min(indices), max(indices)
            resistance = _format_resistance(resistance_by_route[route])
            name = f"CH{route[1]}" + (f" ({resistance})" if resistance else "")
            chart.add_series({
                "name": name,
                "categories": ["Warmup Samples", first_row, elapsed_col,
                               last_row, elapsed_col],
                "values": ["Warmup Samples", first_row, sample_col,
                           last_row, sample_col],
                "line": {"color": colors[series_index % len(colors)], "width": 1},
            })
        chart.set_title({"name": f"ADC{adc} warm-up curves"})
        chart.set_x_axis({"name": "Elapsed time (µs)", "min": 0})
        chart.set_y_axis({"name": "Raw ADC counts", "min": 0, "max": 4095})
        chart.set_legend({"position": "bottom"})
        chart.set_size({"width": 700, "height": 350})
        worksheet.insert_chart(placements[adc], chart)


def _write_filterable_warmup_chart(
    workbook: Any,
    fields: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
) -> None:
    """Chart visible Warmup Samples rows so Excel filters select a channel."""
    if not fields or not rows:
        return
    elapsed_col = fields.index("elapsed_us")
    sample_col = fields.index("sample_raw")
    median_col = fields.index("post_warmup_median_raw")
    first_row, last_row = 1, len(rows)

    worksheet = workbook.add_worksheet("Warmup Channel")
    worksheet.hide_gridlines(2)
    worksheet.set_column("A:A", 115)
    worksheet.write(
        "A1",
        "Filter the ADC and Channel columns on the Warmup Samples worksheet. "
        "This graph plots visible rows only, so it updates to the selected channel.",
    )
    worksheet.write(
        "A2",
        "For a clean curve, select one ADC and one channel; optional filters such "
        "as array or bias resistance may also remain active.",
    )

    chart = workbook.add_chart({"type": "line"})
    chart.add_series({
        "name": "Warm-up sample",
        "categories": ["Warmup Samples", first_row, elapsed_col,
                       last_row, elapsed_col],
        "values": ["Warmup Samples", first_row, sample_col,
                   last_row, sample_col],
        "line": {"color": "#4472C4", "width": 2},
    })
    chart.add_series({
        "name": "Post-warm-up median",
        "categories": ["Warmup Samples", first_row, elapsed_col,
                       last_row, elapsed_col],
        "values": ["Warmup Samples", first_row, median_col,
                   last_row, median_col],
        "line": {"color": "#70AD47", "width": 1.5, "dash_type": "dash"},
    })
    chart.set_title({"name": "Filtered channel warm-up response"})
    chart.set_x_axis({"name": "Elapsed time (µs)", "min": 0})
    chart.set_y_axis({"name": "Raw ADC counts", "min": 0, "max": 4095})
    chart.set_legend({"position": "bottom"})
    chart.set_size({"width": 1100, "height": 600})
    # XlsxWriter charts omit hidden rows by default. Excel table filters hide
    # excluded rows, so this chart follows the Warmup Samples filters.
    worksheet.insert_chart("A4", chart)


def write_benchmark_workbook(
    output_path: Path,
    results_path: Path,
    channel_stats_path: Path,
    warmup_samples_path: Path,
    metadata_path: Path,
    glossary_path: Path,
) -> None:
    try:
        import xlsxwriter
    except ImportError as exc:
        raise RuntimeError("XlsxWriter is required; run 'uv sync'") from exc

    result_fields, result_rows = read_csv_rows(results_path)
    channel_fields, channel_rows = read_csv_rows(channel_stats_path)
    warmup_fields, warmup_rows = read_csv_rows(warmup_samples_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    glossary_rows = read_glossary(glossary_path)

    workbook = xlsxwriter.Workbook(str(output_path))
    workbook.set_properties({
        "title": "TestBoard 7953 benchmark report",
        "subject": "SPI engine, timing, and ADC sample comparison",
        "comments": "Generated by testboard_7953_benchmark.py",
    })
    try:
        _write_summary(workbook, result_rows)
        _write_filterable_warmup_chart(workbook, warmup_fields, warmup_rows)
        _write_warmup_curves(workbook, warmup_fields, warmup_rows)
        summary_test_ids = _summary_test_ids(result_rows)
        excel_result_fields = ["Test", *result_fields]
        excel_result_rows = [
            {
                "Test": summary_test_ids.get(str(row.get("test_id", "")), ""),
                **row,
            }
            for row in result_rows
        ]
        _write_table_sheet(
            workbook, "Results", excel_result_fields, excel_result_rows,
            "BenchmarkResults",
        )
        _write_table_sheet(
            workbook, "Channel Stats", channel_fields, channel_rows,
            "BenchmarkChannelStats",
        )
        if warmup_fields:
            _write_table_sheet(
                workbook, "Warmup Samples", warmup_fields, warmup_rows,
                "BenchmarkWarmupSamples",
            )

        session = workbook.add_worksheet("Session")
        session.hide_gridlines(2)
        session.write_row(0, 0, ["Metadata field", "Value"])
        metadata_rows = list(flatten_metadata(metadata))
        for row_index, (key, value) in enumerate(metadata_rows, 1):
            session.write(row_index, 0, key)
            session.write(row_index, 1, value)
        if metadata_rows:
            session.add_table(
                0, 0, len(metadata_rows), 1,
                {"name": "SessionMetadata", "style": "Table Style Medium 2",
                 "columns": [{"header": "Metadata field"}, {"header": "Value"}]},
            )
        session.set_column("A:A", 42)
        session.set_column("B:B", 90)
        session.freeze_panes(1, 0)

        glossary = workbook.add_worksheet("Glossary")
        glossary.hide_gridlines(2)
        glossary.write_row(0, 0, ["Field", "File", "Meaning"])
        for row_index, row in enumerate(glossary_rows, 1):
            glossary.write_row(row_index, 0, row)
        if glossary_rows:
            glossary.add_table(
                0, 0, len(glossary_rows), 2,
                {"name": "OutputGlossary", "style": "Table Style Medium 2",
                 "columns": [
                     {"header": "Field"}, {"header": "File"},
                     {"header": "Meaning"},
                 ]},
            )
        glossary.set_column("A:A", 38)
        glossary.set_column("B:B", 24)
        glossary.set_column("C:C", 110)
        glossary.freeze_panes(1, 0)
    finally:
        workbook.close()


def write_ghosting_workbook(
    output_path: Path,
    summary_rows: Sequence[Mapping[str, Any]],
    pair_rows: Sequence[Mapping[str, Any]],
    attempt_rows: Sequence[Mapping[str, Any]],
    metadata: Mapping[str, Any],
    graphs: Mapping[str, Mapping[str, Any]],
    glossary_path: Path,
) -> None:
    """Write selected-attempt tables and synchronized native signal charts.

    Graphs contain a shared reduced time vector, all acquired signal columns,
    and Y bounds computed from the full-resolution window before reduction.
    """
    try:
        import xlsxwriter
    except ImportError as exc:
        raise RuntimeError("XlsxWriter is required; run 'uv sync'") from exc
    temporary = output_path.with_suffix(".xlsx.tmp")
    workbook = xlsxwriter.Workbook(str(temporary))
    workbook.set_properties({"title": "TestBoard 7953 ghosting report",
                             "subject": "Sensor coupling amplitudes and synchronized signals"})
    try:
        percentage = workbook.add_format({"num_format": '0.00"%"'})
        correlation = workbook.add_format({"num_format": "0.000"})
        leading_fields = {
            "Summary": ["source", "status", "selected_attempt", "source_peak", "source_stdev", "ghosting_detected", "ghost_targets", "inconclusive_pairs"],
            "Pairs": ["source", "attempt", "target", "status", "source_peak", "target_peak", "source_stdev", "target_stdev", "attenuation_pct", "correlation", "ghosting_detected"],
            "Attempts": ["source", "attempt", "status", "source_peak", "source_stdev", "ghosting_detected", "ghost_targets", "notes"],
        }
        for name, rows in (("Summary", summary_rows), ("Pairs", pair_rows), ("Attempts", attempt_rows)):
            fields = list(dict.fromkeys([*leading_fields[name], *(key for row in rows for key in row)]))
            printable = [{key: ("Yes" if value else "No") if isinstance(value, bool) else value
                          for key, value in row.items()} for row in rows]
            _write_table_sheet(workbook, name, fields, printable, f"Ghosting{name}",
                               {"attenuation_pct": percentage, "correlation": correlation})
        worksheet = workbook.add_worksheet("Signal Graphs")
        worksheet.hide_gridlines(2)
        worksheet.set_column("A:A", 23)
        worksheet.set_column("B:B", 90)
        worksheet.write("A1", "Source signal overlays")
        worksheet.write("A2", "Baseline-relative counts; all measured channels. Detection evaluates only the source ADC.")
        data = workbook.add_worksheet("Chart Data")
        data.hide()
        palette = (
            "#4472C4", "#ED7D31", "#70AD47", "#A5A5A5", "#FFC000",
            "#5B9BD5", "#C55A11", "#548235", "#7F6000", "#7030A0",
            "#00B0F0", "#FF0000", "#76933C", "#8064A2", "#4BACC6",
            "#264478", "#9E480E", "#43682B", "#636363", "#997300",
            "#255E91", "#843C0C", "#375623", "#5F497A", "#31859B",
        )
        source_rows = sorted(summary_rows, key=lambda r: tuple(map(int, str(r["source"]).split(":"))))
        first_graph_row = len(source_rows) + 5
        data_row = 0
        for index, row in enumerate(source_rows):
            source = str(row["source"])
            adc, channel = source.split(":")
            label = f"ADC{adc}_CH{channel}"
            chart_row = first_graph_row + index * 32
            worksheet.write_url(index + 3, 0, f"internal:'Signal Graphs'!A{chart_row + 1}", string=label)
            worksheet.write(index + 3, 1, f"{row['status']} | selected attempt {row.get('selected_attempt', '')}")
            worksheet.write(chart_row, 0, label)
            graph = graphs.get(source)
            if not graph or row.get("selected_attempt", "") == "":
                worksheet.write(chart_row + 1, 0, f"No valid signal graph: {row['status']}")
                continue
            if graph["attempt"] != row["selected_attempt"]:
                raise ValueError(f"Graph attempt differs from summary for {source}")
            times = graph["times_s"]
            signals = graph["signals"]
            routes = list(graph["routes"])
            count = len(times)
            if not count or signals.shape != (count, len(routes)):
                raise ValueError(f"Invalid chart data dimensions for {source}")
            first = data_row + 1
            last = first + count - 1
            data.write_row(data_row, 0, [f"{label} attempt {graph['attempt']} time_s", *routes])
            for offset, elapsed in enumerate(times):
                data.write_number(first + offset, 0, float(elapsed))
                data.write_row(first + offset, 1, [float(value) for value in signals[offset]])
            chart = workbook.add_chart({"type": "scatter", "subtype": "straight"})
            series_order = [i for i, route in enumerate(routes) if route != source] + [routes.index(source)]
            for route_index in series_order:
                route = routes[route_index]
                route_adc, route_channel = route.split(":")
                chart.add_series({
                    "name": f"ADC{route_adc}_CH{route_channel}" + (" (source)" if route == source else ""),
                    "categories": ["Chart Data", first, 0, last, 0],
                    "values": ["Chart Data", first, route_index + 1, last, route_index + 1],
                    "line": {"color": palette[route_index % len(palette)], "width": 3 if route == source else 1},
                    "marker": {"type": "none"},
                })
            reduced = count < graph["full_sample_count"]
            title = f"{label} — attempt {graph['attempt']}"
            if reduced:
                title += f" (display reduced to {count} points)"
            chart.set_title({"name": title})
            chart.set_x_axis({"name": "Time since trigger (s)", "min": 0, "max": 2})
            lower, upper = graph["bounds"]
            chart.set_y_axis({"name": "Baseline-relative ADC counts", "min": lower, "max": upper})
            chart.set_legend({"position": "right"})
            chart.set_size({"width": 1100, "height": 600})
            chart.show_hidden_data()
            worksheet.insert_chart(chart_row + 1, 0, chart)
            data_row = last + 2
        session = workbook.add_worksheet("Session")
        session.write_row(0, 0, ["Metadata field", "Value"])
        for index, (key, value) in enumerate(flatten_metadata(metadata), 1):
            session.write(index, 0, key)
            session.write(index, 1, value)
        session.set_column("A:A", 46)
        session.set_column("B:B", 90)
        session.freeze_panes(1, 0)
        glossary_rows = [{"Field": field, "File": file, "Meaning": meaning}
                         for field, file, meaning in read_glossary(glossary_path)]
        _write_table_sheet(workbook, "Glossary", ["Field", "File", "Meaning"], glossary_rows, "GhostingGlossary")
    finally:
        workbook.close()
    temporary.replace(output_path)


def _sample_summary(values: Sequence[int]) -> dict[str, Any]:
    if not values:
        return {"min": "", "mean": "", "median": "", "max": "", "stdev": "", "mad": ""}
    median = float(statistics.median(values))
    return {
        "min": min(values),
        "mean": statistics.fmean(values),
        "median": median,
        "max": max(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "mad": statistics.median(abs(value - median) for value in values),
    }


def _derive_legacy_sample_statistics(
    samples_path: Path,
    result_rows: Sequence[dict[str, Any]],
    default_spi_clock_hz: int,
) -> tuple[list[dict[str, Any]], dict[tuple[str, str, str], dict[str, Any]]]:
    configs = {
        (
            str(row.get("test_id", "")), str(row.get("repetition", "")),
            str(row.get("attempt", "")),
        ): row
        for row in result_rows
        if row.get("result_scope") == "repetition"
    }
    channel_rows: list[dict[str, Any]] = []
    summaries: dict[tuple[str, str, str], dict[str, Any]] = {}
    current_key: Optional[tuple[str, str, str]] = None
    all_values: list[int] = []
    route_values: dict[tuple[int, int], list[int]] = {}
    route_warnings: dict[tuple[int, int], str] = {}

    def finish_group() -> None:
        nonlocal all_values, route_values, route_warnings
        if current_key is None:
            return
        config = configs.get(current_key, {})
        overall = _sample_summary(all_values)
        summaries[current_key] = overall
        for (adc, channel), values in route_values.items():
            stats = _sample_summary(values)
            channel_rows.append({
                "session_id": config.get("session_id", ""),
                "test_id": current_key[0],
                "repetition": current_key[1],
                "attempt": current_key[2],
                "drift_phase": config.get("drift_phase", ""),
                "route_set": config.get("route_set", ""),
                "array": config.get("array", ""),
                "scanorder": config.get("scanorder", ""),
                "adcseq": config.get("adcseq", ""),
                "spiengine": config.get("spiengine", ""),
                "spi_clock_hz": config.get("spi_clock_hz") or default_spi_clock_hz,
                "channelrepeat_requested": config.get("channelrepeat_requested", ""),
                "channelrepeat_effective": config.get("channelrepeat_effective", ""),
                "vmid_requested": config.get("vmid_requested", ""),
                "vmid_effective": config.get("vmid_effective", ""),
                "adc": adc,
                "channel": channel,
                "sample_count": len(values),
                "sample_min_raw": stats["min"],
                "sample_mean_raw": stats["mean"],
                "sample_median_raw": stats["median"],
                "sample_max_raw": stats["max"],
                "sample_stdev_raw": stats["stdev"],
                "sample_mad_raw": stats["mad"],
                "median_offset_from_vmid": float(stats["median"]) - 2048.0,
                "route_warning": route_warnings.get((adc, channel), ""),
            })
        all_values = []
        route_values = {}
        route_warnings = {}

    with samples_path.open("r", encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            key = (row["test_id"], row["repetition"], row.get("attempt", ""))
            if current_key is not None and key != current_key:
                finish_group()
            current_key = key
            value = int(row["sample_raw"])
            route = (int(row["adc"]), int(row["channel"]))
            all_values.append(value)
            route_values.setdefault(route, []).append(value)
            route_warnings[route] = row.get("route_warning", "")
    finish_group()
    return channel_rows, summaries


def write_existing_session_report(
    session_dir: Path,
    glossary_path: Path,
    output_name: str = "benchmark_report.xlsx",
) -> Path:
    """Create an Excel report, backfilling statistics for pre-v2 sessions."""

    results_path = session_dir / "benchmark_results.csv"
    channel_stats_path = session_dir / "benchmark_channel_stats.csv"
    warmup_samples_path = session_dir / "benchmark_warmup_samples.csv"
    metadata_path = session_dir / "session_metadata.json"
    output_path = session_dir / output_name
    result_fields, result_rows = read_csv_rows(results_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    initial_status = metadata.get("firmware_status_initial") or {}
    configured_clocks = metadata.get("spi_clocks_hz") or []
    default_clock = int(
        configured_clocks[0]
        if configured_clocks
        else initial_status.get("spi_clock_hz", 20_000_000)
    )
    if channel_stats_path.exists():
        write_benchmark_workbook(
            output_path, results_path, channel_stats_path, warmup_samples_path,
            metadata_path, glossary_path,
        )
        return output_path

    samples_path = session_dir / "benchmark_samples.csv"
    channel_rows, summaries = _derive_legacy_sample_statistics(
        samples_path, result_rows, default_clock
    )
    extra_result_fields = [
        "spi_clock_hz", "sample_min_raw", "sample_mean_raw",
        "sample_median_raw", "sample_max_raw", "sample_stdev_raw",
    ]
    for field in extra_result_fields:
        if field not in result_fields:
            result_fields.append(field)
    repetition_summaries: dict[str, list[dict[str, Any]]] = {}
    for row in result_rows:
        row["spi_clock_hz"] = row.get("spi_clock_hz") or default_clock
        if row.get("result_scope") != "repetition":
            continue
        key = (
            str(row.get("test_id", "")), str(row.get("repetition", "")),
            str(row.get("attempt", "")),
        )
        summary = summaries.get(key)
        if summary is None:
            continue
        row.update({
            "sample_min_raw": summary["min"],
            "sample_mean_raw": summary["mean"],
            "sample_median_raw": summary["median"],
            "sample_max_raw": summary["max"],
            "sample_stdev_raw": summary["stdev"],
        })
        repetition_summaries.setdefault(str(row.get("test_id", "")), []).append(summary)
    for row in result_rows:
        if row.get("result_scope") != "aggregate":
            continue
        group = repetition_summaries.get(str(row.get("test_id", "")), [])
        if not group:
            continue
        row.update({
            "sample_min_raw": min(item["min"] for item in group),
            "sample_mean_raw": statistics.median(item["mean"] for item in group),
            "sample_median_raw": statistics.median(item["median"] for item in group),
            "sample_max_raw": max(item["max"] for item in group),
            "sample_stdev_raw": statistics.median(item["stdev"] for item in group),
        })

    channel_fields = list(channel_rows[0].keys()) if channel_rows else []
    with tempfile.TemporaryDirectory(prefix="testboard7953-report-") as temporary:
        temp_dir = Path(temporary)
        enriched_results = temp_dir / "benchmark_results.csv"
        enriched_channels = temp_dir / "benchmark_channel_stats.csv"
        enriched_metadata = temp_dir / "session_metadata.json"
        with enriched_results.open("w", encoding="utf-8", newline="") as destination:
            writer = csv.DictWriter(destination, fieldnames=result_fields)
            writer.writeheader()
            writer.writerows(result_rows)
        with enriched_channels.open("w", encoding="utf-8", newline="") as destination:
            writer = csv.DictWriter(destination, fieldnames=channel_fields)
            writer.writeheader()
            writer.writerows(channel_rows)
        report_metadata = dict(metadata)
        report_metadata.setdefault("spi_clocks_hz", [default_clock])
        report_metadata["report_backfilled_from_legacy_samples"] = True
        enriched_metadata.write_text(
            json.dumps(report_metadata, indent=2), encoding="utf-8"
        )
        write_benchmark_workbook(
            output_path, enriched_results, enriched_channels,
            temp_dir / "benchmark_warmup_samples.csv", enriched_metadata,
            glossary_path,
        )
    return output_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Create an Excel report for an existing benchmark session."
    )
    parser.add_argument("session", type=Path)
    parser.add_argument(
        "--glossary", type=Path,
        default=Path(__file__).resolve().parent / "OUTPUT_GLOSSARY.md",
    )
    cli_args = parser.parse_args()
    print(write_existing_session_report(
        cli_args.session.resolve(), cli_args.glossary.resolve()
    ))
