"""Analyze a benchmark engine/topology matrix directly from retained wire bytes.

Uses device timestamps, post-first-second 20 ms standard-deviation envelopes,
and per-route raw medians. No GUI code, interpolation, or filtering is used.
Single-ADC, single-array, and both-array route sets are supported. The existing
benchmark runner remains responsible for capture and its normal checks.
"""

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path

import numpy as np


def recurrence(envelope):
    centered = envelope - envelope.mean()
    corr = np.correlate(centered, centered, mode="full")[len(centered) - 1:]
    if not corr[0]:
        return {"period_s": None, "autocorrelation": None}
    corr /= corr[0]
    lag = 25 + int(np.argmax(corr[25:101]))
    return {"period_s": float(lag * 0.02), "autocorrelation": float(corr[lag])}


def envelope_stats(envelope):
    return {"std_p10_counts": float(np.percentile(envelope, 10)),
            "std_median_counts": float(np.median(envelope)),
            "std_p95_counts": float(np.percentile(envelope, 95)),
            "std_max_counts": float(envelope.max()), **recurrence(envelope)}


def analyze(raw):
    status = json.loads((raw.parent.parent / (raw.stem + "__status.json")).read_text())
    routes = [tuple(map(int, item.split(":"))) for item in status["adcchannels"].split(",")]
    if status["scanorder"] != "adc" or status["channelrepeat_effective"] != "1":
        raise ValueError(f"Unsupported payload order/repeat: {raw}")
    count = len(routes)
    if not count or len(set(routes)) != count:
        raise ValueError(f"Invalid routes: {raw}")
    dtype = np.dtype([("magic", "u1", (2,)), ("count", "<u2"),
                      ("samples", "<u2", (count,)), ("avg_dt", "<u2"),
                      ("start", "<u4"), ("end", "<u4")])
    wire = np.fromfile(raw, dtype=dtype)
    if (raw.stat().st_size != len(wire) * dtype.itemsize or len(wire) < 2
            or not np.all(wire["magic"] == [0xAA, 0x55])
            or not np.all(wire["count"] == count) or wire["samples"].max() > 4095):
        raise ValueError(f"Invalid wire headers/counts/values: {raw}")
    starts = wire["start"].astype(np.int64)
    t = ((starts - starts[0]) % (1 << 32)) / 1e6
    dt = np.diff(t) * 1e6
    durations = (wire["end"].astype(np.int64) - starts) % (1 << 32)
    gaps = (starts[1:] - wire["end"][:-1].astype(np.int64)) % (1 << 32)
    if (np.any(dt <= 0) or np.any(dt >= (1 << 31))
            or np.any(durations <= 0) or np.any(durations >= (1 << 31))
            or np.any(gaps >= (1 << 31))):
        raise ValueError(f"Nonmonotonic/overlapping device timestamps: {raw}")
    if (len(wire) != int(status["usb_frames_sent"])
            or int(status["sampling_sweeps"]) != len(wire) + int(status["usb_frames_discarded"])):
        raise ValueError(f"Firmware frame-count reconciliation failed: {raw}")
    errors = {key: int(status[key]) for key in
              ("adc1_errors", "adc2_errors", "adc3_errors", "adc4_errors",
               "returned_channel_errors", "transfer_timeouts", "usb_write_errors",
               "dma_start_errors", "lpspi_start_errors")}
    if any(errors.values()):
        raise ValueError(f"Nonzero firmware error counters: {raw}: {errors}")
    x = wire["samples"]
    baseline = np.median(x[t >= 1], axis=0)
    centers, deviations = [], []
    for start in np.arange(1.0, t[-1] - 0.02, 0.02):
        left, right = np.searchsorted(t, [start, start + 0.02])
        if right - left >= 2:
            centers.append(start + 0.01)
            deviations.append(x[left:right].std(axis=0, ddof=1))
    deviations = np.asarray(deviations)
    all_envelope = np.median(deviations, axis=1)
    adcs = sorted({route[0] for route in routes})
    adc_envelopes, adc_stats = [], {}
    for adc in adcs:
        indexes = [i for i, route in enumerate(routes) if route[0] == adc]
        envelope = np.median(deviations[:, indexes], axis=1)
        adc_envelopes.append(envelope)
        medians = baseline[indexes]
        stats = {**envelope_stats(envelope), "channel_baseline_median_counts": float(np.median(medians))}
        for channel in (0, 11):
            if (adc, channel) in routes:
                idx = routes.index((adc, channel))
                others = [i for i in indexes if i != idx]
                stats[f"channel{channel}_median_counts"] = float(baseline[idx])
                stats[f"channel{channel}_deficit_from_other_channels_counts"] = (
                    float(np.median(baseline[others]) - baseline[idx]) if others else None)
        adc_stats[str(adc)] = stats
    test_id = raw.stem.rsplit("__r", 1)[0]
    summary = {"test_id": test_id, "raw": str(raw.resolve()),
               "raw_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
               "route_set": test_id.split("__")[0], "engine": status["spiengine"],
               "spi_clock_hz": int(status["spi_clock_hz"]), "active_adcs": adcs,
               "routes": [list(route) for route in routes], "sweeps": len(wire),
               "measured_sweeps": int(np.count_nonzero(t >= 1)), "duration_s": float(t[-1]),
               "received_period_median_us": float(np.median(dt)),
               "received_period_max_us": float(dt.max()),
               "acquisition_duration_median_us": float(np.median(durations)),
               "usb_frames_discarded": int(status["usb_frames_discarded"]),
               "sampling_period_max_us": int(status["sampling_period_max_us"]),
               "sampling_period_over_1ms": int(status["sampling_period_over_1ms"]),
               "firmware_errors": errors, "wire_integrity": "PASS",
               "all_routes_envelope": envelope_stats(all_envelope), "adcs": adc_stats,
               "adc_envelope_correlation_order": adcs,
               "adc_envelope_correlation_matrix": np.corrcoef(adc_envelopes).tolist() if len(adcs) > 1 else None,
               "channel_baselines": [{"adc": adc, "channel": ch, "median_counts": float(baseline[i])}
                                     for i, (adc, ch) in enumerate(routes)],
               "firmware_status_after": status}
    return summary, np.asarray(centers), all_envelope


