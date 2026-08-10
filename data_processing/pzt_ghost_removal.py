"""Canonical PZT MUX ghost-removal during binary ingest."""

from __future__ import annotations

import numpy as np

from constants.pzt_ghost import (
    PZT_GHOST_ATTENUATION_MAX,
    PZT_GHOST_DEFAULT_ATTENUATION,
    PZT_GHOST_DEFAULT_ENABLED,
    PZT_GHOST_NOISE_MAD_SCALE,
)
from constants.plotting import PZR_AUTO_BASELINE_DELAY_SEC
from constants.pzt_rs import PZT_RS_OUTPUTS_PER_SENSOR


class PztGhostRemovalMixin:
    """Owns PZT ghost-removal state and transformations.

    The normal plot baseline capture is deliberately the sole median producer.
    During the initial calibration window blocks are held only long enough to
    apply that captured baseline before they are archived.
    """

    def _init_pzt_ghost_removal_state(self):
        self.pzt_ghost_removal_enabled = PZT_GHOST_DEFAULT_ENABLED
        self.pzt_ghost_attenuation = PZT_GHOST_DEFAULT_ATTENUATION
        self._pzt_ghost_baselines: np.ndarray | None = None
        self._pzt_ghost_noise: np.ndarray | None = None
        self._pzt_ghost_calibration_pending = False
        self._pzt_ghost_pending_archive_blocks: list[tuple[np.ndarray, np.ndarray]] = []
        self._pzt_ghost_next_calibration_attempt_sec = 0.0

    def is_pzt_ghost_removal_supported(self) -> bool:
        try:
            return bool(self.is_array_pzt1_mode() or self.is_array_pzt_rs_mode())
        except Exception:
            return False

    def should_remove_pzt_ghost(self) -> bool:
        return bool(self.pzt_ghost_removal_enabled and self.is_pzt_ghost_removal_supported())

    def set_pzt_ghost_removal_settings(self, enabled: bool, attenuation: float) -> None:
        self.pzt_ghost_removal_enabled = bool(enabled)
        self.pzt_ghost_attenuation = min(
            PZT_GHOST_ATTENUATION_MAX,
            max(0.0, float(attenuation)),
        )
        if not self.pzt_ghost_removal_enabled:
            self._pzt_ghost_baselines = None
            self._pzt_ghost_noise = None
            self._pzt_ghost_calibration_pending = False
            self._pzt_ghost_pending_archive_blocks = []

    def begin_pzt_ghost_capture(self) -> None:
        """Start a capture-scoped ghost baseline calibration when enabled."""
        self._pzt_ghost_baselines = None
        self._pzt_ghost_noise = None
        self._pzt_ghost_pending_archive_blocks = []
        self._pzt_ghost_calibration_pending = self.should_remove_pzt_ghost()
        self._pzt_ghost_next_calibration_attempt_sec = PZR_AUTO_BASELINE_DELAY_SEC

    def is_pzt_ghost_calibration_pending(self) -> bool:
        return bool(self.should_remove_pzt_ghost() and self._pzt_ghost_calibration_pending)

    def _get_pzt_ghost_groups(self, samples_per_sweep: int) -> list[list[int]]:
        """Return ordered PZT columns, independently for each physical MUX path."""
        width = max(0, int(samples_per_sweep))
        repeat_count = max(1, int(self.config.get('repeat', 1)))

        if hasattr(self, 'is_array_pzt_rs_mode') and self.is_array_pzt_rs_mode():
            selected_groups = []
            if hasattr(self, 'get_array_selected_sensor_groups'):
                selected_groups = [
                    group for group in self.get_array_selected_sensor_groups()
                    if str(group.get('sensor_id', '')).upper().startswith('PZT')
                ]
            sensor_count = len(selected_groups)
            if sensor_count <= 0:
                sensor_count = width // (repeat_count * PZT_RS_OUTPUTS_PER_SENSOR)
            groups = []
            for sensor_index in range(sensor_count):
                for repeat_index in range(repeat_count):
                    base = (sensor_index * repeat_count + repeat_index) * PZT_RS_OUTPUTS_PER_SENSOR
                    columns = list(range(base, base + 5))
                    if columns and columns[-1] < width:
                        groups.append(columns)
            return groups

        if hasattr(self, 'is_array_pzt1_mode') and self.is_array_pzt1_mode():
            if hasattr(self, 'get_channels_for_arduino_command'):
                channels = list(self.get_channels_for_arduino_command())
            else:
                channels = list(self.config.get('channels', []))
            channel_count = len(channels)
            groups = []
            for mux_index in range(2):
                for repeat_index in range(repeat_count):
                    columns = [
                        sequence_index * repeat_count * 2 + repeat_index * 2 + mux_index
                        for sequence_index in range(channel_count)
                    ]
                    columns = [column for column in columns if column < width]
                    if columns:
                        groups.append(columns)
            return groups

        return []

    def _pzt_ghost_baseline_array_from_plot(self, samples_per_sweep: int) -> np.ndarray | None:
        baselines = np.zeros(int(samples_per_sweep), dtype=np.float32)
        covered = np.zeros(int(samples_per_sweep), dtype=bool)
        for spec in self.get_display_channel_specs():
            baseline = self.plot_baselines.get(spec.get('key'))
            if baseline is None:
                continue
            for column in spec.get('sample_indices', []):
                if 0 <= int(column) < len(baselines):
                    baselines[int(column)] = float(baseline)
                    covered[int(column)] = True

        groups = self._get_pzt_ghost_groups(samples_per_sweep)
        required_columns = {column for group in groups for column in group}
        if not required_columns or not all(covered[column] for column in required_columns):
            return None
        return baselines

    def on_plot_baselines_captured(self, data_array=None) -> None:
        """Adopt the existing calibration/Zero Signals event for every PZT slot.

        Paired-MUX firmware emits both physical MUX sides for each pin, even
        when only one side is selected as a displayed logical sensor.  Those
        hidden columns still participate in their own MUX ghost sequence, so
        their medians must be captured from the same baseline sample window.
        """
        if not self.should_remove_pzt_ghost() or self.samples_per_sweep <= 0:
            return
        baselines = None
        noise = None
        candidate_data = None if data_array is None else np.asarray(data_array, dtype=np.float32)
        required_columns = sorted({
            column
            for group in self._get_pzt_ghost_groups(self.samples_per_sweep)
            for column in group
        })
        if (
            candidate_data is not None
            and candidate_data.ndim == 2
            and candidate_data.shape[0] > 0
            and candidate_data.shape[1] == self.samples_per_sweep
            and required_columns
        ):
            baselines = np.zeros(self.samples_per_sweep, dtype=np.float32)
            baseline_columns = np.asarray(required_columns, dtype=np.int32)
            baselines[baseline_columns] = np.median(
                candidate_data[:, baseline_columns], axis=0,
            ).astype(np.float32, copy=False)
            deviations = np.abs(candidate_data[:, baseline_columns] - baselines[baseline_columns])
            noise = np.zeros(self.samples_per_sweep, dtype=np.float32)
            noise[baseline_columns] = (
                PZT_GHOST_NOISE_MAD_SCALE * np.median(deviations, axis=0)
            ).astype(np.float32, copy=False)

        if baselines is None:
            baselines = self._pzt_ghost_baseline_array_from_plot(self.samples_per_sweep)
            if baselines is not None:
                noise = np.zeros(self.samples_per_sweep, dtype=np.float32)
        if baselines is None:
            if hasattr(self, 'log_status'):
                self.log_status('WARNING: PZT ghost removal is waiting for complete channel baselines')
            return

        was_pending = self._pzt_ghost_calibration_pending
        self._pzt_ghost_baselines = baselines
        self._pzt_ghost_noise = noise
        self._pzt_ghost_calibration_pending = False
        if was_pending:
            self._replace_retained_pzt_data_with_clean_signal()
            if hasattr(self, 'log_status'):
                self.log_status('PZT ghost-removal baseline calibrated from the startup Zero Signals window')

    def maybe_finalize_pzt_ghost_calibration(self) -> bool:
        """Use the established automatic baseline window once it is available."""
        if not self.is_pzt_ghost_calibration_pending():
            return False
        if self.sweep_timestamps_buffer is None or self.sweep_count <= 0:
            return False
        with self.buffer_lock:
            latest_index = (int(self.buffer_write_index) - 1) % self.MAX_SWEEPS_BUFFER
            latest_time = float(self.sweep_timestamps_buffer[latest_index])
        if latest_time < float(self._pzt_ghost_next_calibration_attempt_sec):
            return False

        # A failed baseline capture must not retry for every high-rate block;
        # doing so repeatedly copies the display buffer on the GUI thread.
        self._pzt_ghost_next_calibration_attempt_sec = latest_time + 0.5
        self.capture_current_plot_baselines(
            log_message=False,
            min_elapsed_sec=PZR_AUTO_BASELINE_DELAY_SEC,
        )
        return not self.is_pzt_ghost_calibration_pending()

    def finalize_pzt_ghost_calibration_at_capture_end(self) -> bool:
        """Finish a short capture using the same existing baseline routine."""
        if not self.is_pzt_ghost_calibration_pending():
            return False
        self.capture_current_plot_baselines(log_message=False, min_elapsed_sec=0.0)
        return not self.is_pzt_ghost_calibration_pending()

    def _apply_pzt_ghost_removal(self, block_data: np.ndarray) -> np.ndarray:
        data = np.asarray(block_data, dtype=np.float32).copy()
        baselines = self._pzt_ghost_baselines
        if baselines is None or data.ndim != 2 or data.shape[1] != len(baselines):
            return data
        noise = self._pzt_ghost_noise
        if noise is None or len(noise) != len(baselines):
            noise = np.zeros_like(baselines)

        attenuation = float(self.pzt_ghost_attenuation)
        for columns in self._get_pzt_ghost_groups(data.shape[1]):
            column_indices = np.asarray(columns, dtype=np.int32)
            net = data[:, columns] - baselines[column_indices]
            cleaned = net.copy()
            if len(columns) > 1:
                candidate = net[:, 1:] - attenuation * net[:, :-1]
                predecessor_above_noise = np.abs(net[:, :-1]) >= noise[column_indices[:-1]]
                crosses_vmid = (
                    ((net[:, 1:] > 0.0) & (candidate < 0.0))
                    | ((net[:, 1:] < 0.0) & (candidate > 0.0))
                )
                apply_ghost = predecessor_above_noise & ~crosses_vmid
                cleaned[:, 1:] = np.where(apply_ghost, candidate, net[:, 1:])
            data[:, columns] = cleaned
        return data

    def prepare_pzt_ghost_block(self, block_data: np.ndarray) -> np.ndarray:
        """Return the canonical block, or raw startup samples while calibrating."""
        data = np.asarray(block_data, dtype=np.float32)
        if not self.should_remove_pzt_ghost() or self._pzt_ghost_baselines is None:
            return data.copy()
        return self._apply_pzt_ghost_removal(data)

    def reconstruct_pzt_signal_for_baseline_capture(self, data_array: np.ndarray) -> np.ndarray:
        """Recover raw-equivalent PZT data temporarily for a later Zero Signals action."""
        data = np.asarray(data_array, dtype=np.float32).copy()
        baselines = self._pzt_ghost_baselines
        if not self.should_remove_pzt_ghost() or baselines is None or data.ndim != 2:
            return data
        if data.shape[1] != len(baselines):
            return data

        attenuation = float(self.pzt_ghost_attenuation)
        noise = self._pzt_ghost_noise
        if noise is None or len(noise) != len(baselines):
            noise = np.zeros_like(baselines)
        for columns in self._get_pzt_ghost_groups(data.shape[1]):
            column_indices = np.asarray(columns, dtype=np.int32)
            recovered_net = data[:, columns].copy()
            for column_index in range(1, len(columns)):
                previous_net = recovered_net[:, column_index - 1]
                observed_clean = data[:, columns[column_index]]
                proposed_net = observed_clean + attenuation * previous_net
                predecessor_above_noise = (
                    np.abs(previous_net) >= noise[column_indices[column_index - 1]]
                )
                crosses_vmid = (
                    ((proposed_net > 0.0) & (observed_clean < 0.0))
                    | ((proposed_net < 0.0) & (observed_clean > 0.0))
                )
                recovered_net[:, column_index] = np.where(
                    predecessor_above_noise & ~crosses_vmid,
                    proposed_net,
                    observed_clean,
                )
            data[:, columns] = recovered_net + baselines[column_indices]
        return data

    def _replace_retained_pzt_data_with_clean_signal(self) -> None:
        if self.raw_data_buffer is None or self._pzt_ghost_baselines is None:
            return
        with self.buffer_lock:
            actual_sweeps = min(int(self.sweep_count), int(self.MAX_SWEEPS_BUFFER))
            if actual_sweeps <= 0:
                return
            if actual_sweeps < self.MAX_SWEEPS_BUFFER:
                positions = np.arange(actual_sweeps, dtype=np.int32)
            else:
                write_pos = int(self.buffer_write_index) % self.MAX_SWEEPS_BUFFER
                positions = np.concatenate((
                    np.arange(write_pos, self.MAX_SWEEPS_BUFFER, dtype=np.int32),
                    np.arange(0, write_pos, dtype=np.int32),
                ))
            cleaned = self._apply_pzt_ghost_removal(self.raw_data_buffer[positions])
            self.raw_data_buffer[positions] = cleaned
            if self.processed_data_buffer is not None:
                self.processed_data_buffer[positions] = cleaned

    def queue_pzt_ghost_archive_block(self, sweep_timestamps_sec: np.ndarray, raw_block: np.ndarray) -> None:
        self._pzt_ghost_pending_archive_blocks.append((
            np.asarray(sweep_timestamps_sec, dtype=np.float64).copy(),
            np.asarray(raw_block, dtype=np.float32).copy(),
        ))

    def pop_clean_pzt_ghost_archive_blocks(self) -> list[tuple[np.ndarray, np.ndarray]]:
        if self._pzt_ghost_baselines is None:
            return []
        blocks = [
            (timestamps, self._apply_pzt_ghost_removal(block))
            for timestamps, block in self._pzt_ghost_pending_archive_blocks
        ]
        self._pzt_ghost_pending_archive_blocks = []
        return blocks

    def build_pzt_ghost_metadata(self) -> dict:
        return {
            'enabled': bool(self.should_remove_pzt_ghost()),
            'attenuation': float(self.pzt_ghost_attenuation),
            'baseline_source': 'existing automatic calibration and Zero Signals median',
            'noise_estimator': f'{PZT_GHOST_NOISE_MAD_SCALE} * MAD',
            'algorithm_version': 1,
        }
