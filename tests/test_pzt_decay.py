import json
import math

import pytest

from data_processing.adc_mux_timing import Mg24DualMuxTimingCalculator
from data_processing.pzt_decay import (
    PztDecayAnalyzer,
    PztDecaySample,
    PztDecaySettings,
    PztDecaySignalMapping,
    PztDecayState,
    PztDecayTimestampBasis,
    PztDecayTimingContext,
    resolve_pzt_decay_signal_mapping,
)
from file_operations.pzt_decay_exporter import PztDecayExporter, SAMPLE_COLUMNS


def _timing():
    return Mg24DualMuxTimingCalculator().calculate(
        osr=4, gain=1, repeat_count=1, use_ground_between_channels=True
    )


def _mapping():
    return PztDecaySignalMapping("PZT1_C", "PZT1", 1, 4, "S4", 1, "PZT5_C")


def _run_decay(*, values, dt=0.005, settings=None):
    analyzer = PztDecayAnalyzer(
        _mapping(), PztDecayTimingContext.from_adc_mux_timing(_timing(), 1), settings or PztDecaySettings(
            baseline_duration_s=0.1, baseline_min_samples=20, stable_target_duration_s=0.05,
            minimum_fit_samples=20, maximum_recording_duration_s=10,
        ),
    )
    analyzer.begin()
    timestamp = 0.0
    for _ in range(25):
        analyzer.add_sample(1.65, timestamp); timestamp += dt
    for _ in range(20):
        analyzer.add_sample(2.65, timestamp); timestamp += dt
    for value in values:
        analyzer.add_sample(value, timestamp); timestamp += dt
        if analyzer.state in (PztDecayState.COMPLETE, PztDecayState.ERROR):
            break
    return analyzer


def test_mapping_uses_active_mux_map_and_finds_companion():
    mapping = resolve_pzt_decay_signal_mapping({
        "channel_sensor_map": ["T", "R", "C", "L", "B"],
        "mux_mapping": {
            "PZT1": {"mux": 1, "channels": [2, 3, 4, 5, 6]},
            "PZT5": {"mux": 2, "channels": [2, 3, 4, 5, 6]},
        },
    }, "PZT1_C")
    assert mapping.mux_address == 4
    assert mapping.physical_adc_input == 1
    assert mapping.mux_pin_label == "S4"
    assert mapping.companion_signal == "PZT5_C"


def test_default_vmid_operation_uses_1000_samples_and_fast_decay_defaults():
    settings = PztDecaySettings()
    assert settings.baseline_min_samples == 1000
    assert settings.minimum_fit_samples == 3
    assert settings.target_timeout_s == pytest.approx(60.0)
    assert settings.maximum_recording_duration_s == pytest.approx(60.0)
    assert settings.end_threshold_normalized == pytest.approx(0.02)
    assert settings.fit_upper_normalized == pytest.approx(0.85)
    assert settings.fit_lower_normalized == pytest.approx(0.15)
    assert settings.final_baseline_min_samples == 10

    analyzer = PztDecayAnalyzer(_mapping(), PztDecayTimingContext.from_adc_mux_timing(_timing(), 1), settings)
    analyzer.begin()
    for index in range(999):
        analyzer.add_sample(1.65, index * 1e-5)
    assert analyzer.state == PztDecayState.BASELINE
    analyzer.add_sample(1.65, 999e-5)
    assert analyzer.state == PztDecayState.WAITING_FOR_TARGET
    assert analyzer.vmid_v == pytest.approx(1.65)
    assert analyzer.target_voltage_v == pytest.approx(2.65)


def test_baseline_can_discard_settling_samples_before_calculating_vmid():
    settings = PztDecaySettings(
        baseline_duration_s=0.0,
        baseline_min_samples=3,
        baseline_discard_initial_samples=2,
    )
    analyzer = PztDecayAnalyzer(
        _mapping(), PztDecayTimingContext.from_adc_mux_timing(_timing(), 1), settings
    )
    analyzer.begin()
    for index, voltage in enumerate((0.2, 0.4, 1.65, 1.65, 1.65)):
        analyzer.add_sample(voltage, index * 1e-3)

    assert analyzer.state == PztDecayState.WAITING_FOR_TARGET
    assert analyzer.baseline_values == [1.65, 1.65, 1.65]
    assert analyzer.vmid_v == pytest.approx(1.65)


