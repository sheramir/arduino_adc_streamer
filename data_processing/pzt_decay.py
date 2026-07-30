"""PZT voltage-decay characterization domain model and analyzer.

This module deliberately contains no Qt or serial code.  It is used by the
PZT_Decay_Calc tab, but can also be exercised with recorded or synthetic data.
Keeping the state machine here makes the physical-model calculations testable
and prevents a second copy of the MUX/channel mapping from growing in the UI.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from collections import deque
from enum import Enum
import math
import time
import uuid
from typing import Mapping, Sequence

import numpy as np
from scipy.optimize import least_squares

from data_processing.adc_mux_timing import AdcMuxTiming, adc_mux_timing_log


class PztDecayState(Enum):
    IDLE = "idle"
    STOPPING_NORMAL_CAPTURE = "stopping_normal_capture"
    CONFIGURING = "configuring"
    BASELINE = "baseline"
    WAITING_FOR_TARGET = "waiting_for_target"
    TARGET_STABILIZING = "target_stabilizing"
    ARMED = "armed"
    WAITING_FOR_RELEASE = "waiting_for_release"
    RECORDING_DECAY = "recording_decay"
    ANALYZING = "analyzing"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    ERROR = "error"


class PztDecayTimestampBasis(Enum):
    """Meaning of the timestamp supplied with an acquired retained pair."""

    EFFECTIVE_SAMPLE = "effective_sample"
    BURST_START = "burst_start"


@dataclass(frozen=True)
class PztDecaySignalMapping:
    logical_signal: str
    sensor_id: str
    mux_number: int
    mux_address: int
    mux_pin_label: str
    physical_adc_input: int
    companion_signal: str | None


def resolve_pzt_decay_signal_mapping(
    sensor_config: Mapping[str, object], logical_signal: str
) -> PztDecaySignalMapping:
    """Resolve a logical ``PZTn_C`` label using the active sensor mapping.

    Array mappings specify which of the two physical MUX outputs owns a
    sensor.  That MUX number is the physical IADC scan-table input (CH1/CH2),
    not an inferred display-column position.
    """
    try:
        sensor_id, position = logical_signal.rsplit("_", 1)
    except ValueError as exc:
        raise ValueError("logical signal must be in the form PZTn_C") from exc
    position = position.upper()
    mappings = sensor_config.get("mux_mapping", {})
    if not isinstance(mappings, Mapping) or sensor_id not in mappings:
        raise ValueError(f"No MUX mapping exists for {sensor_id}")
    item = mappings[sensor_id]
    if not isinstance(item, Mapping):
        raise ValueError(f"Invalid MUX mapping for {sensor_id}")
    positions = [str(value).upper() for value in sensor_config.get("channel_sensor_map", [])]
    channels = list(item.get("channels", []))
    if position not in positions:
        raise ValueError(f"{position} is not in the active channel sensor map")
    index = positions.index(position)
    if index >= len(channels):
        raise ValueError(f"No MUX address is configured for {logical_signal}")
    mux_number = int(item.get("mux", 0))
    if mux_number not in (1, 2):
        raise ValueError(f"MUX number for {sensor_id} must be 1 or 2")
    address = int(channels[index])
    companion = None
    for other_id, other_item in mappings.items():
        if other_id == sensor_id or not isinstance(other_item, Mapping):
            continue
        other_channels = list(other_item.get("channels", []))
        if int(other_item.get("mux", 0)) != mux_number and index < len(other_channels):
            if int(other_channels[index]) == address:
                companion = f"{other_id}_{position}"
                break
    return PztDecaySignalMapping(
        logical_signal=logical_signal,
        sensor_id=sensor_id,
        mux_number=mux_number,
        mux_address=address,
        mux_pin_label=f"S{address}",
        physical_adc_input=mux_number,
        companion_signal=companion,
    )


@dataclass(frozen=True)
class PztDecayTimingContext:
    timing_source: str
    physical_adc_input: int
    sensor_connected_s: float
    pre_sample_decay_s: float
    post_sample_connected_s: float
    repeat_count: int = 1
    pair_loop_interval_s: float = 0.0
    # From sweep/sequence start to the centre of the selected IADC observation.
    effective_sample_offset_s: float = 0.0
    mean_wall_sample_interval_s: float = 0.0
    median_wall_sample_interval_s: float = 0.0
    wall_sample_interval_std_s: float = 0.0
    mean_disconnected_s: float = 0.0
    median_disconnected_s: float = 0.0
    timing_consistency_valid: bool = True
    timing_consistency_errors: tuple[str, ...] = ()
    calculated_signal_sequence_s: float = 0.0
    calculated_ground_phase_s: float = 0.0
    calculated_complete_sequence_s: float = 0.0
    adc_mux_timing: AdcMuxTiming | None = None

    @classmethod
    def from_adc_mux_timing(cls, timing: AdcMuxTiming, physical_adc_input: int) -> "PztDecayTimingContext":
        if physical_adc_input == 1:
            pre, post = timing.t_decay_before_effective_sample_ch1_s, timing.t_connected_after_effective_sample_ch1_s
            effective_offset = timing.first_sample_effective_from_sequence_us * 1e-6
        elif physical_adc_input == 2:
            pre, post = timing.t_decay_before_effective_sample_ch2_s, timing.t_connected_after_effective_sample_ch2_s
            effective_offset = timing.second_sample_effective_from_sequence_us * 1e-6
        else:
            raise ValueError("physical_adc_input must be 1 or 2")
        return cls(
            timing_source="calculated_adc_mux_plus_measured_timestamps",
            physical_adc_input=physical_adc_input,
            sensor_connected_s=timing.sensor_connected_s,
            pre_sample_decay_s=pre,
            post_sample_connected_s=post,
            repeat_count=timing.repeat_count,
            pair_loop_interval_s=timing.t_pair_loop_total_us * 1e-6,
            effective_sample_offset_s=effective_offset,
            calculated_signal_sequence_s=timing.signal_sequence_us * 1e-6,
            calculated_ground_phase_s=timing.ground_phase_us * 1e-6,
            calculated_complete_sequence_s=timing.complete_sequence_us * 1e-6,
            adc_mux_timing=timing,
        )

    def with_sample_intervals(
        self, wall_intervals: Sequence[float], connected_intervals: Sequence[float]
    ) -> "PztDecayTimingContext":
        """Attach measured wall and interval-specific connected exposure data."""
        if len(wall_intervals) != len(connected_intervals):
            raise ValueError("wall and connected interval counts must match")
        walls = np.asarray(wall_intervals, dtype=float)
        connected = np.asarray(connected_intervals, dtype=float)
        finite = np.isfinite(walls) & np.isfinite(connected) & (walls >= 0.0) & (connected >= 0.0)
        values, connected = walls[finite], connected[finite]
        errors: list[str] = []
        if np.any(connected > values + 1e-9):
            errors.append("connected exposure exceeds measured wall interval")
        disconnected = np.maximum(0.0, values - connected)
        return PztDecayTimingContext(
            **{**asdict(self), "adc_mux_timing": self.adc_mux_timing,
               "mean_wall_sample_interval_s": float(np.mean(values)) if len(values) else 0.0,
               "median_wall_sample_interval_s": float(np.median(values)) if len(values) else 0.0,
               "wall_sample_interval_std_s": float(np.std(values)) if len(values) else 0.0,
               "mean_disconnected_s": float(np.mean(disconnected)) if len(disconnected) else 0.0,
               "median_disconnected_s": float(np.median(disconnected)) if len(disconnected) else 0.0,
               "timing_consistency_valid": self.timing_consistency_valid and not errors,
               "timing_consistency_errors": tuple(dict.fromkeys((*self.timing_consistency_errors, *errors)))})

    def export_dict(self) -> dict:
        payload = asdict(self)
        payload["adc_mux_timing"] = adc_mux_timing_log(self.adc_mux_timing)
        return payload

    def observation_offset_s(self, repeat_index: int) -> float:
        """Time from the sweep start to one CH1/CH2 effective sample."""
        if repeat_index < 0 or repeat_index >= self.repeat_count:
            raise ValueError("repeat index is outside the configured burst")
        return self.effective_sample_offset_s + repeat_index * self.pair_loop_interval_s

    def connected_exposure_between(self, previous_repeat: int | None, current_repeat: int) -> float:
        """Connected exposure between two effective observations of this input."""
        if previous_repeat is None:
            return 0.0
        if current_repeat == previous_repeat + 1:
            return self.pair_loop_interval_s
        if self.adc_mux_timing is not None:
            return (
                self.adc_mux_timing.connected_after_effective_sample_s(
                    adc_input=self.physical_adc_input, repeat_index=previous_repeat
                )
                + self.adc_mux_timing.decay_before_effective_sample_s(
                    adc_input=self.physical_adc_input, repeat_index=current_repeat
                )
            )
        return self.sensor_connected_s

    def connected_exposure_for_transition(
        self, previous: "PztDecaySample | None", *, current_burst_index: int,
        current_repeat_index: int,
    ) -> float | None:
        """Return the physical exposure between two valid retained samples.

        ``None`` deliberately represents an invalid/dropped/reordered
        transition; callers must not invent a duration for it.
        """
        if previous is None:
            return 0.0
        if current_burst_index == previous.burst_index:
            if current_repeat_index == previous.repeat_index + 1:
                return self.pair_loop_interval_s
            return None
        if current_burst_index == previous.burst_index + 1:
            if previous.repeat_index == self.repeat_count - 1 and current_repeat_index == 0:
                return self.connected_exposure_between(previous.repeat_index, current_repeat_index)
            return None
        return None


@dataclass
class PztDecaySample:
    sample_index: int
    timestamp_s: float
    voltage_v: float
    measurement_state: str
    burst_index: int = 0
    repeat_index: int = 0
    timestamp_basis: str = PztDecayTimestampBasis.EFFECTIVE_SAMPLE.value
    connected_exposure_since_previous_s: float = 0.0
    timing_valid: bool = True
    relative_time_s: float = 0.0
    delta_from_vmid_v: float | None = None
    normalized_amplitude: float | None = None
    wall_dt_s: float | None = None
    connected_decay_dt_s: float | None = None
    disconnected_decay_dt_s: float | None = None
    cumulative_wall_time_s: float = 0.0
    cumulative_connected_time_s: float = 0.0
    cumulative_disconnected_time_s: float = 0.0
    calculated_voltage_v: float | None = None
    fit_included: bool = False
    rejection_reason: str | None = None


@dataclass
class PztDecaySettings:
    excitation_above_vmid_v: float = 1.0
    target_tolerance_v: float = 0.020
    stable_target_duration_s: float = 0.0
    stable_peak_to_peak_v: float = 0.020
    stable_slope_v_per_s: float = 0.050
    # Vmid is an explicit pre-measurement operation.  It is driven by the
    # requested sample count so rapid decays do not inherit a one-second wait.
    baseline_duration_s: float = 0.0
    baseline_min_samples: int = 1000
    baseline_discard_initial_samples: int = 0
    baseline_max_slope_v_per_s: float = 0.020
    baseline_validate_stability: bool = True
    release_drop_fraction: float = 0.020
    release_consecutive_samples: int = 3
    fit_upper_normalized: float = 0.85
    # Keep the regression away from the Vmid noise floor; recording itself
    # still continues to the separate 2% final-baseline threshold.
    fit_lower_normalized: float = 0.15
    minimum_fit_samples: int = 3
    # Keep recording close to Vmid: stop at Vmid + 2% of the measured initial
    # amplitude.  This retains the full tail without altering the fit window.
    end_threshold_normalized: float = 0.02
    end_consecutive_samples: int = 1
    final_baseline_min_samples: int = 10
    plateau_window_samples: int = 5
    target_timeout_s: float = 60.0
    maximum_recording_duration_s: float = 60.0
    robust_fit_enabled: bool = True
    robust_mad_multiplier: float = 3.5
    # Fit one regularly sampled segment only; inter-burst/interrupt gaps are
    # excluded relative to the median candidate timestamp interval.
    fit_max_interval_ratio: float = 2.0
    capacitance_estimation_enabled: bool = False
    connected_equivalent_resistance_ohm: float | None = None
    adc_min_v: float = 0.0
    adc_max_v: float = 3.3
    adc_safety_margin_v: float = 0.050

    def validate(self) -> None:
        if not (0.0 < self.fit_lower_normalized < self.fit_upper_normalized <= 1.0):
            raise ValueError("fit limits must satisfy 0 < lower < upper <= 1")
        if (self.baseline_min_samples < 1 or self.baseline_discard_initial_samples < 0
                or self.minimum_fit_samples < 3
                or self.final_baseline_min_samples < 2 or self.plateau_window_samples < 2):
            raise ValueError("baseline sample count must be positive and minimum fit samples must be at least 3")
        if self.excitation_above_vmid_v <= 0:
            raise ValueError("excitation above Vmid must be positive")


@dataclass(frozen=True)
class PztDecayResult:
    schema_version: str
    result_id: str
    created_at: datetime
    logical_signal: str
    mapping: PztDecaySignalMapping
    vmid_v: float
    baseline_sigma_v: float
    target_voltage_v: float
    plateau_voltage_v: float
    initial_amplitude_v: float
    capture_start_time_s: float
    release_time_s: float
    recording_duration_s: float
    total_samples: int
    fit_samples: int
    fit_wall_time_origin_s: float
    fit_connected_time_origin_s: float
    alpha_sample_regression: float | None
    alpha_sample_pairwise_median: float | None
    alpha_sample_pairwise_mad: float | None
    alpha_sample_pairwise_mean: float | None
    alpha_sample_pairwise_std: float | None
    alpha_within_burst: float | None
    alpha_burst_boundary: float | None
    alpha_full_mux_selection: float | None
    fit_quality_valid: bool
    timing_quality_valid: bool
    event_quality_valid: bool
    tau_wall_s: float | None
    tau_on_estimated_s: float | None
    connected_equivalent_resistance_ohm: float | None
    capacitance_estimated_f: float | None
    fitted_amplitude_v: float | None
    fitted_baseline_v: float | None
    fitted_decay_rate_per_s: float | None
    r_squared: float | None
    rmse_voltage_v: float | None
    timing: PztDecayTimingContext
    acquisition_configuration: dict
    quality_status: str
    warnings: tuple[str, ...] = ()

    def export_dict(self) -> dict:
        return {
            "schema_version": self.schema_version, "result_id": self.result_id,
            "timestamp": self.created_at.isoformat(), "measurement_type": "pzt_decay_characterization",
            "signal": {"logical_name": self.logical_signal, "sensor_id": self.mapping.sensor_id,
                       "mux_number": self.mapping.mux_number, "mux_address": self.mapping.mux_address,
                       "mux_pin": self.mapping.mux_pin_label, "physical_adc_input": self.mapping.physical_adc_input,
                       "companion_signal": self.mapping.companion_signal},
            "excitation": {"vmid_v": self.vmid_v, "target_voltage_v": self.target_voltage_v,
                           "plateau_voltage_v": self.plateau_voltage_v, "measured_initial_amplitude_v": self.initial_amplitude_v,
                           "capture_start_time_s": self.capture_start_time_s, "release_time_s": self.release_time_s},
            "acquisition": self.acquisition_configuration, "timing": self.timing.export_dict(),
            "fit": {"sample_count": self.fit_samples,
                    "time_basis": "connected_exposure_from_selected_release",
                    "wall_time_origin_s": self.fit_wall_time_origin_s,
                    "connected_time_origin_s": self.fit_connected_time_origin_s,
                    "alpha_within_burst": self.alpha_within_burst,
                    "alpha_burst_boundary": self.alpha_burst_boundary,
                    "alpha_full_mux_selection": self.alpha_full_mux_selection,
                    "pairwise_rate_per_s_median": self.alpha_sample_pairwise_median,
                    "pairwise_rate_per_s_mad": self.alpha_sample_pairwise_mad, "tau_wall_s": self.tau_wall_s,
                    "tau_on_estimated_s": self.tau_on_estimated_s, "fitted_amplitude_v": self.fitted_amplitude_v,
                    "fitted_baseline_v": self.fitted_baseline_v,
                    "fitted_decay_rate_per_s": self.fitted_decay_rate_per_s, "r_squared": self.r_squared,
                    "rmse_voltage_v": self.rmse_voltage_v},
            "capacitance_estimate": {"enabled": self.capacitance_estimated_f is not None,
                "connected_equivalent_resistance_ohm": self.connected_equivalent_resistance_ohm,
                "capacitance_f": self.capacitance_estimated_f,
                "assumption": "connected resistance dominates; disconnected leakage negligible"},
            "quality": {"status": self.quality_status, "fit_valid": self.fit_quality_valid,
                        "timing_valid": self.timing_quality_valid, "event_valid": self.event_quality_valid,
                        "warnings": list(self.warnings)},
        }


class PztDecayAnalyzer:
    """Stateful, timestamp-driven implementation of the one-channel workflow."""

    def __init__(self, mapping: PztDecaySignalMapping, timing: PztDecayTimingContext,
                 settings: PztDecaySettings | None = None, acquisition_configuration: Mapping[str, object] | None = None):
        self.mapping, self.timing = mapping, timing
        self.settings = settings or PztDecaySettings()
        self.settings.validate()
        self.acquisition_configuration = dict(acquisition_configuration or {})
        self.acquisition_configuration.setdefault(
            "timestamp_basis", "effective_sample"
        )
        self.acquisition_configuration.setdefault("repeat_count", timing.repeat_count)
        self.state = PztDecayState.IDLE
        self.samples: list[PztDecaySample] = []
        self.baseline_values: list[float] = []
        self.baseline_times: list[float] = []
        self._baseline_raw_sample_count = 0
        self.target_samples: list[PztDecaySample] = []
        self._release_candidates: list[PztDecaySample] = []
        self.vmid_v: float | None = None
        self.baseline_sigma_v = 0.0
        self.target_voltage_v: float | None = None
        self.plateau_voltage_v: float | None = None
        self.initial_amplitude_v: float | None = None
        self.capture_start_time_s: float | None = None
        self.release_time_s: float | None = None
        self.result: PztDecayResult | None = None
        self.error_message: str | None = None
        self.warnings: list[str] = []
        self._run_started_s: float | None = None
        self._target_wait_started_s: float | None = None
        self._final_baseline_window: deque[PztDecaySample] = deque(
            maxlen=self.settings.final_baseline_min_samples
        )

    def begin(self, timestamp_s: float | None = None) -> None:
        # The binary stream supplies MCU-relative timestamps.  When no timestamp
        # is supplied, defer the clock origin to the first retained sample rather
        # than mixing wall-clock and MCU-relative time bases.
        self._run_started_s = None if timestamp_s is None else float(timestamp_s)
        self._final_baseline_window.clear()
        self.baseline_values.clear()
        self.baseline_times.clear()
        self._baseline_raw_sample_count = 0
        self.state = PztDecayState.BASELINE

    def begin_with_vmid(self, vmid_v: float, baseline_sigma_v: float = 0.0) -> None:
        """Begin a measurement using a Vmid calculated earlier for this signal."""
        self.vmid_v = float(vmid_v)
        self.baseline_sigma_v = float(baseline_sigma_v)
        self.target_voltage_v = self.vmid_v + self.settings.excitation_above_vmid_v
        if not (self.settings.adc_min_v + self.settings.adc_safety_margin_v < self.target_voltage_v < self.settings.adc_max_v - self.settings.adc_safety_margin_v):
            self.fail("target voltage is outside the ADC safety range")
            return
        self._run_started_s = None
        self._target_wait_started_s = None
        self._final_baseline_window.clear()
        self.state = PztDecayState.WAITING_FOR_TARGET

    def cancel(self) -> None:
        if self.state not in (PztDecayState.COMPLETE, PztDecayState.ERROR):
            self.state = PztDecayState.CANCELLED

    def fail(self, message: str) -> None:
        self.error_message = message
        self.warnings.append(message)
        self.state = PztDecayState.ERROR

    @staticmethod
    def _slope(times: Sequence[float], values: Sequence[float]) -> float:
        if len(times) < 2 or max(times) == min(times):
            return 0.0
        return float(np.polyfit(np.asarray(times, float), np.asarray(values, float), 1)[0])

    def add_sample(
        self, voltage_v: float, timestamp_s: float | None = None, *,
        burst_index: int | None = None, repeat_index: int = 0,
        timestamp_basis: PztDecayTimestampBasis | str = PztDecayTimestampBasis.EFFECTIVE_SAMPLE,
        connected_exposure_since_previous_s: float | None = None,
    ) -> PztDecayState:
        """Add one selected-signal reading.

        ``timestamp_s`` is either the effective ADC observation timestamp or
        the start of its MUX-selection burst.  Normal acquisition supplies the
        latter once per decoded sweep; this engine expands it with the
        CH1/CH2-specific observation offset.  Connected leakage duration is
        derived here from burst/repeat identities, never by the GUI.
        """
        if self.state in (PztDecayState.IDLE, PztDecayState.CANCELLED, PztDecayState.COMPLETE, PztDecayState.ERROR):
            return self.state
        basis = PztDecayTimestampBasis(timestamp_basis)
        supplied_stamp = time.time() if timestamp_s is None else float(timestamp_s)
        if burst_index is None:
            # Compatibility for old single-repeat imports. Repeat bursts in
            # live acquisition must always supply their actual index.
            burst_index = len(self.samples) if self.timing.repeat_count == 1 else 0
        burst_index, repeat_index = int(burst_index), int(repeat_index)
        stamp = supplied_stamp if basis is PztDecayTimestampBasis.EFFECTIVE_SAMPLE else (
            supplied_stamp + self.timing.observation_offset_s(repeat_index)
        )
        if self._run_started_s is None:
            self._run_started_s = stamp
        previous = self.samples[-1] if self.samples else None
        derived_exposure = self.timing.connected_exposure_for_transition(
            previous, current_burst_index=burst_index, current_repeat_index=repeat_index,
        )
        transition_valid = derived_exposure is not None
        if connected_exposure_since_previous_s is None:
            connected_exposure_since_previous_s = derived_exposure if transition_valid else 0.0
        elif transition_valid:
            connected_exposure_since_previous_s = float(connected_exposure_since_previous_s)
        sample = PztDecaySample(
            len(self.samples), stamp, float(voltage_v), self.state.value,
            burst_index=burst_index, repeat_index=repeat_index, timestamp_basis=(
                basis.value if basis is PztDecayTimestampBasis.EFFECTIVE_SAMPLE
                else "burst_start_plus_calculated_observation_offset"
            ),
            connected_exposure_since_previous_s=max(0.0, float(connected_exposure_since_previous_s)),
            timing_valid=transition_valid,
        )
        if previous is not None and stamp <= previous.timestamp_s:
            sample.timing_valid = False
            sample.rejection_reason = "nonmonotonic effective timestamp"
            self.warnings.append("timing timestamps missing or nonmonotonic")
        if not transition_valid:
            sample.rejection_reason = "missing or out-of-order burst sample"
            self.warnings.append("missing or out-of-order burst sample")
        self.samples.append(sample)
        if not math.isfinite(voltage_v) or voltage_v <= self.settings.adc_min_v or voltage_v >= self.settings.adc_max_v:
            self.warnings.append("ADC clipping or invalid voltage detected")

        if self.state == PztDecayState.BASELINE:
            self._handle_baseline(sample)
        elif self.state in (PztDecayState.WAITING_FOR_TARGET, PztDecayState.TARGET_STABILIZING):
            self._handle_target(sample)
        elif self.state == PztDecayState.RECORDING_DECAY:
            self._handle_recording(sample)
        if self.state in (PztDecayState.WAITING_FOR_TARGET, PztDecayState.TARGET_STABILIZING):
            if self._target_wait_started_s is None:
                self._target_wait_started_s = stamp
            elif stamp - self._target_wait_started_s > self.settings.target_timeout_s:
                self.fail("Could not find a signal")
        # Vmid and target acquisition are deliberately outside this budget.
        if (self.state == PztDecayState.RECORDING_DECAY and self.capture_start_time_s is not None
                and stamp - self.capture_start_time_s > self.settings.maximum_recording_duration_s):
            self.fail("Could not find signal decay")
        return self.state

    def _handle_baseline(self, sample: PztDecaySample) -> None:
        self._baseline_raw_sample_count += 1
        if self._baseline_raw_sample_count <= self.settings.baseline_discard_initial_samples:
            return
        self.baseline_values.append(sample.voltage_v); self.baseline_times.append(sample.timestamp_s)
        duration = sample.timestamp_s - self.baseline_times[0]
        if duration < self.settings.baseline_duration_s or len(self.baseline_values) < self.settings.baseline_min_samples:
            return
        self.vmid_v = float(np.median(self.baseline_values))
        self.baseline_sigma_v = float(1.4826 * np.median(np.abs(np.asarray(self.baseline_values) - self.vmid_v)))
        if (self.settings.baseline_validate_stability
                and abs(self._slope(self.baseline_times, self.baseline_values))
                > self.settings.baseline_max_slope_v_per_s):
            self.fail("baseline unstable")
            return
        self.target_voltage_v = self.vmid_v + self.settings.excitation_above_vmid_v
        if not (self.settings.adc_min_v + self.settings.adc_safety_margin_v < self.target_voltage_v < self.settings.adc_max_v - self.settings.adc_safety_margin_v):
            self.fail("target voltage is outside the ADC safety range")
            return
        self.state = PztDecayState.WAITING_FOR_TARGET
        self._target_wait_started_s = sample.timestamp_s

    def _handle_target(self, sample: PztDecaySample) -> None:
        assert self.target_voltage_v is not None
        tolerance = max(self.settings.target_tolerance_v, 5.0 * self.baseline_sigma_v)
        if abs(sample.voltage_v - self.target_voltage_v) > tolerance:
            self.target_samples.clear(); self.state = PztDecayState.WAITING_FOR_TARGET
            return
        self.target_samples.append(sample); self.state = PztDecayState.TARGET_STABILIZING
        cutoff = sample.timestamp_s - self.settings.stable_target_duration_s - 1e-12
        self.target_samples = [item for item in self.target_samples if item.timestamp_s >= cutoff]
        if not self.target_samples or sample.timestamp_s - self.target_samples[0].timestamp_s + 1e-12 < self.settings.stable_target_duration_s:
            return
        values = [item.voltage_v for item in self.target_samples]
        if max(values) - min(values) > self.settings.stable_peak_to_peak_v or abs(self._slope([x.timestamp_s for x in self.target_samples], values)) > self.settings.stable_slope_v_per_s:
            self.target_samples.clear(); self.state = PztDecayState.WAITING_FOR_TARGET
            return
        # Preserve every sample from this first verified plateau onward.  The
        # final plateau/release/decay/baseline event is selected only after a
        # stable final baseline is observed.
        self.capture_start_time_s = sample.timestamp_s
        self._final_baseline_window.clear()
        self._final_baseline_window.append(sample)
        self.state = PztDecayState.RECORDING_DECAY

    def _handle_recording(self, sample: PztDecaySample) -> None:
        assert self.vmid_v is not None
        self._final_baseline_window.append(sample)
        trailing = self._final_baseline_window
        selected_amplitude = self.initial_amplitude_v or self.settings.excitation_above_vmid_v
        baseline_tolerance = max(
            5.0 * self.baseline_sigma_v,
            self.settings.end_threshold_normalized * selected_amplitude,
        )
        stable_limit = max(self.settings.stable_peak_to_peak_v, 5.0 * self.baseline_sigma_v)
        values = [s.voltage_v for s in trailing]
        if (len(trailing) == self.settings.final_baseline_min_samples
                and abs(float(np.median(values)) - self.vmid_v) <= baseline_tolerance
                and max(values) - min(values) <= stable_limit
                and abs(self._slope([s.timestamp_s for s in trailing], values)) <= self.settings.stable_slope_v_per_s):
            self._complete_analysis()

    @staticmethod
    def _voltage_residuals(params: np.ndarray, x: np.ndarray, measured_v: np.ndarray) -> np.ndarray:
        baseline_v, amplitude_v, decay_rate = params
        return baseline_v + amplitude_v * np.exp(-decay_rate * x) - measured_v

    def _fit_voltage_exponential(self, x: np.ndarray, measured_v: np.ndarray) -> tuple[float, float, float, np.ndarray]:
        """Robust nonlinear voltage fit with a free asymptote, amplitude, and rate."""
        if len(x) < 2 or not np.all(np.isfinite(x)) or not np.all(np.isfinite(measured_v)):
            raise ValueError("too few finite samples for nonlinear voltage fit")
        lsb_v = (self.settings.adc_max_v - self.settings.adc_min_v) / 4095.0
        noise_sigma_v = max(self.baseline_sigma_v, lsb_v)
        baseline0 = float(np.min(measured_v))
        amplitude0 = max(float(measured_v[0] - baseline0), noise_sigma_v)
        positive = measured_v - baseline0
        rates = []
        for dt, earlier, later in zip(np.diff(x), positive[:-1], positive[1:]):
            if dt > 0.0 and earlier > noise_sigma_v and later > noise_sigma_v and later < earlier:
                rates.append(-math.log(later / earlier) / dt)
        rate0 = float(np.median(rates)) if rates else 1.0 / max(float(x[-1] - x[0]), 1e-9)
        result = least_squares(
            self._voltage_residuals, x0=[baseline0, amplitude0, max(rate0, 1e-12)],
            bounds=([self.settings.adc_min_v, 0.0, 0.0], [self.settings.adc_max_v, 2.0, np.inf]),
            args=(x, measured_v), loss="soft_l1", f_scale=noise_sigma_v,
        )
        if not result.success or result.x[2] <= 0.0:
            raise ValueError("nonlinear voltage fit did not converge to a decay")
        return (
            float(result.x[0]), float(result.x[1]), float(result.x[2]),
            np.asarray(result.fun, dtype=float),
        )

    def _select_uniform_cadence_run(self, candidates: list[PztDecaySample]) -> list[PztDecaySample]:
        """Keep the largest contiguous candidate run without a large timestamp gap."""
        if len(candidates) < 2:
            return candidates
        intervals = np.asarray([
            current.timestamp_s - previous.timestamp_s
            for previous, current in zip(candidates, candidates[1:])
            if current.timestamp_s > previous.timestamp_s
        ], dtype=float)
        if not len(intervals):
            return candidates
        maximum_dt_s = float(np.median(intervals)) * self.settings.fit_max_interval_ratio
        runs: list[list[PztDecaySample]] = [[candidates[0]]]
        for previous, current in zip(candidates, candidates[1:]):
            if current.timestamp_s - previous.timestamp_s <= maximum_dt_s:
                runs[-1].append(current)
            else:
                runs.append([current])
        selected = max(runs, key=len)
        if len(selected) != len(candidates):
            selected_ids = {id(sample) for sample in selected}
            for sample in candidates:
                if id(sample) not in selected_ids:
                    sample.fit_included = False
                    sample.rejection_reason = "outside uniform sampling interval run"
            self.warnings.append("fit excludes samples separated by a large timestamp gap")
        return selected

    def _complete_analysis(self) -> None:
        if self.state in (PztDecayState.COMPLETE, PztDecayState.ERROR, PztDecayState.CANCELLED):
            return
        self.state = PztDecayState.ANALYZING
        try:
            self.result = self._analyze()
            self.state = PztDecayState.COMPLETE
        except Exception as exc:
            self.fail(str(exc))

    def finalize(self) -> PztDecayResult | None:
        """Analyze collected data now; useful for an intentional timeout/end."""
        self._complete_analysis()
        return self.result

    def _select_final_event(self, capture: Sequence[PztDecaySample]) -> tuple[list[PztDecaySample], list[PztDecaySample]]:
        """Find the last stable target plateau followed by the final baseline."""
        assert self.vmid_v is not None and self.target_voltage_v is not None
        final_count = self.settings.final_baseline_min_samples
        if len(capture) < final_count + self.settings.plateau_window_samples + 2:
            raise ValueError("too few samples to validate plateau, release, decay, and final baseline")
        tail = list(capture[-final_count:])
        baseline_tolerance = max(
            5.0 * self.baseline_sigma_v,
            self.settings.end_threshold_normalized * self.settings.excitation_above_vmid_v,
        )
        stable_limit = max(self.settings.stable_peak_to_peak_v, 5.0 * self.baseline_sigma_v)
        tail_values = [sample.voltage_v for sample in tail]
        if (abs(float(np.median(tail_values)) - self.vmid_v) > baseline_tolerance
                or max(tail_values) - min(tail_values) > stable_limit
                or abs(self._slope([sample.timestamp_s for sample in tail], tail_values)) > self.settings.stable_slope_v_per_s):
            raise ValueError("final baseline window is not stable")

        plateau_count = self.settings.plateau_window_samples
        target_tolerance = max(self.settings.target_tolerance_v, 5.0 * self.baseline_sigma_v)
        plateau_end = None
        plateau: list[PztDecaySample] = []
        for index in range(len(capture) - final_count - 1, plateau_count - 2, -1):
            window = list(capture[index - plateau_count + 1:index + 1])
            values = [sample.voltage_v for sample in window]
            if (all(abs(value - self.target_voltage_v) <= target_tolerance for value in values)
                    and max(values) - min(values) <= stable_limit):
                plateau_end, plateau = index, window
                break
        if plateau_end is None:
            raise ValueError("could not find a stable plateau immediately before the final release")

        plateau_v = float(np.median([sample.voltage_v for sample in plateau]))
        amplitude = plateau_v - self.vmid_v
        if amplitude <= max(5.0 * self.baseline_sigma_v, 1e-9):
            raise ValueError("selected plateau amplitude is too small")
        release_drop = max(self.settings.release_drop_fraction * amplitude, 5.0 * self.baseline_sigma_v)
        release_index = next((
            index for index in range(plateau_end + 1, len(capture))
            if capture[index].voltage_v <= plateau_v - release_drop
        ), None)
        if release_index is None:
            raise ValueError("could not find a release after the selected plateau")
        self.plateau_voltage_v, self.initial_amplitude_v = plateau_v, amplitude
        self.release_time_s = capture[release_index].timestamp_s
        return self._select_final_descending_segment(list(capture[release_index:])), plateau

    def _select_final_descending_segment(self, event: list[PztDecaySample]) -> list[PztDecaySample]:
        """Keep the final noise-tolerant descent, rather than a best-RMSE subset.

        A late positive step is treated as the beginning of a newer final
        descent.  It is not a reason to discard the whole measurement: the
        preceding, recharged portion is excluded and the fit starts after that
        step.  This is important for a real release that crosses an ADC/MUX
        boundary while the source is being removed.
        """
        assert self.vmid_v is not None and self.initial_amplitude_v is not None
        upper = self.vmid_v + self.settings.fit_upper_normalized * self.initial_amplitude_v
        baseline_start = max(0, len(event) - self.settings.final_baseline_min_samples)
        starts = [index for index in range(baseline_start) if event[index].voltage_v >= upper]
        if starts:
            start = starts[-1]
        else:
            # The release detector can see its first retained post-release
            # value below 80% for a very fast decay.  Do not discard that
            # physical final tail merely because the upper crossing happened
            # between two ADC observations.
            start = 0
            self.warnings.append("upper fit-threshold crossing was skipped between retained samples")
        segment = event[start:]
        noise_v = max(5.0 * self.baseline_sigma_v, 0.02 * self.initial_amplitude_v)
        envelope = segment[0].voltage_v
        final_start = 0
        for index, sample in enumerate(segment[1:baseline_start - start], start=1):
            if sample.voltage_v > envelope + noise_v:
                for earlier in segment[final_start:index]:
                    if earlier.rejection_reason is None:
                        earlier.rejection_reason = "before final descending decay trend"
                final_start = index
                envelope = sample.voltage_v
                self.warnings.append("recharging portion excluded before final descending decay")
            else:
                envelope = min(envelope, sample.voltage_v)
        return segment[final_start:]

    def _analyze(self) -> PztDecayResult:
        if self.vmid_v is None or self.target_voltage_v is None or self.capture_start_time_s is None:
            raise ValueError("capture start and Vmid are required before analysis")
        capture = [sample for sample in self.samples if sample.timestamp_s >= self.capture_start_time_s]
        event, plateau = self._select_final_event(capture)
        assert self.initial_amplitude_v is not None and self.plateau_voltage_v is not None and self.release_time_s is not None
        for sample in capture:
            sample.fit_included = False
            if sample not in event and sample.rejection_reason is None:
                sample.rejection_reason = "before final selected decay event"

        wall_intervals: list[float] = []
        connected_intervals: list[float] = []
        cumulative_wall = cumulative_connected = cumulative_disconnected = 0.0
        for index, sample in enumerate(event):
            sample.relative_time_s = sample.timestamp_s - self.release_time_s
            sample.delta_from_vmid_v = sample.voltage_v - self.vmid_v
            sample.normalized_amplitude = sample.delta_from_vmid_v / self.initial_amplitude_v
            if index:
                dt = sample.timestamp_s - event[index - 1].timestamp_s
                connected_dt = sample.connected_exposure_since_previous_s
                if dt <= 0.0:
                    sample.rejection_reason = "nonmonotonic effective timestamp"; sample.timing_valid = False
                    self.warnings.append("timing timestamps missing or nonmonotonic"); dt = 0.0
                if connected_dt > dt + 1e-9:
                    sample.rejection_reason = "connected exposure exceeds wall interval"; sample.timing_valid = False
                    self.warnings.append("sample timing consistency error")
                    connected_dt = max(0.0, dt)
                sample.wall_dt_s = dt; sample.connected_decay_dt_s = connected_dt
                sample.disconnected_decay_dt_s = max(0.0, dt - connected_dt)
                wall_intervals.append(dt)
                connected_intervals.append(connected_dt)
                cumulative_wall += dt; cumulative_connected += connected_dt; cumulative_disconnected += sample.disconnected_decay_dt_s
            sample.cumulative_wall_time_s = cumulative_wall
            sample.cumulative_connected_time_s = cumulative_connected
            sample.cumulative_disconnected_time_s = cumulative_disconnected
            if (sample.timing_valid and sample.rejection_reason is None and sample.delta_from_vmid_v > 0.0
                    and self.settings.fit_lower_normalized <= sample.normalized_amplitude <= self.settings.fit_upper_normalized):
                sample.fit_included = True
            elif sample.rejection_reason is None:
                sample.rejection_reason = "outside normalized fit window"

        candidates = [sample for sample in event if sample.fit_included]
        if len(candidates) < self.settings.minimum_fit_samples:
            # A millisecond-scale release can cross the configured 20–80%
            # window between retained observations even though a usable final
            # descent was captured.  Preserve the configured window whenever
            # possible, but fall back only to the already-recorded 2% tail
            # threshold and make that relaxation explicit in the result.
            fallback_lower = self.settings.end_threshold_normalized
            fallback = [
                sample for sample in event
                if (sample.timing_valid and sample.rejection_reason in (None, "outside normalized fit window")
                    and sample.delta_from_vmid_v is not None
                    and fallback_lower <= sample.normalized_amplitude <= self.settings.fit_upper_normalized)
            ]
            if len(fallback) >= self.settings.minimum_fit_samples:
                for sample in fallback:
                    sample.fit_included = True
                    if sample.rejection_reason == "outside normalized fit window":
                        sample.rejection_reason = "expanded fit window for sparse decay"
                candidates = fallback
                self.warnings.append(
                    "configured fit window contained too few samples; expanded lower bound to the 2% recording threshold"
                )
            else:
                raise ValueError(
                    f"Warning: only {len(candidates)} sampling points in the configured fit range; "
                    f"{len(fallback)} available after expansion (minimum {self.settings.minimum_fit_samples})"
                )
        candidates = self._select_uniform_cadence_run(candidates)
        if len(candidates) < self.settings.minimum_fit_samples:
            raise ValueError(
                "Warning: fewer than the minimum fit samples remain after excluding large timestamp gaps"
            )
        connected_origin_s = candidates[0].cumulative_connected_time_s
        wall_origin_s = candidates[0].timestamp_s
        connected_x = np.asarray([
            sample.cumulative_connected_time_s - connected_origin_s for sample in candidates
        ])
        measured_v = np.asarray([sample.voltage_v for sample in candidates])
        fitted_baseline, fitted_amplitude, connected_rate, residuals = self._fit_voltage_exponential(connected_x, measured_v)
        if self.settings.robust_fit_enabled:
            lsb_v = (self.settings.adc_max_v - self.settings.adc_min_v) / 4095.0
            noise_sigma_v = max(self.baseline_sigma_v, lsb_v)
            robust_sigma_v = 1.4826 * float(np.median(np.abs(residuals - np.median(residuals))))
            threshold_v = self.settings.robust_mad_multiplier * max(noise_sigma_v, robust_sigma_v)
            rejected = (np.abs(residuals) > self.settings.robust_mad_multiplier * noise_sigma_v
                        ) & (np.abs(residuals - np.median(residuals)) > threshold_v)
            if np.any(rejected) and len(candidates) - int(np.sum(rejected)) >= self.settings.minimum_fit_samples:
                for sample, reject in zip(candidates, rejected):
                    if reject:
                        sample.fit_included = False; sample.rejection_reason = "robust voltage-space fit outlier"
                candidates = [sample for sample in candidates if sample.fit_included]
                connected_origin_s = candidates[0].cumulative_connected_time_s
                wall_origin_s = candidates[0].timestamp_s
                connected_x = np.asarray([
                    sample.cumulative_connected_time_s - connected_origin_s for sample in candidates
                ])
                measured_v = np.asarray([sample.voltage_v for sample in candidates])
                fitted_baseline, fitted_amplitude, connected_rate, residuals = self._fit_voltage_exponential(connected_x, measured_v)

        predicted_v = fitted_baseline + fitted_amplitude * np.exp(-connected_rate * connected_x)
        ss_res = float(np.sum((measured_v - predicted_v) ** 2)); ss_tot = float(np.sum((measured_v - np.mean(measured_v)) ** 2))
        r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0.0 else 1.0
        rmse = math.sqrt(ss_res / len(candidates))
        wall_x = np.asarray([sample.timestamp_s - wall_origin_s for sample in candidates])
        _, _, wall_rate, _ = self._fit_voltage_exponential(wall_x, measured_v)
        for sample in event:
            fit_time_s = sample.cumulative_connected_time_s - connected_origin_s
            if fit_time_s >= 0.0:
                sample.calculated_voltage_v = fitted_baseline + fitted_amplitude * math.exp(-connected_rate * fit_time_s)

        tau_wall, tau_on = 1.0 / wall_rate, 1.0 / connected_rate
        alpha_within = math.exp(-connected_rate * self.timing.pair_loop_interval_s)
        alpha_boundary = math.exp(-connected_rate * self.timing.connected_exposure_between(
            self.timing.repeat_count - 1, 0,
        ))
        alpha_full_selection = math.exp(-connected_rate * self.timing.sensor_connected_s)
        pair_rates = [
            -math.log((b.voltage_v - fitted_baseline) / (a.voltage_v - fitted_baseline))
            / (b.cumulative_connected_time_s - a.cumulative_connected_time_s)
            for a, b in zip(candidates, candidates[1:])
            if (a.voltage_v > fitted_baseline and b.voltage_v > fitted_baseline
                and b.cumulative_connected_time_s > a.cumulative_connected_time_s)
        ]
        pair_median = float(np.median(pair_rates)) if pair_rates else None
        pair_mad = float(np.median(np.abs(np.asarray(pair_rates) - pair_median))) if pair_rates else None
        resistance = self.settings.connected_equivalent_resistance_ohm; capacitance = None
        if self.settings.capacitance_estimation_enabled and resistance is not None and resistance > 0.0:
            capacitance = tau_on / resistance
            self.warnings.append("capacitance estimate assumes connected resistance dominates and disconnected leakage is negligible")
        elif self.settings.capacitance_estimation_enabled:
            self.warnings.append("known resistance not supplied; capacitance not calculated")
        if r_squared < 0.98: self.warnings.append("low R²")
        if not self.timing.adc_mux_timing or not self.timing.adc_mux_timing.calibration_metadata.get(
            "pair_loop_interval_empirically_estimated", False
        ):
            self.warnings.append("Retained-pair loop timing has not been empirically estimated for the active firmware")
        context = self.timing.with_sample_intervals(wall_intervals, connected_intervals)
        unique_warnings = tuple(dict.fromkeys(self.warnings))
        timing_valid = context.timing_consistency_valid and not any(
            "out-of-order burst" in warning or "nonmonotonic" in warning for warning in unique_warnings
        )
        fit_valid = r_squared >= 0.98 and len(candidates) >= self.settings.minimum_fit_samples
        event_valid = True
        valid = fit_valid and timing_valid and event_valid and not any("clipping" in warning for warning in unique_warnings)
        quality = "valid" if valid and not unique_warnings else "valid_with_warnings" if valid else "invalid"
        return PztDecayResult(
            schema_version="1.2", result_id=uuid.uuid4().hex, created_at=datetime.now(), logical_signal=self.mapping.logical_signal,
            mapping=self.mapping, vmid_v=self.vmid_v, baseline_sigma_v=self.baseline_sigma_v, target_voltage_v=float(self.target_voltage_v),
            plateau_voltage_v=self.plateau_voltage_v, initial_amplitude_v=self.initial_amplitude_v,
            capture_start_time_s=self.capture_start_time_s, release_time_s=self.release_time_s,
            recording_duration_s=event[-1].relative_time_s, total_samples=len(event), fit_samples=len(candidates),
            fit_wall_time_origin_s=wall_origin_s, fit_connected_time_origin_s=connected_origin_s,
            alpha_sample_regression=alpha_within, alpha_sample_pairwise_median=pair_median, alpha_sample_pairwise_mad=pair_mad,
            alpha_sample_pairwise_mean=float(np.mean(pair_rates)) if pair_rates else None, alpha_sample_pairwise_std=float(np.std(pair_rates)) if pair_rates else None,
            alpha_within_burst=alpha_within, alpha_burst_boundary=alpha_boundary,
            alpha_full_mux_selection=alpha_full_selection, fit_quality_valid=fit_valid,
            timing_quality_valid=timing_valid, event_quality_valid=event_valid,
            tau_wall_s=tau_wall, tau_on_estimated_s=tau_on, connected_equivalent_resistance_ohm=resistance,
            capacitance_estimated_f=capacitance, fitted_amplitude_v=fitted_amplitude,
            fitted_baseline_v=fitted_baseline, fitted_decay_rate_per_s=connected_rate,
            r_squared=r_squared, rmse_voltage_v=rmse, timing=context, acquisition_configuration=self.acquisition_configuration,
            quality_status=quality, warnings=unique_warnings)
