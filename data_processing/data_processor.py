"""
Data Processing Mixin
=====================
Main mixin combining data processing, plotting, timing, and capture lifecycle.

This module combines:
- Serial parsing (SerialParserMixin)
- Binary data processing (BinaryProcessorMixin)
- Force data processing (ForceProcessorMixin)
- Capture lifecycle (CaptureLifecycleMixin)
- Plotting and visualization (defined here)
- Timing calculations (defined here)
"""

import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox

from config_constants import (
    MAX_LOG_LINES, IADC_RESOLUTION_BITS, MAX_PLOT_SWEEPS,
    ANALYZER555_DEFAULT_CF_FARADS, ANALYZER555_DEFAULT_RB_OHMS,
    ANALYZER555_DEFAULT_RK_OHMS,
    X_FORCE_SENSOR_TO_NEWTON, Z_FORCE_SENSOR_TO_NEWTON,
)

# Import sub-module mixins
from data_processing.capture_lifecycle import CaptureLifecycleMixin
from data_processing.adc_plotting import ADCPlottingMixin
from serial_communication.serial_parser import SerialParserMixin
from data_processing.binary_processor import BinaryProcessorMixin
from data_processing.filter_processor import FilterProcessorMixin
from data_processing.force_processor import ForceProcessorMixin


@dataclass
class TimingState:
    """Central store for timing metrics and recent timing history."""

    timing_data: dict
    capture_start_time: float | None = None
    capture_end_time: float | None = None
    last_buffer_time: float | None = None
    last_buffer_end_time: float | None = None
    mcu_last_block_end_us: int | None = None
    buffer_receipt_times: list = field(default_factory=list)
    buffer_gap_times: list = field(default_factory=list)
    arduino_sample_times: list = field(default_factory=list)
    block_sample_counts: list = field(default_factory=list)
    block_sweeps_counts: list = field(default_factory=list)
    block_samples_per_sweep: list = field(default_factory=list)
    mcu_block_start_us: list = field(default_factory=list)
    mcu_block_end_us: list = field(default_factory=list)
    mcu_block_gap_us: list = field(default_factory=list)

    def reset(self, empty_timing_data):
        """Clear scalar fields and keep dict/list identities stable."""
        self.timing_data.clear()
        self.timing_data.update(empty_timing_data)
        self.capture_start_time = None
        self.capture_end_time = None
        self.last_buffer_time = None
        self.last_buffer_end_time = None
        self.mcu_last_block_end_us = None
        self.buffer_receipt_times.clear()
        self.buffer_gap_times.clear()
        self.arduino_sample_times.clear()
        self.block_sample_counts.clear()
        self.block_sweeps_counts.clear()
        self.block_samples_per_sweep.clear()
        self.mcu_block_start_us.clear()
        self.mcu_block_end_us.clear()
        self.mcu_block_gap_us.clear()

    def trim_recent(self, attr_name, max_items):
        """Keep only the newest items in a history list without replacing the list object."""
        history = getattr(self, attr_name)
        if len(history) > max_items:
            del history[:-max_items]


