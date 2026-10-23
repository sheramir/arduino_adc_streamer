"""Adapter that lets the Qspice/Simulator GUI drive the TestBoard_ADC124 model.

Plugin contract (see Qspice/Simulator/README.md):
    build(cfg)   -> {"netlist": str, "t_stop": float, "samples": [{"t": s, "label": str}], "warnings": [str]}
    summary(cfg) -> [(label, text), ...]            optional, shown on the System tab
Both raise ValueError with a readable message for invalid parameters.
"""
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


def build(cfg: dict) -> dict:
    text, slots = bm.build(cfg, with_force=True)
    sensor = [s for s in slots if s["kind"] == "sensor"]
    warnings: list[str] = []
    for kind, f in [("pulse", f) for f in cfg.get("forces", [])] + [("sine", f) for f in cfg.get("forces_sin", [])]:
        sp = bm.sensor_params(cfg, int(f["address"]))
        v_open = sp["d33"] * float(f["amp_N"]) / sp["cp"]
        if cfg["circuit"]["vmid_v"] + v_open > cfg["circuit"]["vdd_v"]:
            warnings.append(f"Force {kind} on address {f['address']} ({f['amp_N']} N) gives {v_open:.2f} V open circuit: "
                            f"the sensor pin would exceed VDD ({cfg['circuit']['vdd_v']} V); the model has no input clamp.")
    return {
        "netlist": text,
        "t_stop": max(s["t1"] for s in slots),
        "samples": [{"t": s["t_sample"], "label": f"addr {s['address']}"} for s in sensor],
        "warnings": warnings,
    }


def summary(cfg: dict) -> list[tuple[str, str]]:
    t = cfg["timing"]
    us = 1e-6
    n = len(t["scan_order"])
    visit = bool(t["vmid_visit_after_each"])
    adc = bm.adc_timing(t)
    busy = adc["busy"]
    settle_v = t["t_vmid_settle_us"] * us
    park = t["t_vmid_park_us"] * us
    if t.get("sampling_rate_hz"):
        rate = float(t["sampling_rate_hz"])
        park = (1.0 / rate / n - busy - settle_v) if visit else (1.0 / rate - n * busy)
    cycle = n * (busy + settle_v + park) if visit else n * busy + park
    sp = bm.sensor_params(cfg, 0)
    out = [
        ("ADC word (conversion) time", f"{adc['word'] * 1e6:.3f} us  ({t['adc_word_clocks']} clocks at {t['adc_spi_clk_hz'] / 1e6:g} MHz)"),
        ("Repeats", f"{adc['repeat']}  (the last conversion is kept)"),
        ("ADC acquisition before the hold", f"{adc['acq'] * 1e9:.1f} ns"),
        ("Hold of the retained sample after the command", f"{adc['hold_offset'] * 1e6:.4f} us  (settle + {adc['repeat'] - 1} extra words + acquisition)"),
        ("Wait on the channel while the other muxes are read", f"{adc['wait_others'] * 1e6:.3f} us  ({adc['n_mux'] - 1} muxes x {adc['repeat']} words)"),
        ("Connected time per sensor visit", f"{busy * 1e6:.3f} us  (settle + {adc['n_mux']} muxes x {adc['repeat']} words)"),
        ("VMID park time used", f"{park * 1e6:.2f} us" + (" after every address" if visit else " once per sweep")
         + ("  (derived from the sampling rate)" if t.get("sampling_rate_hz") else "")),
        ("Scan cycle", f"{cycle * 1e6:.2f} us"),
        ("Sampling rate per sensor", f"{1.0 / cycle:,.1f} Hz" if cycle > 0 else "n/a"),
        ("Connected duty per sensor", f"{busy / cycle * 100:.1f} %  (floating {(cycle - busy) * 1e6:.1f} us per cycle)" if cycle > 0 else "n/a"),
        ("Sensor capacitance (sensor 0)", f"{sp['cp'] * 1e12:.1f} pF"),
        ("Sensitivity, open circuit", f"{sp['d33'] / sp['cp']:.2f} V/N"),
        ("Force for +/-1.65 V swing", f"{1.65 / (sp['d33'] / sp['cp']):.3f} N"),
    ]
    if t.get("run_duration_s") and cycle > 0:
        out.append(("Scan cycles in the run", f"{int((t['run_duration_s'] - t['t_start_us'] * us) / cycle)}"))
    return out
