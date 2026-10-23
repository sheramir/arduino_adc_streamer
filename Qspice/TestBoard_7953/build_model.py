"""Generate the QSPICE netlist for one ADS7953 of TestBoard_7953: PZT sensors -> ADS7953 mux (MXO) -> OPA365 buffer -> AINP -> S/H.

Usage:
    python build_model.py [--config config.json] [--out TestBoard_7953_PZT.cir] [--set section.key=value ...]

`build(cfg)` returns (netlist_text, schedule); `build_schedule(cfg)` describes the SPI frames, the mux channel that is
selected in each frame, and the ADC hold instants (see config.json "timing" _note and README.md).
"""
from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
EPS0 = 8.8541878128e-12
PICO, NANO, MICRO, MILLI = 1e-12, 1e-9, 1e-6, 1e-3
VMID_CH = 15
N_SENSORS = 15


def load_config(path: Path = HERE / "config.json") -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def apply_overrides(cfg: dict, overrides: list[str]) -> dict:
    cfg = copy.deepcopy(cfg)
    for item in overrides:
        key, _, raw = item.partition("=")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        node = cfg
        parts = key.split(".")
        for p in parts[:-1]:
            node = node[p]
        node[parts[-1]] = value
    return cfg


def sensor_params(cfg: dict, addr: int) -> dict:
    p = dict(cfg["sensor_defaults"])
    p.update({k: v for k, v in cfg.get("sensor_overrides", {}).get(str(addr), {}).items() if not k.startswith("_")})
    area = (p["width_mm"] * MILLI) * (p["length_mm"] * MILLI)
    cp = EPS0 * p["eps33_r"] * area / (p["thickness_mm"] * MILLI)
    rp = None
    if p.get("loss_model", "none") == "parallel_r" and p["tan_delta"] > 0:
        rp = 1.0 / (6.283185307 * p["tan_delta_ref_hz"] * cp * p["tan_delta"])
    return {"cp": cp, "d33": p["d33_pC_per_N"] * PICO * p["force_gain"], "rp": rp, "rins": p["r_insulation_ohm"]}


def leakage_levels(cfg: dict) -> tuple[float, float, float]:
    """Pin leakage (amps) at 0 V, 1.25 V and 2.5 V for the chosen temperature, from datasheet Figure 43.

    Log-linear interpolation in temperature; above the last tabulated temperature the final slope is extrapolated.
    """
    import math

    a = cfg["adc"]
    curve = a["leak_curve_nA"]
    temps = curve["temps_c"]
    t = float(a["temperature_c"])
    if t < temps[0]:
        raise ValueError(f"adc.temperature_c must be at least {temps[0]} C (datasheet range)")
    out = []
    for key in ("v_0", "v_1_25", "v_2_5"):
        ys = [math.log(v) for v in curve[key]]
        i = max(1, min(len(temps) - 1, next((k for k, x in enumerate(temps) if x >= t), len(temps) - 1)))
        slope = (ys[i] - ys[i - 1]) / (temps[i] - temps[i - 1])
        out.append(math.exp(ys[i - 1] + slope * (t - temps[i - 1])) * NANO * a["leak_scale"])
    return out[0], out[1], out[2]


# ----------------------------------------------------------------------------- SPI frame timing and schedule
def frame_timing(cfg: dict) -> dict:
    """Frame period and the edge offsets inside a frame (seconds), from the SPI clock and the frame gap."""
    t = cfg["timing"]
    f = float(t["spi_clk_hz"])
    if f <= 0:
        raise ValueError("timing.spi_clk_hz must be positive")
    clk = 1.0 / f
    word = t["adc_word_clocks"] * clk
    period = word + t["frame_gap_ns"] * NANO
    first = t["first_clock_delay_ns"] * NANO
    delta = first + 1.5 * clk        # CS fall -> 2nd SCLK falling edge: the mux changes
    a_off = first + 13.0 * clk       # CS fall -> 14th SCLK rising edge: tracking can open
    if a_off >= period:
        raise ValueError(f"frame period {period * 1e6:.3f} us is shorter than the {a_off * 1e9:.0f} ns the ADC needs before it "
                         "can track again: increase timing.frame_gap_ns or the SPI clock")
    return {"clk": clk, "word": word, "period": period, "delta": delta, "a_off": a_off, "track": period - a_off}


