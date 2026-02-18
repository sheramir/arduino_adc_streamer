"""
Binary Data Processor Mixin
============================
Handles processing of binary ADC data blocks from Arduino.
"""

import time
import json
import csv
from typing import List

import numpy as np

from config_constants import MAX_TIMING_SAMPLES, PLOT_UPDATE_FREQUENCY


class BinaryProcessorMixin:
    """Mixin for binary ADC data processing."""
    
    def process_binary_sweep(self, samples: List[int], avg_sample_time_us: int, block_start_us: int, block_end_us: int):
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
                # Track buffer arrival time (start of reception)
                block_start_time = time.time()
                
                # Keep only last 1000 buffer receipt times to prevent unbounded growth
                self.buffer_receipt_times.append(block_start_time)
                if len(self.buffer_receipt_times) > MAX_TIMING_SAMPLES:
                    self.buffer_receipt_times = self.buffer_receipt_times[-MAX_TIMING_SAMPLES:]
                
                # Track first sweep time for rate calculation - thread safe
                with self.buffer_lock:
                    is_first_sweep = (self.sweep_count == 0)
                
                if is_first_sweep:
                    self.capture_start_time = block_start_time
                    self.force_start_time = self.capture_start_time  # Sync force timing
                    self.last_buffer_time = block_start_time
                
                # Store the average sampling time from Arduino (keep only last 1000)
                self.arduino_sample_times.append(avg_sample_time_us)
                if len(self.arduino_sample_times) > MAX_TIMING_SAMPLES:
                    self.arduino_sample_times = self.arduino_sample_times[-MAX_TIMING_SAMPLES:]

                # Store MCU block timestamps (keep only last 1000)
                self.mcu_block_start_us.append(block_start_us)
                self.mcu_block_end_us.append(block_end_us)
                if len(self.mcu_block_start_us) > MAX_TIMING_SAMPLES:
                    self.mcu_block_start_us = self.mcu_block_start_us[-MAX_TIMING_SAMPLES:]
                    self.mcu_block_end_us = self.mcu_block_end_us[-MAX_TIMING_SAMPLES:]

                # MCU gap between blocks (wrap-safe unsigned math)
                if self.mcu_last_block_end_us is not None:
                    gap_us = (block_start_us - self.mcu_last_block_end_us) & 0xFFFFFFFF
                    self.mcu_block_gap_us.append(gap_us)
                    if len(self.mcu_block_gap_us) > MAX_TIMING_SAMPLES:
                        self.mcu_block_gap_us = self.mcu_block_gap_us[-MAX_TIMING_SAMPLES:]
                self.mcu_last_block_end_us = block_end_us
                
                # Calculate samples per sweep from configuration
                channel_count = len(self.config.get('channels', []))
                repeat_count = self.config.get('repeat', 1)
                samples_per_sweep = channel_count * repeat_count
                
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

                block_samples_array = np.array(samples[:total_samples], dtype=np.float32).reshape(sweeps_in_block, samples_per_sweep)
                total_fs_hz = (1000000.0 / avg_sample_time_us) if avg_sample_time_us > 0 else 0.0
                try:
                    filtered_block_array = self.filter_sweeps_block(block_samples_array, total_fs_hz)
                except Exception as e:
                    self.log_status(f"WARNING: filtering bypassed due to error: {e}")
                    self.filtering_enabled = False
                    filtered_block_array = block_samples_array

                # Track block sizing for timing export (keep only recent)
                self.block_sample_counts.append(total_samples)
                self.block_sweeps_counts.append(sweeps_in_block)
                self.block_samples_per_sweep.append(samples_per_sweep)
                if len(self.block_sample_counts) > MAX_TIMING_SAMPLES:
                    self.block_sample_counts = self.block_sample_counts[-MAX_TIMING_SAMPLES:]
                    self.block_sweeps_counts = self.block_sweeps_counts[-MAX_TIMING_SAMPLES:]
                    self.block_samples_per_sweep = self.block_samples_per_sweep[-MAX_TIMING_SAMPLES:]

                # Stream block timing to sidecar (if open)
                if self._block_timing_file:
                    try:
                        gap_us = ""
                        if self.mcu_block_gap_us:
                            gap_us = self.mcu_block_gap_us[-1]
                        tw = csv.writer(self._block_timing_file)
                        self._block_timing_write_count += 1
                        if self._block_timing_write_count % 100 == 0:
                            try:
                                self._block_timing_file.flush()
                            except Exception:
                                pass
                        tw.writerow([
                            self.block_sample_counts[-1],
                            self.block_samples_per_sweep[-1],
                            self.block_sweeps_counts[-1],
                            self.arduino_sample_times[-1],
                            block_start_us,
                            block_end_us,
                            gap_us
                        ])
                    except Exception:
                        pass
                
                # Process each complete sweep in the block
                # Write directly to numpy buffer (circular buffer)
                for sweep_idx in range(sweeps_in_block):
                    start_idx = sweep_idx * samples_per_sweep
                    end_idx = start_idx + samples_per_sweep
                    sweep_samples = samples[start_idx:end_idx]
                    filtered_sweep_samples = filtered_block_array[sweep_idx, :]
                    
                    # Calculate timestamp for this sweep based on MCU timing
                    # Use wrap-safe 32-bit arithmetic because Arduino micros() overflows ~71 minutes
                    sweep_time_offset_us = start_idx * avg_sample_time_us
                    sweep_timestamp_us = (block_start_us + sweep_time_offset_us) & 0xFFFFFFFF
                    
                    # Initialize first sweep timestamp - check outside lock, init inside lock
                    if not hasattr(self, 'first_sweep_timestamp_us'):
                        with self.buffer_lock:
                            if not hasattr(self, 'first_sweep_timestamp_us'):
                                self.first_sweep_timestamp_us = sweep_timestamp_us & 0xFFFFFFFF
                                self.log_status(f"First sweep timestamp initialized: {self.first_sweep_timestamp_us} µs (wrap-safe)")
                    
                    # Calculate relative timestamp (should always start near 0 for new capture)
                    # Wrap-safe delta to avoid negative time when MCU micros() overflows
                    delta_us = (sweep_timestamp_us - self.first_sweep_timestamp_us) & 0xFFFFFFFF
                    sweep_timestamp_sec = delta_us / 1e6
                    
                    # Write directly to numpy buffer (circular buffer) with thread safety
                    with self.buffer_lock:
                        write_pos = self.buffer_write_index % self.MAX_SWEEPS_BUFFER
                        self.raw_data_buffer[write_pos, :] = sweep_samples
                        self.processed_data_buffer[write_pos, :] = filtered_sweep_samples
                        self.sweep_timestamps_buffer[write_pos] = sweep_timestamp_sec
                        self.buffer_write_index += 1
                        self.sweep_count += 1

                    # Also keep in list for archive writing (only if archive is active)
                    if self._archive_file:
                        try:
                            self._archive_file.write(json.dumps(sweep_samples) + '\n')
                            self._archive_write_count += 1
                            if self._archive_write_count % 1000 == 0:
                                try:
                                    self._archive_file.flush()
                                except Exception:
                                    pass
                        except Exception:
                            pass

                # Update plot periodically for performance (after processing entire block)
                if self.sweep_count % PLOT_UPDATE_FREQUENCY == 0:
                    self.update_plot()
                    # Update info label based on current view mode - use buffer counts!
                    actual_sweeps = min(self.sweep_count, self.MAX_SWEEPS_BUFFER)
                    total_samples = actual_sweeps * samples_per_sweep
                    force_samples = len(self.force_data)
                    if self.is_full_view:
                        self.plot_info_label.setText(
                            f"ADC - Sweeps: {self.sweep_count} (full view) | Samples: {total_samples}  |  Force: {force_samples} samples"
                        )
                    else:
                        window_size = self.window_size_spin.value()
                        displayed_sweeps = min(actual_sweeps, window_size)
                        self.plot_info_label.setText(
                            f"ADC - Sweeps: {self.sweep_count} (showing last {displayed_sweeps}) | Samples: {total_samples}  |  Force: {force_samples} samples"
                        )
                    self.update_force_plot()
                
                # Track when this buffer finished being received
                block_end_time = time.time()
                
                # Calculate gap time between blocks:
                # Time from when last block finished receiving to when this block started receiving
                # This measures the transmission gap + Arduino processing time between blocks
                if self.last_buffer_end_time is not None:
                    gap_time_ms = (block_start_time - self.last_buffer_end_time) * 1000.0
                    self.buffer_gap_times.append(gap_time_ms)
                    # Keep only recent gap times to prevent unbounded growth
                    if len(self.buffer_gap_times) > MAX_TIMING_SAMPLES:
                        self.buffer_gap_times = self.buffer_gap_times[-MAX_TIMING_SAMPLES:]
                
                self.last_buffer_end_time = block_end_time
                
                # Update timing display after each block
                self.update_timing_display()

            except Exception as e:
                self.log_status(f"ERROR: Failed to process binary block - {e}")
