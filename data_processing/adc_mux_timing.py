"""Calculated ADC and external-MUX timing for supported acquisition devices.

The calculator deliberately keeps MG24 IADC hardware timing separate from the
firmware/GPIO estimates.  The latter live in the profile so measurements from a
logic analyser can refine them without changing the calculation flow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


# Estimated software overheads:
# - mux_address_overhead_us: writing MUX address GPIO pins.
# - adc_start_overhead_us: issuing/synchronizing the IADC scan command.
# - post_pair_overhead_us: FIFO polling/result retrieval, formatting and storing
#   both values, repeat/channel bookkeeping, and preparation for the next switch.
MG24_TIMING_PROFILE = {
    "adc_mode": "normal",
    "adc_clk_hz_by_gain": {
        1: 10_000_000,
        2: 5_000_000,
        3: 2_500_000,
        4: 2_500_000,
    },
    "digital_average": 1,
    "mux_settle_us": 20.0,
    "mux_turn_on_us": 0.15,
    "mux_address_overhead_us": 0.25,
    "adc_start_overhead_us": 0.15,
    "post_pair_overhead_us": 1.20,
    "iadc_input_switch_cycles": 2,
    "ground_mode": "dummy_adc_pair",
    "ground_dwell_us": 10.0,
    "warmup_us": 0.0,
}

SUPPORTED_MG24_OSR_VALUES = frozenset({2, 4, 8})


@dataclass(frozen=True)
class AdcMuxTiming:
    device_profile: str
    adc_clk_hz: int
    gain: int
    osr: int
    digital_average: int
    repeat_count: int
    use_ground_between_channels: bool
    ground_mode: str
    t_obs_us: float
    t_conv_us: float
    t_slot_us: float
    t_iadc_input_switch_us: float
    t_pair_hardware_us: float
    t_pair_total_us: float
    ground_phase_us: float
    signal_sequence_us: float
    complete_sequence_us: float
    first_sample_start_us: float
    first_sample_end_us: float
    first_sample_effective_us: float
    first_result_ready_us: float
    second_sample_start_us: float
    second_sample_end_us: float
    second_sample_effective_us: float
    second_result_ready_us: float
    first_sample_effective_from_sequence_us: float
    second_sample_effective_from_sequence_us: float
    sensor_connected_us: float
    sensor_connected_s: float
    calculated_hardware_timing: bool
    estimated_software_overhead: bool


class AdcMuxTimingCalculator:
    """Base class for device-specific ADC/MUX timing calculators."""

    calculator_name = "unknown"

    def calculate(
        self,
        *,
        osr: int,
        gain: int,
        repeat_count: int,
        use_ground_between_channels: bool,
    ) -> AdcMuxTiming:
        raise NotImplementedError


class Mg24DualMuxTimingCalculator(AdcMuxTimingCalculator):
    """Timing model for the MG24 scan-table ADC with two external MUXes."""

    calculator_name = "mg24_dual_mux_v1"

    def __init__(self, *, profile: Mapping[str, object] | None = None, device_profile: str = "Array_PPZT_PZR1"):
        self.profile = dict(MG24_TIMING_PROFILE if profile is None else profile)
        self.device_profile = device_profile

    def calculate(
        self,
        *,
        osr: int,
        gain: int,
        repeat_count: int,
        use_ground_between_channels: bool,
    ) -> AdcMuxTiming:
        osr = int(osr)
        gain = int(gain)
        repeat_count = int(repeat_count)
        if osr not in SUPPORTED_MG24_OSR_VALUES:
            raise ValueError(f"unsupported MG24 OSR: {osr}")
        clocks = self.profile["adc_clk_hz_by_gain"]
        if gain not in clocks:
            raise ValueError(f"unsupported MG24 gain: {gain}")
        if repeat_count < 1:
            raise ValueError("repeat_count must be at least one")

        adc_clk_hz = int(clocks[gain])
        adc_clk_mhz = adc_clk_hz / 1_000_000.0
        average = int(self.profile["digital_average"])
        t_obs_us = (4.0 * osr) / adc_clk_mhz
        t_conv_us = (4.0 * osr + 2.0) / adc_clk_mhz
        t_slot_us = t_conv_us * average
        t_iadc_input_switch_us = float(self.profile["iadc_input_switch_cycles"]) / adc_clk_mhz
        t_pair_hardware_us = 2.0 * t_slot_us + t_iadc_input_switch_us
        t_pair_total_us = (
            float(self.profile["adc_start_overhead_us"])
            + t_pair_hardware_us
            + float(self.profile["post_pair_overhead_us"])
        )

        adc_start_from_signal_switch_us = (
            float(self.profile["mux_address_overhead_us"])
            + float(self.profile["mux_settle_us"])
            + float(self.profile["adc_start_overhead_us"])
        )
        first_sample_start_us = adc_start_from_signal_switch_us
        first_sample_end_us = first_sample_start_us + t_obs_us
        first_sample_effective_us = first_sample_start_us + t_obs_us / 2.0
        first_result_ready_us = adc_start_from_signal_switch_us + t_slot_us
        second_sample_start_us = adc_start_from_signal_switch_us + t_slot_us + t_iadc_input_switch_us
        second_sample_end_us = second_sample_start_us + t_obs_us
        second_sample_effective_us = second_sample_start_us + t_obs_us / 2.0
        second_result_ready_us = adc_start_from_signal_switch_us + t_pair_hardware_us

        ground_mode = str(self.profile["ground_mode"])
        ground_phase_us = 0.0
        if use_ground_between_channels:
            if ground_mode == "dummy_adc_pair":
                ground_phase_us = (
                    float(self.profile["mux_address_overhead_us"])
                    + float(self.profile["mux_settle_us"])
                    + t_pair_total_us
                )
            elif ground_mode == "dwell_only":
                ground_phase_us = (
                    float(self.profile["mux_address_overhead_us"])
                    + float(self.profile["mux_settle_us"])
                    + float(self.profile["ground_dwell_us"])
                )
            else:
                raise ValueError(f"unsupported MG24 ground mode: {ground_mode}")

        signal_sequence_us = (
            float(self.profile["mux_address_overhead_us"])
            + float(self.profile["mux_settle_us"])
            + repeat_count * t_pair_total_us
        )
        sensor_connected_us = (
            max(0.0, float(self.profile["mux_settle_us"]) - float(self.profile["mux_turn_on_us"]))
            + repeat_count * t_pair_total_us
        )
        return AdcMuxTiming(
            device_profile=self.device_profile,
            adc_clk_hz=adc_clk_hz,
            gain=gain,
            osr=osr,
            digital_average=average,
            repeat_count=repeat_count,
            use_ground_between_channels=bool(use_ground_between_channels),
            ground_mode=ground_mode,
            t_obs_us=t_obs_us,
            t_conv_us=t_conv_us,
            t_slot_us=t_slot_us,
            t_iadc_input_switch_us=t_iadc_input_switch_us,
            t_pair_hardware_us=t_pair_hardware_us,
            t_pair_total_us=t_pair_total_us,
            ground_phase_us=ground_phase_us,
            signal_sequence_us=signal_sequence_us,
            complete_sequence_us=ground_phase_us + signal_sequence_us,
            first_sample_start_us=first_sample_start_us,
            first_sample_end_us=first_sample_end_us,
            first_sample_effective_us=first_sample_effective_us,
            first_result_ready_us=first_result_ready_us,
            second_sample_start_us=second_sample_start_us,
            second_sample_end_us=second_sample_end_us,
            second_sample_effective_us=second_sample_effective_us,
            second_result_ready_us=second_result_ready_us,
            first_sample_effective_from_sequence_us=ground_phase_us + first_sample_effective_us,
            second_sample_effective_from_sequence_us=ground_phase_us + second_sample_effective_us,
            sensor_connected_us=sensor_connected_us,
            sensor_connected_s=sensor_connected_us * 1e-6,
            calculated_hardware_timing=True,
            estimated_software_overhead=True,
        )


# The first key is the requested MG24 identifier.  The second is the established
# identifier emitted by the current host/firmware pair, retained as an alias.
TIMING_CALCULATORS = {
    "Array_PPZT_PZR1": Mg24DualMuxTimingCalculator,
    "Array_PZT_PZR1": Mg24DualMuxTimingCalculator,
}


def get_adc_mux_timing_calculator(mcu_id: str | None) -> AdcMuxTimingCalculator | None:
    """Return the registered calculator for an MCU identifier, if any."""
    normalized_id = (mcu_id or "").strip()
    for prefix, calculator_type in TIMING_CALCULATORS.items():
        if normalized_id == prefix or normalized_id.startswith(f"{prefix}."):
            return calculator_type()
    return None


def calculate_adc_mux_timing_for_acquisition(
    mcu_id: str | None,
    config: Mapping[str, object],
) -> AdcMuxTiming | None:
    """Calculate timing from the current acquisition configuration when supported."""
    calculator = get_adc_mux_timing_calculator(mcu_id)
    if calculator is None:
        return None
    return calculator.calculate(
        osr=int(config.get("osr", 2)),
        gain=int(config.get("gain", 1)),
        repeat_count=int(config.get("repeat", config.get("repeat_count", 1))),
        use_ground_between_channels=bool(
            config.get("use_ground", config.get("use_ground_between_channels", False))
        ),
    )


def round_timing_json_values(value):
    """Round floats only while preparing the human-readable timing JSON payload."""
    if isinstance(value, float):
        rounded = round(value, 2)
        return 0.0 if rounded == -0.0 else rounded
    if isinstance(value, dict):
        return {key: round_timing_json_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [round_timing_json_values(item) for item in value]
    return value


def _build_timeline(timing: AdcMuxTiming) -> list[dict[str, float | str]]:
    """Build a compact chronological view from the calculation's shared timings."""
    profile = MG24_TIMING_PROFILE
    address_overhead_us = float(profile["mux_address_overhead_us"])
    mux_settle_us = float(profile["mux_settle_us"])
    mux_turn_on_us = float(profile["mux_turn_on_us"])
    adc_start_overhead_us = float(profile["adc_start_overhead_us"])
    post_pair_overhead_us = float(profile["post_pair_overhead_us"])

    timeline: list[dict[str, float | str]] = []
    t = 0.0
    if timing.use_ground_between_channels:
        timeline.append({"t_us": t, "event": "ground_mux_switch_start"})
        t += address_overhead_us
        timeline.append({"t_us": t, "event": "ground_mux_address_set"})
        t += mux_settle_us
        timeline.append({"t_us": t, "event": "ground_mux_settled"})
        if timing.ground_mode == "dummy_adc_pair":
            t += adc_start_overhead_us
            timeline.append({"t_us": t, "event": "ground_dummy_adc_pair_start"})
            t += timing.t_pair_hardware_us
            timeline.append({"t_us": t, "event": "ground_dummy_adc_pair_hardware_complete"})
            t += post_pair_overhead_us
        elif timing.ground_mode == "dwell_only":
            t += float(profile["ground_dwell_us"])
        # ``ground_phase_us`` is authoritative for any future ground mode.
        t = timing.ground_phase_us

    signal_start_us = t
    timeline.append({"t_us": t, "event": "signal_mux_switch_start"})
    t += address_overhead_us
    timeline.append({"t_us": t, "event": "signal_mux_address_set"})
    timeline.append({"t_us": t + mux_turn_on_us, "event": "sensor_connected_to_mux_output"})
    t = signal_start_us + address_overhead_us + mux_settle_us
    timeline.append({"t_us": t, "event": "signal_mux_settled"})
    t += adc_start_overhead_us
    timeline.append({"t_us": t, "event": "first_input_observation_start"})
    timeline.append({"t_us": t + timing.t_obs_us / 2.0, "event": "first_input_effective_sample"})
    timeline.append({"t_us": t + timing.t_obs_us, "event": "first_input_observation_end"})
    timeline.append({"t_us": t + timing.t_slot_us, "event": "first_input_result_ready"})
    second_start_us = t + timing.t_slot_us + timing.t_iadc_input_switch_us
    timeline.append({"t_us": second_start_us, "event": "second_input_observation_start"})
    timeline.append({"t_us": second_start_us + timing.t_obs_us / 2.0, "event": "second_input_effective_sample"})
    timeline.append({"t_us": second_start_us + timing.t_obs_us, "event": "second_input_observation_end"})
    first_pair_result_us = t + timing.t_pair_hardware_us
    timeline.append({"t_us": first_pair_result_us, "event": "second_input_result_ready"})

    if timing.repeat_count > 1:
        timeline.append({"t_us": first_pair_result_us, "event": "first_retained_adc_pair_complete"})
        timeline.append({"t_us": first_pair_result_us, "event": "additional_retained_pairs_start"})
        timeline.append({
            "t_us": first_pair_result_us + (timing.repeat_count - 1) * timing.t_pair_total_us,
            "event": "all_retained_adc_pairs_complete",
        })

    timeline.append({"t_us": timing.complete_sequence_us, "event": "next_mux_switch_start"})
    return timeline


