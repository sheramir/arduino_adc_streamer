"""
Force Overlay Mixin
===================
Owns force-vs-time overlay rendering on the shared ADC plot.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

import numpy as np
import pyqtgraph as pg

from constants.force import (
    FORCE_PLOT_ZERO_THRESHOLD_MN,
    X_FORCE_SENSOR_TO_NEWTON,
    Z_FORCE_SENSOR_TO_NEWTON,
)
from constants.plotting import MAX_PLOT_SWEEPS
from constants.ui import ROSETTE_TAB_NAME
from data_processing.force_state import get_force_runtime_state


def apply_force_plot_zero_threshold(force_values_newtons):
    """Zero small calibrated forces for plotting without changing stored samples."""
    threshold_newtons = float(FORCE_PLOT_ZERO_THRESHOLD_MN) / 1000.0
    if threshold_newtons <= 0:
        return force_values_newtons
    return np.where(np.abs(force_values_newtons) <= threshold_newtons, 0.0, force_values_newtons)


class ForcePlotTarget(Enum):
    MAIN = auto()
    ROSETTE = auto()


@dataclass(frozen=True)
class ForceOverlayTarget:
    kind: ForcePlotTarget
    viewbox: object
    x_curve_attr: str
    z_curve_attr: str
    x_checkbox: object          # QCheckBox or None
    z_checkbox: object          # QCheckBox or None
    source_widget: object       # PlotWidget to read current view range from
    update_viewbox_fn: object   # callable or None


class ForceOverlayMixin:
    """Force overlay time-window selection and curve rendering."""

    def _resolve_force_plot_target(self) -> ForceOverlayTarget:
        """Return a ForceOverlayTarget for the currently visible force overlay."""
        is_rosette_tab = False
        if hasattr(self, "get_current_visualization_tab_name"):
            try:
                is_rosette_tab = self.get_current_visualization_tab_name() == ROSETTE_TAB_NAME
            except Exception:
                is_rosette_tab = False

        if is_rosette_tab and hasattr(self, "rosette_force_viewbox"):
            return ForceOverlayTarget(
                kind=ForcePlotTarget.ROSETTE,
                viewbox=self.rosette_force_viewbox,
                x_curve_attr="_rosette_force_x_curve",
                z_curve_attr="_rosette_force_z_curve",
                x_checkbox=getattr(self, "rosette_force_x_checkbox", None),
                z_checkbox=getattr(self, "rosette_force_z_checkbox", None),
                source_widget=getattr(self, "rosette_plot_widget", None),
                update_viewbox_fn=getattr(self, "update_rosette_force_viewbox", None),
            )

        return ForceOverlayTarget(
            kind=ForcePlotTarget.MAIN,
            viewbox=getattr(self, "force_viewbox", None),
            x_curve_attr="_force_x_curve",
            z_curve_attr="_force_z_curve",
            x_checkbox=getattr(self, "force_x_checkbox", None),
            z_checkbox=getattr(self, "force_z_checkbox", None),
            source_widget=getattr(self, "plot_widget", None),
            update_viewbox_fn=getattr(self, "update_force_viewbox", None),
        )

    def _resolve_force_x_range(self, target: ForceOverlayTarget):
        """Return (min_time, max_time) that the force viewbox should display.

        For MAIN targets: mirrors the user-visible ADC plot X range when ADC
        channels are selected; falls back to the buffer-derived time window
        when no channels are selected (so force curves stay visible even with
        an empty ADC plot).
        For ROSETTE targets: always uses the buffer-derived time window because
        the rosette plot already manages its own X range via sigXRangeChanged.
        """
        if target.kind == ForcePlotTarget.MAIN:
            selected = self._get_selected_plot_channels() if hasattr(self, '_get_selected_plot_channels') else set()
            if selected and target.source_widget is not None:
                try:
                    x_min, x_max = target.source_widget.getViewBox().viewRange()[0]
                    return float(x_min), float(x_max)
                except Exception:
                    pass

        return self._get_force_plot_time_window()

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
        if hasattr(self, "should_update_live_timeseries_display"):
            try:
                if not self.should_update_live_timeseries_display():
                    return
            except Exception:
                return

        state = get_force_runtime_state(self)
        target = self._resolve_force_plot_target()
        viewbox = target.viewbox
        if viewbox is None:
            return

        x_checkbox = target.x_checkbox
        z_checkbox = target.z_checkbox
        show_x_force = x_checkbox and x_checkbox.isChecked()
        show_z_force = z_checkbox and z_checkbox.isChecked()
        x_curve_attr = target.x_curve_attr
        z_curve_attr = target.z_curve_attr
        x_curve = getattr(self, x_curve_attr, None)
        z_curve = getattr(self, z_curve_attr, None)

        if not show_x_force and x_curve is not None:
            x_curve.setVisible(False)
        if not show_z_force and z_curve is not None:
            z_curve.setVisible(False)

        if not state.data or (not show_x_force and not show_z_force):
            return

        if self.sweep_count == 0:
            return

        time_window = self._resolve_force_x_range(target)
        if time_window is None:
            return
        min_time, max_time = time_window

        if callable(target.update_viewbox_fn):
            target.update_viewbox_fn()

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
            x_forces = apply_force_plot_zero_threshold(x_forces)
            z_forces = apply_force_plot_zero_threshold(z_forces)

            if show_x_force:
                x_curve = getattr(self, x_curve_attr, None)
                if x_curve is None:
                    pen = pg.mkPen(color='r', width=2)
                    x_curve = pg.PlotDataItem([], pen=pen, name='X Force [N]')
                    viewbox.addItem(x_curve)
                    setattr(self, x_curve_attr, x_curve)

                x_curve.setVisible(True)
                x_curve.setData(x=times, y=x_forces)

            if show_z_force:
                z_curve = getattr(self, z_curve_attr, None)
                if z_curve is None:
                    pen = pg.mkPen(color='b', width=2)
                    z_curve = pg.PlotDataItem([], pen=pen, name='Z Force [N]')
                    viewbox.addItem(z_curve)
                    setattr(self, z_curve_attr, z_curve)

                z_curve.setVisible(True)
                z_curve.setData(x=times, y=z_forces)

            viewbox.enableAutoRange(axis='y')
            viewbox.setXRange(min_time, max_time, padding=0)

        except Exception as e:
            self.log_status(f"ERROR: Failed to update force plot - {e}")
