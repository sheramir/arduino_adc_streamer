"""
Force Overlay Mixin
===================
Owns force-vs-time overlay rendering on the shared ADC plot.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg

from config_constants import MAX_PLOT_SWEEPS, X_FORCE_SENSOR_TO_NEWTON, Z_FORCE_SENSOR_TO_NEWTON
from data_processing.force_state import get_force_runtime_state


class ForceOverlayMixin:
    """Force overlay time-window selection and curve rendering."""

    def _get_force_plot_time_window(self):
        """Return the active ADC plot time span that the force overlay should match."""
        if self.is_full_view:
            timestamps = getattr(self, 'sweep_timestamps', None)
            if timestamps is None or len(timestamps) == 0:
                return None

            min_time = float(timestamps[0])
            max_time = float(timestamps[-1])
            return min_time, max_time

        if self.sweep_timestamps_buffer is None:
            return None

        with self.buffer_lock:
            current_sweep_count = self.sweep_count
            current_write_index = self.buffer_write_index
            actual_sweeps = min(current_sweep_count, self.MAX_SWEEPS_BUFFER)

            if actual_sweeps == 0:
                return None

            if self.is_capturing:
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
                if actual_sweeps < self.MAX_SWEEPS_BUFFER:
                    min_time = self.sweep_timestamps_buffer[0]
                    max_time = self.sweep_timestamps_buffer[actual_sweeps - 1]
                else:
                    write_pos = current_write_index % self.MAX_SWEEPS_BUFFER
                    oldest_idx = write_pos
                    newest_idx = (write_pos - 1) % self.MAX_SWEEPS_BUFFER
                    min_time = self.sweep_timestamps_buffer[oldest_idx]
                    max_time = self.sweep_timestamps_buffer[newest_idx]

        return float(min_time), float(max_time)

    def update_force_plot(self):
        """Update the force measurement plot with time-based alignment to ADC data."""
        state = get_force_runtime_state(self)
        show_x_force = self.force_x_checkbox and self.force_x_checkbox.isChecked()
        show_z_force = self.force_z_checkbox and self.force_z_checkbox.isChecked()

        if not show_x_force and self._force_x_curve is not None:
            self._force_x_curve.setVisible(False)
        if not show_z_force and self._force_z_curve is not None:
            self._force_z_curve.setVisible(False)

        if not state.data or (not show_x_force and not show_z_force):
            return

        if self.sweep_count == 0:
            return

        time_window = self._get_force_plot_time_window()
        if time_window is None:
            return
        min_time, max_time = time_window

        if hasattr(self, 'update_force_viewbox'):
            self.update_force_viewbox()

        try:
            force_array = np.array(state.data, dtype=np.float64)
            force_times = force_array[:, 0]

            start_idx = np.searchsorted(force_times, min_time, side='left')
            end_idx = np.searchsorted(force_times, max_time, side='right')

            force_filtered = force_array[start_idx:end_idx]
            if len(force_filtered) == 0:
                return

            max_force_points = 2000
            if len(force_filtered) > max_force_points:
                downsample_factor = len(force_filtered) // max_force_points
                force_filtered = force_filtered[::downsample_factor]

            times = force_filtered[:, 0]
            x_forces = force_filtered[:, 1] / X_FORCE_SENSOR_TO_NEWTON
            z_forces = force_filtered[:, 2] / Z_FORCE_SENSOR_TO_NEWTON

            if show_x_force:
                if self._force_x_curve is None:
                    pen = pg.mkPen(color='r', width=2)
                    self._force_x_curve = pg.PlotDataItem([], pen=pen, name='X Force [N]')
                    self.force_viewbox.addItem(self._force_x_curve)

                self._force_x_curve.setVisible(True)
                self._force_x_curve.setData(x=times, y=x_forces)

            if show_z_force:
                if self._force_z_curve is None:
                    pen = pg.mkPen(color='b', width=2)
                    self._force_z_curve = pg.PlotDataItem([], pen=pen, name='Z Force [N]')
                    self.force_viewbox.addItem(self._force_z_curve)

                self._force_z_curve.setVisible(True)
                self._force_z_curve.setData(x=times, y=z_forces)

            self.force_viewbox.enableAutoRange(axis='y')

        except Exception as e:
            self.log_status(f"ERROR: Failed to update force plot - {e}")
