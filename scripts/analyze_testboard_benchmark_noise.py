"""Compare independent benchmark wire captures with archived GUI raw arrays.

No GUI decoder, filtering, interpolation, or display reduction is used.
The benchmark's own parser decodes the saved binary stream. Channel routes
come from its reported status, not from plot labels.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np

BENCHMARKS = Path(__file__).resolve().parents[1] / "Arduino_Sketches/TestBoard_7953/benchmarks"
sys.path.insert(0, str(BENCHMARKS))
from benchmark_common import BinaryFrameParser, stream_integrity_counts, uint32_delta


def summarize(t, x, routes):
    """Use the same post-first-second 20 ms statistics as the GUI analysis."""
    groups = [[i for i, (adc, _) in enumerate(routes) if adc in pair]
              for pair in ((1, 2), (3, 4))]
    centers, deviations = [], []
    for start in np.arange(1.0, t[-1] - 0.02, 0.02):
        left, right = np.searchsorted(t, [start, start + 0.02])
        if right - left >= 2:
            centers.append(start + 0.01)
            deviations.append(x[left:right].std(axis=0, ddof=1))
    deviations = np.asarray(deviations)
    envelopes = np.array([np.median(deviations[:, group], axis=1) for group in groups])
    periods = []
    for envelope in envelopes:
        centered = envelope - envelope.mean()
        corr = np.correlate(centered, centered, mode="full")[len(centered) - 1:]
        corr /= corr[0]
        lag = 25 + int(np.argmax(corr[25:101]))
        periods.append({"period_s": lag * 0.02, "autocorrelation": float(corr[lag])})
    baseline = np.median(x[t >= 1], axis=0)
    dt = np.diff(t) * 1e6
    adc_envelopes = np.array([np.median(deviations[:,
        [i for i, route in enumerate(routes) if route[0] == adc]], axis=1)
        for adc in (1, 2, 3, 4)])
    summary = {
        "sweeps": len(t), "values": int(x.size), "duration_s": float(t[-1]),
        "received_period_median_us": float(np.median(dt)),
        "received_period_max_us": float(dt.max()),
        "received_omission_intervals": [
            {"before_s": float(t[i]), "after_s": float(t[i + 1]), "interval_us": float(dt[i])}
            for i in np.flatnonzero(dt > 1.5 * np.median(dt))],
        "noise_envelope_bin_s": 0.02,
        "array_envelope_std_median_counts": np.median(envelopes, axis=1).tolist(),
        "array_envelope_std_p95_counts": np.percentile(envelopes, 95, axis=1).tolist(),
        "array_envelope_correlation": float(np.corrcoef(envelopes)[0, 1]),
        "array_envelope_recurrence": periods,
        "channel_baselines": [{"adc": adc, "channel": channel, "median_counts": float(baseline[i])}
                              for i, (adc, channel) in enumerate(routes)],
        "pzt5_l": [],
        "per_adc_envelope_std_p95_counts": {
            str(adc): float(np.percentile(adc_envelopes[adc - 1], 95)) for adc in (1, 2, 3, 4)},
        "per_adc_envelope_correlation_matrix": np.corrcoef(adc_envelopes).tolist(),
    }
    for adc in (2, 4):
        idx = routes.index((adc, 11))
        others = [i for i, route in enumerate(routes) if route[0] == adc and route[1] != 11]
        other_median = float(np.median(baseline[others]))
        summary["pzt5_l"].append({"adc": adc, "channel": 11,
                                 "median_counts": float(baseline[idx]),
                                 "other_channel_baseline_median_counts": other_median,
                                 "deficit_from_other_channels_counts": other_median - float(baseline[idx])})
    return summary, np.asarray(centers), envelopes, baseline


def plot_comparison(output, t, x, routes, data, gui_data):
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
    widget = pg.GraphicsLayoutWidget()
    widget.resize(1400, 1000)
    colors = ["#0072B2", "#D55E00"]
    for name, dataset in (("Standalone benchmark", data), ("Previous GUI capture", gui_data)):
        plot = widget.addPlot(title=f"{name}: both strips unplugged, raw 20 ms variation")
        plot.addLegend()
        for a, color in enumerate(colors):
            plot.plot(dataset[1], dataset[2][a], pen=pg.mkPen(color, width=2), name=f"Array {a + 1}")
        plot.setLabel("left", "Standard deviation", units="ADC counts")
        plot.getAxis("left").enableAutoSIPrefix(False)
        plot.setLabel("bottom", "Time from capture start", units="s")
        plot.showGrid(x=True, y=True, alpha=0.15)
        widget.nextRow()
    plot = widget.addPlot(title="Standalone benchmark: raw PZT5_L baselines (ADC2/4 channel 11)")
    plot.addLegend()
    mask = t >= t[-1] - 1.0
    for adc, color in zip((2, 4), colors):
        idx = routes.index((adc, 11))
        plot.plot(t[mask], x[mask, idx], pen=pg.mkPen(color, width=1), name=f"ADC{adc}:11")
        other = data[0]["pzt5_l"][(adc - 2) // 2]["other_channel_baseline_median_counts"]
        plot.addLine(y=other, pen=pg.mkPen(color, width=1, style=pg.QtCore.Qt.PenStyle.DashLine))
    plot.setLabel("left", "ADC value", units="counts")
    plot.getAxis("left").enableAutoSIPrefix(False)
    plot.setLabel("bottom", "Time from capture start", units="s")
    plot.showGrid(x=True, y=True, alpha=0.15)
    widget.show()
    app.processEvents()
    exporter = pg.exporters.ImageExporter(widget.scene())
    exporter.parameters()["width"] = 1400
    exporter.export(str(output / "raw_benchmark_comparison.png"))
    widget.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw", type=Path)
    parser.add_argument("--gui-npz", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plot", action="store_true")
    args = parser.parse_args()
    session = args.raw.parent.parent
    status = json.loads((session / (args.raw.stem + "__status.json")).read_text())
    metadata = json.loads((session / "session_metadata.json").read_text())
    routes = [tuple(map(int, route.split(":"))) for route in status["adcchannels"].split(",")]
    expected = [(adc, channel) for adc, count in ((1, 10), (2, 15), (3, 10), (4, 15))
                for channel in range(count)]
    if routes != expected or status["channelrepeat_effective"] != "1":
        raise ValueError("This comparison requires all 50 ADC-ordered routes, repeat 1")
    decoder = BinaryFrameParser(expected_sample_count=50)
    frames = []
    digest = hashlib.sha256()
    with args.raw.open("rb") as source:
        while chunk := source.read(65536):
            digest.update(chunk)
            frames.extend(decoder.feed(chunk))
    trailing = decoder.finish()
    integrity = stream_integrity_counts(frames)
    if trailing or decoder.invalid_frames or decoder.discarded_bytes or any(integrity.values()):
        raise ValueError(f"Invalid binary capture: {vars(decoder)}, integrity={integrity}")
    if len(frames) != int(status["usb_frames_sent"]):
        raise ValueError("Binary frame count differs from firmware frames sent")
    x = np.asarray([frame.samples for frame in frames], dtype=np.uint16)
    t = np.array([uint32_delta(frame.block_start_us, frames[0].block_start_us) / 1e6
                  for frame in frames])
    if x.max() > 4095 or np.any(np.diff(t) <= 0):
        raise ValueError("Invalid values or timestamps")
    # Independently check the saved fixed-width byte layout against the parser.
    wire_dtype = np.dtype([("magic", "u1", (2,)), ("count", "<u2"),
                           ("samples", "<u2", (50,)), ("avg_dt", "<u2"),
                           ("start", "<u4"), ("end", "<u4")])
    wire = np.fromfile(args.raw, dtype=wire_dtype)
    if (wire_dtype.itemsize != 114 or args.raw.stat().st_size != len(frames) * 114
            or not np.all(wire["magic"] == [0xAA, 0x55])
            or not np.all(wire["count"] == 50) or not np.array_equal(wire["samples"], x)
            or not np.array_equal(wire["start"], [frame.block_start_us for frame in frames])):
        raise ValueError("Fixed-width wire check differs from benchmark parser")
    data = summarize(t, x, routes)
    with np.load(args.gui_npz) as gui:
        gui_data = summarize(gui["t"] - gui["t"][0], gui["x"], routes)
    summary = {"benchmark_raw": str(args.raw.resolve()), "raw_sha256": digest.hexdigest(),
               "gui_raw_arrays": str(args.gui_npz.resolve()),
               "session_metadata": metadata, "firmware_status_after": status,
               "parser_invalid_frames": decoder.invalid_frames,
               "parser_discarded_bytes": decoder.discarded_bytes,
               "stream_integrity": integrity,
               "fixed_width_wire_check": "PASS",
               "method": "Post-first-second 20 ms bins; median channel standard deviation per array; no filtering",
               "benchmark": data[0], "gui": gui_data[0]}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "comparison.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if args.plot:
        plot_comparison(args.output, t, x, routes, data, gui_data)
    print(json.dumps({key: {field: summary[key][field] for field in
                           ("sweeps", "array_envelope_std_p95_counts", "array_envelope_correlation",
                            "array_envelope_recurrence", "pzt5_l")}
                      for key in ("benchmark", "gui")}, indent=2))


if __name__ == "__main__":
    main()