def test_short_vmid_burst_can_skip_slow_baseline_slope_validation():
    settings = PztDecaySettings(
        baseline_duration_s=0.0,
        baseline_min_samples=3,
        baseline_discard_initial_samples=2,
        baseline_validate_stability=False,
    )
    analyzer = PztDecayAnalyzer(
        _mapping(), PztDecayTimingContext.from_adc_mux_timing(_timing(), 1), settings
    )
    analyzer.begin()
    for index, voltage in enumerate((0.2, 0.4, 1.55, 1.62, 1.65)):
        analyzer.add_sample(voltage, index * 1e-3)

    assert analyzer.state == PztDecayState.WAITING_FOR_TARGET
    assert analyzer.vmid_v == pytest.approx(1.62)


def test_cached_vmid_starts_at_target_wait_without_recollecting_baseline():
    analyzer = PztDecayAnalyzer(_mapping(), PztDecayTimingContext.from_adc_mux_timing(_timing(), 1), PztDecaySettings())
    analyzer.begin_with_vmid(1.67, 0.001)
    assert analyzer.state == PztDecayState.WAITING_FOR_TARGET
    assert analyzer.target_voltage_v == pytest.approx(2.67)
    analyzer.add_sample(1.67, 0.0)
    assert analyzer.state == PztDecayState.WAITING_FOR_TARGET
    assert not analyzer.baseline_values


def test_target_and_decay_timeouts_have_distinct_messages():
    timing = PztDecayTimingContext.from_adc_mux_timing(_timing(), 1)
    target_timeout = PztDecayAnalyzer(_mapping(), timing, PztDecaySettings(target_timeout_s=0.01, maximum_recording_duration_s=1.0))
    target_timeout.begin_with_vmid(1.65)
    target_timeout.add_sample(1.65, 0.0); target_timeout.add_sample(1.65, 0.02)
    assert target_timeout.error_message == "Could not find a signal"

    decay_timeout = PztDecayAnalyzer(_mapping(), timing, PztDecaySettings(target_timeout_s=1.0, maximum_recording_duration_s=0.01))
    decay_timeout.begin_with_vmid(1.65)
    decay_timeout.add_sample(2.65, 0.0); decay_timeout.add_sample(2.65, 0.02)
    assert decay_timeout.error_message == "Could not find signal decay"


def test_fit_uses_only_the_final_descending_decay_not_earlier_jangling_dips():
    settings = PztDecaySettings(
        baseline_duration_s=0.1, baseline_min_samples=20, stable_target_duration_s=0.05,
        minimum_fit_samples=3, maximum_recording_duration_s=10.0,
    )
    analyzer = PztDecayAnalyzer(_mapping(), PztDecayTimingContext.from_adc_mux_timing(_timing(), 1), settings)
    analyzer.begin(); timestamp = 0.0
    for _ in range(25):
        analyzer.add_sample(1.65, timestamp); timestamp += 0.005
    for _ in range(20):
        analyzer.add_sample(2.65, timestamp); timestamp += 0.005

    # The early low samples recover to the original target; the final descent
    # is the only portion valid for an exponential decay fit.
    values = [2.40, 2.30, 2.65, 2.35, *([2.65] * 5), 2.55, 2.40, 2.25, 2.05, 1.85,
              1.70, 1.669, 1.660, 1.659, 1.660, 1.659, 1.660, 1.659, 1.660, 1.659,
              1.660, 1.659, 1.660, 1.659]
    for value in values:
        analyzer.add_sample(value, timestamp); timestamp += 0.005
        if analyzer.state in (PztDecayState.COMPLETE, PztDecayState.ERROR):
            break

    assert analyzer.state == PztDecayState.COMPLETE
    fit_times = [sample.timestamp_s for sample in analyzer.samples if sample.fit_included]
    last_target_time = max(sample.timestamp_s for sample in analyzer.samples if sample.voltage_v >= 2.64)
    assert fit_times and min(fit_times) >= last_target_time
    assert any(sample.rejection_reason == "before final selected decay event" for sample in analyzer.samples)


def test_late_recharge_starts_a_new_final_descending_tail_instead_of_failing_the_run():
    values = [1.65 + math.exp(-(index * 0.005) / 0.3) for index in range(500)]
    values[80] += 0.15  # A physical/MUX transition bump after the upper crossing.
    analyzer = _run_decay(values=values, settings=PztDecaySettings(
        baseline_duration_s=0.1, baseline_min_samples=20, stable_target_duration_s=0.05,
        minimum_fit_samples=3, maximum_recording_duration_s=10,
    ))
    assert analyzer.state == PztDecayState.COMPLETE
    assert analyzer.result is not None
    assert "recharging portion excluded before final descending decay" in analyzer.result.warnings


