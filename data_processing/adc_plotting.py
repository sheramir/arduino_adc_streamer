"""
ADC Plotting Mixin
==================
Owns ADC buffer snapshotting, baseline capture, and ADC curve rendering.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt

from config_constants import IADC_RESOLUTION_BITS, MAX_PLOT_SWEEPS, MAX_TOTAL_POINTS_TO_DISPLAY, PLOT_COLORS


class ADCPlottingMixin:
    """ADC plot snapshotting and curve rendering helpers."""

    PZR_ZERO_BASELINE_WINDOW_SEC = 0.5
    PZR_AUTO_BASELINE_DELAY_SEC = 1.5

    def _get_ordered_active_buffer_snapshot(self):
        active_data_buffer = self.get_active_data_buffer()
        if active_data_buffer is None or self.samples_per_sweep <= 0:
            return None

        with self.buffer_lock:
            current_sweep_count = self.sweep_count
            current_write_index = self.buffer_write_index

        actual_sweeps = min(current_sweep_count, self.MAX_SWEEPS_BUFFER)
        if actual_sweeps <= 0:
            return None

        if actual_sweeps < self.MAX_SWEEPS_BUFFER:
            data_array = active_data_buffer[:actual_sweeps, :].copy()
            timestamps_array = self.sweep_timestamps_buffer[:actual_sweeps].copy()
        else:
            write_pos = current_write_index % self.MAX_SWEEPS_BUFFER
            data_array = np.concatenate([
                active_data_buffer[write_pos:, :],
                active_data_buffer[:write_pos, :],
            ])
            timestamps_array = np.concatenate([
                self.sweep_timestamps_buffer[write_pos:],
                self.sweep_timestamps_buffer[:write_pos],
            ])

        avg_sample_time_sec = getattr(self, '_cached_avg_sample_time_sec', 0.0)
        return data_array, timestamps_array, avg_sample_time_sec

    def capture_current_plot_baselines(self, window_sec=None, log_message=True, min_elapsed_sec=0.0):
        snapshot = self._get_ordered_active_buffer_snapshot()
        if snapshot is None:
            if log_message:
                self.log_status("No data available to zero signals")
            return False

        data_array, timestamps_array, avg_sample_time_sec = snapshot
        display_specs = self.get_display_channel_specs()
        if not display_specs or len(timestamps_array) == 0:
            if log_message:
                self.log_status("No visible channels available to zero signals")
            return False

        latest_time = float(timestamps_array[-1])
        required_elapsed = max(0.0, float(min_elapsed_sec))
        if latest_time < required_elapsed:
            return False

        baseline_window_sec = max(0.05, float(window_sec or self.PZR_ZERO_BASELINE_WINDOW_SEC))
        self.plot_baselines = {}

        for spec in display_specs:
            sample_indices = spec.get('sample_indices', [])
            if not sample_indices:
                continue

            sample_index_array = np.asarray(sample_indices, dtype=np.int32)
            channel_data = data_array[:, sample_index_array].reshape(-1)
            time_offsets = sample_index_array.astype(np.float64) * avg_sample_time_sec
            channel_times = (timestamps_array.reshape(-1, 1) + time_offsets.reshape(1, -1)).reshape(-1)

            if channel_data.size == 0:
                self.plot_baselines[spec['key']] = 0.0
                continue

            recent_mask = channel_times >= (latest_time - baseline_window_sec)
            baseline_samples = channel_data[recent_mask] if np.any(recent_mask) else channel_data
            self.plot_baselines[spec['key']] = float(np.mean(baseline_samples)) if baseline_samples.size else 0.0

        if getattr(self, 'subtract_baseline_check', None) is not None and not self.subtract_baseline_check.isChecked():
            self.subtract_baseline_check.setChecked(True)

        self.reset_555_heatmap_state()

        if log_message:
            self.log_status(f"Zeroed signals using last {baseline_window_sec:.2f}s baseline window")
        return True

    def zero_plot_baselines(self):
        """Zero out the plot baselines using current data."""
        if self.capture_current_plot_baselines():
            self.trigger_plot_update()

    def _hide_all_adc_curves(self):
        """Hide every ADC curve currently attached to the plot."""
        for curve in self._adc_curves.values():
            curve.setVisible(False)

    def _get_selected_plot_channels(self):
        """Return the set of currently selected channel keys."""
        return {
            channel_key
            for channel_key, checkbox in self.channel_checkboxes.items()
            if checkbox.isChecked()
        }

    def _extract_recent_buffer_window(self, active_data_buffer, actual_sweeps, current_write_index, window_sweeps):
        """Copy the requested trailing window from the circular sweep buffers."""
        window_sweeps = min(window_sweeps, actual_sweeps)
        if window_sweeps <= 0:
            return None

        if actual_sweeps < self.MAX_SWEEPS_BUFFER:
            start_idx = max(0, actual_sweeps - window_sweeps)
            return (
                active_data_buffer[start_idx:actual_sweeps, :].copy(),
                self.sweep_timestamps_buffer[start_idx:actual_sweeps].copy(),
            )

        write_pos = current_write_index % self.MAX_SWEEPS_BUFFER
        if window_sweeps >= self.MAX_SWEEPS_BUFFER:
            return (
                np.concatenate([
                    active_data_buffer[write_pos:, :],
                    active_data_buffer[:write_pos, :],
                ]),
                np.concatenate([
                    self.sweep_timestamps_buffer[write_pos:],
                    self.sweep_timestamps_buffer[:write_pos],
                ]),
            )

        start_pos = (write_pos - window_sweeps) % self.MAX_SWEEPS_BUFFER
        if start_pos < write_pos:
            return (
                active_data_buffer[start_pos:write_pos, :].copy(),
                self.sweep_timestamps_buffer[start_pos:write_pos].copy(),
            )

        return (
            np.concatenate([
                active_data_buffer[start_pos:, :],
                active_data_buffer[:write_pos, :],
            ]),
            np.concatenate([
                self.sweep_timestamps_buffer[start_pos:],
                self.sweep_timestamps_buffer[:write_pos],
            ]),
        )

    def _get_plot_data_snapshot(self, active_data_buffer):
        """Return the data/timestamp arrays that should be shown in the ADC plot."""
        if self.is_full_view:
            if hasattr(self, 'get_full_view_plot_snapshot'):
                snapshot = self.get_full_view_plot_snapshot()
                if snapshot is not None:
                    return snapshot

            raw_ok = self.raw_data is not None and hasattr(self.raw_data, '__len__') and len(self.raw_data) > 0
            ts_ok = self.sweep_timestamps is not None and hasattr(self.sweep_timestamps, '__len__') and len(self.sweep_timestamps) > 0
            if not raw_ok or not ts_ok:
                return None

            try:
                return (
                    np.asarray(self.raw_data, dtype=np.float32),
                    np.asarray(self.sweep_timestamps, dtype=np.float64),
                )
            except Exception as e:
                self.log_status(f"Error converting archive data: {e}")
                return None

        if active_data_buffer is None or self.sweep_timestamps_buffer is None:
            return None

        live_snapshot = self._get_live_plot_window_snapshot(active_data_buffer)
        if live_snapshot is None:
            return None

        data_array, timestamps_array, _snapshot_key = live_snapshot
        return data_array, timestamps_array

    def _get_live_plot_window_snapshot(self, active_data_buffer):
        """Return the trailing live window plus a stable key for worker-cached filtering."""
        if active_data_buffer is None or self.sweep_timestamps_buffer is None:
            return None

        with self.buffer_lock:
            current_sweep_count = self.sweep_count
            current_write_index = self.buffer_write_index

        actual_sweeps = min(current_sweep_count, self.MAX_SWEEPS_BUFFER)
        if actual_sweeps == 0:
            return None

        window_sweeps = min(self.window_size_spin.value(), MAX_PLOT_SWEEPS, actual_sweeps)
        snapshot = self._extract_recent_buffer_window(
            active_data_buffer,
            actual_sweeps,
            current_write_index,
            window_sweeps,
        )
        if snapshot is None:
            return None

        data_array, timestamps_array = snapshot
        generation = int(getattr(self, '_live_filter_generation', 0))
        snapshot_key = (generation, int(current_write_index), int(window_sweeps))
        return data_array, timestamps_array, snapshot_key

    def _get_live_plot_filter_snapshot(self, active_data_buffer):
        """Return a live filter input window with extra history to warm up causal filters."""
        if active_data_buffer is None or self.sweep_timestamps_buffer is None:
            return None

        with self.buffer_lock:
            current_sweep_count = self.sweep_count
            current_write_index = self.buffer_write_index

        actual_sweeps = min(current_sweep_count, self.MAX_SWEEPS_BUFFER)
        if actual_sweeps == 0:
            return None

        display_sweeps = min(self.window_size_spin.value(), MAX_PLOT_SWEEPS, actual_sweeps)
        if display_sweeps <= 0:
            return None

        available_history_sweeps = max(0, actual_sweeps - display_sweeps)
        history_sweeps = min(available_history_sweeps, max(display_sweeps, 256))
        filter_sweeps = display_sweeps + history_sweeps

        snapshot = self._extract_recent_buffer_window(
            active_data_buffer,
            actual_sweeps,
            current_write_index,
            filter_sweeps,
        )
        if snapshot is None:
            return None

        data_array, timestamps_array = snapshot
        generation = int(getattr(self, '_live_filter_generation', 0))
        snapshot_key = (generation, int(current_write_index), int(display_sweeps), int(history_sweeps))
        return data_array, timestamps_array, int(display_sweeps), snapshot_key

    def _prepare_channel_plot_series(self, spec, data_array, timestamps_array, avg_sample_time_sec, max_samples_per_series):
        """Build flattened channel samples/timestamps for plotting without changing behavior."""
        sample_indices = spec['sample_indices']
        if not sample_indices:
            return None

        sample_index_array = np.asarray(sample_indices, dtype=np.int32)
        channel_data = data_array[:, sample_index_array].reshape(-1)

        time_offsets = sample_index_array.astype(np.float64) * avg_sample_time_sec
        channel_times = (timestamps_array.reshape(-1, 1) + time_offsets.reshape(1, -1)).reshape(-1)

        latest_value = float(channel_data[-1]) if len(channel_data) > 0 else None

        if getattr(self, 'device_mode', 'adc') != '555' and self.yaxis_units_combo.currentText() == "Voltage":
            vref = self.get_vref_voltage()
            max_adc_value = (2 ** IADC_RESOLUTION_BITS) - 1
            channel_data = (channel_data / max_adc_value) * vref

        if getattr(self, 'subtract_baseline_check', None) and self.subtract_baseline_check.isChecked():
            if spec['key'] not in self.plot_baselines:
                self.capture_current_plot_baselines(
                    log_message=False,
                    min_elapsed_sec=self.PZR_AUTO_BASELINE_DELAY_SEC,
                )

            if spec['key'] in self.plot_baselines:
                channel_data = channel_data - self.plot_baselines[spec['key']]

        if len(channel_data) > max_samples_per_series:
            downsample_factor = max(1, len(channel_data) // max_samples_per_series)
            channel_data = channel_data[::downsample_factor]
            channel_times = channel_times[::downsample_factor]

        return channel_data, channel_times, latest_value

    def _get_or_create_adc_curve(self, curve_key, name, pen):
        """Fetch an existing ADC curve or create it on first use."""
        curve = self._adc_curves.get(curve_key)
        if curve is None:
            curve = self.plot_widget.plot([], pen=pen, name=name)
            self._adc_curves[curve_key] = curve
        return curve

    def _set_adc_curve_data(self, curve_key, name, pen, x_data, y_data):
        """Apply visibility, style, and samples to a single ADC curve."""
        curve = self._get_or_create_adc_curve(curve_key, name, pen)
        curve.setVisible(True)
        curve.setPen(pen)
        curve.setData(x=x_data, y=y_data)

    def _update_plot_axis_labels(self):
        """Update plot axes labels for the active visualization mode."""
        if getattr(self, 'device_mode', 'adc') == '555':
            self.plot_widget.setLabel('left', 'Resistance', units='Î©')
        elif self.yaxis_units_combo.currentText() == "Voltage":
            self.plot_widget.setLabel('left', 'Voltage', units='V')
        else:
            self.plot_widget.setLabel('left', 'ADC Value', units='counts')

        self.plot_widget.setLabel('bottom', 'Time', units='s')


    def apply_y_axis_range(self):
        """Apply Y-axis range setting to the plot."""
        if getattr(self, 'device_mode', 'adc') == '555':
            self.plot_widget.enableAutoRange(axis='y')
            return

        range_text = self.yaxis_range_combo.currentText()
        units_text = self.yaxis_units_combo.currentText()

        if range_text == "Adaptive":
            self.plot_widget.enableAutoRange(axis='y')
        elif range_text == "Full-Scale":
            if units_text == "Voltage":
                vref = self.get_vref_voltage()
                self.plot_widget.setYRange(0, vref, padding=0.02)
            else:
                max_adc_value = (2 ** IADC_RESOLUTION_BITS) - 1
                self.plot_widget.setYRange(0, max_adc_value, padding=0.02)
        else:
            self.plot_widget.enableAutoRange(axis='y')

    def _plot_repeat_series(self, spec, color, channel_data, channel_times, repeat_count, desired_curve_keys):
        """Render each repeat as its own curve without changing existing styling."""
        try:
            num_samples = len(channel_data) // repeat_count
            if num_samples <= 0:
                return False

            channel_data_2d = channel_data[:num_samples * repeat_count].reshape(-1, repeat_count)
            channel_times_2d = channel_times[:num_samples * repeat_count].reshape(-1, repeat_count)

            for repeat_idx in range(repeat_count):
                repeat_data = channel_data_2d[:, repeat_idx]
                repeat_times = channel_times_2d[:, repeat_idx]

                if repeat_idx == 0:
                    pen = pg.mkPen(color=color, width=2)
                else:
                    lighter_color = tuple(int(c * 0.7) for c in color)
                    pen = pg.mkPen(color=lighter_color, width=1.5, style=Qt.PenStyle.DashLine)

                name = f"{spec['label']}.{repeat_idx}"
                curve_key = ("repeat", spec['key'], repeat_idx)
                desired_curve_keys.add(curve_key)
                self._set_adc_curve_data(curve_key, name, pen, repeat_times, repeat_data)

            return True
        except Exception as e:
            self.log_status(f"ERROR: Failed to reshape repeat data - {e}")
            return False

    def _plot_single_or_average_series(self, spec, color, channel_data, channel_times, repeat_count, desired_curve_keys):
        """Render either the averaged repeat series or the default single curve."""
        if self.show_average_radio.isChecked() and repeat_count > 1:
            try:
                num_samples = len(channel_data) // repeat_count
                if num_samples <= 0:
                    return False

                channel_data_2d = channel_data[:num_samples * repeat_count].reshape(-1, repeat_count)
                channel_times_2d = channel_times[:num_samples * repeat_count].reshape(-1, repeat_count)
                channel_data = np.mean(channel_data_2d, axis=1)
                channel_times = channel_times_2d[:, 0]
                name = f"{spec['label']} (avg)"
                pen = pg.mkPen(color=color, width=3, style=Qt.PenStyle.DashLine)
                curve_key = ("avg", spec['key'], 0)
            except Exception as e:
                self.log_status(f"ERROR: Failed to average repeat data - {e}")
                return False
        else:
            name = spec['label']
            pen = pg.mkPen(color=color, width=2)
            curve_key = ("single", spec['key'], 0)

        desired_curve_keys.add(curve_key)
        self._set_adc_curve_data(curve_key, name, pen, channel_times, channel_data)
        return True

    def update_plot(self):
        """Update the plot with current data - optimized for fast updates and max 10K samples."""
        if self.is_updating_plot:
            return

        self.is_updating_plot = True

        try:
            if not self.config['channels']:
                self._hide_all_adc_curves()
                return

            display_specs = self.get_display_channel_specs()

            selected_channels = self._get_selected_plot_channels()
            if not selected_channels:
                self._hide_all_adc_curves()
                return

            repeat_count = self.config['repeat']
            if (
                hasattr(self, 'should_filter_live_timeseries_locally')
                and self.should_filter_live_timeseries_locally()
            ):
                live_snapshot = self._get_live_plot_window_snapshot(self.raw_data_buffer)
                if live_snapshot is None:
                    self._hide_all_adc_curves()
                    return

                data_array, timestamps_array, snapshot_key = live_snapshot
                filter_snapshot = self._get_live_plot_filter_snapshot(self.raw_data_buffer)
                filter_data_array = data_array
                filter_timestamps_array = timestamps_array
                display_sweeps = len(data_array)
                if filter_snapshot is not None:
                    filter_data_array, filter_timestamps_array, display_sweeps, snapshot_key = filter_snapshot
                if hasattr(self, 'maybe_get_live_timeseries_filtered_snapshot'):
                    filtered_snapshot = self.maybe_get_live_timeseries_filtered_snapshot(
                        data_array,
                        timestamps_array,
                        snapshot_key,
                        filter_data_array=filter_data_array,
                        filter_timestamps_sec=filter_timestamps_array,
                        display_sweeps=display_sweeps,
                    )
                    if filtered_snapshot is None:
                        return
                    data_array, timestamps_array = filtered_snapshot
            else:
                active_data_buffer = self.get_active_data_buffer()
                plot_snapshot = self._get_plot_data_snapshot(active_data_buffer)
                if plot_snapshot is None:
                    self._hide_all_adc_curves()
                    return

                data_array, timestamps_array = plot_snapshot

            if len(data_array) == 0 or len(timestamps_array) == 0:
                self._hide_all_adc_curves()
                return

            desired_curve_keys = set()
            latest_channel_values = {}
            visible_series_count = max(1, len(selected_channels))
            max_samples_per_series = max(500, MAX_TOTAL_POINTS_TO_DISPLAY // visible_series_count)
            avg_sample_time_sec = getattr(self, '_cached_avg_sample_time_sec', 0.0)

            for spec in display_specs:
                if spec['key'] not in selected_channels:
                    continue

                color = PLOT_COLORS[spec['color_slot'] % len(PLOT_COLORS)]
                prepared_series = self._prepare_channel_plot_series(
                    spec,
                    data_array,
                    timestamps_array,
                    avg_sample_time_sec,
                    max_samples_per_series,
                )
                if prepared_series is None:
                    continue

                channel_data, channel_times, latest_value = prepared_series

                if latest_value is not None:
                    latest_channel_values[spec['label']] = latest_value

                if self.show_all_repeats_radio.isChecked() and repeat_count > 1:
                    if not self._plot_repeat_series(
                        spec,
                        color,
                        channel_data,
                        channel_times,
                        repeat_count,
                        desired_curve_keys,
                    ):
                        continue
                else:
                    if not self._plot_single_or_average_series(
                        spec,
                        color,
                        channel_data,
                        channel_times,
                        repeat_count,
                        desired_curve_keys,
                    ):
                        continue

            for key, curve in self._adc_curves.items():
                if key not in desired_curve_keys:
                    curve.setVisible(False)

            self._update_plot_axis_labels()
            self.apply_y_axis_range()
            self.update_555_timing_readouts(latest_channel_values)

        except Exception as e:
            self.log_status(f"ERROR updating plot: {e}")
        finally:
            self.is_updating_plot = False
