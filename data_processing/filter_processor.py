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

    def get_default_filter_settings(self) -> dict:
        return build_default_filter_settings()

    def is_adc_filter_supported_mode(self) -> bool:
        """Return True only for ADC acquisition modes that support filtering."""
        return str(getattr(self, 'device_mode', 'adc')).lower() == 'adc'

    def should_filter_adc_data(self) -> bool:
        """Return True when ADC data should flow through the filter pipeline."""
        return self.is_adc_filter_supported_mode() and bool(self.filtering_enabled)

    def get_active_data_buffer(self):
        if self.should_filter_adc_data() and self.processed_data_buffer is not None:
            return self.processed_data_buffer
        return self.raw_data_buffer

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

        self._filter_channel_runtime = self.adc_filter_engine.build_runtime_plan(
            self.filter_settings,
            total_fs_hz,
            channels,
            repeat_count,
        )
        self._filter_total_fs_hz = float(total_fs_hz)
        self._filter_channels_signature = signature
        self.filter_apply_pending = False

    def reset_filter_states(self):
        self.adc_filter_engine.reset_runtime_states(self._filter_channel_runtime)

    def apply_filter_settings(self, settings: dict, reprocess_existing: bool = True):
        self.filter_settings = settings
        self.filtering_enabled = bool(settings.get('enabled', False))

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

    def _build_live_filter_signature(self, settings: dict, total_fs_hz: float, channels, repeat_count: int):
        notches = tuple(
            (
                bool(notch.get('enabled', False)),
                float(notch.get('freq_hz', 0.0)),
                float(notch.get('q', 0.0)),
            )
            for notch in settings.get('notches', [])
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
        )

    def enqueue_live_adc_filter(self, block_data: np.ndarray, total_fs_hz: float, write_base: int, sweeps_in_block: int):
        if not self.should_filter_adc_data():
            return

        worker = getattr(self, 'adc_filter_worker', None)
        if worker is None:
            return

        channels = list(self.config.get('channels', []))
        repeat_count = max(1, int(self.config.get('repeat', 1)))
        settings = {
            **self.filter_settings,
            'notches': [dict(notch) for notch in self.filter_settings.get('notches', [])],
        }
        payload = {
            'settings': settings,
            'total_fs_hz': float(total_fs_hz),
            'channels': channels,
            'repeat_count': repeat_count,
            'signature': self._build_live_filter_signature(settings, total_fs_hz, channels, repeat_count),
            'block_data': block_data.astype(np.float32, copy=True),
            'write_base': int(write_base),
            'sweeps_in_block': int(sweeps_in_block),
        }
        worker.submit(payload)

    def on_adc_filter_worker_result(self, result):
        if not self.should_filter_adc_data():
            return
        if self.processed_data_buffer is None:
            return

        write_base = int(result['write_base'])
        sweeps_in_block = int(result['sweeps_in_block'])
        filtered_block = result['filtered_block']

        with self.buffer_lock:
            if (self.buffer_write_index - write_base) > self.MAX_SWEEPS_BUFFER:
                return
            positions = (write_base + np.arange(sweeps_in_block)) % self.MAX_SWEEPS_BUFFER
            self.processed_data_buffer[positions] = filtered_block.astype(np.float32, copy=False)

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

    def filter_sweeps_block(self, block_data: np.ndarray, total_fs_hz: float):
        if block_data is None:
            return None

        if not self.should_filter_adc_data():
            return block_data.astype(np.float32, copy=True)

        self._ensure_filter_runtime(total_fs_hz)

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

        if not self.should_filter_adc_data():
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
