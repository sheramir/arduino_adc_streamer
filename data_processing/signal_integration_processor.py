"""
Streaming signal integration processor for live ADC acquisition blocks.

This mixin keeps the standalone ``SignalIntegrator`` wired into the application
state so live pressure-map refreshes can consume small rolling display buffers
instead of rebuilding the integrated window from the raw ADC ring on every
frame.

Dependencies:
    numpy, config channel utilities, constants modules, and
    data_processing.signal_integrator.
"""

from __future__ import annotations

import time
import math
from collections import deque
from typing import Hashable, Iterable

import numpy as np

from config.channel_utils import unique_channels_in_order
from constants.plotting import IADC_RESOLUTION_BITS, MICROSECONDS_PER_SECOND
from constants.sensor_config import (
    SENSOR_POLARITY_NORMAL_MULTIPLIER,
    SENSOR_POLARITY_REVERSED_MULTIPLIER,
)
from constants.signal_integration import (
    DEFAULT_DISPLAY_WINDOW_SEC,
    DEFAULT_HPF_CUTOFF_HZ,
    DEFAULT_INTEGRATION_SCALE_BY_DT,
    DEFAULT_INTEGRATION_WINDOW_SAMPLES,
    SIGNAL_INTEGRATION_CHANNEL_COUNT,
    SIGNAL_INTEGRATION_DISPLAY_BUFFER_MARGIN_SAMPLES,
    SIGNAL_INTEGRATION_DISPLAY_SAMPLE_RATE_FALLBACK_HZ,
    SIGNAL_INTEGRATION_DISPLAY_WINDOW_MIN_SEC,
    SIGNAL_INTEGRATION_GROUND_CHANNEL_INDEX,
    SIGNAL_INTEGRATION_MAX_TOTAL_POINTS_TO_DISPLAY,
    SIGNAL_INTEGRATION_PLOT_UPDATE_INTERVAL_SEC,
    SIGNAL_INTEGRATION_POSITION_ORDER,
    SIGNAL_INTEGRATION_PZT1_MUX_COUNT,
)
from data_processing.signal_integrator import SignalIntegrator


SIGNAL_INTEGRATION_SAMPLE_RATE_TOLERANCE_FRACTION = 0.005