def stream_channels(cfg: dict) -> list[int]:
    """Channel applied at the mux in each frame of this ADC's stream (frame 0 = still the previous drain command)."""
    t = cfg["timing"]
    scan, rep = [int(a) for a in t["scan_order"]], int(t["repeat"])
    if not scan or len(set(scan)) != len(scan) or any(not 0 <= a < N_SENSORS for a in scan):
        raise ValueError(f"timing.scan_order must list distinct sensor addresses 0..{N_SENSORS - 1}")
    if rep < 1:
        raise ValueError("timing.repeat must be at least 1")
    seq = [VMID_CH]
    for i, a in enumerate(scan):
        seq += [a] * rep
        if t["vmid_between_channels"] and i < len(scan) - 1:
            seq += [VMID_CH] * int(t["vmid_frames_between"])
    seq += [VMID_CH]          # one trailing VMID frame in both modes: the next command of the second drain falls into the park
    return seq


def other_adc_frames(cfg: dict) -> int:
    """Frames the other ADCs of the sequence clock while this mux is parked: each streams its channels x repeat + 2 pipeline frames."""
    t = cfg["timing"]
    n_other = int(t["n_adc"]) - 1
    if n_other < 0:
        raise ValueError("timing.n_adc must be at least 1")
    return n_other * (int(t["other_adc_channels"]) * int(t["repeat"]) + 2) if n_other else 0


def build_schedule(cfg: dict) -> dict:
    t = cfg["timing"]
    ft = frame_timing(cfg)
    seq = stream_channels(cfg)
    n_park = other_adc_frames(cfg)
    frames_per_cycle = n_park + len(seq)
    cycle = frames_per_cycle * ft["period"] + t["sweep_gap_us"] * MICRO
    n_cycles = int(t["num_cycles"])
    if t.get("run_duration_s"):
        n_cycles = max(1, int((t["run_duration_s"] - t["t_start_us"] * MICRO) / cycle))
    start = t["t_start_us"] * MICRO
    frames: list[dict] = []
    samples: list[dict] = []
    for k in range(n_cycles):
        base = start + k * cycle
        for j in range(frames_per_cycle):
            in_stream = j >= n_park
            ch = seq[j - n_park] if in_stream else VMID_CH
            frames.append({"cycle": k, "j": j, "cs": base + j * ft["period"], "ch": ch, "stream": in_stream})
        # retained hold of each sensor: CS fall of the frame after its last applied frame
        s = 0
        while s < len(seq):
            ch = seq[s]
            e = s
            while e + 1 < len(seq) and seq[e + 1] == ch:
                e += 1
            if ch != VMID_CH:
                samples.append({"t": base + (n_park + e + 1) * ft["period"], "address": ch, "cycle": k,
                                "t_connect": base + (n_park + s) * ft["period"] + ft["delta"]})
            s = e + 1
    t_stop = start + n_cycles * cycle + t["tail_us"] * MICRO
    return {"timing": ft, "frames": frames, "samples": samples, "cycle": cycle, "n_cycles": n_cycles, "t_stop": t_stop,
            "frames_per_cycle": frames_per_cycle, "stream_frames": len(seq), "start": start}


# ----------------------------------------------------------------------------- waveforms
SINE_POINTS_PER_CYCLE = 64        # piecewise-linear sine: 64 points per cycle keep the amplitude error below 0.2 %
MAX_SINE_POINTS = 1_000_000


def check_sines(cfg: dict) -> None:
    for s in cfg.get("forces_sin", []):
        if float(s["freq_hz"]) <= 0 or float(s["cycles"]) <= 0:
            raise ValueError(f"sine force on address {s['address']}: frequency and number of cycles must be positive")


