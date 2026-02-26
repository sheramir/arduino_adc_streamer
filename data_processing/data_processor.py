"""
Data Processing Mixin
=====================
Main mixin combining data processing, plotting, timing, and capture control.

This module combines:
- Serial parsing (SerialParserMixin)
- Binary data processing (BinaryProcessorMixin)
- Force data processing (ForceProcessorMixin)
- Plotting and visualization (defined here)
- Timing calculations (defined here)
- Capture control (defined here)
"""

import time
import csv
import json
from datetime import datetime
from typing import List
from pathlib import Path

import numpy as np
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import Qt, QTimer
import pyqtgraph as pg

from config_constants import (
    MAX_TIMING_SAMPLES, PLOT_UPDATE_FREQUENCY, PLOT_COLORS,
    MAX_FORCE_SAMPLES, MAX_LOG_LINES, IADC_RESOLUTION_BITS,
    ANALYZER555_DEFAULT_CF_FARADS, ANALYZER555_DEFAULT_RB_OHMS,
    ANALYZER555_DEFAULT_RK_OHMS,
    X_FORCE_SENSOR_TO_NEWTON, Z_FORCE_SENSOR_TO_NEWTON,
)

# Import sub-module mixins
from serial_communication.serial_parser import SerialParserMixin
from data_processing.binary_processor import BinaryProcessorMixin
from data_processing.filter_processor import FilterProcessorMixin
from data_processing.force_processor import ForceProcessorMixin


