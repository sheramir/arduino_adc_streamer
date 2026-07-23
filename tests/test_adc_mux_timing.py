import json
from unittest.mock import patch

import numpy as np
import pytest

from config.config_handlers import ConfigurationMixin
from data_processing.adc_mux_timing import (
    MG24_TIMING_PROFILE,
    Mg24DualMuxTimingCalculator,
    adc_mux_timing_log,
    calculate_adc_mux_timing_for_acquisition,
    get_adc_mux_timing_calculator,
)
from data_processing.analysis_workbench import (
    AnalysisSourceSnapshot,
    build_calculated_pzt_force_traces,
    resolve_analysis_pzt_mux_leak_dt_s,
)


def calculate(**overrides):
    inputs = {
        "osr": 2,
        "gain": 1,
        "repeat_count": 1,
        "use_ground_between_channels": True,
    }
    inputs.update(overrides)
    return Mg24DualMuxTimingCalculator().calculate(**inputs)


def test_mg24_osr2_gain1_hardware_timing():
    timing = calculate()

    assert timing.t_obs_us == pytest.approx(0.8)
    assert timing.t_conv_us == pytest.approx(1.0)
    assert timing.t_iadc_input_switch_us == pytest.approx(0.2)
    assert timing.t_pair_hardware_us == pytest.approx(2.2)
    assert timing.t_pair_total_us == pytest.approx(3.55)


def test_mg24_osr4_gain1_hardware_timing():
    timing = calculate(osr=4)

    assert timing.t_obs_us == pytest.approx(1.6)
    assert timing.t_conv_us == pytest.approx(1.8)
    assert timing.t_iadc_input_switch_us == pytest.approx(0.2)
    assert timing.t_pair_hardware_us == pytest.approx(3.8)


def test_ground_repeat_and_sensor_connection_duration():
    without_ground = calculate(use_ground_between_channels=False)
    with_ground = calculate(repeat_count=2, use_ground_between_channels=True)

    assert without_ground.ground_phase_us == 0.0
    assert with_ground.ground_phase_us == pytest.approx(6.8)
    assert with_ground.signal_sequence_us == pytest.approx(10.35)
    assert with_ground.complete_sequence_us == pytest.approx(17.15)
    assert with_ground.sensor_connected_us == pytest.approx(9.95)
    assert with_ground.sensor_connected_s == pytest.approx(9.95e-6)


@pytest.mark.parametrize(
    ("gain", "expected_clock_hz", "expected_observation_us"),
    [(2, 5_000_000, 1.6), (3, 2_500_000, 3.2), (4, 2_500_000, 3.2)],
)
def test_gain_selects_the_profile_adc_clock(gain, expected_clock_hz, expected_observation_us):
    timing = calculate(gain=gain)

    assert timing.adc_clk_hz == expected_clock_hz
    assert timing.t_obs_us == pytest.approx(expected_observation_us)


def test_invalid_inputs_and_unsupported_device_are_explicit():
    with pytest.raises(ValueError, match="OSR"):
        calculate(osr=3)
    with pytest.raises(ValueError, match="gain"):
        calculate(gain=5)
    with pytest.raises(ValueError, match="repeat_count"):
        calculate(repeat_count=0)
    assert get_adc_mux_timing_calculator("MG24_MUX") is None
    assert calculate_adc_mux_timing_for_acquisition("Unsupported.1", {}) is None


def test_registry_supports_requested_identifier_and_existing_host_alias():
    assert get_adc_mux_timing_calculator("Array_PPZT_PZR1.7") is not None
    assert get_adc_mux_timing_calculator("Array_PZT_PZR1.7") is not None


def test_timing_log_is_json_serializable_and_contains_calculated_results():
    payload = adc_mux_timing_log(calculate(osr=4))

    serialized = json.dumps(payload)
    assert json.loads(serialized)["adc"] == "mg24_dual_mux_v1"
    assert payload["constants"]["adc_clk_hz"] == 10_000_000
    assert payload["calculated_timing"]["t_connected_us"] == pytest.approx(8.0)
    assert payload["calculated_timing"]["t_pair_overhead_us"] == pytest.approx(1.35)
    assert payload["calculated_timing"]["t_overhead_per_mux_selection_us"] == pytest.approx(1.6)
    assert "calculator" not in payload
    assert "results" not in payload
    assert "t_total_overhead_us" not in payload["calculated_timing"]
    assert "sensor_connected_s" not in serialized