def sine_value(s: dict, t: float) -> float:
    """Force [N] of one sine row at time t: amp * sin(2 pi f (t - t_start)) for `cycles` periods, zero before and after."""
    t0, f = s["t_start_us"] * MICRO, float(s["freq_hz"])
    if t <= t0 or t >= t0 + float(s["cycles"]) / f:
        return 0.0
    return s["amp_N"] * math.sin(2 * math.pi * f * (t - t0))


def sine_times(s: dict, t_stop: float) -> list[float]:
    t0, f = s["t_start_us"] * MICRO, float(s["freq_hz"])
    t_end = min(t0 + float(s["cycles"]) / f, t_stop)
    if t_end <= t0:
        return []
    n = int(math.ceil((t_end - t0) * f * SINE_POINTS_PER_CYCLE))
    if n > MAX_SINE_POINTS:
        raise ValueError(f"sine force on address {s['address']}: {n} points needed (frequency too high for this run length)")
    return [t0 + k / (f * SINE_POINTS_PER_CYCLE) for k in range(n)] + [t_end]

def force_pwl(cfg: dict, addr: int, t_stop: float) -> list[tuple[float, float]]:
    pulses = [f for f in cfg["forces"] if int(f["address"]) == addr]
    sines = [f for f in cfg.get("forces_sin", []) if int(f["address"]) == addr]
    check_sines(cfg)

    def trap(f, t):
        t0 = f["t_start_us"] * MICRO
        r, w, fl = f["rise_us"] * MICRO, f["width_us"] * MICRO, f["fall_us"] * MICRO
        a = f["amp_N"]
        if t <= t0:
            return 0.0
        if t < t0 + r:
            return a * (t - t0) / r
        if t <= t0 + r + w:
            return a
        if t < t0 + r + w + fl:
            return a * (1 - (t - t0 - r - w) / fl)
        return 0.0

    times = {0.0, t_stop}
    for f in pulses:
        t0 = f["t_start_us"] * MICRO
        r, w, fl = f["rise_us"] * MICRO, f["width_us"] * MICRO, f["fall_us"] * MICRO
        times.update(x for x in (t0, t0 + r, t0 + r + w, t0 + r + w + fl) if x <= t_stop)
    for sn in sines:
        times.update(x for x in sine_times(sn, t_stop) if x <= t_stop)
    return [(x, sum(trap(f, x) for f in pulses) + sum(sine_value(sn, x) for sn in sines)) for x in sorted(times)]


def fmt_pwl(name: str, node: str, pts: list[tuple[float, float]]) -> str:
    words = " ".join(f"{t:.9e} {v:.9e}" for t, v in pts).split(" ")
    lines = [" ".join(words[i:i + 8]) for i in range(0, len(words), 8)]
    return f"{name} {node} 0 PWL(" + "\n+ ".join(lines) + ")"


def control_pwl(cfg: dict, sched: dict) -> dict[int, list[tuple[float, float]]]:
    """Analog enable (0..1) of every mux channel from the per-frame applied channel."""
    a = cfg["adc"]
    ton, toff, edge = a["mux_on_delay_ns"] * NANO, a["mux_off_delay_ns"] * NANO, a["mux_edge_ns"] * NANO
    if ton < toff + edge:
        raise ValueError("adc.mux_on_delay_ns must be >= mux_off_delay_ns + mux_edge_ns (break-before-make)")
    delta = sched["timing"]["delta"]
    merged: list[list] = []
    for fr in sched["frames"]:
        t_apply = fr["cs"] + delta
        if merged and merged[-1][0] == fr["ch"]:
            continue
        merged.append([fr["ch"], t_apply])
    pts = {c: [(0.0, 0.0)] for c in range(16)}
    pts[VMID_CH] = [(0.0, 1.0)]  # parked on VMID before the first frame
    for i, (ch, t0) in enumerate(merged):
        t1 = merged[i + 1][1] if i + 1 < len(merged) else None
        if not (i == 0 and ch == VMID_CH):
            pts[ch] += [(t0 + ton, 0.0), (t0 + ton + edge, 1.0)]
        if t1 is not None:
            pts[ch] += [(t1 + toff, 1.0), (t1 + toff + edge, 0.0)]
        if t1 is not None and t1 - t0 <= ton + edge:
            raise ValueError("a channel is selected for less than the mux switching time: lower the frame gap / SPI clock settings")
    return pts


