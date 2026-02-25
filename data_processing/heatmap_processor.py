"""
Heatmap Processor Mixin
=======================
Handles center-of-pressure calculation and 2D heatmap generation from sensor data.
"""

import math
import numpy as np

from config_constants import (
    HEATMAP_WIDTH, HEATMAP_HEIGHT, SENSOR_POS_X, SENSOR_POS_Y,
    INTENSITY_SCALE, COP_EPS, BLOB_SIGMA_X, BLOB_SIGMA_Y, SMOOTH_ALPHA,
    HEATMAP_REQUIRED_CHANNELS, CONFIDENCE_INTENSITY_REF, SIGMA_SPREAD_FACTOR,
    AXIS_SIGMA_FACTOR, R_HEATMAP_CHANNEL_SENSOR_MAP, R_HEATMAP_DELTA_THRESHOLD,
    R_HEATMAP_DELTA_RELEASE_THRESHOLD, R_HEATMAP_INTENSITY_MIN, R_HEATMAP_INTENSITY_MAX,
    R_HEATMAP_AXIS_ADAPT_STRENGTH, R_HEATMAP_MAP_SMOOTH_ALPHA
)


class HeatmapProcessorMixin:
    """Mixin for processing sensor data into heatmap visualization."""
    
    def __init__(self):
        """Initialize heatmap processor state."""
        super().__init__()
        
        # Smoothed values
        self.smoothed_cop_x = 0.0
        self.smoothed_cop_y = 0.0
        self.smoothed_intensity = 0.0
        
        # Pre-allocate heatmap buffer
        self.heatmap_buffer = np.zeros((HEATMAP_HEIGHT, HEATMAP_WIDTH), dtype=np.float32)
        
        # Pre-compute coordinate grids for Gaussian blob
        y_coords = np.linspace(-1, 1, HEATMAP_HEIGHT).reshape(-1, 1)
        x_coords = np.linspace(-1, 1, HEATMAP_WIDTH).reshape(1, -1)
        self.heatmap_y_grid = np.tile(y_coords, (1, HEATMAP_WIDTH))
        self.heatmap_x_grid = np.tile(x_coords, (HEATMAP_HEIGHT, 1))
        self.reset_555_heatmap_state()

    def reset_555_heatmap_state(self):
        self.r555_prev_values = None
        self.r555_last_deltas = np.zeros(4, dtype=np.float64)
        self.r555_accumulators = np.zeros(4, dtype=np.float64)
        self.r555_last_sensor_values = np.zeros(4, dtype=np.float64)
        self.r555_last_weights = np.zeros(4, dtype=np.float64)
        self.r555_last_confidence = 0.0
        self.r555_last_concentration = 0.0
        self.r555_last_qi = 0.0
        self.r555_smoothed_x = 0.0
        self.r555_smoothed_y = 0.0
        self.r555_smoothed_i = 0.0
        self.r555_smoothed_heatmap = np.zeros((HEATMAP_HEIGHT, HEATMAP_WIDTH), dtype=np.float32)
        self.r555_last_processed_sweep_count = 0

    def _extract_new_sweeps_since(self, last_processed_sweep_count):
        if self.raw_data_buffer is None or self.samples_per_sweep <= 0:
            return None
        if not hasattr(self, 'buffer_lock'):
            return None

        with self.buffer_lock:
            current_sweep_count = self.sweep_count
            current_write_index = self.buffer_write_index

            if current_sweep_count <= last_processed_sweep_count:
                return np.empty((0, self.samples_per_sweep), dtype=np.float32), current_sweep_count

            available = min(current_sweep_count, self.MAX_SWEEPS_BUFFER)
            first_available_global = current_sweep_count - available
            start_global = max(last_processed_sweep_count, first_available_global)
            take_count = current_sweep_count - start_global

            if take_count <= 0:
                return np.empty((0, self.samples_per_sweep), dtype=np.float32), current_sweep_count

            write_pos = current_write_index % self.MAX_SWEEPS_BUFFER
            start_pos = (write_pos - take_count) % self.MAX_SWEEPS_BUFFER

            if start_pos < write_pos:
                data = self.raw_data_buffer[start_pos:write_pos, :].copy()
            else:
                data = np.concatenate([
                    self.raw_data_buffer[start_pos:, :],
                    self.raw_data_buffer[:write_pos, :]
                ])

        return data, current_sweep_count

    def _build_channel_matrix(self, sweeps_array, channels, repeat_count):
        if sweeps_array.size == 0:
            return np.empty((0, 0), dtype=np.float64), []

        unique_channels = []
        for ch in channels:
            if ch not in unique_channels:
                unique_channels.append(ch)

        if not unique_channels:
            return np.empty((0, 0), dtype=np.float64), []

        per_channel_values = []
        for channel in unique_channels:
            positions = [i for i, c in enumerate(channels) if c == channel]
            if not positions:
                per_channel_values.append(np.zeros(sweeps_array.shape[0], dtype=np.float64))
                continue

            position_values = []
            for pos in positions:
                start_idx = pos * repeat_count
                end_idx = start_idx + repeat_count
                if end_idx > sweeps_array.shape[1]:
                    continue
                seg = sweeps_array[:, start_idx:end_idx]
                if seg.size == 0:
                    continue
                position_values.append(np.mean(seg, axis=1))

            if not position_values:
                per_channel_values.append(np.zeros(sweeps_array.shape[0], dtype=np.float64))
            elif len(position_values) == 1:
                per_channel_values.append(np.array(position_values[0], dtype=np.float64))
            else:
                per_channel_values.append(np.mean(np.column_stack(position_values), axis=1))

        matrix = np.column_stack(per_channel_values)
        return matrix, unique_channels

    def process_555_displacement_heatmap(self, settings):
        extract_result = self._extract_new_sweeps_since(getattr(self, 'r555_last_processed_sweep_count', 0))
        if extract_result is None:
            return None

        sweeps_array, current_sweep_count = extract_result
        self.r555_last_processed_sweep_count = current_sweep_count

        channels = self.config.get('channels', [])
        repeat_count = self.config.get('repeat', 1)
        if not channels or repeat_count <= 0:
            return None

        channel_matrix, unique_channels = self._build_channel_matrix(sweeps_array, channels, repeat_count)
        if channel_matrix.size == 0:
            return None

        channel_sensor_map = settings.get('channel_sensor_map', R_HEATMAP_CHANNEL_SENSOR_MAP)
        sensor_order = settings.get('sensor_order', ['R', 'B', 'L', 'T'])

        if len(unique_channels) != len(channel_sensor_map):
            return None

        coord_x = settings.get('sensor_pos_x', [1.0, 0.0, -1.0, 0.0])
        coord_y = settings.get('sensor_pos_y', [0.0, -1.0, 0.0, 1.0])
        coord_map = {
            label: (float(x), float(y))
            for label, x, y in zip(sensor_order, coord_x, coord_y)
        }

        channel_to_sensor = {}
        for idx, channel in enumerate(unique_channels):
            if idx < len(channel_sensor_map):
                channel_to_sensor[channel] = channel_sensor_map[idx]

        sensor_index = {label: idx for idx, label in enumerate(sensor_order)}

        if self.r555_prev_values is None or self.r555_prev_values.shape[0] != len(sensor_order):
            self.r555_prev_values = np.zeros(len(sensor_order), dtype=np.float64)
            if channel_matrix.shape[0] > 0:
                first_values = np.zeros(len(sensor_order), dtype=np.float64)
                for col_idx, channel in enumerate(unique_channels):
                    label = channel_to_sensor.get(channel)
                    if label in sensor_index:
                        first_values[sensor_index[label]] = float(channel_matrix[0, col_idx])
                self.r555_prev_values = first_values

        th = float(settings.get('delta_threshold', R_HEATMAP_DELTA_THRESHOLD))
        th_release = float(settings.get('delta_release_threshold', th if th > 0 else R_HEATMAP_DELTA_RELEASE_THRESHOLD))

        for row_idx in range(channel_matrix.shape[0]):
            current_values = np.array(self.r555_prev_values, copy=True)
            for col_idx, channel in enumerate(unique_channels):
                label = channel_to_sensor.get(channel)
                if label not in sensor_index:
                    continue
                current_values[sensor_index[label]] = float(channel_matrix[row_idx, col_idx])

            deltas = current_values - self.r555_prev_values
            self.r555_last_deltas = deltas

            pos_mask = deltas > th
            neg_mask = deltas < -th_release
            self.r555_accumulators[pos_mask] += deltas[pos_mask]
            self.r555_accumulators[neg_mask] += deltas[neg_mask]

            self.r555_prev_values = current_values
            self.r555_last_sensor_values = current_values

        calibration = np.array(settings.get('sensor_calibration', [1.0, 1.0, 1.0, 1.0]), dtype=np.float64)
        if calibration.shape[0] != len(sensor_order):
            calibration = np.ones(len(sensor_order), dtype=np.float64)

        weights = self.r555_accumulators * calibration
        self.r555_last_weights = weights
        intensity = float(np.sum(weights))

        x_num = 0.0
        y_num = 0.0
        for idx, label in enumerate(sensor_order):
            pos = coord_map.get(label, (0.0, 0.0))
            x_num += weights[idx] * pos[0]
            y_num += weights[idx] * pos[1]

        cop_x = x_num / (intensity + COP_EPS)
        cop_y = y_num / (intensity + COP_EPS)

        cop_alpha = float(settings.get('cop_smooth_alpha', SMOOTH_ALPHA))
        self.r555_smoothed_x = (1.0 - cop_alpha) * self.r555_smoothed_x + cop_alpha * cop_x
        self.r555_smoothed_y = (1.0 - cop_alpha) * self.r555_smoothed_y + cop_alpha * cop_y
        self.r555_smoothed_i = (1.0 - cop_alpha) * self.r555_smoothed_i + cop_alpha * intensity

        i_min = float(settings.get('intensity_min', R_HEATMAP_INTENSITY_MIN))
        i_max = float(settings.get('intensity_max', R_HEATMAP_INTENSITY_MAX))
        if i_max <= i_min:
            q_i = 1.0 if self.r555_smoothed_i >= i_min else 0.0
        else:
            q_i = (self.r555_smoothed_i - i_min) / (i_max - i_min)
        q_i = float(np.clip(q_i, 0.0, 1.0))

        concentration = float(np.max(weights) / (intensity + COP_EPS)) if intensity > 0 else 0.0
        concentration = float(np.clip(concentration, 0.0, 1.0))
        confidence = float(np.clip(q_i * concentration, 0.0, 1.0))
        self.r555_last_qi = q_i
        self.r555_last_concentration = concentration
        self.r555_last_confidence = confidence

        sigma_x = max(float(settings.get('blob_sigma_x', BLOB_SIGMA_X)), 1e-6)
        sigma_y = max(float(settings.get('blob_sigma_y', BLOB_SIGMA_Y)), 1e-6)

        label_to_weight = {label: float(weights[idx]) for idx, label in enumerate(sensor_order)}
        left_weight = label_to_weight.get('L', 0.0)
        right_weight = label_to_weight.get('R', 0.0)
        top_weight = label_to_weight.get('T', 0.0)
        bottom_weight = label_to_weight.get('B', 0.0)
        lr = (left_weight + right_weight) / (intensity + COP_EPS) if intensity > 0 else 0.0
        tb = (top_weight + bottom_weight) / (intensity + COP_EPS) if intensity > 0 else 0.0

        axis_k = max(0.0, float(settings.get('axis_adapt_strength', R_HEATMAP_AXIS_ADAPT_STRENGTH)))
        if lr > tb:
            sigma_x *= (1.0 + axis_k * min(1.0, lr - tb))
        elif tb > lr:
            sigma_y *= (1.0 + axis_k * min(1.0, tb - lr))

        dx = self.heatmap_x_grid - self.r555_smoothed_x
        dy = self.heatmap_y_grid - self.r555_smoothed_y
        gaussian = np.exp(-(dx**2 / (2 * sigma_x**2) + dy**2 / (2 * sigma_y**2)))

        amplitude = self.r555_smoothed_i * float(settings.get('intensity_scale', INTENSITY_SCALE)) * confidence
        heatmap_now = gaussian * amplitude

        map_alpha = float(settings.get('map_smooth_alpha', R_HEATMAP_MAP_SMOOTH_ALPHA))
        map_alpha = float(np.clip(map_alpha, 0.0, 1.0))
        self.r555_smoothed_heatmap = (
            (1.0 - map_alpha) * self.r555_smoothed_heatmap + map_alpha * heatmap_now
        ).astype(np.float32)

        np.clip(self.r555_smoothed_heatmap, 0, 1, out=self.r555_smoothed_heatmap)

        return (
            self.r555_smoothed_heatmap,
            self.r555_smoothed_x,
            self.r555_smoothed_y,
            self.r555_smoothed_i,
            confidence,
            self.r555_last_weights.tolist(),
        )
    
    def calculate_cop_and_intensity(self, sensor_values, settings):
        """Calculate center of pressure and intensity from sensor values.
        
        Args:
            sensor_values: List or array of 5 sensor values
            
        Returns:
            tuple: (cop_x, cop_y, intensity)
        """
        # Ensure non-negative weights
        weights = np.maximum(np.array(sensor_values, dtype=np.float32), 0.0)
        
        # Calculate total intensity
        intensity = np.sum(weights)
        
        # Calculate center of pressure
        total_weight = np.sum(weights) + COP_EPS
        cop_x = np.sum(np.array(SENSOR_POS_X, dtype=np.float32) * weights) / total_weight
        cop_y = np.sum(np.array(SENSOR_POS_Y, dtype=np.float32) * weights) / total_weight
        
        # Apply exponential moving average smoothing
        smooth_alpha = settings.get('smooth_alpha', SMOOTH_ALPHA)
        self.smoothed_cop_x = smooth_alpha * cop_x + (1 - smooth_alpha) * self.smoothed_cop_x
        self.smoothed_cop_y = smooth_alpha * cop_y + (1 - smooth_alpha) * self.smoothed_cop_y
        self.smoothed_intensity = smooth_alpha * intensity + (1 - smooth_alpha) * self.smoothed_intensity
        
        return self.smoothed_cop_x, self.smoothed_cop_y, self.smoothed_intensity
    
    def generate_heatmap(self, cop_x, cop_y, intensity, settings):
        """Generate 2D heatmap as Gaussian blob centered at CoP.
        
        Args:
            cop_x: Center of pressure X coordinate (normalized -1 to 1)
            cop_y: Center of pressure Y coordinate (normalized -1 to 1)
            intensity: Overall pressure intensity
            
        Returns:
            np.ndarray: 2D heatmap array (HEATMAP_HEIGHT x HEATMAP_WIDTH)
        """
        # Calculate Gaussian blob
        # Distance from each pixel to CoP
        dx = self.heatmap_x_grid - cop_x
        dy = self.heatmap_y_grid - cop_y
        
        # Gaussian distribution
        sigma_x = settings.get('blob_sigma_x', BLOB_SIGMA_X)
        sigma_y = settings.get('blob_sigma_y', BLOB_SIGMA_Y)
        sigma_scale = settings.get('sigma_scale', 1.0)
        sigma_scale_x = settings.get('sigma_scale_x', 1.0)
        sigma_scale_y = settings.get('sigma_scale_y', 1.0)
        sigma_x = max(1e-6, sigma_x * sigma_scale * sigma_scale_x)
        sigma_y = max(1e-6, sigma_y * sigma_scale * sigma_scale_y)
        gaussian = np.exp(-(dx**2 / (2 * sigma_x**2) + dy**2 / (2 * sigma_y**2)))
        
        # Scale by intensity
        amplitude = intensity * settings.get('intensity_scale', INTENSITY_SCALE)
        self.heatmap_buffer[:] = gaussian * amplitude
        
        # Clip to reasonable range
        np.clip(self.heatmap_buffer, 0, 1, out=self.heatmap_buffer)
        
        return self.heatmap_buffer
    
    def process_sensor_data_for_heatmap(self, sensor_values, settings):
        """Complete processing pipeline: sensor values -> heatmap.
        
        Args:
            sensor_values: List or array of 5 sensor values
            
        Returns:
            tuple: (heatmap_array, cop_x, cop_y, intensity, sensor_values)
        """
        # Calculate CoP and intensity
        cop_x, cop_y, intensity = self.calculate_cop_and_intensity(sensor_values, settings)

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
        
        # Generate heatmap
        heatmap = self.generate_heatmap(cop_x, cop_y, intensity, settings)
        
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
        if not hasattr(self, 'heatmap_signal_processor'):
            return None

        extract_result = self._extract_heatmap_window_data(settings.get('rms_window_ms', 200))
        if extract_result is None:
            return None

        data_array, timestamps, avg_sample_time_us = extract_result
        channels = self.config.get('channels', [])
        repeat_count = self.config.get('repeat', 1)

        if not channels or repeat_count <= 0:
            return None

        unique_channels = []
        for ch in channels:
            if ch not in unique_channels:
                unique_channels.append(ch)

        if len(unique_channels) != HEATMAP_REQUIRED_CHANNELS:
            return None

        channel_samples = []
        for channel in unique_channels:
            positions = [i for i, c in enumerate(channels) if c == channel]
            channel_data_list = []
            for pos in positions:
                start_idx = pos * repeat_count
                end_idx = start_idx + repeat_count
                if end_idx > data_array.shape[1]:
                    continue
                pos_data = data_array[:, start_idx:end_idx]
                channel_data_list.append(pos_data.reshape(-1))

            if channel_data_list:
                channel_samples.append(np.concatenate(channel_data_list))
            else:
                channel_samples.append(np.array([], dtype=np.float64))

        sample_rate_hz = 1000000.0 / avg_sample_time_us
        per_channel_rate_hz = sample_rate_hz / max(len(unique_channels), 1)

        self.heatmap_signal_processor.set_hpf_cutoff(settings.get('hpf_cutoff_hz', 0.0))
        window_end_time_sec = float(timestamps[-1]) if timestamps.size else None
        rms_values, _ = self.heatmap_signal_processor.compute_rms(
            channel_samples,
            settings.get('dc_removal_mode', 'bias'),
            per_channel_rate_hz,
            window_end_time_sec,
        )

        channel_to_sensor = settings.get('channel_sensor_map', [])
        sensor_labels = ['T', 'B', 'R', 'L', 'C']
        sensor_values_map = {label: 0.0 for label in sensor_labels}
        for idx, sensor_label in enumerate(channel_to_sensor):
            if idx < len(rms_values):
                sensor_values_map[sensor_label] = rms_values[idx]

        sensor_values = [sensor_values_map[label] for label in sensor_labels]

        noise_floor = settings.get('sensor_noise_floor', [0.0] * len(sensor_values))
        calibration = settings.get('sensor_calibration', [1.0] * len(sensor_values))
        calibrated = []
        for value, noise, gain in zip(sensor_values, noise_floor, calibration):
            adjusted = max(0.0, value - noise)
            calibrated.append(adjusted * gain)
        smoothed = self.heatmap_signal_processor.smooth_and_threshold(
            calibrated,
            settings.get('smooth_alpha', SMOOTH_ALPHA),
            settings.get('magnitude_threshold', 0.0),
        )

        return smoothed
