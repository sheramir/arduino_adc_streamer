"""
Filter Processor Mixin
======================
ADC filter state and app-facing integration helpers.
"""

from __future__ import annotations

import numpy as np

from config_constants import FILTER_DEFAULT_ENABLED
from data_processing.adc_filter_worker import ADCFilterWorkerThread
from data_processing.adc_filter_engine import (
    ADCFilterEngine,
    SCIPY_FILTERS_AVAILABLE,
    build_default_filter_settings,
)


class FilterProcessorMixin:
    """Mixin providing ADC filter state, static reprocessing, and live view filtering."""

    # Manual filter validation checklist:
    # 1) Toggle filtering ON/OFF and confirm time-series + spectrum switch together.
    # 2) Enable 60 Hz notch and confirm 60 Hz spectrum peak reduces.
    # 3) Apply low-pass and confirm high-frequency spectrum content drops.
    # 4) Apply high-pass and confirm baseline drift/low-frequency content drops.
    # 5) Apply band-pass and confirm out-of-band content is attenuated.
    # 6) Confirm spectrum always matches filtered time-series data source.

    def _init_filter_state(self):
        self.processed_data_buffer = None

        self.adc_filter_engine = ADCFilterEngine()
        self.adc_filter_worker = ADCFilterWorkerThread()
        self.adc_filter_worker.result_ready.connect(self.on_adc_filter_worker_result)
        self.adc_filter_worker.error_occurred.connect(self.on_adc_filter_worker_error)
        self.adc_filter_worker.start()
        self.filter_settings = self.get_default_filter_settings()
        self.filtering_enabled = FILTER_DEFAULT_ENABLED
        self.filter_apply_pending = True
        self.filter_last_error = None

        self._filter_total_fs_hz = 0.0
        self._filter_channels_signature = None
        self._filter_channel_runtime = {}
        self._live_filtered_start_abs = 0
        self._live_filtered_ready_abs = 0
        self._live_filter_generation = 0
        self._timeseries_filter_pending_key = None
        self._timeseries_filter_cached_key = None
        self._timeseries_filter_cached_data = None
        self._timeseries_filter_cached_timestamps = None

    def get_default_filter_settings(self) -> dict:
        return build_default_filter_settings()

    def is_adc_filter_supported_mode(self) -> bool:
        """Return True only for ADC acquisition modes that support filtering."""
        return str(getattr(self, 'device_mode', 'adc')).lower() == 'adc'

    def should_filter_adc_data(self) -> bool:
        """Return True when ADC data should flow through the filter pipeline."""
        return self.is_adc_filter_supported_mode() and bool(self.filtering_enabled)

    def should_filter_live_timeseries_locally(self) -> bool:
        """Return True when live Time Series should filter only the visible window."""
        if not self.should_filter_adc_data():
            return False
        if not bool(getattr(self, 'is_capturing', False)):
            return False
        if bool(getattr(self, 'is_full_view', False)):
            return False
        if hasattr(self, 'should_update_live_timeseries_display'):
            return bool(self.should_update_live_timeseries_display())
        return True

    def get_active_data_buffer(self):
        if (
            self.should_filter_adc_data()
            and self.processed_data_buffer is not None
            and not self.should_filter_live_timeseries_locally()
        ):
            return self.processed_data_buffer
        return self.raw_data_buffer

    def _invalidate_timeseries_filter_cache(self):
        self._timeseries_filter_pending_key = None
        self._timeseries_filter_cached_key = None
        self._timeseries_filter_cached_data = None
        self._timeseries_filter_cached_timestamps = None

    def _reset_live_filtered_tracking(self, *, preserve_existing=False):
        with self.buffer_lock:
            current_abs = int(getattr(self, 'buffer_write_index', 0))
            current_count = int(getattr(self, 'sweep_count', 0))
            actual_sweeps = min(current_count, getattr(self, 'MAX_SWEEPS_BUFFER', current_count))

        if preserve_existing:
            start_abs = max(0, current_abs - actual_sweeps)
            ready_abs = current_abs
        else:
            start_abs = current_abs
            ready_abs = current_abs

        self._live_filtered_start_abs = int(start_abs)
        self._live_filtered_ready_abs = int(ready_abs)

    def prepare_timeseries_filter_resume(self):
        self._live_filter_generation += 1
        self.filter_apply_pending = True
        self._invalidate_timeseries_filter_cache()

    def maybe_get_live_timeseries_filtered_snapshot(
        self,
        data_array: np.ndarray,
        sweep_timestamps_sec: np.ndarray,
        snapshot_key,
    ):
        if not self.should_filter_live_timeseries_locally():
            return data_array, sweep_timestamps_sec

        if (
            self._timeseries_filter_cached_key == snapshot_key
            and self._timeseries_filter_cached_data is not None
            and self._timeseries_filter_cached_timestamps is not None
        ):
            return self._timeseries_filter_cached_data, self._timeseries_filter_cached_timestamps

        cached_key = self._timeseries_filter_cached_key
        if (
            cached_key is not None
            and self._timeseries_filter_cached_data is not None
            and self._timeseries_filter_cached_timestamps is not None
        ):
            same_generation = (
                len(cached_key) >= 3
                and len(snapshot_key) >= 3
                and int(cached_key[0]) == int(snapshot_key[0])
                and int(cached_key[2]) == int(snapshot_key[2])
            )
            if same_generation:
                if self._timeseries_filter_pending_key != snapshot_key:
                    self.request_live_timeseries_filter_snapshot(
                        data_array,
                        sweep_timestamps_sec,
                        snapshot_key,
                    )
                return self._timeseries_filter_cached_data, self._timeseries_filter_cached_timestamps

        if self._timeseries_filter_pending_key == snapshot_key:
            return data_array, sweep_timestamps_sec

        requested = self.request_live_timeseries_filter_snapshot(
            data_array,
            sweep_timestamps_sec,
            snapshot_key,
        )
        if requested:
            return data_array, sweep_timestamps_sec
        return data_array, sweep_timestamps_sec

    def get_spectrum_source_state(self):
        with self.buffer_lock:
            current_abs = int(getattr(self, 'buffer_write_index', 0))
            current_count = int(getattr(self, 'sweep_count', 0))
            actual_sweeps = min(current_count, getattr(self, 'MAX_SWEEPS_BUFFER', current_count))

        default_start_abs = max(0, current_abs - actual_sweeps)
        default_end_abs = current_abs
        default_buffer = self.get_active_data_buffer()

        current_tab = ''
        if hasattr(self, 'get_current_visualization_tab_name'):
            current_tab = self.get_current_visualization_tab_name()

        if (
            current_tab == 'Spectrum'
            and self.raw_data_buffer is not None
        ):
            return (
                self.raw_data_buffer,
                default_start_abs,
                default_end_abs,
            )

        return default_buffer, default_start_abs, default_end_abs

    def _get_filter_total_sample_rate_hz(self) -> float:
        timing = self.timing_state

        if timing.arduino_sample_times:
            latest_us = float(timing.arduino_sample_times[-1])
            if latest_us > 0:
                return 1_000_000.0 / latest_us

        rate = float(timing.timing_data.get('arduino_sample_rate_hz') or 0.0)
        if rate > 0:
            return rate

        configured_rate = float(self.config.get('sample_rate', 0) or 0.0)
        if configured_rate > 0:
            return configured_rate

        return 0.0

    def _get_ordered_filter_sweep_timestamps(self):
        if self.sweep_timestamps_buffer is None:
            return None

        with self.buffer_lock:
            current_sweep_count = self.sweep_count
            current_write_index = self.buffer_write_index
            actual_sweeps = min(current_sweep_count, self.MAX_SWEEPS_BUFFER)
            if actual_sweeps <= 0:
                return None

            write_pos = current_write_index % self.MAX_SWEEPS_BUFFER
            if actual_sweeps < self.MAX_SWEEPS_BUFFER:
                return self.sweep_timestamps_buffer[:actual_sweeps].copy()

            return np.concatenate([
                self.sweep_timestamps_buffer[write_pos:],
                self.sweep_timestamps_buffer[:write_pos],
            ])

    def _estimate_filter_channel_rates(self, total_fs_hz: float, sweep_timestamps_sec=None):
        channels = list(self.config.get('channels', []))
        repeat_count = max(1, int(self.config.get('repeat', 1)))
        if sweep_timestamps_sec is None:
            sweep_timestamps_sec = self._get_ordered_filter_sweep_timestamps()
        return self.adc_filter_engine.estimate_channel_sample_rates(
            total_fs_hz,
            channels,
            repeat_count,
            sweep_timestamps_sec=sweep_timestamps_sec,
        )

    def _ensure_filter_runtime(self, total_fs_hz: float, sweep_timestamps_sec=None):
        channels = self.config.get('channels', [])
        repeat_count = max(1, int(self.config.get('repeat', 1)))
        channel_rates = self._estimate_filter_channel_rates(total_fs_hz, sweep_timestamps_sec=sweep_timestamps_sec)
        rates_signature = tuple(
            sorted((int(channel), int(round(float(fs_hz) * 1000.0))) for channel, fs_hz in channel_rates.items())
        )
        signature = (tuple(channels), repeat_count, rates_signature)

        if (
            not self.filter_apply_pending
            and abs(self._filter_total_fs_hz - total_fs_hz) <= 1e-6
            and self._filter_channels_signature == signature
        ):
            return

        self._filter_channel_runtime = self.adc_filter_engine.build_runtime_plan(
            self.filter_settings,
            total_fs_hz,
            channels,
            repeat_count,
            sweep_timestamps_sec=sweep_timestamps_sec,
            channel_fs_by_channel=channel_rates,
        )
        self._filter_total_fs_hz = float(total_fs_hz)
        self._filter_channels_signature = signature
        self.filter_apply_pending = False

    def reset_filter_states(self):
        self.adc_filter_engine.reset_runtime_states(self._filter_channel_runtime)

    def apply_filter_settings(self, settings: dict, reprocess_existing: bool = True):
        self.filter_settings = settings
        self.filtering_enabled = bool(settings.get('enabled', False))
        self._invalidate_timeseries_filter_cache()

        if self.filtering_enabled and not self.is_adc_filter_supported_mode():
            self.filtering_enabled = False
            self._filter_channel_runtime = {}
            self.filter_last_error = 'Filtering is available only for ADC data, not 555/PZR mode.'
            return False, self.filter_last_error

        if self.filtering_enabled and not SCIPY_FILTERS_AVAILABLE:
            self.filtering_enabled = False
            self.filter_last_error = 'SciPy is required for filtering. Install scipy and restart.'
            return False, self.filter_last_error

        self.filter_apply_pending = True
        self.filter_last_error = None
        self._live_filter_generation += 1

        try:
            should_reprocess_buffer = bool(reprocess_existing and not bool(getattr(self, 'is_capturing', False)))
            self._reset_live_filtered_tracking(preserve_existing=bool(should_reprocess_buffer and self.filtering_enabled))
            if self.filtering_enabled:
                total_fs_hz = self._get_filter_total_sample_rate_hz()
                if total_fs_hz > 0:
                    sweep_timestamps_sec = self._get_ordered_filter_sweep_timestamps()
                    self._ensure_filter_runtime(total_fs_hz, sweep_timestamps_sec=sweep_timestamps_sec)
                    self.reset_filter_states()
                    if hasattr(self, 'log_status'):
                        channel_rates = ", ".join(
                            f"Ch {channel}: {float(fs_hz):.2f} Hz"
                            for channel, fs_hz in self._estimate_filter_channel_rates(
                                total_fs_hz,
                                sweep_timestamps_sec=sweep_timestamps_sec,
                            ).items()
                        ) or "none"
                        notch_desc = ", ".join(
                            f"{float(notch.get('freq_hz', 0.0)):.2f} Hz (Q={float(notch.get('q', 0.0)):.2f})"
                            for notch in settings.get('notches', [])
                            if notch.get('enabled', False)
                        ) or "none"
                        self.log_status(
                            f"ADC filtering armed: total Fs={float(total_fs_hz):.2f} Hz | "
                            f"per-channel Fs: {channel_rates} | notches: {notch_desc}"
                        )
            else:
                self._filter_channel_runtime = {}

            if should_reprocess_buffer:
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

    def _build_live_filter_signature(self, settings: dict, total_fs_hz: float, channels, repeat_count: int, channel_fs_by_channel=None):
        notches = tuple(
            (
                bool(notch.get('enabled', False)),
                float(notch.get('freq_hz', 0.0)),
                float(notch.get('q', 0.0)),
            )
            for notch in settings.get('notches', [])
        )
        fs_signature = tuple(
            sorted(
                (int(channel), int(round(float(fs_hz) * 1000.0)))
                for channel, fs_hz in (channel_fs_by_channel or {}).items()
            )
        )
        return (
            tuple(int(channel) for channel in channels),
            int(repeat_count),
            int(round(float(total_fs_hz) * 1000.0)),
            bool(settings.get('enabled', False)),
            str(settings.get('main_type', 'none')),
            int(settings.get('order', 1)),
            float(settings.get('low_cutoff_hz', 0.0)),
            float(settings.get('high_cutoff_hz', 0.0)),
            notches,
            fs_signature,
        )

    def request_live_timeseries_filter_snapshot(
        self,
        data_array: np.ndarray,
        sweep_timestamps_sec: np.ndarray,
        snapshot_key,
    ) -> bool:
        snapshot_key = tuple(snapshot_key)

        if not self.should_filter_live_timeseries_locally():
            return False

        worker = getattr(self, 'adc_filter_worker', None)
        if worker is None:
            return False

        if (
            snapshot_key == self._timeseries_filter_pending_key
            or snapshot_key == self._timeseries_filter_cached_key
        ):
            return False

        total_fs_hz = self._get_filter_total_sample_rate_hz()
        if total_fs_hz <= 0:
            return False

        channels = list(self.config.get('channels', []))
        repeat_count = max(1, int(self.config.get('repeat', 1)))
        channel_fs_by_channel = self._estimate_filter_channel_rates(
            total_fs_hz,
            sweep_timestamps_sec=sweep_timestamps_sec,
        )
        settings = {
            **self.filter_settings,
            'notches': [dict(notch) for notch in self.filter_settings.get('notches', [])],
        }
        payload = {
            'mode': 'timeseries_window',
            'settings': settings,
            'total_fs_hz': float(total_fs_hz),
            'channels': channels,
            'repeat_count': repeat_count,
            'signature': self._build_live_filter_signature(
                settings,
                total_fs_hz,
                channels,
                repeat_count,
                channel_fs_by_channel=channel_fs_by_channel,
            ),
            'channel_fs_by_channel': {
                int(channel): float(fs_hz) for channel, fs_hz in channel_fs_by_channel.items()
            },
            'generation': int(self._live_filter_generation),
            'snapshot_key': snapshot_key,
            'window_data': np.asarray(data_array, dtype=np.float32).copy(),
            'sweep_timestamps_sec': np.asarray(sweep_timestamps_sec, dtype=np.float64).copy(),
        }
        worker.submit(payload)
        self._timeseries_filter_pending_key = snapshot_key
        return True

    def enqueue_live_adc_filter(
        self,
        block_data: np.ndarray,
        total_fs_hz: float,
        write_base: int,
        sweeps_in_block: int,
        sweep_timestamps_sec=None,
    ):
        if not self.should_filter_adc_data():
            return

        worker = getattr(self, 'adc_filter_worker', None)
        if worker is None:
            return

        channels = list(self.config.get('channels', []))
        repeat_count = max(1, int(self.config.get('repeat', 1)))
        channel_fs_by_channel = self._estimate_filter_channel_rates(total_fs_hz)
        settings = {
            **self.filter_settings,
            'notches': [dict(notch) for notch in self.filter_settings.get('notches', [])],
        }
        payload = {
            'mode': 'live_block',
            'settings': settings,
            'total_fs_hz': float(total_fs_hz),
            'channels': channels,
            'repeat_count': repeat_count,
            'signature': self._build_live_filter_signature(
                settings,
                total_fs_hz,
                channels,
                repeat_count,
                channel_fs_by_channel=channel_fs_by_channel,
            ),
            'channel_fs_by_channel': {
                int(channel): float(fs_hz) for channel, fs_hz in channel_fs_by_channel.items()
            },
            'generation': int(self._live_filter_generation),
            'block_data': block_data.astype(np.float32, copy=True),
            'write_base': int(write_base),
            'sweeps_in_block': int(sweeps_in_block),
            'sweep_timestamps_sec': None if sweep_timestamps_sec is None else np.asarray(sweep_timestamps_sec, dtype=np.float64).copy(),
        }
        worker.submit(payload)

    def on_adc_filter_worker_result(self, result):
        mode = str(result.get('mode', 'live_block'))
        if mode == 'timeseries_window':
            if int(result.get('generation', -1)) != int(self._live_filter_generation):
                return

            snapshot_key = tuple(result.get('snapshot_key', ()))
            if not snapshot_key:
                return
            filtered_data = result.get('filtered_data')
            filtered_timestamps = result.get('sweep_timestamps_sec')
            if filtered_data is None or filtered_timestamps is None:
                return

            if tuple(self._timeseries_filter_pending_key or ()) == snapshot_key:
                self._timeseries_filter_pending_key = None
            self._timeseries_filter_cached_key = snapshot_key
            self._timeseries_filter_cached_data = np.asarray(
                filtered_data,
                dtype=np.float32,
            )
            self._timeseries_filter_cached_timestamps = np.asarray(
                filtered_timestamps,
                dtype=np.float64,
            )

            if hasattr(self, 'should_update_live_timeseries_display') and self.should_update_live_timeseries_display():
                self.trigger_plot_update()
            return

        if not self.should_filter_adc_data():
            return
        if self.processed_data_buffer is None:
            return
        if int(result.get('generation', -1)) != int(self._live_filter_generation):
            return

        write_base = int(result['write_base'])
        sweeps_in_block = int(result['sweeps_in_block'])
        filtered_block = result['filtered_block']

        with self.buffer_lock:
            if (self.buffer_write_index - write_base) > self.MAX_SWEEPS_BUFFER:
                return
            positions = (write_base + np.arange(sweeps_in_block)) % self.MAX_SWEEPS_BUFFER
            self.processed_data_buffer[positions] = filtered_block.astype(np.float32, copy=False)
            if write_base == self._live_filtered_ready_abs:
                self._live_filtered_ready_abs = write_base + sweeps_in_block

        if hasattr(self, 'should_update_live_timeseries_display') and self.should_update_live_timeseries_display():
            self.trigger_plot_update()
        elif hasattr(self, 'get_current_visualization_tab_name') and self.get_current_visualization_tab_name() == 'Spectrum':
            self.update_spectrum()

    def on_adc_filter_worker_error(self, message: str):
        self.filtering_enabled = False
        self.filter_last_error = str(message)
        if hasattr(self, 'log_status'):
            self.log_status(f"WARNING: live ADC filtering disabled due to worker error: {message}")

    def shutdown_filter_worker(self):
        worker = getattr(self, 'adc_filter_worker', None)
        if worker is not None:
            worker.stop()
            worker.wait(1500)

    def filter_sweeps_block(self, block_data: np.ndarray, total_fs_hz: float, sweep_timestamps_sec=None):
        if block_data is None:
            return None

        if not self.should_filter_adc_data():
            return block_data.astype(np.float32, copy=True)

        self._ensure_filter_runtime(total_fs_hz, sweep_timestamps_sec=sweep_timestamps_sec)

        if not self._filter_channel_runtime:
            return block_data.astype(np.float32, copy=True)

        return self.adc_filter_engine.filter_block(self._filter_channel_runtime, block_data)

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
                ordered_sweep_timestamps = self.sweep_timestamps_buffer[:actual_sweeps].copy()
            else:
                positions = np.concatenate([
                    np.arange(write_pos, self.MAX_SWEEPS_BUFFER, dtype=np.int32),
                    np.arange(0, write_pos, dtype=np.int32),
                ])
                ordered_raw = np.concatenate([
                    self.raw_data_buffer[write_pos:, :],
                    self.raw_data_buffer[:write_pos, :],
                ])
                ordered_sweep_timestamps = np.concatenate([
                    self.sweep_timestamps_buffer[write_pos:],
                    self.sweep_timestamps_buffer[:write_pos],
                ])

        if self.processed_data_buffer is None or self.processed_data_buffer.shape != self.raw_data_buffer.shape:
            with self.buffer_lock:
                self.processed_data_buffer = np.zeros_like(self.raw_data_buffer, dtype=np.float32)

        if not self.should_filter_adc_data():
            with self.buffer_lock:
                self.processed_data_buffer[positions, :] = ordered_raw
            self._reset_live_filtered_tracking(preserve_existing=True)
            return

        total_fs_hz = self._get_filter_total_sample_rate_hz()
        if total_fs_hz <= 0:
            raise ValueError('Cannot reprocess filter buffer: sample rate unavailable.')

        self.filter_apply_pending = True
        self._ensure_filter_runtime(total_fs_hz, sweep_timestamps_sec=ordered_sweep_timestamps)
        self.reset_filter_states()
        ordered_filtered = self.filter_sweeps_block(
            ordered_raw,
            total_fs_hz,
            sweep_timestamps_sec=ordered_sweep_timestamps,
        )

        with self.buffer_lock:
            self.processed_data_buffer[positions, :] = ordered_filtered
        self._reset_live_filtered_tracking(preserve_existing=True)
