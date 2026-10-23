"""TestBoard_7953 model (one ADS7953 with OPA365 buffer): schedule numbers, adapter checks and real QSPICE runs."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from qspice_sim import model_loader, runner

QSPICE_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def model():
    return model_loader.load_model(QSPICE_DIR / "TestBoard_7953")


@pytest.fixture()
def bm(model):
    return model.adapter.bm


def _qspice_or_skip() -> Path:
    try:
        return runner.find_qspice()
    except runner.SimulationError:
        pytest.skip("QSPICE is not installed")


def test_model_is_discovered_without_problems():
    ids = {m.id: m for m in model_loader.discover([QSPICE_DIR])}
    assert {"TestBoard_7953", "TestBoard_ADC124"} <= set(ids)
    assert ids["TestBoard_7953"].problems == []


def test_frame_timing_matches_the_ads7953_description(bm, model):
    cfg = model.default_config()
    ft = bm.frame_timing(cfg)
    assert ft["period"] == pytest.approx(2e-6)            # 16 clocks at 20 MHz + 1200 ns gap
    assert ft["delta"] == pytest.approx(100e-9)           # 25 ns + 1.5 clocks: 2nd SCLK falling edge
    assert ft["a_off"] == pytest.approx(675e-9)           # 25 ns + 13 clocks: 14th rising edge
    assert ft["track"] == pytest.approx(1.325e-6)         # same numbers as the capture-timing report illustration
    sched = bm.build_schedule(cfg)
    assert sched["stream_frames"] == 17 and sched["frames_per_cycle"] == 29           # 15 channels + 2, 12 parked frames
    assert sched["cycle"] == pytest.approx(58e-6)


def test_other_adc_frames_follow_the_number_of_adcs_and_their_timing(bm, model):
    cfg = model.default_config()
    cfg["timing"]["scan_order"] = [0]
    for n_adc, channels, repeat, expected in ((2, 10, 1, 12), (1, 10, 1, 0), (4, 10, 1, 36), (2, 15, 1, 17), (2, 10, 3, 32)):
        cfg["timing"].update(n_adc=n_adc, other_adc_channels=channels, repeat=repeat)
        sched = bm.build_schedule(cfg)
        assert bm.other_adc_frames(cfg) == expected
        assert sched["frames_per_cycle"] == expected + 1 * repeat + 2
        assert sched["cycle"] == pytest.approx(sched["frames_per_cycle"] * 2e-6)
    cfg["timing"]["n_adc"] = 0
    with pytest.raises(ValueError, match="n_adc"):
        bm.build_schedule(cfg)


def test_stream_length_follows_repeat_and_vmid_between_channels(bm, model):
    cfg = model.default_config()
    n = len(cfg["timing"]["scan_order"])
    for repeat, between, expected in ((1, False, n * 1 + 2), (3, False, n * 3 + 2), (1, True, n * 3), (3, True, n * 5)):
        cfg["timing"]["repeat"], cfg["timing"]["vmid_between_channels"] = repeat, between
        assert len(bm.stream_channels(cfg)) == expected


@pytest.mark.parametrize("repeat", [1, 3])
def test_hold_is_repeat_frames_minus_mux_delay_after_connection(bm, model, repeat):
    cfg = model.default_config()
    cfg["timing"]["repeat"] = repeat
    cfg["timing"]["num_cycles"] = 1
    sched = bm.build_schedule(cfg)
    ft = sched["timing"]
    assert len(sched["samples"]) == 15
    for s in sched["samples"]:
        assert s["t"] - s["t_connect"] == pytest.approx(repeat * ft["period"] - ft["delta"])


def test_leakage_follows_datasheet_figure_43(bm, model):
    cfg = model.default_config()
    cfg["adc"]["temperature_c"] = 110.0                     # last tabulated point: 20 / 36 / 44 nA at 0 / 1.25 / 2.5 V
    assert [x * 1e9 for x in bm.leakage_levels(cfg)] == pytest.approx([20.0, 36.0, 44.0])
    cfg["adc"]["temperature_c"] = 25.0
    i0, i1, i2 = (x * 1e9 for x in bm.leakage_levels(cfg))
    assert 3.0 < i0 < i1 < i2 < 8.0                         # a few nA at room temperature, rising with pin voltage
    cfg["adc"]["temperature_c"] = 125.0                     # extrapolated top curve must stay close to the 61 nA of the table
    assert bm.leakage_levels(cfg)[2] * 1e9 == pytest.approx(61.0, rel=0.1)
    cfg["adc"]["leak_scale"] = 0.0
    assert bm.leakage_levels(cfg) == (0.0, 0.0, 0.0)
    cfg["adc"]["temperature_c"] = -50.0
    with pytest.raises(ValueError, match="temperature"):
        bm.leakage_levels(cfg)


def test_adapter_warns_when_the_track_window_is_below_the_datasheet_minimum(model):
    cfg = model.default_config()
    cfg["timing"]["frame_gap_ns"] = 0.0                    # 0.8 us frames: only 125 ns left for tracking
    assert any("minimum acquisition" in w for w in model.build(cfg)["warnings"])
    cfg["timing"]["spi_clk_hz"] = 2e6                      # too slow is fine; a frame shorter than 675 ns is an error
    cfg["timing"]["spi_clk_hz"], cfg["timing"]["adc_word_clocks"] = 20e6, 8
    with pytest.raises(ValueError, match="frame period"):
        model.build(cfg)


def test_force_above_vref_is_flagged(model):
    cfg = model.default_config()
    cfg["forces"] = [{"address": 2, "t_start_us": 20.0, "rise_us": 10.0, "width_us": 50.0, "fall_us": 10.0, "amp_N": 0.5}]
    assert any("VREF" in w for w in model.build(cfg)["warnings"])


def test_invalid_scan_order_is_rejected(model):
    cfg = model.default_config()
    cfg["timing"]["scan_order"] = [0, 1, 1]
    with pytest.raises(ValueError, match="scan_order"):
        model.build(cfg)
    cfg["timing"]["scan_order"] = [0, 15]
    with pytest.raises(ValueError, match="scan_order"):
        model.build(cfg)


def test_real_run_parks_on_vmid_holds_the_sample_and_reads_the_force(tmp_path, model):
    qspice = _qspice_or_skip()
    cfg = model.default_config()
    cfg["forces"] = [{"address": 2, "t_start_us": 5.0, "rise_us": 5.0, "width_us": 400.0, "fall_us": 5.0, "amp_N": 0.05}]
    cfg["timing"]["num_cycles"] = 2
    prepared = runner.prepare(model, cfg)
    raw = runner.run_netlist(prepared.netlist, ["mxo", "ain", "sh", "c2", "c3", "c15"], tmp_path, qspice)
    t, sh, ain, c2, c3, c15 = raw.time, raw.column("sh"), raw.column("ain"), raw.column("c2"), raw.column("c3"), raw.column("c15")
    by_label = {}
    for s in prepared.samples:
        by_label.setdefault(s["label"], []).append(s["t"])
    base = np.interp(by_label["Ch0"][0], t, sh)
    assert base == pytest.approx(1.25, abs=0.01)                          # unstimulated channel reads VMID
    forced = np.interp(by_label["Ch2"][0], t, sh)
    expected_open_circuit = 0.05 * 600e-12 / 60.7e-12
    assert 0.4 * expected_open_circuit < forced - 1.25 < expected_open_circuit
    # no two channels are ever enabled together (break-before-make), and the mux is on VMID during the parked frames
    assert float(np.max(np.minimum(c2, c15))) == 0.0 and float(np.max(np.minimum(c2, c3))) == 0.0
    assert np.interp(10e-6 + 5 * 2e-6, t, c15) == pytest.approx(1.0, abs=0.01)
    # the S/H keeps the sampled value while the mux moves on to the next channel (hold window, 100 ns .. 675 ns after CS falls)
    t_hold = by_label["Ch2"][0]
    assert abs(np.interp(t_hold + 600e-9, t, ain) - np.interp(t_hold, t, ain)) > 0.1
    assert abs(np.interp(t_hold + 600e-9, t, sh) - np.interp(t_hold, t, sh)) < 0.003
    raw.close()