def test_sparse_decay_expands_only_to_the_recording_threshold_when_fit_window_is_skipped():
    settings = PztDecaySettings(
        baseline_duration_s=0.1, baseline_min_samples=20, stable_target_duration_s=0.05,
        minimum_fit_samples=3, maximum_recording_duration_s=10,
    )
    analyzer = _run_decay(values=[2.40, 1.80, 1.68, *([1.66] * 12)], settings=settings)
    assert analyzer.state == PztDecayState.COMPLETE
    assert analyzer.result is not None
    assert analyzer.result.fit_samples >= 3
    assert any("expanded lower bound" in warning for warning in analyzer.result.warnings)


def test_timing_context_selects_channel_specific_pre_and_post_times():
    timing = _timing()
    ch1 = PztDecayTimingContext.from_adc_mux_timing(timing, 1)
    ch2 = PztDecayTimingContext.from_adc_mux_timing(timing, 2)
    assert ch1.pre_sample_decay_s == pytest.approx(timing.t_decay_before_effective_sample_ch1_s)
    assert ch2.post_sample_connected_s == pytest.approx(timing.t_connected_after_effective_sample_ch2_s)
    assert ch1.effective_sample_offset_s == pytest.approx(timing.first_sample_effective_from_sequence_us * 1e-6)
    assert ch2.effective_sample_offset_s == pytest.approx(timing.second_sample_effective_from_sequence_us * 1e-6)
    assert ch1.pre_sample_decay_s + ch1.post_sample_connected_s == pytest.approx(timing.sensor_connected_s)


def test_wall_clock_fit_recovers_tau_and_calculates_curve_for_all_post_release_samples():
    tau = 0.3
    analyzer = _run_decay(values=[1.65 + math.exp(-(index * 0.005) / tau) for index in range(500)])
    assert analyzer.state == PztDecayState.COMPLETE
    assert analyzer.result.tau_wall_s == pytest.approx(tau, rel=0.01)
    assert analyzer.result.r_squared > 0.999
    trend_samples = [sample for sample in analyzer.samples if sample.calculated_voltage_v is not None]
    assert trend_samples
    assert min(sample.timestamp_s for sample in trend_samples) >= analyzer.release_time_s
    first_fit = next(sample for sample in analyzer.samples if sample.fit_included)
    assert analyzer.result.fit_wall_time_origin_s == pytest.approx(0.0)
    assert analyzer.result.fit_connected_time_origin_s == pytest.approx(0.0)
    first_event = min(trend_samples, key=lambda sample: sample.relative_time_s)
    assert first_event.calculated_voltage_v == pytest.approx(
        analyzer.result.vmid_v + analyzer.result.fitted_amplitude_v
    )


def test_connected_time_fit_and_capacitance_use_connected_exposure_not_wall_time():
    timing = _timing(); tau_on = 0.002; resistance = 1_000_000.0
    settings = PztDecaySettings(
        baseline_duration_s=0.1, baseline_min_samples=20, stable_target_duration_s=0.05,
        minimum_fit_samples=20, maximum_recording_duration_s=10,
        capacitance_estimation_enabled=True, connected_equivalent_resistance_ohm=resistance,
    )
    analyzer = _run_decay(
        values=[1.65 + math.exp(-(index * timing.sensor_connected_s) / tau_on) for index in range(1000)],
        settings=settings,
    )
    assert analyzer.state == PztDecayState.COMPLETE
    assert analyzer.result.tau_on_estimated_s == pytest.approx(tau_on, rel=0.02)
    assert analyzer.result.capacitance_estimated_f == pytest.approx(tau_on / resistance, rel=0.02)


def test_repeat_burst_uses_pair_time_inside_the_burst_and_connection_time_between_bursts():
    timing = Mg24DualMuxTimingCalculator().calculate(
        osr=4, gain=1, repeat_count=30, use_ground_between_channels=True
    )
    context = PztDecayTimingContext.from_adc_mux_timing(timing, 1)
    assert context.observation_offset_s(1) - context.observation_offset_s(0) == pytest.approx(context.pair_interval_s)
    assert context.connected_exposure_between(0, 1) == pytest.approx(context.pair_interval_s)
    assert context.connected_exposure_between(29, 0) == pytest.approx(
        timing.connected_after_effective_sample_s(adc_input=1, repeat_index=29)
        + timing.decay_before_effective_sample_s(adc_input=1, repeat_index=0)
    )


