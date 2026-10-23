"""Build, run and post-process the TestBoard_ADC124 QSPICE model.

Scenarios (config.json -> "scenarios"):
    two_pulses   force pulses on two sensors with soft edges; compared with a zero-force baseline run
    baseline     no force; 60 ms of continuous scanning at full resolution to see where the baseline of each channel settles

Usage:
    python run_simulation.py                          # both scenarios
    python run_simulation.py --scenario two_pulses
    python run_simulation.py --scenario baseline --set timing.run_duration_s=0.2
    python run_simulation.py --sweep timing.t_vmid_park_us=0,7,20 --no-plots     # two_pulses sweep

Outputs go to results/<scenario>/.  Requires numpy and matplotlib.  QSPICE path: env QSPICE_EXE or the default
install location.
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

import build_model as bm

HERE = bm.HERE
RESULTS = HERE / "results"
QSPICE_EXE = os.environ.get("QSPICE_EXE", r"C:\Program Files\QSPICE\QSPICE64.exe")


# ----------------------------------------------------------------------------- QSPICE I/O
def run_qspice(netlist: Path) -> Path:
    proc = subprocess.run([QSPICE_EXE, str(netlist), "-binary", "-o", str(netlist.with_suffix(".out"))],
                          capture_output=True, text=True, timeout=3600)
    raw = netlist.with_suffix(".qraw")
    if not raw.exists():
        raise RuntimeError(f"QSPICE produced no .qraw\n{proc.stdout}\n{proc.stderr}")
    return raw


def read_qraw(path: Path) -> dict[str, np.ndarray]:
    with path.open("rb") as fh:
        head = fh.read(1 << 16)
    split = head.find(b"Binary:")
    header = head[:split].decode("latin1").splitlines()
    nvar = int(next(l for l in header if l.startswith("No. Variables")).split(":")[1])
    npts = int(next(l for l in header if l.startswith("No. Points")).split(":")[1])
    i0 = next(i for i, l in enumerate(header) if l.startswith("Variables"))
    names = [header[i0 + 1 + k].split("\t")[2] for k in range(nvar)]
    offset = split + len(b"Binary:") + 1  # +1 skips the newline after "Binary:"
    arr = np.memmap(path, dtype="<f8", mode="r", offset=offset, shape=(npts, nvar))
    return {n.lower(): arr[:, k] for k, n in enumerate(names)}


def apply_scenario(cfg: dict, name: str, extra: list[str]) -> dict:
    out = bm.apply_overrides(cfg, [])
    for key, value in cfg["scenarios"][name]["overrides"].items():
        node = out
        parts = key.split(".")
        for p in parts[:-1]:
            node = node[p]
        node[parts[-1]] = value
    return bm.apply_overrides(out, extra)


def simulate(cfg: dict, outdir: Path, tag: str, with_force: bool) -> tuple[dict[str, np.ndarray], list[dict]]:
    outdir.mkdir(parents=True, exist_ok=True)
    text, slots = bm.build(cfg, with_force=with_force)
    net = outdir / f"{tag}.cir"
    net.write_text(text, encoding="utf-8")
    return read_qraw(run_qspice(net)), slots


def write_csv(rows: list[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows({k: (f"{v:.6g}" if isinstance(v, float) else v) for k, v in r.items()} for r in rows)


# ----------------------------------------------------------------------------- scenario: two_pulses
def analyse_pulses(cfg: dict, sig: dict, base: dict, slots: list[dict]) -> list[dict]:
    t_stop = sig["time"][-1]
    rows = []
    for n, s in enumerate(x for x in slots if x["kind"] != "tail"):
        ts = s["t_sample"]
        v = float(np.interp(ts, sig["time"], sig["v(ain)"]))
        v0 = float(np.interp(ts, base["time"], base["v(ain)"]))
        row = {"slot": n, "cycle": s["cycle"], "address": s["address"], "kind": s["kind"],
               "t_sample_us": ts * 1e6, "v_ain": v, "v_ain_baseline": v0, "delta_mV": (v - v0) * 1e3,
               "force_N": 0.0, "open_circuit_mV": 0.0}
        if s["kind"] == "sensor":
            pts = bm.force_pwl(cfg, s["address"], t_stop)
            f = float(np.interp(ts, [p[0] for p in pts], [p[1] for p in pts]))
            sp = bm.sensor_params(cfg, s["address"])
            row["force_N"] = f
            row["open_circuit_mV"] = sp["d33"] * f / sp["cp"] * 1e3
        rows.append(row)
    return rows


def summarise(cfg: dict, rows: list[dict]) -> dict:
    """Signal = slots of sensors that have a force pulse; ghost = every other sensor slot + VMID slots."""
    driven = {int(f["address"]) for f in cfg["forces"] + cfg.get("forces_sin", [])}
    sig_rows = [r for r in rows if r["kind"] == "sensor" and r["address"] in driven]
    ghost = [r for r in rows if r["kind"] == "vmid" or r["address"] not in driven]
    return {
        "max_abs_ghost_mV": max((abs(r["delta_mV"]) for r in ghost), default=0.0),
        "max_abs_vmid_slot_mV": max((abs(r["delta_mV"]) for r in rows if r["kind"] == "vmid"), default=0.0),
        "max_abs_signal_mV": max((abs(r["delta_mV"]) for r in sig_rows), default=0.0),
        "n_signal_slots": len(sig_rows),
    }


def plots_pulses(cfg: dict, sig: dict, base: dict, slots: list[dict], rows: list[dict], outdir: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t = sig["time"] * 1e6
    fig, ax = plt.subplots(4, 1, figsize=(12, 10), sharex=True)
    for k in range(7):
        if np.max(np.abs(sig[f"v(f{k})"])) > 0:
            ax[0].plot(t, sig[f"v(f{k})"], label=f"sensor {k}")
    ax[0].set_ylabel("Applied force [N]"); ax[0].legend(loc="upper right")
    for k in range(8):
        ax[1].plot(t, sig[f"v(s{k})"], lw=0.8, label=f"S{k}" + (" (VMID)" if k == 7 else ""))
    ax[1].set_ylabel("MUX source pins [V]"); ax[1].legend(ncol=8, fontsize=7, loc="upper right")
    ax[2].plot(t, sig["v(muxd)"], lw=0.8, label="MUX D / buffer input")
    ax[2].plot(t, sig["v(ain)"], lw=0.8, label="AIN_B4")
    ax[2].plot([r["t_sample_us"] for r in rows], [r["v_ain"] for r in rows], "k.", ms=4, label="samples")
    ax[2].set_ylabel("[V]"); ax[2].legend(loc="upper right")
    ax[3].plot([r["t_sample_us"] for r in rows], [r["delta_mV"] for r in rows], "o-", ms=3, lw=0.6)
    ax[3].set_ylabel("sample - baseline [mV]"); ax[3].set_xlabel("time [us]")
    ax[3].axhline(0, color="gray", lw=0.5)
    fig.suptitle("TestBoard_ADC124 PZT front end - two soft force pulses")
    fig.tight_layout(); fig.savefig(outdir / "overview.png", dpi=130); plt.close(fig)

    tgt = next((s for s in slots if s["kind"] == "sensor" and any(
        int(f["address"]) == s["address"] and (f["t_start_us"] + f["rise_us"]) * 1e-6 < s["t0"] < (f["t_start_us"] + f["rise_us"] + f["width_us"]) * 1e-6
        for f in cfg["forces"])), None)
    if tgt:
        t0, t1 = tgt["t0"] - 1e-6, tgt["t0"] + 20e-6
        m = (sig["time"] >= t0) & (sig["time"] <= t1)
        mb = (base["time"] >= t0) & (base["time"] <= t1)
        fig, ax = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
        tt = sig["time"][m] * 1e6
        for k in (tgt["address"], bm.VMID_ADDR):
            ax[0].plot(tt, sig[f"v(c{k})"][m], label=f"enable S{k}")
        ax[0].legend(); ax[0].set_ylabel("MUX enable")
        ax[1].plot(tt, sig[f"v(s{tgt['address']})"][m], label=f"S{tgt['address']} pin")
        ax[1].plot(tt, sig["v(muxd)"][m], label="MUX D")
        ax[1].legend(); ax[1].set_ylabel("[V]")
        ax[2].plot(tt, sig["v(ain)"][m], label="AIN stimulated")
        ax[2].plot(base["time"][mb] * 1e6, base["v(ain)"][mb], "--", label="AIN baseline")
        ax[2].axvline(tgt["t_sample"] * 1e6, color="k", lw=0.5)
        ax[2].legend(); ax[2].set_ylabel("[V]"); ax[2].set_xlabel("time [us]")
        fig.suptitle(f"Zoom: switch to sensor {tgt['address']} (cycle {tgt['cycle']}); vertical line = ADC hold")
        fig.tight_layout(); fig.savefig(outdir / "switch_zoom.png", dpi=130); plt.close(fig)


def run_pulses(cfg: dict, make_plots: bool = True, write_outputs: bool = True, outdir: Path | None = None):
    outdir = outdir or RESULTS / "two_pulses"
    sig, slots = simulate(cfg, outdir, "run", True)
    base, _ = simulate(cfg, outdir, "run_baseline", False)
    rows = analyse_pulses(cfg, sig, base, slots)
    if write_outputs:
        write_csv(rows, outdir / "samples.csv")
        (HERE / "TestBoard_ADC124_PZT.cir").write_text((outdir / "run.cir").read_text(encoding="utf-8"), encoding="utf-8")
    if make_plots:
        plots_pulses(cfg, sig, base, slots, rows, outdir)
    return rows, summarise(cfg, rows)


# ----------------------------------------------------------------------------- scenario: baseline_3s
def run_baseline(cfg: dict, make_plots: bool = True, name: str = "baseline") -> dict:
    outdir = RESULTS / name
    t_run = time.time()
    sig, slots = simulate(cfg, outdir, "run", False)
    sim_s = time.time() - t_run
    tm, ain = np.asarray(sig["time"]), np.asarray(sig["v(ain)"])
    scan = list(cfg["timing"]["scan_order"])
    sens = [s for s in slots if s["kind"] == "sensor"]
    vm = [s for s in slots if s["kind"] == "vmid"]
    n_cyc = len(sens) // len(scan)
    t_s = np.array([s["t_sample"] for s in sens]).reshape(n_cyc, len(scan))
    v_s = np.interp(t_s, tm, ain)                                   # (cycle, sensor position)
    t_v = np.array([s["t_sample"] for s in vm]).reshape(n_cyc, -1) if vm else None
    v_v = np.interp(t_v, tm, ain) if vm else None
    vmid = cfg["circuit"]["vmid_v"]
    t_cyc = t_s[:, 0]

    # decimated CSV: log-spaced cycles plus the last 5
    idx = np.unique(np.concatenate([np.unique(np.geomspace(1, n_cyc, 400).astype(int) - 1), np.arange(max(0, n_cyc - 5), n_cyc)]))
    with (outdir / "samples_decimated.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["cycle", "t_s"] + [f"ain_addr{a}_V" for a in scan])
        for i in idx:
            w.writerow([int(i), f"{t_cyc[i]:.6f}"] + [f"{v:.6f}" for v in v_s[i]])

    t_last = float(t_cyc[-1])
    marks = [("first cycle", 0.0)] + [(f"{x*1e3:g} ms", x) for x in (1e-3, 5e-3, 10e-3, 30e-3) if x < t_last * 0.95] + [("last cycle", t_last)]
    print(f"\nbaseline run: {n_cyc} cycles, {len(slots)} slots, simulated in {sim_s:.0f} s, {len(tm):,} time points")
    print("AIN_B4 sample per sensor address [V]  (deviation from VMID in mV in brackets)")
    print(f"{'time':>20s} " + " ".join(f"{'addr ' + str(a):>16s}" for a in scan))
    summary_rows = []
    for label, tt in marks:
        i = int(np.argmin(np.abs(t_cyc - tt)))
        print(f"{label + f' ({t_cyc[i]*1e3:.4g}ms)':>20s} " + " ".join(f"{v_s[i, k]:8.5f} ({(v_s[i, k]-vmid)*1e3:+6.2f})" for k in range(len(scan))))
        summary_rows.append({"label": label, "t_s": float(t_cyc[i]), **{f"addr{a}_V": float(v_s[i, k]) for k, a in enumerate(scan)}})
    tail = slice(max(0, n_cyc - 100), n_cyc)
    final = v_s[tail].mean(axis=0)
    spread = v_s[tail].std(axis=0)
    settle = []
    for k in range(len(scan)):
        off = np.nonzero(np.abs(v_s[:, k] - final[k]) > 0.3e-3)[0]
        settle.append(float(t_cyc[off[-1] + 1]) if len(off) and off[-1] + 1 < n_cyc else 0.0)
    print("steady state (mean of last 100 cycles) [mV vs VMID]: " + " ".join(f"{(f - vmid) * 1e3:+.2f}" for f in final))
    print("cycle-to-cycle spread (std) [mV]:                    " + " ".join(f"{x * 1e3:.2f}" for x in spread))
    print("last time more than 0.3 mV from steady state [ms]:    " + " ".join(f"{x * 1e3:.1f}" for x in settle))
    if v_v is not None:
        print("VMID-slot sample vs VMID, last cycle: " + " ".join(f"{(v - vmid) * 1e3:+.3f} mV" for v in v_v[-1]))
    write_csv(summary_rows, outdir / "summary.csv")

    if make_plots:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        step = max(1, n_cyc // 4000)
        fig, ax = plt.subplots(2, 1, figsize=(12, 8))
        for k, a in enumerate(scan):
            ax[0].plot(t_cyc[::step], (v_s[::step, k] - vmid) * 1e3, lw=1.0, label=f"addr {a}")
        ax[0].set_xscale("log"); ax[0].set_xlabel("time [s]"); ax[0].set_ylabel("AIN_B4 sample - VMID [mV]")
        ax[0].set_title("Baseline (no force) of every sensor channel, one sample per scan cycle"); ax[0].legend(ncol=7, fontsize=8)
        ax[0].grid(True, which="both", alpha=0.3)
        m = tm >= t_s[-1, 0] - 20e-6
        t0 = tm[m][0]
        ax[1].plot((tm[m] - t0) * 1e6, ain[m], lw=0.8, label="AIN_B4")
        ax[1].plot((t_s[-1] - t0) * 1e6, v_s[-1], "k.", label="ADC samples")
        ax[1].set_xlabel("time within last cycle [us]"); ax[1].set_ylabel("[V]"); ax[1].legend()
        ax[1].set_title(f"Last scan cycle (t = {t_cyc[-1]:.3f} s)")
        fig.tight_layout(); fig.savefig(outdir / f"{name}.png", dpi=130); plt.close(fig)
    return {"cycles": n_cyc, "final_V": {a: float(v_s[-1, k]) for k, a in enumerate(scan)}}


def _read_decimated(name: str):
    with (RESULTS / name / "samples_decimated.csv").open(encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    return np.array([[float(x) for x in r] for r in rows[1:]]), rows[0]


def compare_baselines(a: str, b: str) -> None:
    """Print and plot two finished baseline scenarios (results/<name>/samples_decimated.csv)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    vmid = bm.load_config()["circuit"]["vmid_v"]
    da, _ = _read_decimated(a)
    db, _ = _read_decimated(b)
    fig, ax = plt.subplots(1, 1, figsize=(11, 6))
    for name, d, style in ((a, da, "-"), (b, db, "--")):
        for k in range(2, d.shape[1]):
            ax.plot(d[:, 1] * 1e3, (d[:, k] - vmid) * 1e3, style, marker="o" if len(d) < 60 else None, ms=3, lw=1,
                    label=name if k == 2 else None, color="C0" if name == a else "C3", alpha=0.8)
    ax.set_xscale("log"); ax.set_xlabel("time [ms]"); ax.set_ylabel("AIN_B4 sample - VMID [mV]")
    ax.set_title(f"Baseline comparison: {a} (solid) vs {b} (dashed), all sensor addresses"); ax.grid(True, which="both", alpha=0.3); ax.legend()
    fig.tight_layout(); fig.savefig(RESULTS / f"compare_{a}_vs_{b}.png", dpi=130); plt.close(fig)
    for name, d in ((a, da), (b, db)):
        last = d[-1:, 2:]
        print(f"{name:18s} last-cycle mean {((last.mean() - vmid) * 1e3):+8.2f} mV   spread across sensors {((last.max(axis=1) - last.min(axis=1)).max() * 1e3):.3f} mV")


