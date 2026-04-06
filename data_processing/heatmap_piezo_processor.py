"""
Piezo Heatmap Processor Mixin
=============================
Piezoelectric-specific heatmap signal processing and CoP generation.
"""

import math
import numpy as np

from config_constants import (
    SENSOR_POS_X, SENSOR_POS_Y,
    INTENSITY_SCALE, COP_EPS, BLOB_SIGMA_X, BLOB_SIGMA_Y, SMOOTH_ALPHA,
    HEATMAP_REQUIRED_CHANNELS, CONFIDENCE_INTENSITY_REF, SIGMA_SPREAD_FACTOR,
    AXIS_SIGMA_FACTOR,
)


class PiezoHeatmapProcessorMixin:
    """Piezoelectric (5-sensor) heatmap processing pipeline."""

    @staticmethod
    def _threshold_label_order():
        return ["T", "B", "R", "L", "C"]

    def _build_piezo_channel_value_array(self, values, default, size):
        result = [float(default)] * size
        if not isinstance(values, (list, tuple, np.ndarray)):
            return result

        for idx in range(min(size, len(self._threshold_label_order()), len(values))):
            result[idx] = float(values[idx])
        return result

    def calculate_cop_and_intensity(self, sensor_values, settings, package_index=0):
        """Calculate center of pressure and intensity from sensor values."""
        weights = np.maximum(np.array(sensor_values, dtype=np.float32), 0.0)
        intensity = np.sum(weights)

        total_weight = np.sum(weights) + COP_EPS
        cop_x = np.sum(np.array(SENSOR_POS_X, dtype=np.float32) * weights) / total_weight
        cop_y = np.sum(np.array(SENSOR_POS_Y, dtype=np.float32) * weights) / total_weight

        smooth_alpha = settings.get('smooth_alpha', SMOOTH_ALPHA)
        self.smoothed_cop_x[package_index] = smooth_alpha * cop_x + (1 - smooth_alpha) * self.smoothed_cop_x[package_index]
        self.smoothed_cop_y[package_index] = smooth_alpha * cop_y + (1 - smooth_alpha) * self.smoothed_cop_y[package_index]
        self.smoothed_intensity[package_index] = smooth_alpha * intensity + (1 - smooth_alpha) * self.smoothed_intensity[package_index]

        return (
            self.smoothed_cop_x[package_index],
            self.smoothed_cop_y[package_index],
            self.smoothed_intensity[package_index],
        )

    def generate_heatmap(self, cop_x, cop_y, intensity, settings, package_index=0):
        """Generate 2D Gaussian heatmap centered at CoP."""
        dx = self.heatmap_x_grid - cop_x
        dy = self.heatmap_y_grid - cop_y

        sigma_x = settings.get('blob_sigma_x', BLOB_SIGMA_X)
        sigma_y = settings.get('blob_sigma_y', BLOB_SIGMA_Y)
        sigma_scale = settings.get('sigma_scale', 1.0)
        sigma_scale_x = settings.get('sigma_scale_x', 1.0)
        sigma_scale_y = settings.get('sigma_scale_y', 1.0)
        sigma_x = max(1e-6, sigma_x * sigma_scale * sigma_scale_x)
        sigma_y = max(1e-6, sigma_y * sigma_scale * sigma_scale_y)
        gaussian = np.exp(-(dx**2 / (2 * sigma_x**2) + dy**2 / (2 * sigma_y**2)))

        amplitude = intensity * settings.get('intensity_scale', INTENSITY_SCALE)
        self.heatmap_buffers[package_index][:] = gaussian * amplitude
        np.clip(self.heatmap_buffers[package_index], 0, 1, out=self.heatmap_buffers[package_index])

        return self.heatmap_buffers[package_index]

    def process_sensor_data_for_heatmap(self, sensor_values, settings, package_index=0):
        """Complete piezo processing pipeline: sensor values -> heatmap."""
        cop_x, cop_y, intensity = self.calculate_cop_and_intensity(sensor_values, settings, package_index=package_index)

        weights = np.maximum(np.array(sensor_values, dtype=np.float32), 0.0)
        confidence, concentration = self.calculate_confidence(weights, intensity, settings)
        sigma_scale = 1.0 + (1.0 - concentration) * settings.get('sigma_spread_factor', SIGMA_SPREAD_FACTOR)

        axis_sigma_factor = settings.get('axis_sigma_factor', AXIS_SIGMA_FACTOR)
        axis_sigma_factor = max(0.0, axis_sigma_factor)
        x_sum = float(weights[2] + weights[3]) if weights.size >= 4 else 0.0
        y_sum = float(weights[0] + weights[1]) if weights.size >= 2 else 0.0
        axis_total = x_sum + y_sum
        if axis_total > 0:
            x_ratio = x_sum / axis_total
            y_ratio = y_sum / axis_total
            sigma_scale_x = 1.0 + axis_sigma_factor * ((x_ratio - 0.5) * 2.0)
            sigma_scale_y = 1.0 + axis_sigma_factor * ((y_ratio - 0.5) * 2.0)
        else:
            sigma_scale_x = 1.0
            sigma_scale_y = 1.0

        settings = dict(settings)
        settings['sigma_scale'] = sigma_scale
        settings['sigma_scale_x'] = sigma_scale_x
        settings['sigma_scale_y'] = sigma_scale_y

        heatmap = self.generate_heatmap(cop_x, cop_y, intensity, settings, package_index=package_index)
        return heatmap, cop_x, cop_y, intensity, confidence, sensor_values

    def calculate_confidence(self, weights, intensity, settings):
        if intensity <= 0:
            return 0.0, 0.0

        q_i = min(1.0, intensity / max(settings.get('confidence_intensity_ref', CONFIDENCE_INTENSITY_REF), 1e-6))
        q_c = float(np.max(weights)) / float(intensity)
        q_f = q_i * q_c
        return q_f, q_c

    def _extract_heatmap_window_data(self, window_ms):
        if self.raw_data_buffer is None or self.samples_per_sweep <= 0:
            return None

        if not hasattr(self, 'buffer_lock'):
            return None

        with self.buffer_lock:
            current_sweep_count = self.sweep_count
            current_write_index = self.buffer_write_index

        actual_sweeps = min(current_sweep_count, self.MAX_SWEEPS_BUFFER)
        if actual_sweeps == 0:
            return None

        avg_sample_time_us = 0.0
        if hasattr(self, 'arduino_sample_times') and self.arduino_sample_times:
            avg_sample_time_us = float(self.arduino_sample_times[-1])

        if avg_sample_time_us <= 0:
            return None

        sweep_time_sec = (self.samples_per_sweep * avg_sample_time_us) / 1e6
        if sweep_time_sec <= 0:
            return None

        window_sec = max(0.001, window_ms / 1000.0)
        window_sweeps = max(1, int(math.ceil(window_sec / sweep_time_sec)))
        window_sweeps = min(window_sweeps, actual_sweeps)

        with self.buffer_lock:
            write_pos = current_write_index % self.MAX_SWEEPS_BUFFER
            if actual_sweeps < self.MAX_SWEEPS_BUFFER:
                start_idx = max(0, actual_sweeps - window_sweeps)
                data_array = self.raw_data_buffer[start_idx:actual_sweeps, :].copy()
                timestamps = self.sweep_timestamps_buffer[start_idx:actual_sweeps].copy()
            else:
                start_pos = (write_pos - window_sweeps) % self.MAX_SWEEPS_BUFFER
                if start_pos < write_pos:
                    data_array = self.raw_data_buffer[start_pos:write_pos, :].copy()
                    timestamps = self.sweep_timestamps_buffer[start_pos:write_pos].copy()
                else:
                    data_array = np.concatenate([
                        self.raw_data_buffer[start_pos:, :],
                        self.raw_data_buffer[:write_pos, :]
                    ])
                    timestamps = np.concatenate([
                        self.sweep_timestamps_buffer[start_pos:],
                        self.sweep_timestamps_buffer[:write_pos]
                    ])

        return data_array, timestamps, avg_sample_time_us

    def compute_channel_intensities(self, settings):
        if not hasattr(self, 'heatmap_signal_processors'):
            return None

        extract_result = self._extract_heatmap_window_data(settings.get('rms_window_ms', 200))
        if extract_result is None:
            return None

        data_array, timestamps, avg_sample_time_us = extract_result
        channels = self.config.get('channels', [])
        repeat_count = self.config.get('repeat', 1)

        if not channels or repeat_count <= 0:
            return None

        use_array_sensor_groups = self.is_array_sensor_selection_mode()
        array_sensor_groups = self.get_array_selected_sensor_groups() if use_array_sensor_groups else []

        standard_package_channels = []
        if use_array_sensor_groups and array_sensor_groups:
            if any(len(group.get('channels', [])) != HEATMAP_REQUIRED_CHANNELS for group in array_sensor_groups):
                return None
            package_count = len(array_sensor_groups)
        else:
            unique_channels = []
            for ch in channels:
                if ch not in unique_channels:
                    unique_channels.append(ch)

            if (
                len(unique_channels) < HEATMAP_REQUIRED_CHANNELS
                or len(unique_channels) % HEATMAP_REQUIRED_CHANNELS != 0
            ):
                return None

            package_count = len(unique_channels) // HEATMAP_REQUIRED_CHANNELS
            for package_index in range(package_count):
                start = package_index * HEATMAP_REQUIRED_CHANNELS
                end = (package_index + 1) * HEATMAP_REQUIRED_CHANNELS
                standard_package_channels.append(unique_channels[start:end])
            array_sensor_groups = []

        sample_rate_hz = 1000000.0 / avg_sample_time_us
        per_channel_rate_hz = sample_rate_hz / max(len(channels), 1)
        window_end_time_sec = float(timestamps[-1]) if timestamps.size else None
        channel_to_sensor = settings.get('channel_sensor_map', [])
        channel_to_baseline = settings.get('channel_to_baseline', {})
        sensor_labels = ['T', 'B', 'R', 'L', 'C']
        package_sensor_values = []

        for package_index in range(package_count):
            if array_sensor_groups:
                group = array_sensor_groups[package_index]
                package_channels = list(group.get('channels', []))
                package_positions = list(group.get('positions', []))
            else:
                package_channels = list(standard_package_channels[package_index])
                package_positions = []

            channel_samples = []
            for local_idx, channel in enumerate(package_channels):
                if package_positions:
                    positions = [int(package_positions[local_idx])] if local_idx < len(package_positions) else []
                else:
                    positions = [i for i, c in enumerate(channels) if c == channel]
                channel_data_list = []
                for pos in positions:
                    start_idx = pos * repeat_count
                    end_idx = start_idx + repeat_count
                    if end_idx > data_array.shape[1]:
                        continue
                    pos_data = data_array[:, start_idx:end_idx]
                    
                    # Apply baseline subtraction if baseline is available for this channel
                    if channel in channel_to_baseline:
                        baseline_value = float(channel_to_baseline[channel])
                        pos_data = pos_data - baseline_value
                    
                    channel_data_list.append(pos_data.reshape(-1))

                if channel_data_list:
                    channel_samples.append(np.concatenate(channel_data_list))
                else:
                    channel_samples.append(np.array([], dtype=np.float64))

            processor = self.heatmap_signal_processors[package_index]
            processor.set_hpf_cutoff(settings.get('hpf_cutoff_hz', 0.0))
            rms_values, _ = processor.compute_rms(
                channel_samples,
                settings.get('dc_removal_mode', 'bias'),
                per_channel_rate_hz,
                window_end_time_sec,
            )

            sensor_values_map = {label: 0.0 for label in sensor_labels}
            for idx, sensor_label in enumerate(channel_to_sensor):
                if idx < len(rms_values):
                    sensor_values_map[sensor_label] = rms_values[idx]

            sensor_values = [sensor_values_map[label] for label in sensor_labels]
            noise_floor = settings.get('sensor_noise_floor', [0.0] * len(sensor_values))
            calibration = settings.get('sensor_calibration', [1.0] * len(sensor_values))
            
            # Determine sensor_id for this package
            if use_array_sensor_groups and package_index < len(array_sensor_groups):
                sensor_id = array_sensor_groups[package_index].get('sensor_id', '')
            else:
                sensor_id = f"Sensor{package_index + 1}"
            
            # Get per-sensor gains and thresholds from sensor_calibration_dict
            sensor_calibration_dict = settings.get('sensor_calibration_dict', {})
            per_sensor_gains = [1.0] * len(sensor_values)
            per_sensor_thresholds = [0.0] * len(sensor_values)
            
            if sensor_id in sensor_calibration_dict:
                calib_data = sensor_calibration_dict[sensor_id]
                per_sensor_gains = self._build_piezo_channel_value_array(calib_data.get('gains', []), 1.0, len(sensor_values))
                per_sensor_thresholds = self._build_piezo_channel_value_array(calib_data.get('thresholds', []), 0.0, len(sensor_values))
            
            calibrated = []
            for value, noise, gain, per_gain, per_thresh in zip(sensor_values, noise_floor, calibration, per_sensor_gains, per_sensor_thresholds):
                adjusted = max(0.0, value - noise)
                # Apply both general calibration gain and per-sensor gain
                calibrated_val = adjusted * gain * per_gain
                calibrated.append(calibrated_val)

            global_thresholds = self._build_piezo_channel_value_array(
                settings.get('global_channel_thresholds', []),
                settings.get('general_threshold', settings.get('magnitude_threshold', 0.0)),
                len(sensor_values),
            )
            total_thresholds = [global_thresh + per_thresh for global_thresh, per_thresh in zip(global_thresholds, per_sensor_thresholds)]

            thresholded = []
            for val, thresh in zip(calibrated, total_thresholds):
                thresholded.append(val if val >= thresh else 0.0)
            
            smoothed = processor.smooth_and_threshold(
                thresholded,
                settings.get('smooth_alpha', SMOOTH_ALPHA),
                0.0,  # No additional threshold since we already applied per-sensor thresholds
            )
            package_sensor_values.append(smoothed)

        return package_sensor_values
