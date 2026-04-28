"""
Streaming signal integration for 5-channel piezoelectric sensor packages.

This module owns the first two stages of the Shear & Pressure Map pipeline:
DC bias removal and rectangular-window integration. It is intentionally GUI
independent so it can be unit-tested with synthetic waveforms and reused by the
PyQt evaluation tab. The preferred DC-removal path uses SciPy's first-order
Butterworth high-pass filter with per-channel streaming state; a running-mean
fallback is included for environments where SciPy is unavailable.

Usage:
    integrator = SignalIntegrator(sample_rate_hz=1000.0)
    outputs = integrator.process({0: samples_t, 1: samples_b})

Dependencies:
    numpy, scipy.signal when available, and constants.pressure_map for defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Hashable, Mapping, Sequence

import numpy as np

from constants.pressure_map import (
    DEFAULT_HPF_CUTOFF_HZ,
    DEFAULT_INTEGRATION_SCALE_BY_DT,
    DEFAULT_INTEGRATION_WINDOW_SAMPLES,
    SIGNAL_INTEGRATION_CHANNEL_COUNT,
    SIGNAL_INTEGRATION_DISABLED_HPF_CUTOFF_HZ,
    SIGNAL_INTEGRATION_FALLBACK_MEAN_WINDOW_MULTIPLIER,
    SIGNAL_INTEGRATION_HPF_FILTER_ORDER,
    SIGNAL_INTEGRATION_WINDOW_MIN_SAMPLES,
)

try:
    from scipy.signal import butter, sosfilt, sosfilt_zi

    SCIPY_SIGNAL_INTEGRATION_AVAILABLE = True
except Exception:
    SCIPY_SIGNAL_INTEGRATION_AVAILABLE = False


@dataclass(slots=True)
class _ChannelIntegratorState:
    """Mutable per-channel state for streaming filtering and integration."""

    filter_zi: np.ndarray | None = None
    integration_history: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float64))
    fallback_raw_history: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float64))
    current_integrated_value: float = 0.0


class SignalIntegrator:
    """Remove DC bias and integrate streaming piezoelectric sensor samples.

    Each input channel owns an independent high-pass filter state and moving-sum
    history. By default the integrated value is a raw rectangular sum rather
    than a time-scaled integral; this preserves the relative channel amplitudes
    expected by later calibration stages. Set ``scale_by_dt=True`` to multiply
    each sum by ``1 / sample_rate_hz`` when physical time scaling is desired.

    Args:
        channel_count: Number of channel streams the integrator should manage.
        hpf_cutoff_hz: High-pass cutoff used for DC-bias removal. A cutoff of
            ``SIGNAL_INTEGRATION_DISABLED_HPF_CUTOFF_HZ`` disables filtering.
        integration_window_samples: Number of filtered samples in the
            rectangular moving-sum integration window.
        sample_rate_hz: Optional initial per-channel sample rate used for HPF
            coefficient design. It can also be supplied on each ``process`` call.
        channel_map: Optional map from input channel index to position label.
            When provided, output dictionaries are keyed by those labels.
        scale_by_dt: Whether to multiply moving sums by ``1 / sample_rate_hz``.

    Usage example:
        integrator = SignalIntegrator(channel_map={0: "T", 1: "B"})
        integrated = integrator.process({0: top_samples, 1: bottom_samples}, 1000.0)

    Raises:
        ValueError: If channel count, sample rate, cutoff, or integration
            window parameters are outside supported ranges.
    """

    def __init__(
        self,
        channel_count: int = SIGNAL_INTEGRATION_CHANNEL_COUNT,
        hpf_cutoff_hz: float = DEFAULT_HPF_CUTOFF_HZ,
        integration_window_samples: int = DEFAULT_INTEGRATION_WINDOW_SAMPLES,
        sample_rate_hz: float | None = None,
        channel_map: Mapping[int, Hashable] | Sequence[Hashable] | None = None,
        scale_by_dt: bool = DEFAULT_INTEGRATION_SCALE_BY_DT,
    ) -> None:
        self.channel_count = self._validate_channel_count(channel_count)
        self.hpf_cutoff_hz = float(hpf_cutoff_hz)
        self.integration_window_samples = self._validate_window_size(integration_window_samples)
        self.sample_rate_hz = self._validate_optional_sample_rate(sample_rate_hz)
        self.scale_by_dt = bool(scale_by_dt)

        self._channel_map: dict[int, Hashable] | None = None
        self.set_channel_map(channel_map)

        self._sos: np.ndarray | None = None
        self._filter_signature: tuple[float, float] | None = None
        self._states: dict[int, _ChannelIntegratorState] = {
            channel_index: _ChannelIntegratorState()
            for channel_index in range(self.channel_count)
        }

        if self.sample_rate_hz is not None and self._is_hpf_enabled():
            self._ensure_filter_design()

    def set_channel_map(
        self,
        channel_map: Mapping[int, Hashable] | Sequence[Hashable] | None,
    ) -> None:
        """Set or clear the input-channel to output-label map.

        Args:
            channel_map: Mapping keyed by input channel index, sequence ordered
                by input channel index, or ``None`` to use integer output keys.

        Returns:
            None.

        Raises:
            ValueError: If a mapped channel index is out of range.
        """
        if channel_map is None:
            self._channel_map = None
            return

        if isinstance(channel_map, Mapping):
            normalized = {int(index): label for index, label in channel_map.items()}
        else:
            normalized = {
                channel_index: label
                for channel_index, label in enumerate(channel_map)
            }

        for channel_index in normalized:
            self._validate_channel_index(channel_index)

        self._channel_map = normalized

    def update_parameters(
        self,
        *,
        hpf_cutoff_hz: float | None = None,
        integration_window_samples: int | None = None,
        sample_rate_hz: float | None = None,
        channel_map: Mapping[int, Hashable] | Sequence[Hashable] | None = None,
        scale_by_dt: bool | None = None,
    ) -> None:
        """Update runtime parameters without discarding integration histories.

        Existing per-channel moving-sum histories are trimmed only when the new
        integration window is smaller. Filter states are reset when the HPF
        cutoff or sample rate changes because old IIR state is tied to the old
        coefficient set.

        Args:
            hpf_cutoff_hz: Optional replacement high-pass cutoff in Hz.
            integration_window_samples: Optional replacement moving-sum window.
            sample_rate_hz: Optional replacement sample rate in Hz.
            channel_map: Optional replacement channel label map.
            scale_by_dt: Optional replacement time-scaling mode.

        Returns:
            None.

        Raises:
            ValueError: If any supplied parameter is outside supported ranges.
        """
        filter_parameters_changed = False

        if hpf_cutoff_hz is not None:
            next_cutoff = float(hpf_cutoff_hz)
            if next_cutoff != self.hpf_cutoff_hz:
                self.hpf_cutoff_hz = next_cutoff
                filter_parameters_changed = True

        if sample_rate_hz is not None:
            next_sample_rate = self._validate_optional_sample_rate(sample_rate_hz)
            if next_sample_rate != self.sample_rate_hz:
                self.sample_rate_hz = next_sample_rate
                filter_parameters_changed = True

        if integration_window_samples is not None:
            next_window = self._validate_window_size(integration_window_samples)
            if next_window != self.integration_window_samples:
                self.integration_window_samples = next_window
                self._trim_integration_histories()

        if channel_map is not None:
            self.set_channel_map(channel_map)

        if scale_by_dt is not None:
            self.scale_by_dt = bool(scale_by_dt)

        if filter_parameters_changed:
            self._filter_signature = None
            self._sos = None
            self._reset_filter_states()
            if self.sample_rate_hz is not None and self._is_hpf_enabled():
                self._ensure_filter_design()

    def reset(self) -> None:
        """Clear filter states, integration histories, and current values.

        Args:
            None.

        Returns:
            None.

        Raises:
            None.
        """
        for channel_index in range(self.channel_count):
            self._states[channel_index] = _ChannelIntegratorState()
        self._filter_signature = None
        self._sos = None
        if self.sample_rate_hz is not None and self._is_hpf_enabled():
            self._ensure_filter_design()

    def process(
        self,
        samples_by_channel: Mapping[int, Sequence[float] | np.ndarray] | Sequence[Sequence[float] | np.ndarray],
        sample_rate_hz: float | None = None,
    ) -> dict[Hashable, np.ndarray]:
        """Filter and integrate a streaming batch for each provided channel.

        The returned arrays have the same length as their corresponding input
        arrays. The moving-sum window spans across calls, so callers may pass
        small hardware-sized batches without resetting the signal history.

        Args:
            samples_by_channel: Dict keyed by input channel index, or a sequence
                ordered by input channel index. Values are one-dimensional sample
                arrays for each channel.
            sample_rate_hz: Optional per-channel sample rate in Hz for this
                batch. Required before HPF processing can run.

        Returns:
            Dictionary of integrated output arrays keyed by channel index or by
            sensor-position label when ``channel_map`` is configured.

        Raises:
            ValueError: If HPF is enabled without a valid sample rate, if a
                cutoff is at or above Nyquist, or if channel indices are invalid.
        """
        if sample_rate_hz is not None:
            self.update_parameters(sample_rate_hz=sample_rate_hz)

        if self._is_hpf_enabled():
            self._ensure_filter_design()

        normalized_samples = self._normalize_samples(samples_by_channel)
        integrated_by_key: dict[Hashable, np.ndarray] = {}

        for channel_index, raw_samples in normalized_samples.items():
            self._validate_channel_index(channel_index)
            samples = np.asarray(raw_samples, dtype=np.float64).reshape(-1)
            if samples.size == 0:
                integrated_by_key[self._output_key(channel_index)] = np.empty(0, dtype=np.float64)
                continue

            filtered_samples = self._remove_dc(channel_index, samples)
            integrated_samples = self._integrate_filtered_samples(channel_index, filtered_samples)
            integrated_by_key[self._output_key(channel_index)] = integrated_samples

        return integrated_by_key

    def get_current_values(self) -> dict[Hashable, float]:
        """Return the latest integrated scalar for every managed channel.

        Args:
            None.

        Returns:
            Dictionary keyed by channel index or by sensor-position label when
            ``channel_map`` is configured. Channels that have not received data
            return ``0.0``.

        Raises:
            None.
        """
        return {
            self._output_key(channel_index): float(state.current_integrated_value)
            for channel_index, state in self._states.items()
        }

    @staticmethod
    def _validate_channel_count(channel_count: int) -> int:
        count = int(channel_count)
        if count < SIGNAL_INTEGRATION_WINDOW_MIN_SAMPLES:
            raise ValueError("channel_count must be at least 1.")
        return count

    @staticmethod
    def _validate_window_size(integration_window_samples: int) -> int:
        window = int(integration_window_samples)
        if window < SIGNAL_INTEGRATION_WINDOW_MIN_SAMPLES:
            raise ValueError("integration_window_samples must be at least 1.")
        return window

    @staticmethod
    def _validate_optional_sample_rate(sample_rate_hz: float | None) -> float | None:
        if sample_rate_hz is None:
            return None
        sample_rate = float(sample_rate_hz)
        if sample_rate <= 0.0:
            raise ValueError("sample_rate_hz must be greater than zero.")
        return sample_rate

    def _validate_channel_index(self, channel_index: int) -> None:
        if channel_index < 0 or channel_index >= self.channel_count:
            raise ValueError(f"channel index {channel_index} is outside 0..{self.channel_count - 1}.")

    def _normalize_samples(
        self,
        samples_by_channel: Mapping[int, Sequence[float] | np.ndarray] | Sequence[Sequence[float] | np.ndarray],
    ) -> dict[int, Sequence[float] | np.ndarray]:
        if isinstance(samples_by_channel, Mapping):
            return {int(index): samples for index, samples in samples_by_channel.items()}
        return {
            channel_index: samples
            for channel_index, samples in enumerate(samples_by_channel)
        }

    def _output_key(self, channel_index: int) -> Hashable:
        if self._channel_map is None:
            return channel_index
        return self._channel_map.get(channel_index, channel_index)

    def _is_hpf_enabled(self) -> bool:
        return self.hpf_cutoff_hz > SIGNAL_INTEGRATION_DISABLED_HPF_CUTOFF_HZ

    def _ensure_filter_design(self) -> None:
        if not self._is_hpf_enabled():
            self._sos = None
            self._filter_signature = None
            return

        if self.sample_rate_hz is None:
            raise ValueError("sample_rate_hz is required when HPF is enabled.")

        nyquist_hz = self.sample_rate_hz / 2.0
        if self.hpf_cutoff_hz >= nyquist_hz:
            raise ValueError("hpf_cutoff_hz must be below Nyquist frequency.")

        signature = (float(self.hpf_cutoff_hz), float(self.sample_rate_hz))
        if signature == self._filter_signature:
            return

        if SCIPY_SIGNAL_INTEGRATION_AVAILABLE:
            normalized_cutoff = self.hpf_cutoff_hz / nyquist_hz
            self._sos = butter(
                SIGNAL_INTEGRATION_HPF_FILTER_ORDER,
                normalized_cutoff,
                btype="highpass",
                output="sos",
            )
        else:
            self._sos = None

        self._filter_signature = signature
        self._reset_filter_states()

    def _reset_filter_states(self) -> None:
        for state in self._states.values():
            state.filter_zi = None
            state.fallback_raw_history = np.empty(0, dtype=np.float64)

    def _remove_dc(self, channel_index: int, samples: np.ndarray) -> np.ndarray:
        if not self._is_hpf_enabled():
            return samples.copy()

        if SCIPY_SIGNAL_INTEGRATION_AVAILABLE and self._sos is not None:
            return self._remove_dc_with_scipy(channel_index, samples)

        return self._remove_dc_with_running_mean(channel_index, samples)

    def _remove_dc_with_scipy(self, channel_index: int, samples: np.ndarray) -> np.ndarray:
        state = self._states[channel_index]
        if state.filter_zi is None:
            # Initialize the IIR state at the first observed sample. For a DC
            # biased piezo signal this starts the high-pass filter at steady
            # state, preventing the integration stage from seeing a startup ramp.
            state.filter_zi = sosfilt_zi(self._sos) * float(samples[0])

        filtered, final_zi = sosfilt(self._sos, samples, zi=state.filter_zi)
        state.filter_zi = final_zi
        return np.asarray(filtered, dtype=np.float64)

    def _remove_dc_with_running_mean(self, channel_index: int, samples: np.ndarray) -> np.ndarray:
        state = self._states[channel_index]
        mean_window_samples = max(
            self.integration_window_samples * SIGNAL_INTEGRATION_FALLBACK_MEAN_WINDOW_MULTIPLIER,
            self.integration_window_samples,
        )
        history = state.fallback_raw_history
        combined = np.concatenate([history, samples]) if history.size else samples.copy()

        cumsum = np.concatenate([np.zeros(1, dtype=np.float64), np.cumsum(combined)])
        end_positions = np.arange(history.size, history.size + samples.size)
        start_positions = np.maximum(0, end_positions - mean_window_samples + 1)
        window_lengths = end_positions - start_positions + 1
        running_mean = (cumsum[end_positions + 1] - cumsum[start_positions]) / window_lengths

        keep_count = max(0, mean_window_samples - 1)
        state.fallback_raw_history = combined[-keep_count:].copy() if keep_count else np.empty(0, dtype=np.float64)
        return samples - running_mean

    def _integrate_filtered_samples(self, channel_index: int, filtered_samples: np.ndarray) -> np.ndarray:
        state = self._states[channel_index]
        history = state.integration_history
        combined = np.concatenate([history, filtered_samples]) if history.size else filtered_samples.copy()

        # Piezoelectric elements respond to changes in force/charge. After DC
        # removal, summing the recent filtered samples approximates charge over
        # the integration window. The default deliberately omits dt scaling so
        # later calibration can compare relative channel impulses in raw units.
        cumsum = np.concatenate([np.zeros(1, dtype=np.float64), np.cumsum(combined)])
        end_positions = np.arange(history.size, history.size + filtered_samples.size)
        start_positions = np.maximum(0, end_positions - self.integration_window_samples + 1)
        integrated = cumsum[end_positions + 1] - cumsum[start_positions]

        if self.scale_by_dt:
            if self.sample_rate_hz is None:
                raise ValueError("sample_rate_hz is required when scale_by_dt is enabled.")
            integrated = integrated / self.sample_rate_hz

        keep_count = max(0, self.integration_window_samples - 1)
        state.integration_history = combined[-keep_count:].copy() if keep_count else np.empty(0, dtype=np.float64)
        state.current_integrated_value = float(integrated[-1]) if integrated.size else state.current_integrated_value
        return np.asarray(integrated, dtype=np.float64)

    def _trim_integration_histories(self) -> None:
        keep_count = max(0, self.integration_window_samples - 1)
        for state in self._states.values():
            if keep_count:
                state.integration_history = state.integration_history[-keep_count:].copy()
            else:
                state.integration_history = np.empty(0, dtype=np.float64)