@pytest.mark.parametrize("repeat_count", [1, 2, 5, 10])
@pytest.mark.parametrize("adc_input", [1, 2])
def test_burst_connected_exposure_accounts_for_one_complete_mux_selection(repeat_count, adc_input):
    timing = Mg24DualMuxTimingCalculator().calculate(
        osr=4, gain=1, repeat_count=repeat_count, use_ground_between_channels=True,
    )
    context = PztDecayTimingContext.from_adc_mux_timing(timing, adc_input)
    within = (repeat_count - 1) * context.repeat_pair_interval_s
    boundary = context.connected_exposure_between(repeat_count - 1, 0)
    assert within + boundary == pytest.approx(timing.sensor_connected_s)


def test_analyzer_derives_burst_exposure_and_expands_burst_start_timestamps():
    timing = Mg24DualMuxTimingCalculator().calculate(
        osr=4, gain=1, repeat_count=3, use_ground_between_channels=True,
    )
    context = PztDecayTimingContext.from_adc_mux_timing(timing, 2)
    analyzer = PztDecayAnalyzer(_mapping(), context)
    analyzer.begin()
    for burst in range(2):
        for repeat in range(3):
            analyzer.add_sample(
                1.65, burst * 1e-3, burst_index=burst, repeat_index=repeat,
                timestamp_basis=PztDecayTimestampBasis.BURST_START,
            )
    samples = analyzer.samples
    assert samples[1].timestamp_s - samples[0].timestamp_s == pytest.approx(context.repeat_pair_interval_s)
    assert samples[1].connected_exposure_since_previous_s == pytest.approx(context.repeat_pair_interval_s)
    assert samples[3].connected_exposure_since_previous_s == pytest.approx(
        context.connected_exposure_between(2, 0)
    )


def test_analyzer_marks_missing_or_reordered_burst_sample_invalid_without_inventing_exposure():
    timing = Mg24DualMuxTimingCalculator().calculate(
        osr=4, gain=1, repeat_count=3, use_ground_between_channels=True,
    )
    analyzer = PztDecayAnalyzer(_mapping(), PztDecayTimingContext.from_adc_mux_timing(timing, 1))
    analyzer.begin()
    analyzer.add_sample(1.65, 0.0, burst_index=0, repeat_index=0)
    analyzer.add_sample(1.65, 1e-6, burst_index=0, repeat_index=2)
    invalid = analyzer.samples[-1]
    assert not invalid.timing_valid
    assert invalid.connected_exposure_since_previous_s == 0.0
    assert invalid.rejection_reason == "missing or out-of-order burst sample"


def test_export_contains_required_timing_and_fit_columns(tmp_path):
    analyzer = _run_decay(values=[1.65 + math.exp(-(index * .005) / .3) for index in range(500)])
    paths = PztDecayExporter().export(tmp_path, analyzer.result, analyzer.samples)
    assert paths["samples_csv"].read_text(encoding="utf-8").splitlines()[0].split(",") == list(SAMPLE_COLUMNS)
    payload = json.loads(paths["result_json"].read_text(encoding="utf-8"))
    assert payload["timing"]["sensor_connected_s"] > 0
    assert payload["fit"]["rmse_voltage_v"] is not None
    assert payload["signal"]["physical_adc_input"] == 1


def test_sample_export_omits_target_wait_and_keeps_requested_decay_context():
    samples = [
        PztDecaySample(index, float(index), 1.65, "waiting_for_target")
        for index in range(20)
    ]
    samples.extend(
        PztDecaySample(index, float(index), 2.65, "recording_decay",
                       rejection_reason="before final descending decay trend")
        for index in range(20, 35)
    )
    samples.extend([
        PztDecaySample(35, 35.0, 2.45, "recording_decay", rejection_reason="outside normalized fit window"),
        PztDecaySample(36, 36.0, 2.25, "recording_decay", fit_included=True),
        PztDecaySample(37, 37.0, 2.00, "recording_decay", fit_included=True),
        PztDecaySample(38, 38.0, 1.80, "recording_decay", rejection_reason="robust connected-exposure fit outlier"),
        PztDecaySample(39, 39.0, 1.67, "recording_decay", rejection_reason="outside normalized fit window"),
    ])
    samples.extend(PztDecaySample(index, float(index), 1.66, "recording_decay") for index in range(40, 55))

    selected = PztDecayExporter.select_samples_for_csv(samples)
    selected_indices = [sample.sample_index for sample in selected]

    assert selected_indices == list(range(25, 49))
    assert 0 not in selected_indices
