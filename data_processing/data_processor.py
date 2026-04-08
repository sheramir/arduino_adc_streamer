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
from datetime import datetime

import numpy as np
import pyqtgraph as pg

from config_constants import (
    MAX_LOG_LINES, IADC_RESOLUTION_BITS, MAX_PLOT_SWEEPS,
    X_FORCE_SENSOR_TO_NEWTON, Z_FORCE_SENSOR_TO_NEWTON,
)

# Import sub-module mixins
from data_processing.capture_lifecycle import CaptureLifecycleMixin
from data_processing.capture_cache import CaptureCacheMixin
from data_processing.adc_plotting import ADCPlottingMixin
from data_processing.timing_display import TimingDisplayMixin
from serial_communication.serial_parser import SerialParserMixin
from data_processing.binary_processor import BinaryProcessorMixin
from data_processing.filter_processor import FilterProcessorMixin
from data_processing.force_processor import ForceProcessorMixin


class DataProcessorMixin(CaptureCacheMixin, TimingDisplayMixin, ADCPlottingMixin, CaptureLifecycleMixin, FilterProcessorMixin, SerialParserMixin, BinaryProcessorMixin, ForceProcessorMixin):
    """Main mixin class for data processing, visualization, timing, and capture lifecycle."""

    PZR_ZERO_BASELINE_WINDOW_SEC = 0.5
    PZR_AUTO_BASELINE_DELAY_SEC = 1.5

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
