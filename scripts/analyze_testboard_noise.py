"""Read a saved GUI archive without changing it; summarize raw channel variation.

Example: python scripts/analyze_testboard_noise.py capture.jsonl --output analysis
Window standard deviations include actual input motion/interference, not just
ADC electronic noise. No filtering, interpolation, or baseline correction is
applied to the archived samples.
"""

import argparse
import json
import os
from pathlib import Path

import numpy as np


def window_stats(t, x, start, end, specs, groups):
    z = x[(t >= start) & (t < end)]
    if len(z) < 2:
        raise ValueError(f"Insufficient samples in window {start}..{end}")
    std = z.std(axis=0, ddof=1)
    med = np.median(z, axis=0)
    centered = z - z.mean(axis=0)
    # A quantized channel can be constant in a short quiet window. Its
    # correlation is undefined; exclude it rather than emitting NaN in JSON.
    pairs = [(i, j) for i, j in zip(*groups) if std[i] > 0 and std[j] > 0]
    correlations = [float(np.dot(centered[:, i], centered[:, j]) /
                          ((len(z) - 1) * std[i] * std[j])) for i, j in pairs]
    return {
        "start_s": start, "end_s": end, "sweeps": len(z),
        "array_median_channel_std_counts": [float(np.median(std[g])) for g in groups],
        "paired_channel_correlation_median": float(np.median(correlations)) if correlations else None,
        "paired_channel_correlation_defined_pairs": len(pairs),
        "channels": [{"label": s["label"], "median_counts": float(med[i]),
                      "std_counts": float(std[i]), "min_counts": int(z[:, i].min()),
                      "max_counts": int(z[:, i].max())} for i, s in enumerate(specs)],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--quiet", nargs=2, type=float, default=[10.45, 10.56])
    parser.add_argument("--burst", nargs=2, type=float, default=[10.60, 10.78])
    parser.add_argument("--plot", action="store_true")
    parser.add_argument("--array1-label", default="Array 1")
    parser.add_argument("--array2-label", default="Array 2")
    args = parser.parse_args()
    timestamps, samples = [], []
    footer = None
    with args.archive.open(encoding="utf-8") as source:
        metadata = json.loads(next(source))["metadata"]
        for line in source:
            record = json.loads(line)
            if "samples" in record:
                timestamps.append(record["timestamp_s"])
                samples.append(record["samples"])
            elif "capture_summary" in record:
                footer = record["capture_summary"]
    descriptor = metadata["testboard_acquisition"]
    specs = descriptor["channel_specs"]
    t = np.asarray(timestamps, dtype=np.float64)
    raw = np.asarray(samples, dtype=np.uint16)
    # Use the frozen sample indices, rather than assuming GUI or firmware order.
    if any(len(s["sample_indices"]) != 1 for s in specs):
        raise ValueError("This analyzer requires one retained sample per route")
    x = raw[:, [s["sample_indices"][0] for s in specs]].astype(np.float64)
    groups = [[i for i, s in enumerate(specs) if s["array_number"] == a] for a in (1, 2)]
    if not groups[0] or len(groups[0]) != len(groups[1]):
        raise ValueError("Matched channels from both arrays are required")
    if [specs[i]["label"][3:] for i in groups[0]] != [specs[i]["label"][3:] for i in groups[1]]:
        raise ValueError("Array channel orders do not match")
    dt = np.diff(t)
    if np.any(dt <= 0) or raw.max() > 4095:
        raise ValueError("Nonmonotonic timestamps or invalid 12-bit values")
    if footer is None or len(t) != footer["archive_written_sweeps"]:
        raise ValueError("Archive footer/count mismatch")
    centers, deviations = [], []
    for start in np.arange(1.0, t[-1] - 0.02, 0.02):
        z = x[(t >= start) & (t < start + 0.02)]
        if len(z) >= 2:
            centers.append(start + 0.01)
            deviations.append(z.std(axis=0, ddof=1))
    deviations = np.asarray(deviations)
    envelopes = [np.median(deviations[:, g], axis=1) for g in groups]
    # Report the strongest envelope recurrence between 0.5 and 2 seconds;
    # this describes burst timing, not the frequency of electrical interference.
    centered_envelope = envelopes[0] - envelopes[0].mean()
    autocorrelation = np.correlate(centered_envelope, centered_envelope, mode="full")
    autocorrelation = autocorrelation[len(centered_envelope) - 1:]
    autocorrelation /= autocorrelation[0]
    recurrence_index = 25 + int(np.argmax(autocorrelation[25:101]))
    quiet = window_stats(t, x, *args.quiet, specs, groups)
    burst = window_stats(t, x, *args.burst, specs, groups)
    baseline = np.median(x[t >= 1], axis=0)
    gap_indices = np.flatnonzero(dt > 3 * np.median(dt))
    summary = {
        "archive": str(args.archive.resolve()), "sweeps": len(t), "values": raw.size,
        "array_plot_annotations": [args.array1_label, args.array2_label],
        "duration_s": float(t[-1] - t[0]), "spi_clock_hz": descriptor["spi_clock_hz"],
        "spi_engine": descriptor["spi_engine"], "sequence": descriptor["sequence"],
        "repeat": descriptor["channelrepeat_effective"],
        "ghost_removal": metadata.get("pzt_ghost_removal"),
        "received_period_median_us": float(np.median(dt) * 1e6),
        "received_period_max_us": float(dt.max() * 1e6),
        "gaps_above_three_periods": [{"before_s": float(t[i]), "after_s": float(t[i+1]),
                                     "interval_us": float(dt[i] * 1e6)} for i in gap_indices],
        "noise_envelope_bin_s": 0.02,
        "noise_envelope_correlation": float(np.corrcoef(*envelopes)[0, 1]),
        "array1_envelope_recurrence_search_s": [0.5, 2.0],
        "array1_envelope_recurrence_s": recurrence_index * 0.02,
        "array1_envelope_recurrence_correlation": float(autocorrelation[recurrence_index]),
        "duplicate_column_pairs": [[specs[i]["label"], specs[j]["label"]]
                                   for i in range(len(specs)) for j in range(i)
                                   if np.array_equal(x[:, i], x[:, j])],
        "baseline_after_1s": [{"label": s["label"], "adc": s["adc_lane"],
                               "sample_indices": s["sample_indices"],
                               "median_counts": float(baseline[i])} for i, s in enumerate(specs)],
        "quiet": quiet, "burst": burst, "capture_summary": footer,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if args.plot:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import pyqtgraph as pg
        import pyqtgraph.exporters
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QFont, QFontDatabase
        app = QApplication.instance() or QApplication([])
        # Qt's offscreen platform can lack the Windows system font database.
        if not QFontDatabase.families() and os.name == "nt":
            font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/arial.ttf"
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                app.setFont(QFont(families[0], 11))
        pg.setConfigOptions(background="w", foreground="#263238", antialias=True)
        widget = pg.GraphicsLayoutWidget()
        widget.resize(1400, 1000)
        colors = ["#0072B2", "#D55E00"]
        plot = widget.addPlot(title="Raw variation: median channel standard deviation in 20 ms bins")
        plot.addLegend()
        for label, e, c in zip((args.array1_label, args.array2_label), envelopes, colors):
            plot.plot(centers, e, pen=pg.mkPen(c, width=2), name=label)
        plot.setLabel("left", "Standard deviation", units="ADC counts")
        plot.getAxis("left").enableAutoSIPrefix(False)
        plot.setLabel("bottom", "Device time", units="s")
        plot.showGrid(x=True, y=True, alpha=0.15)
        for label, centered in [("PZT7_R", True), ("PZT5_L", False)]:
            widget.nextRow()
            title = ("Raw PZT7_R: own median subtracted, showing correlated bursts" if centered
                     else "Raw PZT5_L: baseline and short-term variation")
            plot = widget.addPlot(title=title)
            plot.addLegend()
            mask = t >= max(1.0, t[-1] - 1.0)
            for a, c, annotation in zip((1, 2), colors, (args.array1_label, args.array2_label)):
                i = next(i for i, s in enumerate(specs) if s["label"] == f"A{a}_{label}")
                y = x[mask, i] - (baseline[i] if centered else 0)
                plot.plot(t[mask], y, pen=pg.mkPen(c, width=1), name=annotation)
            plot.setLabel("left", "Deviation" if centered else "ADC value", units="counts")
            plot.setLabel("bottom", "Device time", units="s")
            plot.showGrid(x=True, y=True, alpha=0.15)
        widget.show()
        app.processEvents()
        exporter = pg.exporters.ImageExporter(widget.scene())
        exporter.parameters()["width"] = 1400
        exporter.export(str(args.output / "raw_noise.png"))
        widget.close()
    print(json.dumps({k: summary[k] for k in ("sweeps", "values", "duration_s",
                                              "noise_envelope_correlation", "gaps_above_three_periods")}))


if __name__ == "__main__":
    main()