class SignalIntegrationProcessorMixin:
    """Own dormant integration state for the first 5-channel sensor package.

    The mixin is intended for ``ADCStreamerGUI`` and assumes the owner provides
    configuration helpers such as ``get_sensor_package_groups`` and
    ``get_active_channel_sensor_map``. Its processing methods remain testable
    but are intentionally not invoked by live acquisition in the raw-preview
    phase.

    Usage example:
        self._init_signal_integration_state()
        self.process_signal_integration_block(block, timestamps, avg_dt_us)
    """

    def _init_signal_integration_state(self) -> None:
        self.signal_integration_hpf_cutoff_hz = DEFAULT_HPF_CUTOFF_HZ
        self.signal_integration_window_samples = DEFAULT_INTEGRATION_WINDOW_SAMPLES
        self.signal_integration_display_window_sec = DEFAULT_DISPLAY_WINDOW_SEC
        self.signal_integrator: SignalIntegrator | None = None
        self.signal_integration_display_buffers: dict[Hashable, dict[str, deque]] = {}
        self.signal_integration_display_sample_rate_hz = 0.0
        self.signal_integration_display_decimation = 1
        self._signal_integration_display_sample_counters: dict[Hashable, int] = {}
        self._signal_integration_display_buffer_capacity = self._calculate_signal_integration_display_capacity()
        self._signal_integration_data_signature = None
        self._signal_integration_last_error = ""
        self._signal_integration_latest_sweep_time_sec: float | None = None
        self._signal_integration_stable_sample_rate_hz: float | None = None
        self._last_signal_integration_plot_update_time = 0.0
        self.reset_signal_integration_state(clear_display=True)

    def reset_signal_integration_state(self, *, clear_display: bool = True) -> None:
        """Reset streaming integration state for the current sensor mapping.

        Args:
            clear_display: When ``True``, also clears the rolling plot buffers.

        Returns:
            None.

        Raises:
            ValueError: If the configured integration defaults are invalid.
        """
        channel_map = self._build_signal_integration_channel_map()
        self.signal_integrator = SignalIntegrator(
            channel_count=SIGNAL_INTEGRATION_CHANNEL_COUNT,
            hpf_cutoff_hz=float(self.signal_integration_hpf_cutoff_hz),
            integration_window_samples=int(self.signal_integration_window_samples),
            channel_map=channel_map,
            scale_by_dt=DEFAULT_INTEGRATION_SCALE_BY_DT,
        )
        self._signal_integration_data_signature = None
        self._signal_integration_last_error = ""
        self._signal_integration_latest_sweep_time_sec = None
        self._signal_integration_stable_sample_rate_hz = None

        if clear_display:
            self._clear_signal_integration_display_buffers()
            self._signal_integration_display_sample_counters = {}

    def apply_signal_integration_settings(
        self,
        *,
        hpf_cutoff_hz: float,
        integration_window_samples: int,
        display_window_sec: float,
    ) -> None:
        """Apply runtime settings from the Signal Integration evaluation tab.

        Args:
            hpf_cutoff_hz: High-pass cutoff in Hz. Use zero to disable HPF.
            integration_window_samples: Moving-sum integration window length.
            display_window_sec: Rolling plot window in seconds.

        Returns:
            None.

        Raises:
            ValueError: If the integrator rejects the cutoff, sample rate, or
                integration window.
        """
        self.signal_integration_hpf_cutoff_hz = float(hpf_cutoff_hz)
        self.signal_integration_window_samples = int(integration_window_samples)
        self.signal_integration_display_window_sec = max(
            SIGNAL_INTEGRATION_DISPLAY_WINDOW_MIN_SEC,
            float(display_window_sec),
        )
        self._refresh_signal_integration_display_buffer_shape()

        if self.signal_integrator is None:
            self.reset_signal_integration_state(clear_display=False)
            return

        self.signal_integrator.update_parameters(
            hpf_cutoff_hz=self.signal_integration_hpf_cutoff_hz,
            integration_window_samples=self.signal_integration_window_samples,
            channel_map=self._build_signal_integration_channel_map(),
            scale_by_dt=DEFAULT_INTEGRATION_SCALE_BY_DT,
        )
        self._prune_signal_integration_display_buffers()

    def process_signal_integration_block(
        self,
        block_samples_array: np.ndarray,
        sweep_timestamps_sec: np.ndarray,
        avg_sample_time_us: float,
    ) -> bool:
        """Process one incoming ADC block through the SignalIntegrator.

        Args:
            block_samples_array: Two-dimensional block with shape
                ``(sweeps_in_block, samples_per_sweep)``.
            sweep_timestamps_sec: Timestamp for the first physical sample in
                each sweep, in seconds from capture start.
            avg_sample_time_us: Average physical sample interval reported by
                the MCU in microseconds.

        Returns:
            ``True`` when a valid signal-integration batch was processed;
            otherwise ``False``.

        Raises:
            None. Recoverable extraction and filtering errors are logged through
            the owning GUI when a ``log_status`` method is available.
        """
        try:
            batch = self._build_signal_integration_batch(
                block_samples_array,
                sweep_timestamps_sec,
                avg_sample_time_us,
            )
            if batch is None:
                return False

            signature = batch["signature"]
            if signature != self._signal_integration_data_signature:
                self.reset_signal_integration_state(clear_display=True)
                self._signal_integration_data_signature = signature

            if self.signal_integrator is None:
                self.reset_signal_integration_state(clear_display=True)

            channel_map = batch["channel_map"]
            sample_rate_hz = self._stable_signal_integration_sample_rate(float(batch["sample_rate_hz"]))
            self._refresh_signal_integration_display_buffer_shape(sample_rate_hz=sample_rate_hz)
            self.signal_integrator.update_parameters(channel_map=channel_map)
            integrated_outputs = self.signal_integrator.process(
                batch["samples_by_channel"],
                sample_rate_hz=sample_rate_hz,
            )

            self._append_signal_integration_outputs(
                integrated_outputs,
                batch["times_by_channel"],
                channel_map,
            )
            self._signal_integration_latest_sweep_time_sec = float(np.max(sweep_timestamps_sec))
            self._signal_integration_last_error = ""
            self._maybe_update_signal_integration_plot()
            return True
        except Exception as exc:
            message = f"Signal integration unavailable: {exc}"
            if message != self._signal_integration_last_error:
                self._signal_integration_last_error = message
                if hasattr(self, "log_status"):
                    self.log_status(message)
            return False

    def get_signal_integration_display_snapshot(
        self,
        labels: Iterable[Hashable] | None = None,
    ) -> dict[Hashable, tuple[np.ndarray, np.ndarray]]:
        """Return a copy of rolling display buffers for plotting.

        Args:
            labels: Optional subset of labels to copy. Supplying only visible
                labels keeps GUI refreshes from converting hidden channel
                buffers into numpy arrays.

        Returns:
            Dictionary keyed by sensor-position label. Each value is a
            ``(times_sec, integrated_values)`` tuple.

        Raises:
            None.
        """
        requested_labels = set(labels) if labels is not None else None
        snapshot: dict[Hashable, tuple[np.ndarray, np.ndarray]] = {}
        for label, buffers in self.signal_integration_display_buffers.items():
            if requested_labels is not None and label not in requested_labels:
                continue
            snapshot[label] = (
                np.asarray(buffers["time"], dtype=np.float64),
                np.asarray(buffers["value"], dtype=np.float64),
            )
        return snapshot

    def get_signal_integration_current_values(self) -> dict[Hashable, float]:
        """Return latest integrated scalar values from the streaming integrator.

        Args:
            None.

        Returns:
            Dictionary keyed by sensor-position label with the latest integrated
            value for each managed channel.

        Raises:
            None.
        """
        if self.signal_integrator is None:
            return {}
        return self.signal_integrator.get_current_values()

    def get_signal_integration_current_display_values(self) -> dict[Hashable, float]:
        """Return latest integrated values after display polarity is applied."""
        current_values = self.get_signal_integration_current_values()
        return {
            label: float(self._apply_signal_integration_polarity(np.asarray([value], dtype=np.float64))[0])
            for label, value in current_values.items()
        }

    def _stable_signal_integration_sample_rate(self, sample_rate_hz: float) -> float:
        sample_rate = float(sample_rate_hz)
        previous = self._signal_integration_stable_sample_rate_hz
        if previous is None or previous <= 0.0:
            self._signal_integration_stable_sample_rate_hz = sample_rate
            return sample_rate

        relative_change = abs(sample_rate - previous) / max(abs(previous), 1e-12)
        if relative_change <= SIGNAL_INTEGRATION_SAMPLE_RATE_TOLERANCE_FRACTION:
            return float(previous)

        self._signal_integration_stable_sample_rate_hz = sample_rate
        return sample_rate

    def _build_signal_integration_channel_map(self) -> dict[int, Hashable]:
        if hasattr(self, "get_active_channel_sensor_map"):
            raw_map = self.get_active_channel_sensor_map()
        else:
            raw_map = list(SIGNAL_INTEGRATION_POSITION_ORDER)

        normalized = [
            str(label).strip().upper()
            for label in list(raw_map)[:SIGNAL_INTEGRATION_CHANNEL_COUNT]
        ]
        if len(normalized) != SIGNAL_INTEGRATION_CHANNEL_COUNT:
            normalized = list(SIGNAL_INTEGRATION_POSITION_ORDER)

        return {
            channel_index: normalized[channel_index]
            for channel_index in range(SIGNAL_INTEGRATION_CHANNEL_COUNT)
        }

    def _clear_signal_integration_display_buffers(self) -> None:
        self.signal_integration_display_buffers = {
            label: self._new_signal_integration_display_buffer()
            for label in SIGNAL_INTEGRATION_POSITION_ORDER
        }

    def _ensure_signal_integration_display_buffer(self, label: Hashable) -> dict[str, deque]:
        if label not in self.signal_integration_display_buffers:
            self.signal_integration_display_buffers[label] = self._new_signal_integration_display_buffer()
        return self.signal_integration_display_buffers[label]

    def _new_signal_integration_display_buffer(self) -> dict[str, deque]:
        return {
            "time": deque(maxlen=self._signal_integration_display_buffer_capacity),
            "value": deque(maxlen=self._signal_integration_display_buffer_capacity),
        }

    def _calculate_signal_integration_display_capacity(self, sample_rate_hz: float | None = None) -> int:
        _ = sample_rate_hz
        max_points_per_channel = self._signal_integration_max_points_per_channel()
        return max(
            SIGNAL_INTEGRATION_CHANNEL_COUNT,
            max_points_per_channel + SIGNAL_INTEGRATION_DISPLAY_BUFFER_MARGIN_SAMPLES,
        )

    def _calculate_signal_integration_display_decimation(self, sample_rate_hz: float | None = None) -> int:
        effective_rate_hz = float(
            sample_rate_hz
            or self.signal_integration_display_sample_rate_hz
            or SIGNAL_INTEGRATION_DISPLAY_SAMPLE_RATE_FALLBACK_HZ
        )
        display_window_sec = max(
            SIGNAL_INTEGRATION_DISPLAY_WINDOW_MIN_SEC,
            float(self.signal_integration_display_window_sec),
        )
        estimated_window_samples = max(1, int(math.ceil(display_window_sec * effective_rate_hz)))
        return max(1, int(math.ceil(estimated_window_samples / self._signal_integration_max_points_per_channel())))

    def _signal_integration_max_points_per_channel(self) -> int:
        return max(
            SIGNAL_INTEGRATION_CHANNEL_COUNT,
            int(SIGNAL_INTEGRATION_MAX_TOTAL_POINTS_TO_DISPLAY // SIGNAL_INTEGRATION_CHANNEL_COUNT),
        )

    def _refresh_signal_integration_display_buffer_shape(self, sample_rate_hz: float | None = None) -> None:
        if sample_rate_hz is not None and float(sample_rate_hz) > 0.0:
            self.signal_integration_display_sample_rate_hz = float(sample_rate_hz)
        self.signal_integration_display_decimation = self._calculate_signal_integration_display_decimation()
        self._refresh_signal_integration_display_buffer_capacity()

    def _refresh_signal_integration_display_buffer_capacity(self, sample_rate_hz: float | None = None) -> None:
        if sample_rate_hz is not None and float(sample_rate_hz) > 0.0:
            self.signal_integration_display_sample_rate_hz = float(sample_rate_hz)

        next_capacity = self._calculate_signal_integration_display_capacity()
        if next_capacity == self._signal_integration_display_buffer_capacity:
            return

        self._signal_integration_display_buffer_capacity = next_capacity
        for label, buffers in list(self.signal_integration_display_buffers.items()):
            times = list(buffers["time"])[-next_capacity:]
            values = list(buffers["value"])[-next_capacity:]
            sample_count = min(len(times), len(values))
            self.signal_integration_display_buffers[label] = {
                "time": deque(times[-sample_count:], maxlen=next_capacity),
                "value": deque(values[-sample_count:], maxlen=next_capacity),
            }

    def _build_signal_integration_batch(
        self,
        block_samples_array: np.ndarray,
        sweep_timestamps_sec: np.ndarray,
        avg_sample_time_us: float,
    ) -> dict[str, object] | None:
        block = np.asarray(block_samples_array, dtype=np.float64)
        timestamps = np.asarray(sweep_timestamps_sec, dtype=np.float64).reshape(-1)

        if block.ndim != 2 or block.shape[0] == 0 or timestamps.size != block.shape[0]:
            return None

        sample_interval_sec = float(avg_sample_time_us) / MICROSECONDS_PER_SECOND
        if sample_interval_sec <= 0.0:
            return None

        channels = list(self.config.get("channels", [])) if hasattr(self, "config") else []
        repeat_count = max(1, int(self.config.get("repeat", 1))) if hasattr(self, "config") else 1
        group = self._get_first_signal_integration_group(channels)
        if group is None:
            return None

        sample_indices_by_channel = self._build_signal_integration_sample_indices(
            group,
            channels,
            repeat_count,
            block.shape[1],
        )
        if len(sample_indices_by_channel) != SIGNAL_INTEGRATION_CHANNEL_COUNT:
            return None

        samples_by_channel: dict[int, np.ndarray] = {}
        times_by_channel: dict[int, np.ndarray] = {}

        for channel_index, sample_indices in sample_indices_by_channel.items():
            index_array = np.asarray(sample_indices, dtype=np.int32)
            if index_array.size == 0 or np.max(index_array) >= block.shape[1]:
                return None

            samples_by_channel[channel_index] = self._convert_signal_integration_counts_to_voltage(
                block[:, index_array].reshape(-1)
            )
            time_matrix = timestamps.reshape(-1, 1) + (
                index_array.astype(np.float64).reshape(1, -1) * sample_interval_sec
            )
            times_by_channel[channel_index] = time_matrix.reshape(-1)

        sample_rate_hz = self._estimate_signal_integration_sample_rate(
            times_by_channel,
            channels,
            repeat_count,
            sample_interval_sec,
        )
        if sample_rate_hz <= 0.0:
            return None

        channel_map = self._build_signal_integration_channel_map()
        signature = (
            tuple(int(channel) for channel in group.get("channels", [])),
            tuple(channel_map.items()),
            int(group.get("mux", 1)),
            int(repeat_count),
            bool(self._is_signal_integration_pzt1_mode()),
            bool(self._is_signal_integration_reverse_polarity()),
        )

        return {
            "samples_by_channel": samples_by_channel,
            "times_by_channel": times_by_channel,
            "sample_rate_hz": sample_rate_hz,
            "channel_map": channel_map,
            "signature": signature,
        }

    def _convert_signal_integration_counts_to_voltage(self, adc_counts: np.ndarray) -> np.ndarray:
        max_adc_value = float((2 ** IADC_RESOLUTION_BITS) - 1)
        if hasattr(self, "get_vref_voltage"):
            vref = float(self.get_vref_voltage())
        else:
            vref = 1.0
        return (np.asarray(adc_counts, dtype=np.float64) / max_adc_value) * vref

    def _get_first_signal_integration_group(self, channels: list[int]) -> dict[str, object] | None:
        if hasattr(self, "get_sensor_package_groups"):
            groups = self.get_sensor_package_groups(SIGNAL_INTEGRATION_CHANNEL_COUNT, channels=channels)
            if groups:
                return dict(groups[0])

        unique_channels = unique_channels_in_order(channels)
        if (
            unique_channels
            and int(unique_channels[0]) == SIGNAL_INTEGRATION_GROUND_CHANNEL_INDEX
            and len(unique_channels) > SIGNAL_INTEGRATION_CHANNEL_COUNT
        ):
            unique_channels = unique_channels[1:]

        if len(unique_channels) < SIGNAL_INTEGRATION_CHANNEL_COUNT:
            return None

        return {
            "sensor_id": None,
            "mux": 1,
            "channels": unique_channels[:SIGNAL_INTEGRATION_CHANNEL_COUNT],
            "positions": [],
        }

    def _build_signal_integration_sample_indices(
        self,
        group: dict[str, object],
        channels: list[int],
        repeat_count: int,
        samples_per_sweep: int,
    ) -> dict[int, list[int]]:
        package_channels = [int(channel) for channel in group.get("channels", [])]
        package_positions = [int(position) for position in group.get("positions", [])]
        sample_indices_by_channel: dict[int, list[int]] = {}

        if self._is_signal_integration_pzt1_mode():
            unique_channels = unique_channels_in_order(channels)
            unique_channel_positions = {
                int(channel): position
                for position, channel in enumerate(unique_channels)
            }
            mux_index = max(0, int(group.get("mux", 1)) - 1)

            for local_index, channel in enumerate(package_channels[:SIGNAL_INTEGRATION_CHANNEL_COUNT]):
                unique_position = unique_channel_positions.get(channel)
                if unique_position is None:
                    continue
                base_index = unique_position * repeat_count * SIGNAL_INTEGRATION_PZT1_MUX_COUNT
                indices = [
                    base_index + (repeat_index * SIGNAL_INTEGRATION_PZT1_MUX_COUNT) + mux_index
                    for repeat_index in range(repeat_count)
                ]
                sample_indices_by_channel[local_index] = [
                    index for index in indices if 0 <= index < samples_per_sweep
                ]
            return sample_indices_by_channel

        for local_index, channel in enumerate(package_channels[:SIGNAL_INTEGRATION_CHANNEL_COUNT]):
            sequence_positions: list[int]
            if package_positions and local_index < len(package_positions):
                sequence_positions = [package_positions[local_index]]
            else:
                sequence_positions = [
                    sequence_index
                    for sequence_index, sequence_channel in enumerate(channels)
                    if int(sequence_channel) == int(channel)
                ]

            indices: list[int] = []
            for sequence_position in sequence_positions:
                base_index = sequence_position * repeat_count
                indices.extend(
                    base_index + repeat_index
                    for repeat_index in range(repeat_count)
                )
            sample_indices_by_channel[local_index] = [
                index for index in indices if 0 <= index < samples_per_sweep
            ]

        return sample_indices_by_channel

    def _estimate_signal_integration_sample_rate(
        self,
        times_by_channel: dict[int, np.ndarray],
        channels: list[int],
        repeat_count: int,
        sample_interval_sec: float,
    ) -> float:
        rates_hz: list[float] = []
        for sample_times in times_by_channel.values():
            diffs = np.diff(sample_times)
            positive_diffs = diffs[diffs > 0.0]
            if positive_diffs.size > 0:
                rates_hz.append(1.0 / float(np.median(positive_diffs)))

        if rates_hz:
            return float(np.median(np.asarray(rates_hz, dtype=np.float64)))

        total_sample_rate_hz = 1.0 / sample_interval_sec
        sequence_length = max(1, len(channels))
        return float(total_sample_rate_hz / sequence_length)

    def _is_signal_integration_pzt1_mode(self) -> bool:
        if hasattr(self, "is_array_pzt1_mode"):
            return bool(self.is_array_pzt1_mode())
        return False

    def _is_signal_integration_reverse_polarity(self) -> bool:
        if hasattr(self, "is_active_sensor_reverse_polarity"):
            return bool(self.is_active_sensor_reverse_polarity())
        return False

    def _apply_signal_integration_polarity(self, values: np.ndarray) -> np.ndarray:
        samples = np.asarray(values, dtype=np.float64)
        multiplier = (
            SENSOR_POLARITY_REVERSED_MULTIPLIER
            if self._is_signal_integration_reverse_polarity()
            else SENSOR_POLARITY_NORMAL_MULTIPLIER
        )
        return samples * multiplier

    def _append_signal_integration_outputs(
        self,
        integrated_outputs: dict[Hashable, np.ndarray],
        times_by_channel: dict[int, np.ndarray],
        channel_map: dict[int, Hashable],
    ) -> None:
        for channel_index, label in channel_map.items():
            values = integrated_outputs.get(label)
            sample_times = times_by_channel.get(channel_index)
            if values is None or sample_times is None:
                continue

            value_array = np.asarray(values, dtype=np.float64).reshape(-1)
            value_array = self._apply_signal_integration_polarity(value_array)
            time_array = np.asarray(sample_times, dtype=np.float64).reshape(-1)
            sample_count = min(value_array.size, time_array.size)
            if sample_count <= 0:
                continue

            value_array, time_array = self._decimate_signal_integration_display_batch(
                label,
                value_array[:sample_count],
                time_array[:sample_count],
            )
            if value_array.size == 0:
                continue

            buffers = self._ensure_signal_integration_display_buffer(label)
            buffers["time"].extend(float(value) for value in time_array)
            buffers["value"].extend(float(value) for value in value_array)

        self._prune_signal_integration_display_buffers()

    def _decimate_signal_integration_display_batch(
        self,
        label: Hashable,
        values: np.ndarray,
        times: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        decimation = max(1, int(self.signal_integration_display_decimation))
        if decimation <= 1:
            return values, times

        sample_count = min(values.size, times.size)
        if sample_count <= 0:
            return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)

        start_counter = int(self._signal_integration_display_sample_counters.get(label, 0))
        sample_offsets = np.arange(sample_count, dtype=np.int64)
        keep_mask = ((start_counter + sample_offsets) % decimation) == 0
        self._signal_integration_display_sample_counters[label] = start_counter + sample_count
        if not np.any(keep_mask):
            return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)
        return values[:sample_count][keep_mask], times[:sample_count][keep_mask]

    def _prune_signal_integration_display_buffers(self) -> None:
        latest_time = None
        for buffers in self.signal_integration_display_buffers.values():
            if buffers["time"]:
                candidate = float(buffers["time"][-1])
                latest_time = candidate if latest_time is None else max(latest_time, candidate)

        if latest_time is None:
            return

        cutoff_time = latest_time - max(
            SIGNAL_INTEGRATION_DISPLAY_WINDOW_MIN_SEC,
            float(self.signal_integration_display_window_sec),
        )
        for buffers in self.signal_integration_display_buffers.values():
            while buffers["time"] and float(buffers["time"][0]) < cutoff_time:
                buffers["time"].popleft()
                buffers["value"].popleft()

    def _maybe_update_signal_integration_plot(self) -> None:
        if not hasattr(self, "update_signal_integration_plot"):
            return
        if hasattr(self, "should_update_signal_integration_display"):
            if not self.should_update_signal_integration_display():
                return
        elif hasattr(self, "get_current_visualization_tab_name"):
            if self.get_current_visualization_tab_name() != "Signal Integration":
                return

        now = time.time()
        if now - self._last_signal_integration_plot_update_time < SIGNAL_INTEGRATION_PLOT_UPDATE_INTERVAL_SEC:
            return

        self._last_signal_integration_plot_update_time = now
        if hasattr(self, "trigger_signal_integration_update"):
            self.trigger_signal_integration_update()
        else:
            self.update_signal_integration_plot()
