"""Sine force input profile ("Add sin" table): waveform generation, warnings, GUI table and a real QSPICE run."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from qspice_sim import model_loader, runner

QSPICE_DIR = Path(__file__).resolve().parents[2]
MODELS = ["TestBoard_7953", "TestBoard_ADC124"]
SIN = {"address": 2, "t_start_us": 20.0, "freq_hz": 50000.0, "cycles": 3, "amp_N": 0.05}


@pytest.fixture(params=MODELS)
def model(request):
    return model_loader.load_model(QSPICE_DIR / request.param)


def _cfg(model, **sin):
    cfg = model.default_config()
    cfg["forces"] = []
    cfg["forces_sin"] = [{**SIN, **sin}]
    return cfg


def test_default_config_has_an_empty_sine_table_and_manifest_entry(model):
    assert model.problems == []
    assert model.default_config()["forces_sin"] == []
    spec = next(t for t in model.manifest["tables"] if t["path"] == "forces_sin")
    assert spec["add_label"] == "Add sin"
    assert [c["key"] for c in spec["columns"]] == ["address", "t_start_us", "freq_hz", "cycles", "amp_N"]


def test_sine_pwl_follows_amplitude_frequency_and_cycles(model):
    bm = model.adapter.bm
    cfg = _cfg(model)
    pts = bm.force_pwl(cfg, 2, 200e-6)
    t, v = np.array([p[0] for p in pts]), np.array([p[1] for p in pts])
    assert np.all(v[t <= 20e-6] == 0.0) and np.all(v[t >= 20e-6 + 3 / 50e3] == 0.0)    # silent before the start and after the last cycle
    assert v.max() == pytest.approx(0.05, rel=2e-3) and v.min() == pytest.approx(-0.05, rel=2e-3)
    quarter = 20e-6 + 0.25 / 50e3
    assert np.interp(quarter, t, v) == pytest.approx(0.05, rel=2e-3)                   # peak a quarter period after the start
    zero_crossings = np.where(np.diff(np.sign(v[(t > 20e-6) & (t < 20e-6 + 3 / 50e3 - 1e-9)])) != 0)[0]
    assert len(zero_crossings) == 5                                                    # 3 cycles: 5 interior zero crossings
    assert bm.force_pwl(cfg, 3, 200e-6) == [(0.0, 0.0), (200e-6, 0.0)]                 # other sensors stay at rest


def test_sine_adds_to_pulses_on_the_same_address(model):
    bm = model.adapter.bm
    cfg = _cfg(model)
    cfg["forces"] = [{"address": 2, "t_start_us": 0.0, "rise_us": 1.0, "width_us": 500.0, "fall_us": 1.0, "amp_N": 0.02}]
    t, v = zip(*bm.force_pwl(cfg, 2, 200e-6))
    assert np.interp(20e-6 + 0.25 / 50e3, t, v) == pytest.approx(0.07, rel=3e-3)


def test_sine_is_cut_at_the_end_of_the_run(model):
    pts = model.adapter.bm.force_pwl(_cfg(model, cycles=100), 2, 60e-6)
    assert pts[-1][0] == pytest.approx(60e-6) and max(t for t, _ in pts) <= 60e-6 + 1e-15


def test_invalid_sine_rows_are_rejected(model):
    with pytest.raises(ValueError, match="positive"):
        model.build(_cfg(model, freq_hz=0.0))
    with pytest.raises(ValueError, match="positive"):
        model.build(_cfg(model, cycles=0))
    with pytest.raises(ValueError, match="points"):
        model.adapter.bm.force_pwl(_cfg(model, freq_hz=1e6, cycles=1e9), 2, 1.0)


def test_sine_amplitude_over_the_supply_is_flagged(model):
    assert not any("sine" in w for w in model.build(_cfg(model))["warnings"])
    assert any("Force sine" in w for w in model.build(_cfg(model, amp_N=0.5))["warnings"])


def _qspice_or_skip() -> Path:
    try:
        return runner.find_qspice()
    except runner.SimulationError:
        pytest.skip("QSPICE is not installed")


def test_real_run_shows_a_bipolar_sine_on_the_driven_sensor_only(tmp_path):
    qspice = _qspice_or_skip()
    model = model_loader.load_model(QSPICE_DIR / "TestBoard_7953")
    cfg = _cfg(model, t_start_us=5.0, amp_N=0.02)
    cfg["timing"]["num_cycles"] = 1
    prepared = runner.prepare(model, cfg)
    raw = runner.run_netlist(prepared.netlist, ["p2", "p3"], tmp_path, qspice)
    p2, p3 = raw.column("p2"), raw.column("p3")
    assert p2.max() - p2.min() > 0.2                       # 0.02 N x 600 pC/N / 60.7 pF = 0.2 V open circuit: +/-0.2 V swing
    assert p2.max() > p2[0] + 0.1 and p2.min() < p2[0] - 0.1
    assert (p3.max() - p3.min()) < 0.2 * (p2.max() - p2.min())      # an undriven neighbour only sees the mux charge sharing and leakage
    raw.close()