def test_timing_log_timeline_is_chronological_and_uses_ground_sequence():
    timing = calculate(osr=4, use_ground_between_channels=True)
    payload = adc_mux_timing_log(timing)
    timeline = payload["timeline"]

    assert timeline[0]["event"] == "ground_mux_switch_start"
    assert timeline[-1] == {"t_us": 16.8, "event": "next_mux_switch_start"}
    assert [item["t_us"] for item in timeline] == sorted(item["t_us"] for item in timeline)
    connected_at = next(item["t_us"] for item in timeline if item["event"] == "sensor_connected_to_mux_output")
    assert timeline[-1]["t_us"] - connected_at == pytest.approx(
        payload["calculated_timing"]["t_connected_us"]
    )


def test_timing_log_starts_with_signal_and_stays_compact_for_repeats():
    payload = adc_mux_timing_log(calculate(repeat_count=3, use_ground_between_channels=False))
    timeline = payload["timeline"]

    assert timeline[0] == {"t_us": 0.0, "event": "signal_mux_switch_start"}
    assert timeline[-1]["event"] == "next_mux_switch_start"
    assert any(item["event"] == "additional_retained_pairs_start" for item in timeline)
    assert any(item["event"] == "all_retained_adc_pairs_complete" for item in timeline)
    assert len(timeline) < 20


def test_timing_log_rounds_every_float_only_at_json_boundary():
    timing = calculate(osr=4)
    payload = adc_mux_timing_log(timing)

    def assert_rounded(value):
        if isinstance(value, float):
            assert len(f"{value}".split(".")[-1]) <= 2
        elif isinstance(value, dict):
            for item in value.values():
                assert_rounded(item)
        elif isinstance(value, list):
            for item in value:
                assert_rounded(item)

    assert_rounded(payload)
    assert timing.t_pair_total_us == pytest.approx(5.1499999999999995)
    assert payload["calculated_timing"]["t_pair_total_us"] == 5.15
    assert "3.8000000000000003" not in json.dumps(payload)


def test_ground_dwell_only_profile_is_ready_for_future_firmware_mode():
    profile = {**MG24_TIMING_PROFILE, "ground_mode": "dwell_only"}
    timing = Mg24DualMuxTimingCalculator(profile=profile).calculate(
        osr=2, gain=1, repeat_count=1, use_ground_between_channels=True
    )

    assert timing.ground_phase_us == pytest.approx(13.25)


def test_configuration_refresh_recalculates_after_timing_input_changes():
    harness = type("Harness", (), {})()
    harness.current_mcu = "Array_PPZT_PZR1.7"
    harness.config = {"osr": 2, "gain": 1, "repeat": 1, "use_ground": False}

    first = ConfigurationMixin.refresh_adc_mux_timing(harness)
    harness.config.update({"osr": 4, "gain": 2, "repeat": 3, "use_ground": True})
    second = ConfigurationMixin.refresh_adc_mux_timing(harness)

    assert first.t_pair_hardware_us == pytest.approx(2.2)
    assert second.t_pair_hardware_us == pytest.approx(7.6)
    assert second.repeat_count == 3
    assert second.use_ground_between_channels is True


def test_analysis_force_auto_mode_uses_calculated_sensor_connected_duration():
    timing = calculate()
    snapshot = AnalysisSourceSnapshot(
        data=np.asarray([[1.0], [2.0]]),
        timestamps_s=np.asarray([0.0, 0.1]),
        channel_labels=["PZT1_C"],
        metadata={
            "adc_mux_timing": adc_mux_timing_log(timing),
            "timing": {
                "pzt_mux_connected_time_s": timing.sensor_connected_s,
                "pzt_mux_connected_time_source": "adc_mux_timing.t_connected_s",
            },
        },
    )

    leak_dt_s, status = resolve_analysis_pzt_mux_leak_dt_s(
        snapshot, {"enabled": True, "mux_timing_mode": "auto"}
    )

    assert leak_dt_s == pytest.approx(timing.sensor_connected_s)
    assert "t_connected_s" in status


def test_force_calculation_receives_calculated_sensor_connected_duration():
    timing = calculate()
    snapshot = AnalysisSourceSnapshot(
        data=np.asarray([[1.0], [2.0]]),
        timestamps_s=np.asarray([0.0, 0.1]),
        channel_labels=["PZT1_C"],
    )
    with patch("data_processing.analysis_workbench.calculate_pzt_force_from_settings") as force_calculation:
        force_calculation.return_value = np.zeros(2)
        build_calculated_pzt_force_traces(
            snapshot,
            np.asarray([[0.0], [0.1]]),
            np.asarray([[0.0], [0.1]]),
            {"PZT1_C": np.asarray([1.0, 1.1])},
            {"enabled": True},
            leak_dt_s=timing.sensor_connected_s,
        )

    assert force_calculation.call_args.kwargs["leak_dt_s"] == pytest.approx(timing.sensor_connected_s)