class DataProcessorMixin(ADCPlottingMixin, CaptureLifecycleMixin, FilterProcessorMixin, SerialParserMixin, BinaryProcessorMixin, ForceProcessorMixin):
    """Main mixin class for data processing, visualization, timing, and capture lifecycle."""

    PZR_ZERO_BASELINE_WINDOW_SEC = 0.5
    PZR_AUTO_BASELINE_DELAY_SEC = 1.5

    def _build_empty_timing_data(self):
        return {
            'per_channel_rate_hz': None,
            'total_rate_hz': None,
            'between_samples_us': None,
            'arduino_sample_time_us': None,
            'arduino_sample_rate_hz': None,
            'buffer_gap_time_ms': None,
            'mcu_block_start_us': None,
            'mcu_block_end_us': None,
            'mcu_block_gap_us': None,
        }

    def _create_timing_state(self):
        return TimingState(timing_data=self._build_empty_timing_data())

    def _ensure_timing_state(self):
        if getattr(self, '_timing_state', None) is None:
            self._timing_state = self._create_timing_state()
        return self._timing_state

    @property
    def timing_state(self):
        return self._ensure_timing_state()















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
                window_size = min(window_size, MAX_PLOT_SWEEPS, actual_sweeps)
                
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
            timing = self.timing_state
            timing_data = timing.timing_data
            # Use only the most recent timing value from Arduino
            arduino_avg_sample_time_us = 0
            if timing.arduino_sample_times:
                arduino_avg_sample_time_us = timing.arduino_sample_times[-1]
            
            # Calculate sampling rate from Arduino's measurement
            arduino_sample_rate_hz = 0
            arduino_per_channel_rate_hz = 0
            if arduino_avg_sample_time_us > 0:
                # Total sampling rate: 1,000,000 µs/s ÷ sample_time_us
                arduino_sample_rate_hz = 1000000.0 / arduino_avg_sample_time_us
                
                # Per-channel rate: divide total rate by number of unique channels
                display_channels = self.get_display_channel_specs()
                if display_channels:
                    num_unique_channels = len(display_channels)
                    arduino_per_channel_rate_hz = arduino_sample_rate_hz / num_unique_channels
                else:
                    arduino_per_channel_rate_hz = arduino_sample_rate_hz
            
            # Calculate gap between blocks (prefer MCU timing if available)
            buffer_gap_time_ms = 0
            if timing.mcu_block_gap_us:
                buffer_gap_time_ms = timing.mcu_block_gap_us[-1] / 1000.0
            elif timing.buffer_gap_times:
                # Average all host gap times to smooth out fluctuations
                buffer_gap_time_ms = sum(timing.buffer_gap_times) / len(timing.buffer_gap_times)
            
            # Store timing data
            timing_data['arduino_sample_time_us'] = arduino_avg_sample_time_us
            timing_data['arduino_sample_rate_hz'] = arduino_sample_rate_hz
            timing_data['per_channel_rate_hz'] = arduino_per_channel_rate_hz
            timing_data['total_rate_hz'] = arduino_sample_rate_hz
            timing_data['buffer_gap_time_ms'] = buffer_gap_time_ms
            # Store latest MCU timing values (if available)
            if timing.mcu_block_start_us:
                timing_data['mcu_block_start_us'] = timing.mcu_block_start_us[-1]
                timing_data['mcu_block_end_us'] = timing.mcu_block_end_us[-1]
                if timing.mcu_block_gap_us:
                    timing_data['mcu_block_gap_us'] = timing.mcu_block_gap_us[-1]
            
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
            elif timing.mcu_block_gap_us:
                self.block_gap_label.setText(f"{(timing.mcu_block_gap_us[-1] / 1000.0):.2f} ms")
            elif timing.buffer_gap_times:
                # Show even if current value is 0, as long as we have history
                avg_gap = sum(timing.buffer_gap_times) / len(timing.buffer_gap_times)
                self.block_gap_label.setText(f"{avg_gap:.2f} ms")
            else:
                self.block_gap_label.setText("- ms")
            
        except Exception as e:
            self.log_status(f"ERROR: Failed to update timing display - {e}")
    
    # ========================================================================
    # Capture Control
    # ========================================================================
    




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
            self.drain_serial_input(0.05)

            self._reset_capture_buffer_state(reset_samples_per_sweep=True)
            self._reset_force_capture_state()
            self._reset_timing_measurements(log_timestamp_clear=True, reset_labels=True)
            self._reset_signal_processing_state(reset_shear=True)
            self._reset_full_view_state(button_enabled=False, trigger_plot_update=False)
            
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
            self.cleanup_capture_cache(block=False)
    
    # ========================================================================
    # Helper Methods
    # ========================================================================

    def _delete_capture_cache_files(self, archive_path, block_timing_path, cache_dir_path):
        """Delete cache files and remove the cache directory when empty."""
        removed_files = 0
        for cache_path in [archive_path, block_timing_path]:
            if not cache_path:
                continue
            try:
                path_obj = Path(cache_path)
                if path_obj.exists() and path_obj.is_file():
                    path_obj.unlink()
                    removed_files += 1
            except Exception as e:
                self.log_status(f"WARNING: Failed to remove cache file {cache_path}: {e}")

        if cache_dir_path:
            try:
                cache_dir = Path(cache_dir_path)
                if cache_dir.exists() and cache_dir.is_dir() and not any(cache_dir.iterdir()):
                    cache_dir.rmdir()
            except Exception as e:
                self.log_status(f"WARNING: Failed to remove cache directory {cache_dir_path}: {e}")

        if removed_files > 0:
            self.log_status(f"Cache cleaned: removed {removed_files} file(s)")

    def _defer_capture_cache_cleanup(self, writer, archive_path, block_timing_path, cache_dir_path, attempts_left=100):
        """Poll for writer shutdown, then remove cache files without blocking the UI."""
        if writer is not None and writer.is_alive() and attempts_left > 0:
            QTimer.singleShot(
                100,
                lambda: self._defer_capture_cache_cleanup(
                    writer, archive_path, block_timing_path, cache_dir_path, attempts_left - 1
                ),
            )
            return

        if writer is not None and hasattr(writer, "get_status_snapshot"):
            snapshot = writer.get_status_snapshot()
            if snapshot.get("state") == "failed":
                error_text = snapshot.get("last_error") or "unknown archive writer failure"
                self.log_status(f"WARNING: Archive writer failed before cache cleanup: {error_text}")

        self._delete_capture_cache_files(archive_path, block_timing_path, cache_dir_path)

    def _close_capture_cache_handles(self, *, block=True):
        """Close open cache file handles, optionally waiting for the archive writer."""
        writer = getattr(self, '_archive_writer', None)
        try:
            if writer is not None:
                if block:
                    final_snapshot = writer.stop()
                    if final_snapshot.get("state") == "failed":
                        error_text = final_snapshot.get("last_error") or "unknown archive writer failure"
                        self.log_status(f"WARNING: Archive writer failed during close: {error_text}")
                else:
                    snapshot = writer.stop_nowait()
                    if snapshot.get("state") == "failed":
                        error_text = snapshot.get("last_error") or "unknown archive writer failure"
                        self.log_status(f"WARNING: Archive writer failed before background close: {error_text}")
        finally:
            self._archive_writer = None

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
        finally:
            self._block_timing_file = None

        return writer

    def cleanup_capture_cache(self, *, block=True):
        """Delete capture cache files and remove empty cache directory."""
        archive_path = getattr(self, '_archive_path', None)
        block_timing_path = getattr(self, '_block_timing_path', None)
        cache_dir_path = getattr(self, '_cache_dir_path', None)
        writer = self._close_capture_cache_handles(block=block)

        self._archive_path = None
        self._block_timing_path = None
        self._cache_dir_path = None
        self._archive_write_count = 0
        self._block_timing_write_count = 0

        if not block and writer is not None and writer.is_alive():
            self._defer_capture_cache_cleanup(writer, archive_path, block_timing_path, cache_dir_path)
            return

        self._delete_capture_cache_files(archive_path, block_timing_path, cache_dir_path)
    
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