class DataProcessorMixin(FilterProcessorMixin, SerialParserMixin, BinaryProcessorMixin, ForceProcessorMixin):
    """Main mixin class for data processing, visualization, and capture control."""
    
    # ========================================================================
    # Plotting and Visualization
    # ========================================================================
    
    def update_plot(self):
        """Update the plot with current data - optimized for fast updates and max 10K samples."""
        # Prevent concurrent updates
        if self.is_updating_plot:
            return

        self.is_updating_plot = True

        try:
            active_data_buffer = self.get_active_data_buffer()

            if not self.is_capturing and active_data_buffer is None:
                # No data in buffer
                for curve in self._adc_curves.values():
                    curve.setVisible(False)
                self.is_updating_plot = False
                return
            
            if not self.config['channels']:
                for curve in self._adc_curves.values():
                    curve.setVisible(False)
                self.is_updating_plot = False
                return

            # Get selected channels from checkboxes
            selected_channels = [ch for ch, checkbox in self.channel_checkboxes.items() if checkbox.isChecked()]
            if not selected_channels:
                for curve in self._adc_curves.values():
                    curve.setVisible(False)
                self.is_updating_plot = False
                return

            # Configuration
            channels = self.config['channels']
            repeat_count = self.config['repeat']
            samples_per_sweep = len(channels) * repeat_count
            MAX_SAMPLES_TO_DISPLAY = 10000
            
            # Determine which data to plot - use numpy buffer directly with thread safety!
            if active_data_buffer is None:
                self.is_updating_plot = False
                return
            
            # Get snapshot of buffer state with lock
            with self.buffer_lock:
                current_sweep_count = self.sweep_count
                current_write_index = self.buffer_write_index
            
            # Calculate actual number of sweeps in buffer
            actual_sweeps = min(current_sweep_count, self.MAX_SWEEPS_BUFFER)
            
            if actual_sweeps == 0:
                for curve in self._adc_curves.values():
                    curve.setVisible(False)
                self.is_updating_plot = False
                return
            
            if self.is_full_view:
                # Full view: use legacy raw_data list loaded from archive
                if not self.raw_data or not self.sweep_timestamps:
                    self.is_updating_plot = False
                    return
                
                # Convert list data to numpy for plotting
                try:
                    # All sweeps have same length
                    samples_per_sweep = len(self.raw_data[0])
                    num_sweeps = len(self.raw_data)
                    
                    # Create numpy array from list data
                    data_array = np.array(self.raw_data, dtype=np.float32)  # shape: (num_sweeps, samples_per_sweep)
                    timestamps_array = np.array(self.sweep_timestamps, dtype=np.float64)
                except Exception as e:
                    self.log_status(f"Error converting archive data: {e}")
                    self.is_updating_plot = False
                    return
            elif self.is_capturing:
                # During capture: show last window_size sweeps
                window_size = self.window_size_spin.value()
                window_size = min(window_size, actual_sweeps)
                
                # Use circular buffer logic
                if actual_sweeps < self.MAX_SWEEPS_BUFFER:
                    # Buffer not yet full - data is contiguous from start
                    start_idx = max(0, actual_sweeps - window_size)
                    end_idx = actual_sweeps
                    data_array = active_data_buffer[start_idx:end_idx, :].copy()
                    timestamps_array = self.sweep_timestamps_buffer[start_idx:end_idx].copy()
                else:
                    # Buffer is full - need to handle circular wrap
                    # write_index points to next write position (oldest data will be overwritten there)
                    # So oldest data is at write_pos, newest is at write_pos-1
                    write_pos = current_write_index % self.MAX_SWEEPS_BUFFER
                    
                    if window_size >= self.MAX_SWEEPS_BUFFER:
                        # Show entire buffer - reorder to show oldest first
                        data_array = np.concatenate([
                            active_data_buffer[write_pos:, :],
                            active_data_buffer[:write_pos, :]
                        ])
                        timestamps_array = np.concatenate([
                            self.sweep_timestamps_buffer[write_pos:],
                            self.sweep_timestamps_buffer[:write_pos]
                        ])
                    else:
                        # Show last window_size from circular buffer
                        # Newest is at write_pos-1, so we want [write_pos-window_size : write_pos]
                        start_pos = (write_pos - window_size) % self.MAX_SWEEPS_BUFFER
                        if start_pos < write_pos:
                            data_array = active_data_buffer[start_pos:write_pos, :].copy()
                            timestamps_array = self.sweep_timestamps_buffer[start_pos:write_pos].copy()
                        else:
                            # Wrap around
                            data_array = np.concatenate([
                                active_data_buffer[start_pos:, :],
                                active_data_buffer[:write_pos, :]
                            ])
                            timestamps_array = np.concatenate([
                                self.sweep_timestamps_buffer[start_pos:],
                                self.sweep_timestamps_buffer[:write_pos]
                            ])
            else:
                # After capture: show same window as during capture for consistency
                # Use the window_size setting so user sees what they were looking at
                window_size = self.window_size_spin.value()
                max_sweeps = min(window_size, actual_sweeps)
                
                # Extract from circular buffer
                if actual_sweeps < self.MAX_SWEEPS_BUFFER:
                    # Buffer not yet full
                    start_idx = max(0, actual_sweeps - max_sweeps)
                    data_array = active_data_buffer[start_idx:actual_sweeps, :].copy()
                    timestamps_array = self.sweep_timestamps_buffer[start_idx:actual_sweeps].copy()
                else:
                    # Buffer is full
                    write_pos = current_write_index % self.MAX_SWEEPS_BUFFER
                    start_pos = (write_pos - max_sweeps) % self.MAX_SWEEPS_BUFFER
                    if start_pos < write_pos:
                        data_array = active_data_buffer[start_pos:write_pos, :].copy()
                        timestamps_array = self.sweep_timestamps_buffer[start_pos:write_pos].copy()
                    else:
                        data_array = np.concatenate([
                            active_data_buffer[start_pos:, :],
                            active_data_buffer[:write_pos, :]
                        ])
                        timestamps_array = np.concatenate([
                            self.sweep_timestamps_buffer[start_pos:],
                            self.sweep_timestamps_buffer[:write_pos]
                        ])
            
            if len(data_array) == 0 or len(timestamps_array) == 0:
                self.is_updating_plot = False
                return

            # Get unique channels in order
            unique_channels = []
            for ch in channels:
                if ch not in unique_channels:
                    unique_channels.append(ch)

            desired_curve_keys = set()
            latest_channel_values = {}
            
            # Calculate average sample time for intra-sweep timing
            if hasattr(self, 'arduino_sample_times') and self.arduino_sample_times:
                avg_sample_time_sec = (sum(self.arduino_sample_times) / len(self.arduino_sample_times)) / 1e6
            else:
                avg_sample_time_sec = 0

            # Data is ALREADY numpy array from buffer - no conversion needed!
            # Extract and plot data for each channel
            for ch_idx, channel in enumerate(unique_channels):
                if channel not in selected_channels:
                    continue

                color = PLOT_COLORS[ch_idx % len(PLOT_COLORS)]

                # Find all positions of this channel in the sequence
                positions = [i for i, c in enumerate(channels) if c == channel]

                # Extract data using numpy slicing (MUCH faster than loops!)
                channel_data_list = []
                channel_times_list = []
                
                for pos in positions:
                    start_idx = pos * repeat_count
                    end_idx = start_idx + repeat_count
                    
                    # Extract all repeats for this position across all sweeps (single numpy operation!)
                    pos_data = data_array[:, start_idx:end_idx]  # Shape: (num_sweeps, repeat_count)
                    
                    # Flatten to 1D: [sweep0_r0, sweep0_r1, ..., sweep1_r0, sweep1_r1, ...]
                    pos_data_flat = pos_data.flatten()
                    channel_data_list.append(pos_data_flat)
                    
                    # Generate timestamps for all samples
                    # Create time offsets for each sample within a sweep
                    sample_indices = np.arange(start_idx, end_idx)
                    time_offsets = sample_indices * avg_sample_time_sec
                    
                    # Repeat sweep timestamps for each repeat, then add offsets
                    sweep_times = np.repeat(timestamps_array, repeat_count)
                    offsets_tiled = np.tile(time_offsets, len(timestamps_array))
                    pos_times = sweep_times + offsets_tiled
                    channel_times_list.append(pos_times)
                
                # Concatenate all positions
                if not channel_data_list:
                    continue
                    
                channel_data = np.concatenate(channel_data_list)
                channel_times = np.concatenate(channel_times_list)

                if len(channel_data) > 0:
                    latest_channel_values[channel] = float(channel_data[-1])

                # Convert to voltage if voltage units mode is enabled
                if getattr(self, 'device_mode', 'adc') != '555' and self.yaxis_units_combo.currentText() == "Voltage":
                    vref = self.get_vref_voltage()
                    max_adc_value = (2 ** IADC_RESOLUTION_BITS) - 1  # 4095 for 12-bit
                    channel_data = (channel_data / max_adc_value) * vref

                # Downsample if too many points for this channel
                if len(channel_data) > MAX_SAMPLES_TO_DISPLAY:
                    downsample_factor = len(channel_data) // MAX_SAMPLES_TO_DISPLAY
                    channel_data = channel_data[::downsample_factor]
                    channel_times = channel_times[::downsample_factor]

                # Show based on visualization mode
                if self.show_all_repeats_radio.isChecked() and repeat_count > 1:
                    # Reshape to separate repeats
                    try:
                        num_samples = len(channel_data) // repeat_count
                        if num_samples > 0:
                            channel_data_2d = channel_data[:num_samples * repeat_count].reshape(-1, repeat_count)
                            channel_times_2d = channel_times[:num_samples * repeat_count].reshape(-1, repeat_count)

                            # Plot each repeat as a separate line
                            for repeat_idx in range(repeat_count):
                                repeat_data = channel_data_2d[:, repeat_idx]
                                repeat_times = channel_times_2d[:, repeat_idx]

                                # Use slightly different line styles for each repeat
                                if repeat_idx == 0:
                                    pen = pg.mkPen(color=color, width=2)
                                else:
                                    lighter_color = tuple(int(c * 0.7) for c in color)
                                    pen = pg.mkPen(color=lighter_color, width=1.5, style=Qt.PenStyle.DashLine)
                                
                                name = f"Ch {channel}.{repeat_idx}"
                                curve_key = ("repeat", channel, repeat_idx)
                                desired_curve_keys.add(curve_key)
                                
                                curve = self._adc_curves.get(curve_key)
                                if curve is None:
                                    curve = self.plot_widget.plot([], pen=pen, name=name)
                                    self._adc_curves[curve_key] = curve
                                
                                curve.setVisible(True)
                                curve.setPen(pen)
                                curve.setData(x=repeat_times, y=repeat_data)
                    except Exception as e:
                        self.log_status(f"ERROR: Failed to reshape repeat data - {e}")
                        continue
                else:
                    # Single line for all data (either single repeat or averaging mode)
                    if self.show_average_radio.isChecked() and repeat_count > 1:
                        # Compute average across repeats
                        try:
                            num_samples = len(channel_data) // repeat_count
                            if num_samples > 0:
                                channel_data_2d = channel_data[:num_samples * repeat_count].reshape(-1, repeat_count)
                                channel_times_2d = channel_times[:num_samples * repeat_count].reshape(-1, repeat_count)
                                channel_data = np.mean(channel_data_2d, axis=1)
                                channel_times = channel_times_2d[:, 0]  # Use first repeat's times
                                name = f"Ch {channel} (avg)"
                                pen = pg.mkPen(color=color, width=3, style=Qt.PenStyle.DashLine)
                                curve_key = ("avg", channel, 0)
                            else:
                                continue
                        except Exception as e:
                            self.log_status(f"ERROR: Failed to average repeat data - {e}")
                            continue
                    else:
                        # Single repeat or show all together
                        name = f"Ch {channel}"
                        pen = pg.mkPen(color=color, width=2)
                        curve_key = ("single", channel, 0)
                    
                    desired_curve_keys.add(curve_key)
                    curve = self._adc_curves.get(curve_key)
                    if curve is None:
                        curve = self.plot_widget.plot([], pen=pen, name=name)
                        self._adc_curves[curve_key] = curve
                    
                    curve.setVisible(True)
                    curve.setPen(pen)
                    curve.setData(x=channel_times, y=channel_data)

            # Hide curves that are not in use
            for key, curve in self._adc_curves.items():
                if key not in desired_curve_keys:
                    curve.setVisible(False)

            # Update axis labels
            if getattr(self, 'device_mode', 'adc') == '555':
                self.plot_widget.setLabel('left', 'Resistance', units='Ω')
            elif self.yaxis_units_combo.currentText() == "Voltage":
                self.plot_widget.setLabel('left', 'Voltage', units='V')
            else:
                self.plot_widget.setLabel('left', 'ADC Value', units='counts')
            
            self.plot_widget.setLabel('bottom', 'Time', units='s')

            # Apply Y-axis range
            self.apply_y_axis_range()

            # Update 555 analyzer timing readouts
            self.update_555_timing_readouts(latest_channel_values)

        except Exception as e:
            self.log_status(f"ERROR updating plot: {e}")
        finally:
            self.is_updating_plot = False
    
    def update_force_plot(self):
        """Update the force measurement plot with time-based alignment to ADC data."""
        show_x_force = self.force_x_checkbox and self.force_x_checkbox.isChecked()
        show_z_force = self.force_z_checkbox and self.force_z_checkbox.isChecked()

        # Hide curves if not selected
        if not show_x_force and self._force_x_curve is not None:
            self._force_x_curve.setVisible(False)
        if not show_z_force and self._force_z_curve is not None:
            self._force_z_curve.setVisible(False)

        if not self.force_data or (not show_x_force and not show_z_force):
            return
        
        # Need timestamps from buffer, not legacy list
        if self.sweep_timestamps_buffer is None:
            return
        
        # Get snapshot of buffer state with lock
        with self.buffer_lock:
            current_sweep_count = self.sweep_count
            current_write_index = self.buffer_write_index
            # Copy min/max timestamps while locked
            actual_sweeps = min(current_sweep_count, self.MAX_SWEEPS_BUFFER)
            
            if actual_sweeps == 0:
                return
            
            # Calculate indices and copy timestamps inside lock to avoid race
            if self.is_full_view:
                # Would need archive data
                return
            elif self.is_capturing:
                window_size = self.window_size_spin.value()
                window_size = min(window_size, actual_sweeps)
                
                if actual_sweeps < self.MAX_SWEEPS_BUFFER:
                    start_idx = max(0, actual_sweeps - window_size)
                    min_time = self.sweep_timestamps_buffer[start_idx]
                    max_time = self.sweep_timestamps_buffer[actual_sweeps - 1]
                else:
                    write_pos = current_write_index % self.MAX_SWEEPS_BUFFER
                    newest_idx = (write_pos - 1) % self.MAX_SWEEPS_BUFFER
                    oldest_idx = (write_pos - window_size) % self.MAX_SWEEPS_BUFFER
                    min_time = self.sweep_timestamps_buffer[oldest_idx]
                    max_time = self.sweep_timestamps_buffer[newest_idx]
            else:
                # After capture
                if actual_sweeps < self.MAX_SWEEPS_BUFFER:
                    min_time = self.sweep_timestamps_buffer[0]
                    max_time = self.sweep_timestamps_buffer[actual_sweeps - 1]
                else:
                    write_pos = current_write_index % self.MAX_SWEEPS_BUFFER
                    oldest_idx = write_pos
                    newest_idx = (write_pos - 1) % self.MAX_SWEEPS_BUFFER
                    min_time = self.sweep_timestamps_buffer[oldest_idx]
                    max_time = self.sweep_timestamps_buffer[newest_idx]
        
        if current_sweep_count == 0:
            return

        try:
            # Filter and downsample force data
            if not self.force_data:
                return
            
            # Convert force data to numpy once if not already
            # (Future optimization: store force_data as numpy buffer too)
            force_array = np.array(self.force_data, dtype=np.float64)
            force_times = force_array[:, 0]
            
            # Use numpy binary search (much faster than linear!)
            start_idx = np.searchsorted(force_times, min_time, side='left')
            end_idx = np.searchsorted(force_times, max_time, side='right')
            
            # Slice the relevant data
            force_filtered = force_array[start_idx:end_idx]
            if len(force_filtered) == 0:
                return
            
            # Downsample after filtering
            MAX_FORCE_POINTS = 2000
            if len(force_filtered) > MAX_FORCE_POINTS:
                downsample_factor = len(force_filtered) // MAX_FORCE_POINTS
                force_filtered = force_filtered[::downsample_factor]

            # Extract X and Z force data
            times = force_filtered[:, 0]
            x_forces = force_filtered[:, 1] / X_FORCE_SENSOR_TO_NEWTON
            z_forces = force_filtered[:, 2] / Z_FORCE_SENSOR_TO_NEWTON

            # Plot X force (red)
            if show_x_force:
                if self._force_x_curve is None:
                    pen = pg.mkPen(color='r', width=2)
                    self._force_x_curve = pg.PlotDataItem([], pen=pen, name='X Force [N]')
                    self.force_viewbox.addItem(self._force_x_curve)
                
                self._force_x_curve.setVisible(True)
                self._force_x_curve.setData(x=times, y=x_forces)

            # Plot Z force (blue)
            if show_z_force:
                if self._force_z_curve is None:
                    pen = pg.mkPen(color='b', width=2)
                    self._force_z_curve = pg.PlotDataItem([], pen=pen, name='Z Force [N]')
                    self.force_viewbox.addItem(self._force_z_curve)
                
                self._force_z_curve.setVisible(True)
                self._force_z_curve.setData(x=times, y=z_forces)

        except Exception as e:
            self.log_status(f"ERROR: Failed to update force plot - {e}")
    
    def apply_y_axis_range(self):
        """Apply Y-axis range setting to the plot."""
        if getattr(self, 'device_mode', 'adc') == '555':
            self.plot_widget.enableAutoRange(axis='y')
            return

        range_text = self.yaxis_range_combo.currentText()
        units_text = self.yaxis_units_combo.currentText()
        
        if range_text == "Adaptive":
            # Auto-scale to visible data
            self.plot_widget.enableAutoRange(axis='y')
        elif range_text == "Full-Scale":
            # Fixed range based on ADC resolution and units
            if units_text == "Voltage":
                # Full voltage range based on reference
                vref = self.get_vref_voltage()
                self.plot_widget.setYRange(0, vref, padding=0.02)
            else:
                # Full ADC range (raw values: 0 to 4095 for 12-bit)
                max_adc_value = (2 ** IADC_RESOLUTION_BITS) - 1  # 4095
                self.plot_widget.setYRange(0, max_adc_value, padding=0.02)
        else:
            # Fallback to adaptive
            self.plot_widget.enableAutoRange(axis='y')
    
    # ========================================================================
    # Timing Display
    # ========================================================================
    
    def update_timing_display(self):
        """Update timing display based on Arduino measurements and buffer gap timing."""
        try:
            # Use only the most recent timing value from Arduino
            arduino_avg_sample_time_us = 0
            if hasattr(self, 'arduino_sample_times') and self.arduino_sample_times:
                # Use only the last received value
                arduino_avg_sample_time_us = self.arduino_sample_times[-1]
            
            # Calculate sampling rate from Arduino's measurement
            arduino_sample_rate_hz = 0
            arduino_per_channel_rate_hz = 0
            if arduino_avg_sample_time_us > 0:
                # Total sampling rate: 1,000,000 µs/s ÷ sample_time_us
                arduino_sample_rate_hz = 1000000.0 / arduino_avg_sample_time_us
                
                # Per-channel rate: divide total rate by number of unique channels
                channels = self.config.get('channels', [])
                if channels:
                    num_unique_channels = len(set(channels))
                    arduino_per_channel_rate_hz = arduino_sample_rate_hz / num_unique_channels
                else:
                    arduino_per_channel_rate_hz = arduino_sample_rate_hz
            
            # Calculate gap between blocks (prefer MCU timing if available)
            buffer_gap_time_ms = 0
            if hasattr(self, 'mcu_block_gap_us') and self.mcu_block_gap_us:
                buffer_gap_time_ms = self.mcu_block_gap_us[-1] / 1000.0
            elif hasattr(self, 'buffer_gap_times') and self.buffer_gap_times:
                # Average all host gap times to smooth out fluctuations
                buffer_gap_time_ms = sum(self.buffer_gap_times) / len(self.buffer_gap_times)
            
            # Store timing data
            self.timing_data['arduino_sample_time_us'] = arduino_avg_sample_time_us
            self.timing_data['arduino_sample_rate_hz'] = arduino_sample_rate_hz
            self.timing_data['per_channel_rate_hz'] = arduino_per_channel_rate_hz
            self.timing_data['total_rate_hz'] = arduino_sample_rate_hz
            self.timing_data['buffer_gap_time_ms'] = buffer_gap_time_ms
            # Store latest MCU timing values (if available)
            if hasattr(self, 'mcu_block_start_us') and self.mcu_block_start_us:
                self.timing_data['mcu_block_start_us'] = self.mcu_block_start_us[-1]
                self.timing_data['mcu_block_end_us'] = self.mcu_block_end_us[-1]
                if self.mcu_block_gap_us:
                    self.timing_data['mcu_block_gap_us'] = self.mcu_block_gap_us[-1]
            
            # Update timing labels with Arduino data
            if arduino_avg_sample_time_us > 0:
                self.per_channel_rate_label.setText(f"{arduino_per_channel_rate_hz:.2f} Hz")
                self.total_rate_label.setText(f"{arduino_sample_rate_hz:.2f} Hz")
                self.between_samples_label.setText(f"{arduino_avg_sample_time_us:.2f} µs")
            else:
                self.per_channel_rate_label.setText("- Hz")
                self.total_rate_label.setText("- Hz")
                self.between_samples_label.setText("- µs")
            
            # Display block gap time (always show if we have data)
            if buffer_gap_time_ms > 0:
                self.block_gap_label.setText(f"{buffer_gap_time_ms:.2f} ms")
            elif hasattr(self, 'mcu_block_gap_us') and len(self.mcu_block_gap_us) > 0:
                self.block_gap_label.setText(f"{(self.mcu_block_gap_us[-1] / 1000.0):.2f} ms")
            elif hasattr(self, 'buffer_gap_times') and len(self.buffer_gap_times) > 0:
                # Show even if current value is 0, as long as we have history
                avg_gap = sum(self.buffer_gap_times) / len(self.buffer_gap_times)
                self.block_gap_label.setText(f"{avg_gap:.2f} ms")
            else:
                self.block_gap_label.setText("- ms")
            
        except Exception as e:
            self.log_status(f"ERROR: Failed to update timing display - {e}")
    
    # ========================================================================
    # Capture Control
    # ========================================================================
    
    def start_capture(self):
        """Start data capture."""
        if not self.config['channels']:
            QMessageBox.warning(
                self,
                "Configuration Error",
                "Please configure channels before starting capture."
            )
            return

        # Configuration should already be done via Configure button
        # No need to send it again here

        # Lock configuration controls
        self.set_controls_enabled(False)

        # If currently in full view, reset to normal view before starting new capture
        if self.is_full_view:
            self.reset_graph_view()
            self.log_status("Resetting from full view to normal view for new capture")
        
        # Disable Full View button during capture
        self.full_view_btn.setEnabled(False)

        # Clear previous data - thread safe
        with self.buffer_lock:
            self.raw_data.clear()
            self.sweep_timestamps.clear()
            self.sweep_count = 0
            self.buffer_write_index = 0
            # Zero out buffers to prevent old data from showing
            if self.raw_data_buffer is not None:
                self.raw_data_buffer.fill(0)
            if self.processed_data_buffer is not None:
                self.processed_data_buffer.fill(0)
            if self.sweep_timestamps_buffer is not None:
                self.sweep_timestamps_buffer.fill(0)

        self.filter_apply_pending = True
        self.reset_filter_states()
        
        self.force_data.clear()
        self.force_start_time = None
        
        # Reset timestamp reference to ensure time starts at 0
        if hasattr(self, 'first_sweep_timestamp_us'):
            delattr(self, 'first_sweep_timestamp_us')

        # Clear timing data for new measurement
        self.timing_data = {
            'per_channel_rate_hz': None,
            'total_rate_hz': None,
            'between_samples_us': None,
            'arduino_sample_time_us': None,
            'arduino_sample_rate_hz': None,
            'buffer_gap_time_ms': None,
            'mcu_block_start_us': None,
            'mcu_block_end_us': None,
            'mcu_block_gap_us': None
        }
        self.capture_start_time = None
        self.capture_end_time = None
        self.last_buffer_time = None
        self.last_buffer_end_time = None
        self.buffer_receipt_times.clear()
        self.buffer_gap_times.clear()
        self.arduino_sample_times.clear()
        self.block_sample_counts.clear()
        self.block_sweeps_counts.clear()
        self.block_samples_per_sweep.clear()
        self.mcu_block_start_us.clear()
        self.mcu_block_end_us.clear()
        self.mcu_block_gap_us.clear()
        self.mcu_last_block_end_us = None
        self.per_channel_rate_label.setText("- Hz")
        self.total_rate_label.setText("- Hz")
        self.between_samples_label.setText("- µs")
        self.block_gap_label.setText("- ms")

        # Disable plot interactions during capture (scrolling mode)
        self.plot_widget.setMouseEnabled(x=False, y=False)
        self.plot_widget.setMenuEnabled(False)

        # Switch to binary capture mode BEFORE sending run command
        # Open an archive file so we persist every sweep to disk. This ensures we
        # never lose access to data even though the in-memory buffer is a rolling window.
        save_dir = Path(self.dir_input.text()) if hasattr(self, 'dir_input') else Path.cwd()
        save_dir.mkdir(parents=True, exist_ok=True)
        base_name = self.filename_input.text().strip() if hasattr(self, 'filename_input') else 'adc_data'
        # Use minute-resolution filenames (no seconds)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        archive_name = f"{base_name}_{timestamp}.jsonl"
        archive_path = save_dir / archive_name
        timing_name = f"{base_name}_{timestamp}_block_timing.csv"
        timing_path = save_dir / timing_name

        try:
            # Open for write (overwrite any existing file with same name) and store handle
            self._archive_file = open(archive_path, 'w', encoding='utf-8')
            self._archive_path = str(archive_path)
            self._archive_write_count = 0
            # Write a metadata header line for later reference
            try:
                metadata = {
                    'metadata': {
                        'channels': self.config.get('channels', []),
                        'repeat': self.config.get('repeat', 1),
                        'ground_pin': self.config.get('ground_pin'),
                        'use_ground': self.config.get('use_ground'),
                        'osr': self.config.get('osr'),
                        'gain': self.config.get('gain'),
                        'reference': self.config.get('reference'),
                        'notes': self.notes_input.toPlainText() if hasattr(self, 'notes_input') else None,
                        'start_time': datetime.now().isoformat()
                    }
                }
                self._archive_file.write(json.dumps(metadata) + '\n')
            except Exception:
                pass
            self.log_status(f"Archive opened: {self._archive_path}")
        except Exception as e:
            self.log_status(f"WARNING: Could not open archive file: {e}")

        try:
            # Open block timing sidecar and write header
            self._block_timing_file = open(timing_path, 'w', encoding='utf-8', newline='')
            self._block_timing_path = str(timing_path)
            try:
                tw = csv.writer(self._block_timing_file)
                tw.writerow(["sample_count", "samples_per_sweep", "sweeps_in_block", "avg_dt_us", "block_start_us", "block_end_us", "mcu_gap_us"])
                self._block_timing_file.flush()
            except Exception:
                pass
            if self._block_timing_path:
                self.log_status(f"Block timing opened: {self._block_timing_path}")
        except Exception as e:
            self._block_timing_file = None
            self._block_timing_path = None
            self.log_status(f"WARNING: Could not open block timing file: {e}")

        self.is_capturing = True
        if self.serial_thread:
            self.serial_thread.set_capturing(True)
        
        # Wait for thread to fully switch modes
        time.sleep(0.05)

        # Send run command - binary data will start flowing
        if self.timed_run_check.isChecked():
            duration_ms = self.timed_run_spin.value()
            self.send_command(f"run {duration_ms}")
            self.log_status(f"Starting timed capture for {duration_ms} ms")

            # Set timer to re-enable controls after timed run
            QTimer.singleShot(duration_ms + 500, self.on_capture_finished)
        else:
            self.send_command("run")
            self.log_status("Starting continuous capture")

        self.start_btn.setEnabled(False)
        self.start_btn.setStyleSheet("QPushButton { background-color: #CCCCCC; color: #666666; font-weight: bold; }")
        self.stop_btn.setEnabled(True)
        self.stop_btn.setStyleSheet("QPushButton { background-color: #f44336; color: white; font-weight: bold; }")
        self.statusBar().showMessage("Capturing - Scrolling Mode")

    def stop_capture(self):
        """Stop data capture."""
        if not self.is_capturing:
            self.log_status("Stop requested but capture already stopped")
            return

        self.log_status("Stopping capture")

        # Ask MCU to stop and wait briefly for acknowledgement
        success, _ = self.send_command_and_wait_ack(
            "stop",
            expected_value=None,
            timeout=0.5,
            max_retries=3
        )

        if not success:
            self.log_status("WARNING: Stop command not acknowledged; halting locally")

        # Immediately exit binary mode on the reader thread
        if self.serial_thread:
            self.serial_thread.set_capturing(False)

        self.is_capturing = False

        # Flush any residual binary bytes so the next run starts clean
        self.drain_serial_input(0.5)

        self.on_capture_finished()

    def on_capture_finished(self):
        """Handle capture finished (either stopped or timed out)."""
        # Record end time
        self.capture_end_time = time.time()
        
        self.is_capturing = False
        
        # Stop force data collection by clearing force_start_time
        # This prevents force data from continuing after ADC stops
        self.force_start_time = None
        
        # Notify serial thread that we're not capturing (disables binary mode)
        if self.serial_thread:
            self.serial_thread.set_capturing(False)
        
        # Log final timing summary
        time.sleep(0.1)  # Wait for Arduino to finish sending binary data
        if hasattr(self, 'arduino_sample_times') and self.arduino_sample_times:
            avg_sample_time = sum(self.arduino_sample_times) / len(self.arduino_sample_times)
            total_rate = 1000000.0 / avg_sample_time if avg_sample_time > 0 else 0
            self.log_status(f"Capture complete - Sample interval: {avg_sample_time:.2f} µs, Total rate: {total_rate:.2f} Hz")
        
        if hasattr(self, 'buffer_gap_times') and self.buffer_gap_times:
            avg_gap = sum(self.buffer_gap_times) / len(self.buffer_gap_times)
            self.log_status(f"Average block gap: {avg_gap:.2f} ms ({len(self.buffer_gap_times)} blocks)")
        
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("QPushButton { background-color: #CCCCCC; color: #666666; font-weight: bold; }")
        self.update_start_button_state()  # Restore start button to proper state
        self.set_controls_enabled(True)

        # Final safety: discard any leftover bytes so the next capture starts clean
        self.drain_serial_input(0.3)
        
        # Enable Full View button now that capture is finished (unless already in full view)
        if not self.is_full_view:
            self.full_view_btn.setEnabled(True)

        # Enable plot interactions for static mode (zoom/scroll enabled)
        self.plot_widget.setMouseEnabled(x=True, y=True)
        self.plot_widget.setMenuEnabled(True)

        self.statusBar().showMessage("Connected - Static Display Mode")

        # Final plot update (shows all data)
        self.update_plot()
        # Calculate total samples correctly from buffer
        with self.buffer_lock:
            actual_sweeps = min(self.sweep_count, self.MAX_SWEEPS_BUFFER)
            total_samples = actual_sweeps * self.samples_per_sweep if self.samples_per_sweep > 0 else 0
        force_samples = len(self.force_data)
        self.plot_info_label.setText(
            f"ADC - Sweeps: {self.sweep_count} | Samples: {total_samples}  |  Force: {force_samples} samples"
        )

        # Close archive file if open
        try:
            if self._archive_file:
                try:
                    self._archive_file.flush()
                except Exception:
                    pass
                try:
                    self._archive_file.close()
                except Exception:
                    pass
                self.log_status(f"Archive saved: {self._archive_path}")
        except Exception:
            pass
        # Close block timing file if open
        try:
            if self._block_timing_file:
                try:
                    self._block_timing_file.flush()
                except Exception:
                    pass
                try:
                    self._block_timing_file.close()
                except Exception:
                    pass
                self.log_status(f"Block timing saved: {self._block_timing_path}")
        except Exception:
            pass

        self.log_status(f"Capture finished. Total sweeps: {self.sweep_count}, Total samples: {total_samples}, Force samples: {force_samples}")

    def set_controls_enabled(self, enabled: bool):
        """Enable or disable configuration controls."""
        # Serial connection
        self.port_combo.setEnabled(enabled and not self.serial_port)
        self.refresh_ports_btn.setEnabled(enabled and not self.serial_port)

        # ADC configuration
        self.vref_combo.setEnabled(enabled)
        self.osr_combo.setEnabled(enabled)
        self.gain_combo.setEnabled(enabled)

        # Acquisition settings
        self.channels_input.setEnabled(enabled)
        self.ground_pin_spin.setEnabled(enabled)
        self.use_ground_check.setEnabled(enabled)
        self.repeat_spin.setEnabled(enabled)
        self.buffer_spin.setEnabled(enabled)

        # Run control
        self.timed_run_check.setEnabled(enabled)
        if enabled:
            self.timed_run_spin.setEnabled(self.timed_run_check.isChecked())
        else:
            self.timed_run_spin.setEnabled(False)

        # Visualization controls
        self.window_size_spin.setEnabled(enabled)

    def clear_data(self):
        """Clear all captured data and completely reset plot to initial state."""
        # Prevent clearing during capture to avoid race conditions
        if self.is_capturing:
            QMessageBox.warning(self, "Cannot Clear", "Cannot clear data during capture. Please stop capture first.")
            return
        
        reply = QMessageBox.question(
            self,
            "Clear Data",
            "Are you sure you want to clear all captured data?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Ensure any leftover bytes from a previous capture are discarded
            self.drain_serial_input(0.3)

            # Clear all data structures with thread safety
            with self.buffer_lock:
                self.raw_data.clear()
                self.sweep_timestamps.clear()
                self.sweep_count = 0
                self.buffer_write_index = 0
                # Reset buffer to zeros (optional, but cleaner)
                if self.raw_data_buffer is not None:
                    self.raw_data_buffer.fill(0)
                    if self.processed_data_buffer is not None:
                        self.processed_data_buffer.fill(0)
                    self.sweep_timestamps_buffer.fill(0)
            
            self.force_data.clear()
            
            # Reset ALL timestamp and timing references for next capture
            if hasattr(self, 'first_sweep_timestamp_us'):
                self.log_status(f"Clearing first_sweep_timestamp_us (was {self.first_sweep_timestamp_us} µs)")
                delattr(self, 'first_sweep_timestamp_us')
            else:
                self.log_status("first_sweep_timestamp_us already cleared")
            self.capture_start_time = None
            self.capture_end_time = None
            self.force_start_time = None
            self.last_buffer_time = None
            self.last_buffer_end_time = None
            self.mcu_last_block_end_us = None
            
            # Clear all timing data lists
            self.buffer_receipt_times.clear()
            self.buffer_gap_times.clear()
            self.arduino_sample_times.clear()
            self.block_sample_counts.clear()
            self.block_sweeps_counts.clear()
            self.block_samples_per_sweep.clear()
            self.mcu_block_start_us.clear()
            self.mcu_block_end_us.clear()
            self.mcu_block_gap_us.clear()
            
            # Reset samples_per_sweep to force buffer reinitialization
            self.samples_per_sweep = 0
            self.filter_apply_pending = True
            self.reset_filter_states()
            
            # Reset view mode flags
            self.is_full_view = False
            self.full_view_btn.setEnabled(False)
            
            # COMPLETELY DELETE all ADC curves (not just hide)
            for curve in self._adc_curves.values():
                self.plot_widget.removeItem(curve)
            self._adc_curves.clear()
            
            # COMPLETELY DELETE force curves
            if self._force_x_curve is not None:
                self.force_viewbox.removeItem(self._force_x_curve)
                self._force_x_curve = None
            if self._force_z_curve is not None:
                self.force_viewbox.removeItem(self._force_z_curve)
                self._force_z_curve = None
            
            # Clear and recreate legends to reset them
            self.plot_widget.removeItem(self.adc_legend)
            self.adc_legend = self.plot_widget.addLegend(offset=(10, 10))
            
            # Reset plot to initial state
            self.plot_widget.setXRange(0, 1, padding=0)
            self.plot_widget.setYRange(0, 1, padding=0)
            self.force_viewbox.setXRange(0, 1, padding=0)
            self.force_viewbox.setYRange(0, 1, padding=0)
            
            # Reset zoom/pan - enable auto range
            self.plot_widget.enableAutoRange()
            self.force_viewbox.enableAutoRange()
            
            # Reset axis labels to initial state
            self.plot_widget.setLabel('left', 'ADC Value', units='counts')
            self.plot_widget.setLabel('bottom', 'Time', units='s')
            self.plot_widget.setLabel('right', 'Force', units='N')
            
            # Update info label
            self.plot_info_label.setText("ADC - Sweeps: 0 | Samples: 0  |  Force: 0 samples")
            self.log_status("Data cleared - plot reset to initial state")
    
    # ========================================================================
    # Helper Methods
    # ========================================================================
    
    def get_vref_voltage(self) -> float:
        """Get the numeric voltage reference value."""
        vref_str = self.config['reference']

        # Map reference strings to voltage values
        if vref_str == "1.2":
            return 1.2
        elif vref_str == "3.3" or vref_str == "vdd":
            return 3.3
        elif vref_str == "0.8vdd":
            return 3.3 * 0.8  # 2.64V
        elif vref_str == "ext":
            return 1.25  # External reference
        else:
            return 3.3  # Default to VDD

    def _format_time_auto(self, seconds: float) -> str:
        value = max(0.0, float(seconds))
        if value < 1e-3:
            return f"{value * 1e6:.2f} µs"
        if value < 1.0:
            return f"{value * 1e3:.2f} ms"
        return f"{value:.4f} s"

    def update_555_timing_readouts(self, latest_channel_values):
        if not hasattr(self, 'charge_time_label') or not hasattr(self, 'discharge_time_label'):
            return

        if getattr(self, 'device_mode', 'adc') != '555':
            self.charge_time_label.setVisible(False)
            self.discharge_time_label.setVisible(False)
            return

        self.charge_time_label.setVisible(True)
        self.discharge_time_label.setVisible(True)

        cf_farads = float(self.config.get('cf_farads', ANALYZER555_DEFAULT_CF_FARADS))
        rb_ohms = float(self.config.get('rb_ohms', ANALYZER555_DEFAULT_RB_OHMS))
        rk_ohms = float(self.config.get('rk_ohms', ANALYZER555_DEFAULT_RK_OHMS))
        ln2 = 0.69314718056

        t_discharge = ln2 * cf_farads * rb_ohms

        if not latest_channel_values:
            self.charge_time_label.setText("Charge time: waiting for channel data...")
            self.discharge_time_label.setText(f"Discharge time: {self._format_time_auto(t_discharge)}")
            return

        parts = []
        for channel in sorted(latest_channel_values.keys()):
            rx = max(0.0, float(latest_channel_values[channel]))
            t_charge = ln2 * cf_farads * (rx + rk_ohms + rb_ohms)
            parts.append(f"Ch{channel}: {self._format_time_auto(t_charge)}")

        self.charge_time_label.setText("Charge time: " + " | ".join(parts))
        self.discharge_time_label.setText(f"Discharge time: {self._format_time_auto(t_discharge)}")
    
    def log_status(self, message: str):
        """Log a status message."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.status_text.append(f"[{timestamp}] {message}")
        
        # Limit status text to prevent memory overflow during long sessions
        # QTextEdit.toPlainText() includes all lines with newlines
        current_text = self.status_text.toPlainText()
        lines = current_text.split('\n')
        if len(lines) > MAX_LOG_LINES:
            # Keep only the most recent lines
            self.status_text.setPlainText('\n'.join(lines[-MAX_LOG_LINES:]))
        
        # Auto-scroll to bottom
        self.status_text.verticalScrollBar().setValue(
            self.status_text.verticalScrollBar().maximum()
        )
