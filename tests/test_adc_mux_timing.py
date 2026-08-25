import json
from unittest.mock import patch

import numpy as np
import pytest

from config.config_handlers import ConfigurationMixin
from data_processing.adc_mux_timing import (
    MG24_GROUND_DWELL_US,
    MG24_GROUND_READ_ADC,
    MG24_TIMING_PROFILE,
    Mg24DualMuxTimingCalculator,
    adc_mux_timing_log,
    calculate_adc_mux_timing_for_acquisition,
    estimate_repeat_pair_interval_from_measurements,
    get_adc_mux_timing_calculator,
)
from data_processing.analysis_workbench import (
    AnalysisSourceSnapshot,
    build_calculated_pzt_force_traces,
    resolve_analysis_pzt_pre_sample_decay_dt_s,
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
    assert timing.t_pair_loop_software_overhead_us == pytest.approx(8.293)
    assert timing.t_pair_loop_total_us == pytest.approx(10.493)
    assert timing.signal_sequence_us == pytest.approx(20.383)
    assert timing.sensor_connected_us == pytest.approx(19.983)


def test_mg24_osr4_gain1_hardware_timing():
    timing = calculate(osr=4)

    assert timing.t_obs_us == pytest.approx(1.6)
    assert timing.t_conv_us == pytest.approx(1.8)
    assert timing.t_iadc_input_switch_us == pytest.approx(0.2)
    assert timing.t_pair_hardware_us == pytest.approx(3.8)
    assert timing.t_pair_loop_software_overhead_us == pytest.approx(8.293)
    assert timing.t_pair_loop_total_us == pytest.approx(12.093)
    assert timing.signal_sequence_us == pytest.approx(21.983)
    assert timing.sensor_connected_us == pytest.approx(21.583)
    assert timing.sensor_connected_s == pytest.approx(21.583e-6, abs=1e-9)


@pytest.mark.parametrize(
    ("repeat_count", "signal_sequence_us", "sensor_connected_us"),
    [(1, 21.983, 21.583), (16, 203.378, 202.978)],
)
def test_calibrated_uniform_pair_loop_sequence_equations(
    repeat_count, signal_sequence_us, sensor_connected_us,
):
    timing = calculate(osr=4, repeat_count=repeat_count, use_ground_between_channels=False)

    assert timing.t_pair_loop_total_us == pytest.approx(12.093)
    assert timing.signal_sequence_us == pytest.approx(signal_sequence_us)
    assert timing.sensor_connected_us == pytest.approx(sensor_connected_us)


def test_mg24_ground_timing_mirrors_the_firmware_constants():
    timing = calculate(osr=4, use_ground_between_channels=True)

    expected_mode = "dummy_adc_pair" if MG24_GROUND_READ_ADC else "dwell_only"
    assert timing.ground_mode == expected_mode
    assert timing.ground_dwell_us == pytest.approx(MG24_GROUND_DWELL_US)
    assert timing.ground_phase_us == pytest.approx(59.890)
    assert timing.complete_sequence_us == pytest.approx(81.873)
    assert timing.t_decay_before_effective_sample_ch1_us == pytest.approx(3.80)
    assert timing.t_decay_before_effective_sample_ch2_us == pytest.approx(5.80)
    assert timing.t_connected_after_effective_sample_ch1_us == pytest.approx(17.783)
    assert timing.t_connected_after_effective_sample_ch2_us == pytest.approx(15.783)
    assert (
        timing.t_decay_before_effective_sample_ch1_us
        + timing.t_connected_after_effective_sample_ch1_us
    ) == pytest.approx(timing.sensor_connected_us)
    assert (
        timing.t_decay_before_effective_sample_ch2_us
        + timing.t_connected_after_effective_sample_ch2_us
    ) == pytest.approx(timing.sensor_connected_us)


def test_repeat_specific_effective_sample_helpers_are_explicit():
    timing = calculate(osr=4, repeat_count=2, use_ground_between_channels=True)

    assert timing.decay_before_effective_sample_s(adc_input=1) == pytest.approx(3.80e-6)
    assert timing.decay_before_effective_sample_s(adc_input=1, repeat_index=1) == pytest.approx(
        (3.80 + 12.093) * 1e-6
    )
    assert timing.decay_before_effective_sample_s(adc_input=2, repeat_index=1) == pytest.approx(
        (5.80 + 12.093) * 1e-6
    )
    with pytest.raises(ValueError, match="adc_input"):
        timing.decay_before_effective_sample_s(adc_input=3)
    with pytest.raises(ValueError, match="repeat_index"):
        timing.connected_after_effective_sample_s(adc_input=1, repeat_index=2)


def test_sweeps_per_block_extends_one_continuous_connection():
    # Verified against live MG24 hardware block timestamps (2026-08-11):
    # muxSelect() no-ops on every sweep after the first when the same single
    # channel repeats with ground sampling off, so sweeps_per_block behaves
    # exactly like additional repeat_count pairs in one continuous connection.
    folded = calculate(osr=4, repeat_count=4, sweeps_per_block=10, use_ground_between_channels=False)
    equivalent = calculate(osr=4, repeat_count=40, use_ground_between_channels=False)

    assert folded.continuous_pair_count == 40
    assert folded.repeat_count == 4
    assert folded.sweeps_per_block == 10
    assert folded.signal_sequence_us == pytest.approx(equivalent.signal_sequence_us)
    assert folded.sensor_connected_us == pytest.approx(equivalent.sensor_connected_us)
    assert folded.signal_sequence_us == pytest.approx(493.61, abs=0.01)


def test_sweeps_per_block_defaults_to_one_and_matches_prior_behavior():
    default = calculate(osr=4, repeat_count=4, use_ground_between_channels=False)

    assert default.sweeps_per_block == 1
    assert default.continuous_pair_count == default.repeat_count


def test_sweeps_per_block_requires_ground_sampling_off():
    with pytest.raises(ValueError, match="sweeps_per_block"):
        calculate(repeat_count=1, sweeps_per_block=2, use_ground_between_channels=True)


def test_sweeps_per_block_extends_repeat_index_bounds_for_decay_helpers():
    timing = calculate(osr=4, repeat_count=2, sweeps_per_block=3, use_ground_between_channels=False)

    assert timing.decay_before_effective_sample_s(adc_input=1, repeat_index=5) == pytest.approx(
        (3.80 + 5 * 12.093) * 1e-6
    )
    with pytest.raises(ValueError, match="repeat_index"):
        timing.decay_before_effective_sample_s(adc_input=1, repeat_index=6)


def test_acquisition_helper_only_folds_sweeps_for_single_channel_no_ground():
    single_no_ground = calculate_adc_mux_timing_for_acquisition(
        "Array_PZT_PZR1.7",
        {"osr": 4, "gain": 1, "repeat": 4, "channels": [1], "use_ground": False, "buffer": 10},
    )
    assert single_no_ground.sweeps_per_block == 10
    assert single_no_ground.continuous_pair_count == 40

    multi_channel = calculate_adc_mux_timing_for_acquisition(
        "Array_PZT_PZR1.7",
        {"osr": 4, "gain": 1, "repeat": 4, "channels": [1, 2], "use_ground": False, "buffer": 10},
    )
    assert multi_channel.sweeps_per_block == 1

    grounded = calculate_adc_mux_timing_for_acquisition(
        "Array_PZT_PZR1.7",
        {"osr": 4, "gain": 1, "repeat": 4, "channels": [1], "use_ground": True, "buffer": 10},
    )
    assert grounded.sweeps_per_block == 1


def test_sequence_model_does_not_force_complete_block_timestamp_measurements():
    no_ground = calculate(osr=4, use_ground_between_channels=False)
    with_ground = calculate(osr=4, use_ground_between_channels=True)

    predicted_no_ground_block_us = (
        no_ground.t_block_fixed_overhead_us + 15 * no_ground.signal_sequence_us
    )
    predicted_ground_block_us = (
        with_ground.t_block_fixed_overhead_us + 15 * with_ground.complete_sequence_us
    )
    assert predicted_no_ground_block_us == pytest.approx(338.975, abs=0.001)
    assert predicted_ground_block_us == pytest.approx(1237.325, abs=0.001)
    assert predicted_ground_block_us / 30 != pytest.approx(22.858, abs=0.01)


def test_mg24_osr8_gain1_uses_calibrated_pair_overhead():
    timing = calculate(osr=8)

    assert timing.t_pair_hardware_us == pytest.approx(7.0)
    assert timing.t_pair_loop_total_us == pytest.approx(15.293)
    assert timing.signal_sequence_us == pytest.approx(25.183)
    assert timing.sensor_connected_us == pytest.approx(24.783)


def test_ground_repeat_and_sensor_connection_duration():
    without_ground = calculate(use_ground_between_channels=False)
    with_ground = calculate(repeat_count=2, use_ground_between_channels=True)

    assert without_ground.ground_phase_us == 0.0
    assert with_ground.ground_phase_us == pytest.approx(59.890)
    assert with_ground.signal_sequence_us == pytest.approx(30.876)
    assert with_ground.complete_sequence_us == pytest.approx(90.766)
    assert with_ground.sensor_connected_us == pytest.approx(30.476)
    assert with_ground.sensor_connected_s == pytest.approx(30.476e-6)


def test_repeat_count_ten_scales_only_pair_work_in_connection_time():
    timing = calculate(osr=4, repeat_count=10, use_ground_between_channels=True)

    assert timing.signal_sequence_us == pytest.approx(0.25 + 3.0 + 6.64 + 10 * 12.093)
    assert timing.sensor_connected_us == pytest.approx(3.0 - 0.15 + 6.64 + 10 * 12.093)
    assert timing.ground_phase_us == pytest.approx(59.890)


def test_custom_profile_uses_one_uniform_pair_loop_interval():
    profile = {
        **MG24_TIMING_PROFILE,
        "pair_loop_software_overhead_us": 8.0,
        "burst_finalize_overhead_us": 4.0,
    }
    timing = Mg24DualMuxTimingCalculator(profile=profile).calculate(
        osr=4, gain=1, repeat_count=3, use_ground_between_channels=False,
    )
    assert timing.t_pair_loop_total_us == pytest.approx(11.8)
    assert timing.t_burst_finalize_overhead_us == pytest.approx(4.0)
    assert timing.signal_sequence_us == pytest.approx(0.25 + 3.0 + 3 * 11.8 + 4.0)
    assert timing.decay_before_effective_sample_s(adc_input=2, repeat_index=2) == pytest.approx(
        (5.8 + 2 * 11.8) * 1e-6
    )


def test_pair_loop_calibration_helper_fits_repeat_count_slope():
    fixed_overhead_us = 37.5
    repeat_counts = [1, 2, 5, 10, 16]
    result = estimate_repeat_pair_interval_from_measurements(
        repeat_counts, [fixed_overhead_us + count * 12.093 for count in repeat_counts],
    )
    assert result["pair_loop_interval_us"] == pytest.approx(12.093)
    assert result["fixed_overhead_us"] == pytest.approx(fixed_overhead_us)
    assert result["rmse_us"] == pytest.approx(0.0)


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
    assert calculate().device_profile == "Array_PZT_PZR1"


def test_timing_log_is_json_serializable_and_contains_calculated_results():
    payload = adc_mux_timing_log(calculate(osr=4))

    serialized = json.dumps(payload)
    assert json.loads(serialized)["adc"] == "mg24_dual_mux_v3"
    assert payload["constants"]["adc_clk_hz"] == 10_000_000
    assert payload["constants"]["pair_loop_software_overhead_us"] == pytest.approx(8.29)
    assert payload["constants"]["per_mux_selection_overhead_us"] == pytest.approx(6.64)
    assert payload["constants"]["block_fixed_overhead_us"] == pytest.approx(9.23)
    assert payload["constants"]["ground_dummy_software_overhead_us"] == pytest.approx(12.32)
    assert "post_pair_overhead_us" not in payload["constants"]
    assert payload["calculated_timing"]["t_connected_us"] == pytest.approx(21.58)
    assert payload["calculated_timing"]["t_pair_loop_total_us"] == pytest.approx(12.09)
    assert payload["calculated_timing"]["t_per_mux_selection_overhead_us"] == pytest.approx(6.64)
    assert payload["calculated_timing"]["t_ground_dummy_software_overhead_us"] == pytest.approx(12.32)
    assert "calculator" not in payload
    assert "results" not in payload
    assert "t_total_overhead_us" not in payload["calculated_timing"]
    assert "sensor_connected_s" not in serialized


def test_timing_log_timeline_is_chronological_and_uses_ground_sequence():
    timing = calculate(osr=4, use_ground_between_channels=True)
    payload = adc_mux_timing_log(timing)
    timeline = payload["timeline"]

    assert timeline[0]["event"] == "ground_mux_switch_start"
    assert timeline[-1] == {"t_us": 81.87, "event": "next_mux_switch_start"}
    assert [item["t_us"] for item in timeline] == sorted(item["t_us"] for item in timeline)
    assert next(item["t_us"] for item in timeline if item["event"] == "ground_dwell_complete") == pytest.approx(53.25)
    assert next(item["t_us"] for item in timeline if item["event"] == "ground_mux_selection_processing_complete") == pytest.approx(59.89)
    assert not any(item["event"] == "ground_dummy_processing_complete" for item in timeline)
    assert timeline[-1]["t_us"] == pytest.approx(round(timing.complete_sequence_us, 2))
    assert timing.complete_sequence_us - (
        timing.ground_phase_us + timing.mux_address_overhead_us + timing.mux_turn_on_us
    ) == pytest.approx(timing.sensor_connected_us)


def test_timing_log_starts_with_signal_and_stays_compact_for_repeats():
    payload = adc_mux_timing_log(calculate(repeat_count=3, use_ground_between_channels=False))
    timeline = payload["timeline"]

    assert timeline[0] == {"t_us": 0.0, "event": "signal_mux_switch_start"}
    assert timeline[-1]["event"] == "next_mux_switch_start"
    assert any(item["event"] == "additional_retained_pairs_start" for item in timeline)
    assert any(item["event"] == "all_retained_adc_pairs_complete" for item in timeline)
    assert len(timeline) < 20


def test_timeline_first_pair_consumes_one_uniform_pair_loop_interval():
    payload = adc_mux_timing_log(calculate(osr=4, repeat_count=3, use_ground_between_channels=False))
    timeline = payload["timeline"]
    settled_at = next(item["t_us"] for item in timeline if item["event"] == "signal_mux_settled")
    first_complete_at = next(
        item["t_us"] for item in timeline if item["event"] == "first_retained_adc_pair_complete"
    )

    assert first_complete_at - settled_at == pytest.approx(12.09)


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
    assert timing.t_pair_loop_total_us == pytest.approx(12.093)
    assert payload["calculated_timing"]["t_pair_loop_total_us"] == 12.09
    assert "3.8000000000000003" not in json.dumps(payload)


def test_ground_dwell_only_profile_uses_configured_dwell_constant():
    profile = {**MG24_TIMING_PROFILE, "ground_mode": "dwell_only"}
    timing = Mg24DualMuxTimingCalculator(profile=profile).calculate(
        osr=2, gain=1, repeat_count=1, use_ground_between_channels=True
    )

    assert timing.ground_phase_us == pytest.approx(59.89)


def test_custom_profile_controls_calculation_timeline_and_json_consistently():
    profile = {
        **MG24_TIMING_PROFILE,
        "mux_settle_us": 10.0,
        "mux_turn_on_us": 0.10,
        "mux_address_overhead_us": 0.50,
        "adc_start_overhead_us": 0.20,
        "pair_loop_software_overhead_us": 8.0,
        "per_mux_selection_overhead_us": 4.0,
        "block_fixed_overhead_us": 7.0,
        "ground_dummy_software_overhead_us": 12.0,
    }
    timing = Mg24DualMuxTimingCalculator(profile=profile).calculate(
        osr=4, gain=1, repeat_count=1, use_ground_between_channels=True
    )
    payload = adc_mux_timing_log(timing)

    assert timing.signal_sequence_us == pytest.approx(26.3)
    assert timing.complete_sequence_us == pytest.approx(90.8)
    assert payload["constants"]["mux_settle_us"] == 10.0
    assert payload["constants"]["pair_loop_software_overhead_us"] == 8.0
    assert payload["timeline"][-1]["t_us"] == pytest.approx(90.8)


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
            pre_sample_decay_dt_s_by_label={
                "PZT1_C": timing.decay_before_effective_sample_s(adc_input=2),
            },
        )

    assert force_calculation.call_args.kwargs["leak_dt_s"] == pytest.approx(timing.sensor_connected_s)
    assert force_calculation.call_args.kwargs["pre_sample_decay_dt_s"] == pytest.approx(
        timing.decay_before_effective_sample_s(adc_input=2)
    )


def test_force_pre_sample_decay_uses_explicit_physical_mux_mapping():
    timing = calculate(osr=4)
    snapshot = AnalysisSourceSnapshot(
        data=np.asarray([[1.0, 2.0], [1.1, 2.1]]),
        timestamps_s=np.asarray([0.0, 0.1]),
        channel_labels=["PZT1_C", "PZT2_C"],
        metadata={
            "timing": {
                "pzt_pre_sample_decay_s_by_adc_input": {
                    "1": timing.decay_before_effective_sample_s(adc_input=1),
                    "2": timing.decay_before_effective_sample_s(adc_input=2),
                },
                "pzt_adc_input_by_label": {"PZT1_C": 2, "PZT2_C": 1},
            }
        },
    )

    decay_by_label = resolve_analysis_pzt_pre_sample_decay_dt_s(snapshot, {"enabled": True})

    assert decay_by_label["PZT1_C"] == pytest.approx(5.80e-6)
    assert decay_by_label["PZT2_C"] == pytest.approx(3.80e-6)