def plot_offset_fanout(a: str = "baseline", b: str = "baseline_vmid1ms") -> Path:
    """Offset and fan-out figure from the saved samples_decimated.csv of two baseline scenarios."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    vmid = bm.load_config()["circuit"]["vmid_v"]
    data = {n: _read_decimated(n)[0] for n in (a, b)}
    label = {a: "VMID settle 5 us (cycle 133 us)", b: "VMID settle 1 ms (cycle 7.1 ms)"}
    color = {a: "C0", b: "C3"}
    fig, ax = plt.subplots(2, 2, figsize=(13, 9))
    for n, d in data.items():
        t_ms = d[:, 1] * 1e3
        off = (d[:, 2:] - vmid) * 1e3
        ax[0, 0].plot(t_ms, off.mean(axis=1), "-o" if len(d) < 60 else "-", ms=4, color=color[n], label=label[n])
        ax[0, 1].plot(t_ms, off.max(axis=1) - off.min(axis=1), "-o" if len(d) < 60 else "-", ms=4, color=color[n], label=label[n])
    ax[0, 0].set_xscale("log"); ax[0, 0].set_xlabel("time [ms]"); ax[0, 0].set_ylabel("mean baseline offset vs VMID [mV]")
    ax[0, 0].set_title("Baseline offset (mean over the 7 sensor addresses)"); ax[0, 0].grid(True, which="both", alpha=0.3); ax[0, 0].legend()
    ax[0, 1].set_xscale("log"); ax[0, 1].set_yscale("log"); ax[0, 1].set_xlabel("time [ms]"); ax[0, 1].set_ylabel("max - min across addresses [mV]")
    ax[0, 1].set_title("Fan-out between sensor addresses"); ax[0, 1].grid(True, which="both", alpha=0.3); ax[0, 1].legend()
    d = data[b]
    pick = sorted({0, 1, 2, 4, len(d) - 1})
    cmap = plt.get_cmap("viridis")
    for j, i in enumerate(pick):
        ax[1, 0].plot(range(7), (d[i, 2:] - vmid) * 1e3, "-o", color=cmap(j / max(1, len(pick) - 1)),
                      label=f"cycle {int(d[i, 0])} (t = {d[i, 1]*1e3:.1f} ms)")
    ax[1, 0].set_xlabel("sensor address (read order within the scan)"); ax[1, 0].set_ylabel("baseline offset [mV]")
    ax[1, 0].set_title(f"Fan-out across addresses, {label[b]}"); ax[1, 0].grid(True, alpha=0.3); ax[1, 0].legend(fontsize=8)
    d = data[a]
    ax[1, 1].plot(range(7), (d[-1, 2:] - vmid) * 1e3, "-o", color=color[a], label=f"last cycle (t = {d[-1, 1]*1e3:.1f} ms)")
    ax[1, 1].plot(range(7), (d[0, 2:] - vmid) * 1e3, "--o", color="gray", label=f"first cycle (t = {d[0, 1]*1e3:.3f} ms)")
    ax[1, 1].set_xlabel("sensor address (read order within the scan)"); ax[1, 1].set_ylabel("baseline offset [mV]")
    ax[1, 1].set_title(f"Fan-out across addresses, {label[a]}"); ax[1, 1].grid(True, alpha=0.3); ax[1, 1].legend(fontsize=8)
    fig.suptitle("TestBoard_ADC124 baseline offset and address fan-out (no force, 1 nA same-sign mux leakage)")
    fig.tight_layout()
    out = RESULTS / "baseline_offset_fanout.png"
    fig.savefig(out, dpi=130); plt.close(fig)
    return out


# ----------------------------------------------------------------------------- CLI
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(HERE / "config.json"))
    ap.add_argument("--scenario", choices=["two_pulses", "baseline", "baseline_vmid1ms", "all"], default="all")
    ap.add_argument("--compare", metavar="A,B", help="plot/print two finished baseline scenarios against each other")
    ap.add_argument("--set", action="append", default=[], metavar="SECTION.KEY=VALUE")
    ap.add_argument("--sweep", metavar="SECTION.KEY=V1,V2,...", help="two_pulses only: run once per value and tabulate ghosting")
    ap.add_argument("--no-plots", action="store_true")
    args = ap.parse_args()
    base_cfg = bm.load_config(Path(args.config))

    if args.sweep:
        cfg = apply_scenario(base_cfg, "two_pulses", args.set)
        key, _, vals = args.sweep.partition("=")
        print(f"{key:32s} {'signal mV':>10s} {'ghost mV':>10s} {'vmid-slot mV':>13s}")
        for v in vals.split(","):
            s = run_pulses(bm.apply_overrides(cfg, [f"{key}={v}"]), make_plots=False, write_outputs=False,
                           outdir=RESULTS / "_sweep")[1]
            print(f"{v:32s} {s['max_abs_signal_mV']:10.2f} {s['max_abs_ghost_mV']:10.2f} {s['max_abs_vmid_slot_mV']:13.2f}")
        return 0

    if args.compare:
        compare_baselines(*args.compare.split(","))
        print("figure:", plot_offset_fanout(*args.compare.split(",")))
        return 0

    if args.scenario in ("two_pulses", "all"):
        cfg = apply_scenario(base_cfg, "two_pulses", args.set)
        rows, s = run_pulses(cfg, make_plots=not args.no_plots)
        driven = {int(f["address"]) for f in cfg["forces"]}
        print("== two_pulses ==  (sensors with a force pulse)")
        print(f"{'slot':>4} {'cyc':>3} {'addr':>4} {'t_smp[us]':>10} {'AIN[V]':>8} {'delta[mV]':>10} {'F[N]':>6} {'Voc[mV]':>9}")
        for r in rows:
            if r["kind"] == "sensor" and r["address"] in driven:
                print(f"{r['slot']:4d} {r['cycle']:3d} {r['address']:4d} {r['t_sample_us']:10.2f} "
                      f"{r['v_ain']:8.4f} {r['delta_mV']:10.3f} {r['force_N']:6.3f} {r['open_circuit_mV']:9.1f}")
        print("summary:", {k: round(v, 3) if isinstance(v, float) else v for k, v in s.items()})
    for name in ("baseline", "baseline_vmid1ms"):
        if args.scenario == name or (args.scenario == "all" and name == "baseline"):
            print(f"== {name} ==")
            run_baseline(apply_scenario(base_cfg, name, args.set), make_plots=not args.no_plots, name=name)
    print(f"\noutputs: {RESULTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
