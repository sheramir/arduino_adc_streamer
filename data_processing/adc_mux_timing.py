"""Calculated ADC and external-MUX timing for supported acquisition devices.

MG24 IADC durations are calculated from ADC clock, OSR, gain, and digital
averaging. Signal-pair timing constants are calibrated from repeat-count and
multi-channel measurements. The discarded dummy-ground pair has a separate
empirical software overhead because it does not perform the retained-data
formatting and storage used for a signal pair.

The total sensor-connected interval models PZT charge leakage while a selected
PZT sensor is connected through the external MUX; fixed block overhead is
intentionally excluded. Channel-specific pre-sample decay starts when the
sensor physically connects to the MUX output and ends at the center of that
ADC input's observation window. It corrects newly accumulated PZT charge
before force extraction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


# Empirically calibrated for the current MG24 firmware, Arduino core,
# compiler, ADG1206 hardware, Normal IADC mode, gain 1, 10 MHz ADC clock,
# AVG1, and 20 us MUX settling. The pair software overhead includes the ADC
# start command, FIFO polling/retrieval, result handling/storage, and repeat
# loop work. Per-selection and fixed-block costs are intentionally separate.
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
    # Used only to place the ADC-start event in the timeline. It is already
    # included in pair_software_overhead_us and must not be added twice.
    "adc_start_overhead_us": 0.15,
    "pair_software_overhead_us": 10.11,
    "per_mux_selection_overhead_us": 6.64,
    "block_fixed_overhead_us": 9.23,
    "ground_dummy_software_overhead_us": 14.25,
    "iadc_input_switch_cycles": 2,
    "ground_mode": "dummy_adc_pair",
    "ground_dwell_us": 10.0,
    "warmup_us": 0.0,
    "calibration": {
        "version": "2026-07-24",
        "method": (
            "repeat-count linear fit, 15-selection no-ground measurement, "
            "and matched 15-selection dummy-ground measurement"
        ),
        "calibrated_osr": 4,
        "calibrated_gain": 1,
        "calibrated_adc_clk_hz": 10_000_000,
        "calibrated_mux_settle_us": 20.0,
        "note": (
            "Signal and dummy-ground firmware overheads are empirical estimates "
            "for the current MG24 firmware, Arduino core, compiler, and hardware."
        ),
    },
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
    mux_settle_us: float
    mux_turn_on_us: float
    mux_address_overhead_us: float
    adc_start_overhead_us: float
    t_pair_software_overhead_us: float
    t_per_mux_selection_overhead_us: float
    t_block_fixed_overhead_us: float
    t_ground_dummy_software_overhead_us: float
    iadc_input_switch_cycles: int
    ground_dwell_us: float
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
    # Scalar pre/post fields describe the first retained pair. Use the helper
    # methods below for later pairs when repeat_count is greater than one.
    t_decay_before_effective_sample_ch1_us: float
    t_decay_before_effective_sample_ch1_s: float
    t_decay_before_effective_sample_ch2_us: float
    t_decay_before_effective_sample_ch2_s: float
    t_connected_after_effective_sample_ch1_us: float
    t_connected_after_effective_sample_ch1_s: float
    t_connected_after_effective_sample_ch2_us: float
    t_connected_after_effective_sample_ch2_s: float
    calculated_hardware_timing: bool
    estimated_software_overhead: bool

    def decay_before_effective_sample_s(
        self, *, adc_input: int, repeat_index: int = 0
    ) -> float:
        """Return physical connection-to-effective-sample decay for one pair."""
        if adc_input not in (1, 2):
            raise ValueError("adc_input must be 1 or 2")
        if repeat_index < 0 or repeat_index >= self.repeat_count:
            raise ValueError(
                f"repeat_index must be between 0 and {self.repeat_count - 1}"
            )
        base_us = (
            self.t_decay_before_effective_sample_ch1_us
            if adc_input == 1
            else self.t_decay_before_effective_sample_ch2_us
        )
        return (base_us + repeat_index * self.t_pair_total_us) * 1e-6

    def connected_after_effective_sample_s(
        self, *, adc_input: int, repeat_index: int = 0
    ) -> float:
        """Return effective-sample-to-disconnection time for one retained pair."""
        pre_sample_s = self.decay_before_effective_sample_s(
            adc_input=adc_input, repeat_index=repeat_index
        )
        remaining_s = self.sensor_connected_s - pre_sample_s
        if remaining_s < 0.0:
            raise ValueError("effective sample occurs after sensor disconnection")
        return remaining_s


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

    calculator_name = "mg24_dual_mux_v3"

    def __init__(
        self,
        *,
        profile: Mapping[str, object] | None = None,
        device_profile: str = "Array_PZT_PZR1",
    ):
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
        mux_settle_us = float(self.profile["mux_settle_us"])
        mux_turn_on_us = float(self.profile["mux_turn_on_us"])
        mux_address_overhead_us = float(self.profile["mux_address_overhead_us"])
        adc_start_overhead_us = float(self.profile["adc_start_overhead_us"])
        pair_software_overhead_us = float(self.profile["pair_software_overhead_us"])
        per_mux_selection_overhead_us = float(self.profile["per_mux_selection_overhead_us"])
        block_fixed_overhead_us = float(self.profile["block_fixed_overhead_us"])
        ground_dummy_software_overhead_us = float(
            self.profile["ground_dummy_software_overhead_us"]
        )
        iadc_input_switch_cycles = int(self.profile["iadc_input_switch_cycles"])
        ground_dwell_us = float(self.profile["ground_dwell_us"])

        t_obs_us = (4.0 * osr) / adc_clk_mhz
        t_conv_us = (4.0 * osr + 2.0) / adc_clk_mhz
        t_slot_us = t_conv_us * average
        t_iadc_input_switch_us = iadc_input_switch_cycles / adc_clk_mhz
        t_pair_hardware_us = 2.0 * t_slot_us + t_iadc_input_switch_us
        t_pair_total_us = t_pair_hardware_us + pair_software_overhead_us

        adc_start_from_signal_switch_us = (
            mux_address_overhead_us + mux_settle_us + adc_start_overhead_us
        )
        first_sample_start_us = adc_start_from_signal_switch_us
        first_sample_end_us = first_sample_start_us + t_obs_us
        first_sample_effective_us = first_sample_start_us + t_obs_us / 2.0
        first_result_ready_us = adc_start_from_signal_switch_us + t_slot_us
        second_sample_start_us = (
            adc_start_from_signal_switch_us + t_slot_us + t_iadc_input_switch_us
        )
        second_sample_end_us = second_sample_start_us + t_obs_us
        second_sample_effective_us = second_sample_start_us + t_obs_us / 2.0
        second_result_ready_us = adc_start_from_signal_switch_us + t_pair_hardware_us

        sensor_connection_start_from_signal_switch_us = (
            mux_address_overhead_us + mux_turn_on_us
        )
        t_decay_before_effective_sample_ch1_us = (
            first_sample_effective_us - sensor_connection_start_from_signal_switch_us
        )
        t_decay_before_effective_sample_ch2_us = (
            second_sample_effective_us - sensor_connection_start_from_signal_switch_us
        )

        ground_mode = str(self.profile["ground_mode"])
        ground_phase_us = 0.0
        if use_ground_between_channels:
            if ground_mode == "dummy_adc_pair":
                ground_phase_us = (
                    mux_address_overhead_us
                    + mux_settle_us
                    + t_pair_hardware_us
                    + ground_dummy_software_overhead_us
                )
            elif ground_mode == "dwell_only":
                ground_phase_us = (
                    mux_address_overhead_us
                    + mux_settle_us
                    + ground_dwell_us
                    + per_mux_selection_overhead_us
                )
            else:
                raise ValueError(f"unsupported MG24 ground mode: {ground_mode}")

        signal_sequence_us = (
            mux_address_overhead_us
            + mux_settle_us
            + per_mux_selection_overhead_us
            + repeat_count * t_pair_total_us
        )
        sensor_connected_us = (
            max(0.0, mux_settle_us - mux_turn_on_us)
            + per_mux_selection_overhead_us
            + repeat_count * t_pair_total_us
        )
        t_connected_after_effective_sample_ch1_us = (
            sensor_connected_us - t_decay_before_effective_sample_ch1_us
        )
        t_connected_after_effective_sample_ch2_us = (
            sensor_connected_us - t_decay_before_effective_sample_ch2_us
        )
        if t_connected_after_effective_sample_ch1_us < 0.0:
            raise ValueError("channel-1 effective sample occurs after sensor disconnection")
        if t_connected_after_effective_sample_ch2_us < 0.0:
            raise ValueError("channel-2 effective sample occurs after sensor disconnection")
        return AdcMuxTiming(
            device_profile=self.device_profile,
            adc_clk_hz=adc_clk_hz,
            gain=gain,
            osr=osr,
            digital_average=average,
            repeat_count=repeat_count,
            use_ground_between_channels=bool(use_ground_between_channels),
            ground_mode=ground_mode,
            mux_settle_us=mux_settle_us,
            mux_turn_on_us=mux_turn_on_us,
            mux_address_overhead_us=mux_address_overhead_us,
            adc_start_overhead_us=adc_start_overhead_us,
            t_pair_software_overhead_us=pair_software_overhead_us,
            t_per_mux_selection_overhead_us=per_mux_selection_overhead_us,
            t_block_fixed_overhead_us=block_fixed_overhead_us,
            t_ground_dummy_software_overhead_us=ground_dummy_software_overhead_us,
            iadc_input_switch_cycles=iadc_input_switch_cycles,
            ground_dwell_us=ground_dwell_us,
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
            t_decay_before_effective_sample_ch1_us=t_decay_before_effective_sample_ch1_us,
            t_decay_before_effective_sample_ch1_s=t_decay_before_effective_sample_ch1_us * 1e-6,
            t_decay_before_effective_sample_ch2_us=t_decay_before_effective_sample_ch2_us,
            t_decay_before_effective_sample_ch2_s=t_decay_before_effective_sample_ch2_us * 1e-6,
            t_connected_after_effective_sample_ch1_us=t_connected_after_effective_sample_ch1_us,
            t_connected_after_effective_sample_ch1_s=t_connected_after_effective_sample_ch1_us * 1e-6,
            t_connected_after_effective_sample_ch2_us=t_connected_after_effective_sample_ch2_us,
            t_connected_after_effective_sample_ch2_s=t_connected_after_effective_sample_ch2_us * 1e-6,
            calculated_hardware_timing=True,
            estimated_software_overhead=True,
        )


# ``Array_PZT_PZR1`` is the identifier emitted by the current firmware. The
# doubled-P spelling appeared in an earlier timing specification, so retain it
# as an input-only compatibility alias; logs always use the canonical profile.
TIMING_CALCULATORS = {
    "Array_PZT_PZR1": Mg24DualMuxTimingCalculator,
    "Array_PPZT_PZR1": Mg24DualMuxTimingCalculator,
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


def _append_pair_timeline(
    timeline: list[dict[str, float | str]],
    *,
    t: float,
    timing: AdcMuxTiming,
    first_pair: bool,
    ground: bool = False,
) -> tuple[float, float]:
    """Append one pair timeline, returning pair-software and total completion times."""
    pair_post_hardware_overhead_us = (
        timing.t_pair_software_overhead_us - timing.adc_start_overhead_us
    )
    if pair_post_hardware_overhead_us < 0.0:
        raise ValueError("pair software overhead must include ADC-start overhead")

    if first_pair:
        timeline.append({"t_us": t, "event": "first_input_observation_start"})
        timeline.append({"t_us": t + timing.t_obs_us / 2.0, "event": "first_input_effective_sample"})
        timeline.append({"t_us": t + timing.t_obs_us, "event": "first_input_observation_end"})
        timeline.append({"t_us": t + timing.t_slot_us, "event": "first_input_result_ready"})
        second_start_us = t + timing.t_slot_us + timing.t_iadc_input_switch_us
        timeline.append({"t_us": second_start_us, "event": "second_input_observation_start"})
        timeline.append({"t_us": second_start_us + timing.t_obs_us / 2.0, "event": "second_input_effective_sample"})
        timeline.append({"t_us": second_start_us + timing.t_obs_us, "event": "second_input_observation_end"})
        timeline.append({"t_us": t + timing.t_pair_hardware_us, "event": "second_input_result_ready"})

    hardware_complete_us = t + timing.t_pair_hardware_us
    pair_complete_us = hardware_complete_us + pair_post_hardware_overhead_us
    timeline.append({"t_us": pair_complete_us, "event": "pair_software_processing_complete"})
    return pair_complete_us, pair_complete_us


def _build_timeline(timing: AdcMuxTiming) -> list[dict[str, float | str]]:
    """Build a compact chronological timeline from the calculated timing object."""
    timeline: list[dict[str, float | str]] = []
    t = 0.0
    if timing.use_ground_between_channels:
        timeline.append({"t_us": t, "event": "ground_mux_switch_start"})
        t += timing.mux_address_overhead_us
        timeline.append({"t_us": t, "event": "ground_mux_address_set"})
        t += timing.mux_settle_us
        timeline.append({"t_us": t, "event": "ground_mux_settled"})
        if timing.ground_mode == "dummy_adc_pair":
            t += timing.adc_start_overhead_us
            timeline.append({"t_us": t, "event": "ground_dummy_adc_pair_start"})
            t += timing.t_pair_hardware_us
            timeline.append({"t_us": t, "event": "ground_dummy_adc_pair_hardware_complete"})
            ground_post_hardware_overhead_us = (
                timing.t_ground_dummy_software_overhead_us - timing.adc_start_overhead_us
            )
            if ground_post_hardware_overhead_us < 0.0:
                raise ValueError(
                    "ground dummy software overhead must include ADC-start overhead"
                )
            t += ground_post_hardware_overhead_us
            timeline.append({"t_us": t, "event": "ground_dummy_processing_complete"})
        elif timing.ground_mode == "dwell_only":
            t += timing.ground_dwell_us
            timeline.append({"t_us": t, "event": "ground_dwell_complete"})
            t += timing.t_per_mux_selection_overhead_us
            timeline.append({"t_us": t, "event": "ground_mux_selection_processing_complete"})
        if abs(t - timing.ground_phase_us) > 1e-9:
            raise ValueError("ground timeline does not match calculated ground phase")
        t = timing.ground_phase_us

    signal_start_us = t
    timeline.append({"t_us": t, "event": "signal_mux_switch_start"})
    t += timing.mux_address_overhead_us
    timeline.append({"t_us": t, "event": "signal_mux_address_set"})
    timeline.append({
        "t_us": t + timing.mux_turn_on_us,
        "event": "sensor_connected_to_mux_output",
    })
    t = signal_start_us + timing.mux_address_overhead_us + timing.mux_settle_us
    timeline.append({"t_us": t, "event": "signal_mux_settled"})
    t += timing.adc_start_overhead_us
    first_pair_complete_us, _ = _append_pair_timeline(
        timeline, t=t, timing=timing, first_pair=True
    )

    t = first_pair_complete_us
    if timing.repeat_count > 1:
        timeline.append({"t_us": t, "event": "first_retained_adc_pair_complete"})
        timeline.append({"t_us": t, "event": "additional_retained_pairs_start"})
        t += (timing.repeat_count - 1) * timing.t_pair_total_us
        timeline.append({"t_us": t, "event": "all_retained_adc_pairs_complete"})
    t += timing.t_per_mux_selection_overhead_us
    timeline.append({"t_us": t, "event": "mux_selection_processing_complete"})
    # The complete-sequence value is authoritative, including any future profile additions.
    timeline.append({"t_us": timing.complete_sequence_us, "event": "next_mux_switch_start"})
    return timeline


def adc_mux_timing_log(timing: AdcMuxTiming | None) -> dict | None:
    """Build the compact, JSON-safe acquisition metadata representation."""
    if timing is None:
        return None
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
            "mux_settle_us": timing.mux_settle_us,
            "mux_turn_on_us": timing.mux_turn_on_us,
            "mux_address_overhead_us": timing.mux_address_overhead_us,
            "adc_start_overhead_us": timing.adc_start_overhead_us,
            "pair_software_overhead_us": timing.t_pair_software_overhead_us,
            "per_mux_selection_overhead_us": timing.t_per_mux_selection_overhead_us,
            "block_fixed_overhead_us": timing.t_block_fixed_overhead_us,
            "ground_dummy_software_overhead_us": timing.t_ground_dummy_software_overhead_us,
            "iadc_input_switch_cycles": timing.iadc_input_switch_cycles,
        },
        "calculated_timing": {
            "t_obs_us": timing.t_obs_us,
            "t_conv_us": timing.t_conv_us,
            "t_iadc_input_switch_us": timing.t_iadc_input_switch_us,
            "t_pair_hardware_us": timing.t_pair_hardware_us,
            "t_pair_software_overhead_us": timing.t_pair_software_overhead_us,
            "t_pair_total_us": timing.t_pair_total_us,
            "t_ground_dummy_software_overhead_us": timing.t_ground_dummy_software_overhead_us,
            "t_per_mux_selection_overhead_us": timing.t_per_mux_selection_overhead_us,
            "t_block_fixed_overhead_us": timing.t_block_fixed_overhead_us,
            "t_ground_phase_us": timing.ground_phase_us,
            "t_signal_sequence_us": timing.signal_sequence_us,
            "t_complete_sequence_us": timing.complete_sequence_us,
            "t_connected_us": timing.sensor_connected_us,
            "t_decay_before_effective_sample_ch1_us": timing.t_decay_before_effective_sample_ch1_us,
            "t_connected_after_effective_sample_ch1_us": timing.t_connected_after_effective_sample_ch1_us,
            "t_decay_before_effective_sample_ch2_us": timing.t_decay_before_effective_sample_ch2_us,
            "t_connected_after_effective_sample_ch2_us": timing.t_connected_after_effective_sample_ch2_us,
        },
        "timeline": _build_timeline(timing),
    }
    return round_timing_json_values(payload)