def hold_pwl(cfg: dict, sched: dict) -> list[tuple[float, float]]:
    """S/H control: 1 = tracking, 0 = hold during the first 14th-clock-edge window of every frame of this ADC's stream."""
    e = cfg["adc"]["sh_edge_ns"] * NANO
    a_off = sched["timing"]["a_off"]
    pts = [(0.0, 1.0)]
    for fr in sched["frames"]:
        if fr["stream"]:
            c = fr["cs"]
            pts += [(c, 1.0), (c + e, 0.0), (c + a_off, 0.0), (c + a_off + e, 1.0)]
    return pts


# ----------------------------------------------------------------------------- netlist
def build(cfg: dict) -> tuple[str, dict]:
    c, par, a, op, sim = cfg["circuit"], cfg["parasitics"], cfg["adc"], cfg["opamp"], cfg["simulation"]
    sched = build_schedule(cfg)
    t_stop = sched["t_stop"]
    ctl = control_pwl(cfg, sched)
    leak = leakage_levels(cfg)
    L: list[str] = []
    add = L.append
    add("* TestBoard_7953 - 15 PZT sensors -> ADS7953 mux (MXO) -> OPA365 buffer -> AINP -> S/H (one ADC; the other ADC pair parks this mux on VMID)")
    add("* GENERATED by build_model.py from config.json - edit the config, not this file.")
    add("* Sensor k is on ADS7953 channel Chk; channel 15 is the VMID channel.")
    add("")
    add("* ---- global parameters ----")
    params = {
        "ads_ron": a["ron_ohm"], "ads_roff": a["roff_ohm"], "ads_cs_off": a["cs_off_pF"] * PICO,
        "ads_c_ft": a["c_feedthrough_pF"] * PICO, "ads_qinj": a["qinj_pC"] * PICO, "ads_qinj_src_frac": a["qinj_src_fraction"],
        "ads_il0": leak[0], "ads_il1": leak[1], "ads_il2": leak[2],
        "op_gbw": op["gbw_hz"], "op_aol": op["aol"], "op_sr": op["slew_v_per_us"] * 1e6, "op_vos": op["vos_uV"] * MICRO,
        "op_ib": op["ib_pA"] * PICO, "op_cdiff": op["cdiff_pF"] * PICO, "op_ccm": op["ccm_pF"] * PICO,
        "op_ro": op["ro_ohm"], "op_vmargin": op["rail_margin_mV"] * MILLI,
    }
    for k, v in params.items():
        add(f".param {k}={v:.9e}")
    add("")
    add("* ---- behavioral cells ----")
    for lib in ("ADS7953_mux_channel.lib", "OPA365_behavioral.lib"):
        add(f"* --- begin models/{lib} ---")
        add((HERE / "models" / lib).read_text(encoding="utf-8").rstrip())
        add(f"* --- end models/{lib} ---")
    add("")
    add(f"Vdd vdd 0 {c['vdd_v']}")
    add(f"Vvmid vmid 0 {c['vmid_v']}")
    add("")
    add("* ---- PZT sensors: force [N] as volts -> charge source d33*dF/dt || Cp || insulation ----")
    for k in range(N_SENSORS):
        sp = sensor_params(cfg, k)
        add(f"* sensor {k} -> Ch{k}: Cp={sp['cp'] / PICO:.1f} pF, d33={sp['d33'] / PICO:.1f} pC/N")
        add(fmt_pwl(f"Vf{k}", f"f{k}", force_pwl(cfg, k, t_stop)))
        add(f"Bq{k} 0 p{k} I={sp['d33']:.9e}*ddt(V(f{k}))")
        add(f"Cp{k} p{k} 0 {sp['cp']:.9e}")
        if sp["rp"]:
            add(f"Rp{k} p{k} 0 {sp['rp']:.9e}")
        add(f"Ri{k} p{k} 0 {sp['rins']:.9e}")
        add(f"Rt{k} p{k} s{k} {par['sensor_trace_r_ohm']}")
        add(f"Cpar{k} s{k} 0 {par['sensor_trace_c_pF'] * PICO:.9e}")
        if k < N_SENSORS - 1 and par["c_coupling_adjacent_pF"] > 0:
            add(f"Ccpl{k} s{k} s{k + 1} {par['c_coupling_adjacent_pF'] * PICO:.9e}")
    add("")
    add("* ---- VMID channel (Ch15) ----")
    add(f"R5 vmid s{VMID_CH} {c['r_vmid_series_ohm']}")
    add(f"C5 s{VMID_CH} 0 {c['c_vmid_ch15_pF'] * PICO:.9e}")
    add("")
    add("* ---- mux channel enables (from the SPI frame schedule) ----")
    for ch in range(16):
        add(fmt_pwl(f"Vc{ch}", f"c{ch}", ctl[ch]))
    add("")
    add("* ---- ADS7953 mux: 16 channels -> MXO ----")
    for ch in range(16):
        add(f"Xch{ch} s{ch} mxo c{ch} ADS_CH")
    add(f"Cmxo mxo 0 {c['c_mxo_pF'] * PICO:.9e}")
    add("")
    add("* ---- OPA365 unity buffer, bias resistor to VMID, buffer output -> AINP, ADC sample-and-hold ----")
    add(f"Rbias mxo vmid {c['r_bias_ohm']}")
    add("XU mxo bufo bufo vdd 0 OPA365_BEH")
    add(f"Rout bufo ain {c['r_out_ohm']}")
    add(f"Cain ain 0 {c['c_ain_pF'] * PICO:.9e}")
    add(f"Bsh ain sh I=V(ain,sh)*limit(V(shc),0,1)/{a['r_track_ohm']}")
    add(f"Csh sh 0 {a['c_sample_pF'] * PICO:.9e}")
    add(f"Blkain ain 0 I={leak[0]:.9e} + ({leak[1]:.9e}-{leak[0]:.9e})*limit(V(ain),0,1.25)/1.25 + ({leak[2]:.9e}-{leak[1]:.9e})*limit(V(ain)-1.25,0,1.25)/1.25")
    add(fmt_pwl("Vshc", "shc", hold_pwl(cfg, sched)))
    add("")
    ic = c["initial_sensor_node_v"]
    add(" ".join([".ic"] + [f"V(s{k})={ic} V(p{k})={ic}" for k in range(N_SENSORS)] + [f"V(sh)={c['vmid_v']}"]))
    add(f".tran 0 {t_stop:.9e} 0 {sim['max_step_ns'] * NANO:.9e}")
    names = ["ain", "mxo", "bufo", "sh", "shc", "vmid"] + [f"s{k}" for k in range(16)] + [f"f{k}" for k in range(N_SENSORS)] \
        + [f"c{k}" for k in range(16)]
    add(".save " + " ".join(f"V({n})" for n in names))
    add(".end")
    return "\n".join(L) + "\n", sched


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(HERE / "config.json"))
    ap.add_argument("--out", default=str(HERE / "TestBoard_7953_PZT.cir"))
    ap.add_argument("--set", action="append", default=[], metavar="SECTION.KEY=VALUE")
    args = ap.parse_args()
    text, sched = build(apply_overrides(load_config(Path(args.config)), args.set))
    Path(args.out).write_text(text, encoding="utf-8")
    print(f"wrote {args.out} ({sched['n_cycles']} sweeps, {len(sched['samples'])} samples)")


if __name__ == "__main__":
    main()
