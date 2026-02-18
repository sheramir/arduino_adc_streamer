"""
Filter Processor Mixin
======================
Real-time friendly IIR filtering for time-series and spectrum paths.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from config_constants import (
    FILTER_DEFAULT_ENABLED,
    FILTER_DEFAULT_MAIN_TYPE,
    FILTER_DEFAULT_ORDER,
    FILTER_DEFAULT_LOW_CUTOFF_HZ,
    FILTER_DEFAULT_HIGH_CUTOFF_HZ,
    FILTER_NOTCH1_DEFAULT_ENABLED,
    FILTER_NOTCH1_DEFAULT_FREQ_HZ,
    FILTER_NOTCH1_DEFAULT_Q,
    FILTER_NOTCH2_DEFAULT_ENABLED,
    FILTER_NOTCH2_DEFAULT_FREQ_HZ,
    FILTER_NOTCH2_DEFAULT_Q,
    FILTER_NOTCH3_DEFAULT_ENABLED,
    FILTER_NOTCH3_DEFAULT_FREQ_HZ,
    FILTER_NOTCH3_DEFAULT_Q,
)

try:
    from scipy.signal import butter, iirnotch, sosfilt, sosfilt_zi, tf2sos
    SCIPY_FILTERS_AVAILABLE = True
except Exception:
    SCIPY_FILTERS_AVAILABLE = False


class FilterProcessorMixin:
    """Mixin providing filter coefficient/state management and block filtering."""

    # Manual filter validation checklist:
    # 1) Toggle filtering ON/OFF and confirm time-series + spectrum switch together.
    # 2) Enable 60 Hz notch and confirm 60 Hz spectrum peak reduces.
    # 3) Apply low-pass and confirm high-frequency spectrum content drops.
    # 4) Apply high-pass and confirm baseline drift/low-frequency content drops.
    # 5) Apply band-pass and confirm out-of-band content is attenuated.
    # 6) Confirm spectrum always matches filtered time-series data source.

    def _init_filter_state(self):
        self.processed_data_buffer = None

        self.filter_settings = self.get_default_filter_settings()
        self.filtering_enabled = FILTER_DEFAULT_ENABLED
        self.filter_apply_pending = True
        self.filter_last_error = None

        self._filter_total_fs_hz = 0.0
        self._filter_channels_signature = None
        self._filter_channel_runtime: Dict[int, Dict] = {}

    def get_default_filter_settings(self) -> dict:
        return {
            'enabled': FILTER_DEFAULT_ENABLED,
            'main_type': FILTER_DEFAULT_MAIN_TYPE,
            'order': FILTER_DEFAULT_ORDER,
            'low_cutoff_hz': FILTER_DEFAULT_LOW_CUTOFF_HZ,
            'high_cutoff_hz': FILTER_DEFAULT_HIGH_CUTOFF_HZ,
            'notches': [
                {'enabled': FILTER_NOTCH1_DEFAULT_ENABLED, 'freq_hz': FILTER_NOTCH1_DEFAULT_FREQ_HZ, 'q': FILTER_NOTCH1_DEFAULT_Q},
                {'enabled': FILTER_NOTCH2_DEFAULT_ENABLED, 'freq_hz': FILTER_NOTCH2_DEFAULT_FREQ_HZ, 'q': FILTER_NOTCH2_DEFAULT_Q},
                {'enabled': FILTER_NOTCH3_DEFAULT_ENABLED, 'freq_hz': FILTER_NOTCH3_DEFAULT_FREQ_HZ, 'q': FILTER_NOTCH3_DEFAULT_Q},
            ],
        }

    def get_active_data_buffer(self):
        if self.filtering_enabled and self.processed_data_buffer is not None:
            return self.processed_data_buffer
        return self.raw_data_buffer

    def _get_filter_total_sample_rate_hz(self) -> float:
        if hasattr(self, 'arduino_sample_times') and self.arduino_sample_times:
            latest_us = float(self.arduino_sample_times[-1])
            if latest_us > 0:
                return 1_000_000.0 / latest_us

        rate = float(self.timing_data.get('arduino_sample_rate_hz') or 0.0)
        if rate > 0:
            return rate

        configured_rate = float(self.config.get('sample_rate', 0) or 0.0)
        if configured_rate > 0:
            return configured_rate

        return 0.0

    def _validate_filter_settings(self, settings: dict, channel_fs_hz: float) -> Tuple[bool, str]:
        if channel_fs_hz <= 0:
            return False, 'Sample rate unavailable for filtering.'

        nyquist = channel_fs_hz / 2.0
        low = float(settings['low_cutoff_hz'])
        high = float(settings['high_cutoff_hz'])

        for notch in settings['notches']:
            if not notch['enabled']:
                continue
            freq = float(notch['freq_hz'])
            q = float(notch['q'])
            if freq <= 0 or freq >= nyquist:
                return False, f'Notch frequency {freq:.2f} must be between 0 and Nyquist ({nyquist:.2f} Hz).'
            if q <= 0:
                return False, 'Notch Q must be > 0.'

        main_type = settings['main_type']
        if main_type == 'lowpass':
            if low <= 0 or low >= nyquist:
                return False, f'Low-pass cutoff must be between 0 and Nyquist ({nyquist:.2f} Hz).'
        elif main_type == 'highpass':
            if high <= 0 or high >= nyquist:
                return False, f'High-pass cutoff must be between 0 and Nyquist ({nyquist:.2f} Hz).'
        elif main_type == 'bandpass':
            if low <= 0 or high <= 0:
                return False, 'Band-pass cutoffs must be > 0.'
            if low >= high:
                return False, 'Band-pass low cutoff must be less than high cutoff.'
            if high >= nyquist:
                return False, f'Band-pass high cutoff must be below Nyquist ({nyquist:.2f} Hz).'

        return True, ''

    def _design_channel_sos(self, settings: dict, channel_fs_hz: float):
        # Coefficients are built as SOS cascades (notches + one optional main filter)
        # for numerical stability in real-time IIR processing.
        if not SCIPY_FILTERS_AVAILABLE:
            raise RuntimeError('SciPy is required for filtering. Install scipy and restart.')

        valid, error = self._validate_filter_settings(settings, channel_fs_hz)
        if not valid:
            raise ValueError(error)

        sos_parts = []
        nyquist = channel_fs_hz / 2.0

        for notch in settings['notches']:
            if not notch['enabled']:
                continue
            w0 = float(notch['freq_hz']) / nyquist
            q = float(notch['q'])
            b, a = iirnotch(w0, q)
            sos_parts.append(tf2sos(b, a))

        order = max(1, int(settings['order']))
        main_type = settings['main_type']
        low = float(settings['low_cutoff_hz'])
        high = float(settings['high_cutoff_hz'])

        if main_type == 'lowpass':
            wn = low / nyquist
            sos_parts.append(butter(order, wn, btype='lowpass', output='sos'))
        elif main_type == 'highpass':
            wn = high / nyquist
            sos_parts.append(butter(order, wn, btype='highpass', output='sos'))
        elif main_type == 'bandpass':
            wn = [low / nyquist, high / nyquist]
            sos_parts.append(butter(order, wn, btype='bandpass', output='sos'))

        if not sos_parts:
            return None

        if len(sos_parts) == 1:
            return sos_parts[0]
        return np.vstack(sos_parts)

    def _build_channel_plan(self, total_fs_hz: float, channels: List[int], repeat_count: int):
        unique_channels = []
        for channel in channels:
            if channel not in unique_channels:
                unique_channels.append(channel)

        sequence_len = max(1, len(channels))
        counts = {channel: channels.count(channel) for channel in unique_channels}

        plan = {}
        for channel in unique_channels:
            indices = []
            for seq_idx, seq_channel in enumerate(channels):
                if seq_channel != channel:
                    continue
                base = seq_idx * repeat_count
                indices.extend(range(base, base + repeat_count))

            if not indices:
                continue

            channel_fs_hz = total_fs_hz * (counts[channel] / sequence_len)
            sos = self._design_channel_sos(self.filter_settings, channel_fs_hz)
            zi = None
            if sos is not None:
                zi = sosfilt_zi(sos) * 0.0

            plan[channel] = {
                'indices': np.asarray(indices, dtype=np.int32),
                'fs_hz': float(channel_fs_hz),
                'sos': sos,
                'zi': zi,
            }

        return plan

    def _ensure_filter_runtime(self, total_fs_hz: float):
        channels = self.config.get('channels', [])
        repeat_count = max(1, int(self.config.get('repeat', 1)))
        signature = (tuple(channels), repeat_count)

        if (
            not self.filter_apply_pending
            and abs(self._filter_total_fs_hz - total_fs_hz) <= 1e-6
            and self._filter_channels_signature == signature
        ):
            return

        self._filter_channel_runtime = self._build_channel_plan(total_fs_hz, channels, repeat_count)
        self._filter_total_fs_hz = float(total_fs_hz)
        self._filter_channels_signature = signature
        self.filter_apply_pending = False

    def reset_filter_states(self):
        for runtime in self._filter_channel_runtime.values():
            sos = runtime.get('sos')
            if sos is None:
                runtime['zi'] = None
            else:
                runtime['zi'] = sosfilt_zi(sos) * 0.0

    def apply_filter_settings(self, settings: dict, reprocess_existing: bool = True):
        self.filter_settings = settings
        self.filtering_enabled = bool(settings.get('enabled', False))

        if self.filtering_enabled and not SCIPY_FILTERS_AVAILABLE:
            self.filtering_enabled = False
            self.filter_last_error = 'SciPy is required for filtering. Install scipy and restart.'
            return False, self.filter_last_error

        self.filter_apply_pending = True
        self.filter_last_error = None

        try:
            if self.filtering_enabled:
                total_fs_hz = self._get_filter_total_sample_rate_hz()
                if total_fs_hz > 0:
                    self._ensure_filter_runtime(total_fs_hz)
                    self.reset_filter_states()
            else:
                self._filter_channel_runtime = {}

            if reprocess_existing:
                if self.filtering_enabled:
                    total_fs_hz = self._get_filter_total_sample_rate_hz()
                    if total_fs_hz > 0:
                        self.reprocess_filtered_buffer()
                else:
                    self.reprocess_filtered_buffer()

            return True, ''
        except Exception as exc:
            self.filter_last_error = str(exc)
            return False, self.filter_last_error

    def filter_sweeps_block(self, block_data: np.ndarray, total_fs_hz: float):
        if block_data is None:
            return None

        if not self.filtering_enabled:
            return block_data.astype(np.float32, copy=True)

        self._ensure_filter_runtime(total_fs_hz)

        if not self._filter_channel_runtime:
            return block_data.astype(np.float32, copy=True)

        filtered = block_data.astype(np.float64, copy=True)

        for runtime in self._filter_channel_runtime.values():
            indices = runtime['indices']
            sos = runtime['sos']
            if sos is None:
                continue

            stream = filtered[:, indices].reshape(-1)
            zi = runtime['zi']
            if zi is None:
                zi = sosfilt_zi(sos) * 0.0
            y, zf = sosfilt(sos, stream, zi=zi)
            # Keep channel-specific IIR state so filtering is continuous across blocks.
            runtime['zi'] = zf
            filtered[:, indices] = y.reshape(filtered.shape[0], len(indices))

        return filtered.astype(np.float32, copy=False)

    def reprocess_filtered_buffer(self):
        if self.raw_data_buffer is None or self.samples_per_sweep <= 0:
            return

        with self.buffer_lock:
            current_sweep_count = self.sweep_count
            current_write_index = self.buffer_write_index
            actual_sweeps = min(current_sweep_count, self.MAX_SWEEPS_BUFFER)

            if actual_sweeps <= 0:
                if self.processed_data_buffer is not None:
                    self.processed_data_buffer.fill(0)
                return

            write_pos = current_write_index % self.MAX_SWEEPS_BUFFER

            if actual_sweeps < self.MAX_SWEEPS_BUFFER:
                positions = np.arange(actual_sweeps, dtype=np.int32)
                ordered_raw = self.raw_data_buffer[:actual_sweeps, :].copy()
            else:
                positions = np.concatenate([
                    np.arange(write_pos, self.MAX_SWEEPS_BUFFER, dtype=np.int32),
                    np.arange(0, write_pos, dtype=np.int32),
                ])
                ordered_raw = np.concatenate([
                    self.raw_data_buffer[write_pos:, :],
                    self.raw_data_buffer[:write_pos, :],
                ])

        if self.processed_data_buffer is None or self.processed_data_buffer.shape != self.raw_data_buffer.shape:
            with self.buffer_lock:
                self.processed_data_buffer = np.zeros_like(self.raw_data_buffer, dtype=np.float32)

        if not self.filtering_enabled:
            with self.buffer_lock:
                self.processed_data_buffer[positions, :] = ordered_raw
            return

        total_fs_hz = self._get_filter_total_sample_rate_hz()
        if total_fs_hz <= 0:
            raise ValueError('Cannot reprocess filter buffer: sample rate unavailable.')

        self.filter_apply_pending = True
        self._ensure_filter_runtime(total_fs_hz)
        self.reset_filter_states()
        ordered_filtered = self.filter_sweeps_block(ordered_raw, total_fs_hz)

        with self.buffer_lock:
            self.processed_data_buffer[positions, :] = ordered_filtered
