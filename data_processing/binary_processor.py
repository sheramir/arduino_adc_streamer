"""
Binary Data Processor Mixin
============================
Handles processing of binary ADC data blocks from Arduino.
"""

import time
import csv

import numpy as np

from constants.plotting import (
    MAX_PLOT_SWEEPS,
    PLOT_UPDATE_INTERVAL_SEC,
)
from constants.runtime import MAX_TIMING_SAMPLES
from constants.signal_integration import SIGNAL_INTEGRATION_PLOT_UPDATE_INTERVAL_SEC
from data_processing.force_state import get_force_runtime_state


class BinaryProcessorMixin:
    """Mixin for binary ADC data processing."""

    _SLOW_TIMESERIES_UPDATE_MS = 120.0
    _SLOW_TIMESERIES_LOG_INTERVAL_SEC = 2.0
    
    def process_binary_sweep(self, samples: np.ndarray, avg_sample_time_us: int, block_start_us: int, block_end_us: int):
        """Process incoming binary block data containing one or more sweeps.
        
        The Arduino now sends blocks of sweeps. Each block contains:
        - Multiple complete sweeps (samples_per_sweep * sweeps_in_block)
        - Possibly a partial block at the end of capture
        - Average sampling time per sample (in microseconds) from Arduino
        
        Args:
            samples: List of ADC sample values
            avg_sample_time_us: Average time per sample in microseconds (from Arduino)
            block_start_us: MCU micros() at first sample in block
            block_end_us: MCU micros() at last sample in block
        """
        if self.is_capturing:
            try:
                force_state = get_force_runtime_state(self)
                timing = self.timing_state
                if not hasattr(self, '_debug_capture_blocks_seen'):
                    self._debug_capture_blocks_seen = 0
                store_capture_data = True
                if hasattr(self, "should_store_capture_data"):
                    store_capture_data = bool(self.should_store_capture_data())

                # Track buffer arrival time (start of reception)
                block_start_time = time.time()
                
                # Keep only last 1000 buffer receipt times to prevent unbounded growth
                timing.buffer_receipt_times.append(block_start_time)
                timing.trim_recent('buffer_receipt_times', MAX_TIMING_SAMPLES)
                
                # Track first sweep time for rate calculation - thread safe
                with self.buffer_lock:
                    is_first_sweep = (self.sweep_count == 0)
                
                if is_first_sweep:
                    timing.capture_start_time = block_start_time
                    force_state.start_time = timing.capture_start_time  # Sync force timing
                    timing.last_buffer_time = block_start_time
                
                # Store the average sampling time from Arduino (keep only last 1000)
                timing.arduino_sample_times.append(avg_sample_time_us)
                timing.trim_recent('arduino_sample_times', MAX_TIMING_SAMPLES)

                # Store MCU block timestamps (keep only last 1000)
                timing.mcu_block_start_us.append(block_start_us)
                timing.mcu_block_end_us.append(block_end_us)
                timing.trim_recent('mcu_block_start_us', MAX_TIMING_SAMPLES)
                timing.trim_recent('mcu_block_end_us', MAX_TIMING_SAMPLES)

                # MCU gap between blocks (wrap-safe unsigned math)
                if timing.mcu_last_block_end_us is not None:
                    gap_us = (block_start_us - timing.mcu_last_block_end_us) & 0xFFFFFFFF
                    timing.mcu_block_gap_us.append(gap_us)
                    timing.trim_recent('mcu_block_gap_us', MAX_TIMING_SAMPLES)
                timing.mcu_last_block_end_us = block_end_us
                
                # Calculate samples per sweep from the same physical-width rule
                # used when capture starts, so parser expectations and buffer
                # layout stay aligned for paired-MUX array modes.
                samples_per_sweep = self.get_effective_samples_per_sweep()
                
                if samples_per_sweep == 0:
                    self.log_status("ERROR: Invalid configuration, samples_per_sweep is 0")
                    return
                
                # Initialize numpy buffers if not done or if config changed - THREAD SAFE
                with self.buffer_lock:
                    if (self.raw_data_buffer is None or 
                        self.samples_per_sweep != samples_per_sweep):
                        self.samples_per_sweep = samples_per_sweep
                        self.raw_data_buffer = np.zeros((self.MAX_SWEEPS_BUFFER, samples_per_sweep), dtype=np.float32)
                        self.processed_data_buffer = np.zeros((self.MAX_SWEEPS_BUFFER, samples_per_sweep), dtype=np.float32)
                        self.sweep_timestamps_buffer = np.zeros(self.MAX_SWEEPS_BUFFER, dtype=np.float64)
                        self.buffer_write_index = 0
                        self.log_status(f"Initialized numpy buffers: {self.MAX_SWEEPS_BUFFER} sweeps × {samples_per_sweep} samples")
                    elif self.processed_data_buffer is None or self.processed_data_buffer.shape != self.raw_data_buffer.shape:
                        self.processed_data_buffer = np.zeros_like(self.raw_data_buffer, dtype=np.float32)
                
                # The sample count comes from the header, which reflects what Arduino actually sent
                # Arduino may reduce sweeps per block to fit in RAM, so use actual count
                total_samples = len(samples)
                
                # Verify the total samples is a multiple of samples_per_sweep
                if total_samples % samples_per_sweep != 0:
                    self.log_status(f"WARNING: Block has {total_samples} samples, not a multiple of {samples_per_sweep}. Block may be corrupted.")
                    # Process only complete sweeps, discard partial data
                    total_samples = (total_samples // samples_per_sweep) * samples_per_sweep
                
                # Calculate actual sweeps in this block (may be less than requested buffer size)
                sweeps_in_block = total_samples // samples_per_sweep
                if self._debug_capture_blocks_seen < 10:
                    self._debug_capture_blocks_seen += 1
                    self.log_status(
                        f"Capture block {self._debug_capture_blocks_seen}: total_samples={total_samples}, "
                        f"samples_per_sweep={samples_per_sweep}, sweeps_in_block={sweeps_in_block}, "
                        f"avg_dt_us={avg_sample_time_us}"
                    )

                # Keep uint16 view for archive (preserves integer format); cast to float32 for processing.
                block_u16 = samples[:total_samples].reshape(sweeps_in_block, samples_per_sweep)
                block_samples_array = block_u16.astype(np.float32)
                # Track block sizing for timing export (keep only recent)
                timing.block_sample_counts.append(total_samples)
                timing.block_sweeps_counts.append(sweeps_in_block)
                timing.block_samples_per_sweep.append(samples_per_sweep)
                timing.trim_recent('block_sample_counts', MAX_TIMING_SAMPLES)
                timing.trim_recent('block_sweeps_counts', MAX_TIMING_SAMPLES)
                timing.trim_recent('block_samples_per_sweep', MAX_TIMING_SAMPLES)

                # Stream block timing to sidecar (if open)
                if store_capture_data and self._block_timing_file:
                    try:
                        gap_us = ""
                        if timing.mcu_block_gap_us:
                            gap_us = timing.mcu_block_gap_us[-1]
                        tw = csv.writer(self._block_timing_file)
                        self._block_timing_write_count += 1
                        if self._block_timing_write_count % 100 == 0:
                            try:
                                self._block_timing_file.flush()
                            except Exception:
                                pass
                        tw.writerow([
                            timing.block_sample_counts[-1],
                            timing.block_samples_per_sweep[-1],
                            timing.block_sweeps_counts[-1],
                            timing.arduino_sample_times[-1],
                            block_start_us,
                            block_end_us,
                            gap_us
                        ])
                    except Exception:
                        pass
                
                # --- Vectorized timestamp computation for the whole block ---
                # Mask block_start_us to uint32 range: pyqtSignal(object) passes
                # Python ints without truncation, but guard anyway for safety.
                block_start_us_u32 = int(block_start_us) & 0xFFFFFFFF

                # Each sweep's first sample offset in the total sample stream.
                sweep_first_sample_idx = np.arange(sweeps_in_block, dtype=np.uint64) * samples_per_sweep
                sweep_time_offsets_us = sweep_first_sample_idx * int(avg_sample_time_us)
                # Wrap-safe uint32: Arduino micros() overflows after ~71 minutes.
                sweep_timestamps_us = (block_start_us_u32 + sweep_time_offsets_us) & 0xFFFFFFFF

                # Initialize first-sweep timestamp reference once per capture.
                if not hasattr(self, 'first_sweep_timestamp_us'):
                    with self.buffer_lock:
                        if not hasattr(self, 'first_sweep_timestamp_us'):
                            self.first_sweep_timestamp_us = int(sweep_timestamps_us[0])
                            self.log_status(
                                f"First sweep timestamp initialized: {self.first_sweep_timestamp_us} µs (wrap-safe)"
                            )

                delta_us = (sweep_timestamps_us - self.first_sweep_timestamp_us) & 0xFFFFFFFF
                sweep_timestamps_sec = delta_us / 1_000_000.0

                # --- Vectorized circular buffer write (single lock per block) ---
                with self.buffer_lock:
                    block_write_base = self.buffer_write_index
                    positions = (
                        block_write_base + np.arange(sweeps_in_block)
                    ) % self.MAX_SWEEPS_BUFFER
                    self.raw_data_buffer[positions] = block_samples_array
                    self.processed_data_buffer[positions] = block_samples_array.astype(np.float32, copy=False)
                    self.sweep_timestamps_buffer[positions] = sweep_timestamps_sec
                    self.buffer_write_index += sweeps_in_block
                    self.sweep_count += sweeps_in_block

                # Cache avg sample time so update_plot avoids O(n) list sum on every frame.
                self._cached_avg_sample_time_sec = (
                    avg_sample_time_us / 1_000_000.0 if avg_sample_time_us > 0 else 0.0
                )

                # --- Enqueue archive write (handled by background ArchiveWriterThread) ---
                if store_capture_data and getattr(self, '_archive_writer', None):
                    # Pass uint16 block so row.tolist() produces integers matching original format.
                    self._archive_writer.enqueue(sweep_timestamps_sec, block_u16)

                # Rate-limit plot updates using wall-clock time.
                # The old sweep_count % N check broke when sweep_count jumps by
                # sweeps_in_block (the remainder may never land on zero).
                # Direct call is safe because process_binary_sweep runs on the
                # GUI thread (queued Qt signal connection).
                if store_capture_data:
                    now = time.time()
                    if (
                        (
                            not hasattr(self, 'should_update_live_timeseries_display')
                            or self.should_update_live_timeseries_display()
                        )
                        and now - getattr(self, '_last_plot_update_time', 0.0) >= PLOT_UPDATE_INTERVAL_SEC
                    ):
                        self._last_plot_update_time = now
                        redraw_start = time.perf_counter()
                        self.update_plot()
                        after_main_plot = time.perf_counter()
                        self.update_force_plot()
                        redraw_end = time.perf_counter()
                        self._maybe_log_slow_timeseries_redraw(
                            main_plot_ms=(after_main_plot - redraw_start) * 1000.0,
                            force_plot_ms=(redraw_end - after_main_plot) * 1000.0,
                            total_ms=(redraw_end - redraw_start) * 1000.0,
                            sweeps_in_block=int(sweeps_in_block),
                            samples_per_sweep=int(samples_per_sweep),
                        )
                    elif (
                        hasattr(self, 'should_update_signal_integration_display')
                        and self.should_update_signal_integration_display()
                        and now - getattr(self, '_last_signal_integration_plot_update_time', 0.0)
                        >= SIGNAL_INTEGRATION_PLOT_UPDATE_INTERVAL_SEC
                    ):
                        self._last_signal_integration_plot_update_time = now
                        if hasattr(self, 'trigger_signal_integration_update'):
                            self.trigger_signal_integration_update()
                        else:
                            self.update_signal_integration_plot()
                    # Always update the info label
                    total_samples = int(self.sweep_count) * samples_per_sweep
                    force_samples = len(force_state.data)
                    if self.is_full_view:
                        self.plot_info_label.setText(
                            f"ADC - Sweeps: {self.sweep_count} (full view) | Samples: {total_samples}  |  Force: {force_samples} samples"
                        )
                    else:
                        window_size = self.window_size_spin.value()
                        actual_sweeps = min(self.sweep_count, self.MAX_SWEEPS_BUFFER)
                        displayed_sweeps = min(actual_sweeps, window_size, MAX_PLOT_SWEEPS)
                        self.plot_info_label.setText(
                            f"ADC - Sweeps: {self.sweep_count} (showing last {displayed_sweeps}) | Samples: {total_samples}  |  Force: {force_samples} samples"
                        )
                
                # Track when this buffer finished being received
                block_end_time = time.time()
                
                # Calculate gap time between blocks:
                # Time from when last block finished receiving to when this block started receiving
                # This measures the transmission gap + Arduino processing time between blocks
                if timing.last_buffer_end_time is not None:
                    gap_time_ms = (block_start_time - timing.last_buffer_end_time) * 1000.0
                    timing.buffer_gap_times.append(gap_time_ms)
                    # Keep only recent gap times to prevent unbounded growth
                    timing.trim_recent('buffer_gap_times', MAX_TIMING_SAMPLES)
                
                timing.last_buffer_end_time = block_end_time
                
                # Update timing display after each block
                self.update_timing_display()

            except Exception as e:
                self.log_status(f"ERROR: Failed to process binary block - {e}")

    def _maybe_log_slow_timeseries_redraw(
        self,
        *,
        main_plot_ms: float,
        force_plot_ms: float,
        total_ms: float,
        sweeps_in_block: int,
        samples_per_sweep: int,
    ) -> None:
        """Emit sparse diagnostics when live Time Series redraw gets slow."""
        if total_ms < self._SLOW_TIMESERIES_UPDATE_MS:
            return
        if not hasattr(self, "log_status"):
            return

        now = time.time()
        last_log = getattr(self, "_last_slow_timeseries_log_time", 0.0)
        if (now - last_log) < self._SLOW_TIMESERIES_LOG_INTERVAL_SEC:
            return
        self._last_slow_timeseries_log_time = now

        self.log_status(
            "TimeSeries redraw slow: "
            f"main={main_plot_ms:.1f}ms, force={force_plot_ms:.1f}ms, total={total_ms:.1f}ms, "
            f"block_sweeps={sweeps_in_block}, samples_per_sweep={samples_per_sweep}, "
            f"sweep_count={int(getattr(self, 'sweep_count', 0))}"
        )