def adc_mux_timing_log(timing: AdcMuxTiming | None) -> dict | None:
    """Build the compact, JSON-safe acquisition metadata representation."""
    if timing is None:
        return None
    # t_overhead_per_mux_selection_us includes MUX address GPIO-write overhead, IADC
    # start-command overhead, and FIFO/result formatting/storage/loop overhead.
    # It does not include MUX settling, IADC conversion hardware, or MUX turn-on.
    t_pair_overhead_us = (
        float(MG24_TIMING_PROFILE["adc_start_overhead_us"])
        + float(MG24_TIMING_PROFILE["post_pair_overhead_us"])
    )
    t_overhead_per_mux_selection_us = (
        float(MG24_TIMING_PROFILE["mux_address_overhead_us"])
        + t_pair_overhead_us
    )
    payload = {
        "adc": Mg24DualMuxTimingCalculator.calculator_name,
        "device_profile": timing.device_profile,
        "inputs": {
            "gain": timing.gain,
            "osr": timing.osr,
            "digital_average": timing.digital_average,
            "repeat_count": timing.repeat_count,
            "use_ground_between_channels": timing.use_ground_between_channels,
            "ground_mode": timing.ground_mode,
        },
        "constants": {
            "adc_clk_hz": timing.adc_clk_hz,
            "mux_settle_us": MG24_TIMING_PROFILE["mux_settle_us"],
            "mux_turn_on_us": MG24_TIMING_PROFILE["mux_turn_on_us"],
            "mux_address_overhead_us": MG24_TIMING_PROFILE["mux_address_overhead_us"],
            "adc_start_overhead_us": MG24_TIMING_PROFILE["adc_start_overhead_us"],
            "post_pair_overhead_us": MG24_TIMING_PROFILE["post_pair_overhead_us"],
            "iadc_input_switch_cycles": MG24_TIMING_PROFILE["iadc_input_switch_cycles"],
        },
        "calculated_timing": {
            "t_obs_us": timing.t_obs_us,
            "t_conv_us": timing.t_conv_us,
            "t_iadc_input_switch_us": timing.t_iadc_input_switch_us,
            "t_pair_hardware_us": timing.t_pair_hardware_us,
            "t_pair_overhead_us": t_pair_overhead_us,
            "t_pair_total_us": timing.t_pair_total_us,
            "t_overhead_per_mux_selection_us": t_overhead_per_mux_selection_us,
            "t_ground_phase_us": timing.ground_phase_us,
            "t_signal_sequence_us": timing.signal_sequence_us,
            "t_complete_sequence_us": timing.complete_sequence_us,
            "t_connected_us": timing.sensor_connected_us,
        },
        "timeline": _build_timeline(timing),
    }
    return round_timing_json_values(payload)
