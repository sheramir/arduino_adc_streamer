"""
555 Heatmap Processor Mixin
===========================
555-resistance-specific displacement heatmap processing.
"""

import numpy as np

from config_constants import (
    HEATMAP_WIDTH, HEATMAP_HEIGHT,
    INTENSITY_SCALE, COP_EPS, BLOB_SIGMA_X, BLOB_SIGMA_Y, SMOOTH_ALPHA,
    R_HEATMAP_CHANNEL_SENSOR_MAP, R_HEATMAP_DELTA_THRESHOLD,
    R_HEATMAP_DELTA_RELEASE_THRESHOLD, R_HEATMAP_INTENSITY_MIN, R_HEATMAP_INTENSITY_MAX,
    R_HEATMAP_AXIS_ADAPT_STRENGTH, R_HEATMAP_MAP_SMOOTH_ALPHA,
)


class Heatmap555ProcessorMixin:
    """555 resistance mode (4-sensor) displacement heatmap pipeline."""

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