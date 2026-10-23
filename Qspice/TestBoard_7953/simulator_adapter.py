"""Adapter that lets the Qspice/Simulator GUI drive the TestBoard_7953 model (see ../Simulator/README.md for the contract)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _load_sibling(name: str):
    """Import a sibling module under a model-specific name so several models can each have a build_model.py."""
    mod_name = f"qspice_model_{_HERE.name}_{name}"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, _HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


bm = _load_sibling("build_model")
MIN_ACQUISITION_S = 325e-9      # ADS7953 datasheet SLAS605C, section 7.6


def build(cfg: dict) -> dict:
    text, sched = bm.build(cfg)
    warnings: list[str] = []
    c = cfg["circuit"]
    for kind, f in [("pulse", f) for f in cfg.get("forces", [])] + [("sine", f) for f in cfg.get("forces_sin", [])]:
        sp = bm.sensor_params(cfg, int(f["address"]))
        v_open = sp["d33"] * float(f["amp_N"]) / sp["cp"]
        if c["vmid_v"] + v_open > c["vref_v"]:
            warnings.append(f"Force {kind} on address {f['address']} ({f['amp_N']} N) gives {v_open:.2f} V open circuit: the sensor "
                            f"pin would exceed VREF ({c['vref_v']} V, ADS7953 range 1); the model has no input clamp.")
        if c["vmid_v"] - v_open < 0:
            warnings.append(f"Force {kind} on address {f['address']}: the release swing would go below 0 V (ADS7953 absolute range -0.2 V).")
    track = sched["timing"]["track"]
    if track < MIN_ACQUISITION_S:
        warnings.append(f"Track window {track * 1e9:.0f} ns is shorter than the ADS7953 minimum acquisition time of 325 ns "
                        "(datasheet): the real ADC would not settle. Increase the frame gap or lower the SPI clock.")
    return {
        "netlist": text,
        "t_stop": sched["t_stop"],
        "samples": [{"t": s["t"], "label": f"Ch{s['address']}"} for s in sched["samples"]],
        "warnings": warnings,
    }


def summary(cfg: dict) -> list[tuple[str, str]]:
    t = cfg["timing"]
    ft = bm.frame_timing(cfg)
    seq = bm.stream_channels(cfg)
    n = len(t["scan_order"])
    rep = int(t["repeat"])
    other = bm.other_adc_frames(cfg)
    frames = other + len(seq)
    cycle = frames * ft["period"] + t["sweep_gap_us"] * 1e-6
    connected = rep * ft["period"]
    sp = bm.sensor_params(cfg, 0)
    c = cfg["circuit"]
    return [
        ("Frame period", f"{ft['period'] * 1e6:.3f} us  ({t['adc_word_clocks']} clocks at {t['spi_clk_hz'] / 1e6:g} MHz + {t['frame_gap_ns']:g} ns gap)"),
        ("Mux changes after CS falls", f"{ft['delta'] * 1e9:.0f} ns  (2nd SCLK falling edge)"),
        ("Mux settling before tracking opens", f"{(ft['a_off'] - ft['delta']) * 1e9:.0f} ns  (datasheet: ~600 ns)"),
        ("Track window per frame", f"{ft['track'] * 1e9:.0f} ns  (datasheet minimum 325 ns)" + ("  <-- TOO SHORT" if ft["track"] < MIN_ACQUISITION_S else "")),
        ("Connected time per sensor", f"{connected * 1e6:.3f} us  ({rep} frame{'s' if rep > 1 else ''})"),
        ("Connection to retained hold", f"{(connected - ft['delta']) * 1e6:.3f} us"),
        ("Stream frames of this ADC", f"{len(seq)}  ({'n*(repeat+2)' if t['vmid_between_channels'] else 'n*repeat+2'} for n = {n})"),
        ("Frames of the other ADCs per sweep", f"{other}  ({int(t['n_adc']) - 1} x ({int(t['other_adc_channels'])} channels x {rep} + 2) frames, {other * ft['period'] * 1e6:.2f} us)"),
        ("Frames per sweep (all ADCs)", f"{frames}"),
        ("Sweep period", f"{cycle * 1e6:.2f} us  ({1.0 / cycle:,.0f} sweeps/s)"),
        ("Connected duty per sensor", f"{connected / cycle * 100:.1f} %"),
        ("Pin leakage at 0 / 1.25 / 2.5 V (Figure 43)", " / ".join(f"{x * 1e9:.3g}" for x in bm.leakage_levels(cfg)) + f" nA at {cfg['adc']['temperature_c']:g} C"),
        ("Sensor capacitance (sensor 0)", f"{sp['cp'] * 1e12:.1f} pF"),
        ("Sensitivity, open circuit", f"{sp['d33'] / sp['cp']:.2f} V/N"),
        ("Force for +/-1.25 V swing", f"{c['vmid_v'] / (sp['d33'] / sp['cp']):.3f} N"),
    ]