def plot(output, runs):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import pyqtgraph as pg
    import pyqtgraph.exporters
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QFont, QFontDatabase
    app = QApplication.instance() or QApplication([])
    if not QFontDatabase.families() and os.name == "nt":
        font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/arial.ttf"
        families = QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(str(font)))
        if families:
            app.setFont(QFont(families[0], 11))
    pg.setConfigOptions(background="w", foreground="#263238", antialias=True)
    colors = {"blocking": "#0072B2", "dma": "#D55E00", "lpspi": "#009E73"}
    names = {**{f"single_adc{adc}": f"ADC{adc} alone" for adc in (1, 2, 3, 4)},
             "full_array1": "Array 1 only (ADC1 + ADC2)",
             "full_array2": "Array 2 only (ADC3 + ADC4)",
             "all_four_full": "Both arrays (all four ADCs)"}
    widget = pg.GraphicsLayoutWidget()
    widget.resize(1400, 1900)
    for topology, name in names.items():
        panel = widget.addPlot(title=f"{name}: median channel variation in 20 ms bins")
        panel.addLegend()
        for summary, centers, envelope in runs:
            if summary["route_set"] == topology:
                engine = summary["engine"]
                panel.plot(centers, envelope, pen=pg.mkPen(colors[engine], width=1.5), name=engine)
        panel.setLabel("left", "Standard deviation", units="counts")
        panel.getAxis("left").enableAutoSIPrefix(False)
        panel.setLabel("bottom", "Time from independent capture start", units="s")
        panel.showGrid(x=True, y=True, alpha=0.15)
        widget.nextRow()
    widget.show()
    app.processEvents()
    exporter = pg.exporters.ImageExporter(widget.scene())
    exporter.parameters()["width"] = 1400
    exporter.export(str(output / "engine_topology_envelopes.png"))
    widget.close()
    widget = pg.GraphicsLayoutWidget()
    widget.resize(1400, 850)
    topology_colors = ["#0072B2", "#D55E00", "#009E73"]
    for adc in (2, 4):
        for engine in colors:
            panel = widget.addPlot(title=f"ADC{adc}: {engine}, raw channel baselines")
            panel.addLegend()
            topologies = [f"single_adc{adc}", "full_array1" if adc == 2 else "full_array2", "all_four_full"]
            for topology, name, color in zip(topologies, ("ADC alone", "One array", "Both arrays"), topology_colors):
                match = next((s for s, _, _ in runs if s["engine"] == engine and s["route_set"] == topology), None)
                if match:
                    channels = [r for r in match["channel_baselines"] if r["adc"] == adc]
                    panel.plot([r["channel"] for r in channels], [r["median_counts"] for r in channels],
                               pen=pg.mkPen(color, width=2), symbol="o", symbolSize=5, name=name)
            panel.addLine(y=2048, pen=pg.mkPen("#999999", style=pg.QtCore.Qt.PenStyle.DashLine))
            panel.setLabel("left", "Median", units="ADC counts")
            panel.getAxis("left").enableAutoSIPrefix(False)
            panel.setLabel("bottom", "Physical ADC channel (11 = PZT5_L)")
            panel.showGrid(x=True, y=True, alpha=0.15)
        widget.nextRow()
    widget.show()
    app.processEvents()
    exporter = pg.exporters.ImageExporter(widget.scene())
    exporter.parameters()["width"] = 1400
    exporter.export(str(output / "engine_topology_baselines.png"))
    widget.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--partial", action="store_true")
    parser.add_argument("--plot", action="store_true")
    args = parser.parse_args()
    metadata = json.loads((args.session / "session_metadata.json").read_text())
    runs = []
    for raw in sorted((args.session / "raw").glob("*.bin")):
        if (args.session / (raw.stem + "__status.json")).exists():
            runs.append(analyze(raw))
    csv_validation = "PENDING"
    if not args.partial:
        if metadata["status"] != "complete" or len(runs) != len(metadata["test_ids"]):
            raise ValueError("Benchmark matrix is incomplete; use --partial for intermediate analysis")
        with (args.session / "benchmark_channel_stats.csv").open(newline="") as source:
            reference = {(row["test_id"], int(row["adc"]), int(row["channel"])):
                         float(row["sample_median_raw"]) for row in csv.DictReader(source)}
        for summary, _, _ in runs:
            for route in summary["channel_baselines"]:
                key = summary["test_id"], route["adc"], route["channel"]
                if reference[key] != route["median_counts"]:
                    raise ValueError(f"Independent median differs from benchmark channel CSV: {key}")
        csv_validation = f"PASS: {sum(len(s['routes']) for s, _, _ in runs)} channel medians"
    args.output.mkdir(parents=True, exist_ok=True)
    summary = {"session": str(args.session.resolve()), "session_metadata": metadata,
               "method": "Raw fixed-width wire decode; post-first-second complete 20 ms bins; per-channel standard deviation; no filtering",
               "recurrence_method": "Strongest envelope autocorrelation between 0.5 and 2 s; weak maxima are not evidence of periodic bursts",
               "independent_channel_csv_validation": csv_validation,
               "runs": [s for s, _, _ in runs]}
    restored_path = args.session / "restored_status.json"
    if restored_path.exists():
        summary["restored_configuration_status"] = json.loads(restored_path.read_text())
    (args.output / "comparison.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    for s, _, _ in runs:
        print(f"{s['route_set']:14} {s['engine']:8} period={s['received_period_median_us']:6.1f}us discards={s['usb_frames_discarded']:5} "
              + "; ".join(f"ADC{adc} std95={a['std_p95_counts']:.3f} recurrence={a['period_s']}s r={a['autocorrelation']:.3f} "
                           f"ch11={a.get('channel11_median_counts', '-') }" for adc, a in s["adcs"].items()))
    if args.plot:
        plot(args.output, runs)


if __name__ == "__main__":
    main()
