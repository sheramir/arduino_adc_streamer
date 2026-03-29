"""
555 Heatmap Processor Mixin
===========================
555-resistance-specific displacement heatmap processing.
"""

import numpy as np

from config_constants import (
    HEATMAP_WIDTH, HEATMAP_HEIGHT,
    INTENSITY_SCALE, COP_EPS, BLOB_SIGMA_X, BLOB_SIGMA_Y, SMOOTH_ALPHA,
    R_HEATMAP_CHANNEL_SENSOR_MAP, R_HEATMAP_REQUIRED_CHANNELS,
    R_HEATMAP_SENSOR_POS_X, R_HEATMAP_SENSOR_POS_Y,
    R_HEATMAP_DELTA_THRESHOLD, R_HEATMAP_DELTA_RELEASE_THRESHOLD,
    R_HEATMAP_INTENSITY_MIN, R_HEATMAP_INTENSITY_MAX,
    R_HEATMAP_AXIS_ADAPT_STRENGTH, R_HEATMAP_MAP_SMOOTH_ALPHA,
    R_HEATMAP_COP_SMOOTH_ALPHA,
)


class Heatmap555ProcessorMixin:
    """555 resistance mode (4-sensor) displacement heatmap pipeline."""

    @staticmethod
    def _threshold_label_order():
        return ["T", "B", "R", "L", "C"]

    def _get_package_sensor_id(self, package_index):
        if hasattr(self, 'is_array_sensor_selection_mode') and self.is_array_sensor_selection_mode():
            selected = list(self.config.get('selected_array_sensors', [])) if hasattr(self, 'config') else []
            if package_index < len(selected):
                return str(selected[package_index])
        return f"Sensor{package_index + 1}"

    def _build_r555_channel_value_array(self, label_order, values, default):
        result = np.full(len(label_order), float(default), dtype=np.float64)
        if not isinstance(values, (list, tuple, np.ndarray)):
            return result

        for idx, label in enumerate(self._threshold_label_order()):
            if idx >= len(values):
                continue
            if label in label_order:
                result[label_order.index(label)] = float(values[idx])
        return result

    def reset_555_heatmap_state(self):
        self.r555_package_states = {}
        self.r555_last_processed_sweep_count = 0

    def _get_r555_package_state(self, package_index, sensor_count):
        if not hasattr(self, 'r555_package_states') or not isinstance(self.r555_package_states, dict):
            self.r555_package_states = {}
        if not hasattr(self, 'r555_last_processed_sweep_count'):
            self.r555_last_processed_sweep_count = 0

        state = self.r555_package_states.get(package_index)
        if state is None or state['sensor_count'] != sensor_count:
            state = {
                'sensor_count': sensor_count,
                'prev_values': None,
                'baseline_values': None,
                'last_deltas': np.zeros(sensor_count, dtype=np.float64),
                'last_sensor_values': np.zeros(sensor_count, dtype=np.float64),
                'last_weights': np.zeros(sensor_count, dtype=np.float64),
                'last_confidence': 0.0,
                'last_concentration': 0.0,
                'last_qi': 0.0,
                'smoothed_x': 0.0,
                'smoothed_y': 0.0,
                'smoothed_i': 0.0,
                'smoothed_heatmap': np.zeros((HEATMAP_HEIGHT, HEATMAP_WIDTH), dtype=np.float32),
            }
            self.r555_package_states[package_index] = state
        return state

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
        sensor_order = self._threshold_label_order()

        required_channels = max(1, int(R_HEATMAP_REQUIRED_CHANNELS))
        if (
            len(unique_channels) < required_channels
            or len(unique_channels) % required_channels != 0
            or len(channel_sensor_map) != required_channels
        ):
            return None

        sensor_calibration_dict = settings.get('sensor_calibration_dict', {})
        channel_to_baseline = settings.get('channel_to_baseline', {})
        global_thresholds = self._build_r555_channel_value_array(
            sensor_order,
            settings.get('global_channel_thresholds', []),
            max(0.0, float(settings.get('delta_threshold', R_HEATMAP_DELTA_THRESHOLD))),
        )
        global_release_thresholds = self._build_r555_channel_value_array(
            sensor_order,
            settings.get('global_channel_release_thresholds', []),
            max(0.0, float(settings.get('delta_release_threshold', R_HEATMAP_DELTA_RELEASE_THRESHOLD))),
        )
        
        coord_x = settings.get('sensor_pos_x', list(R_HEATMAP_SENSOR_POS_X))
        coord_y = settings.get('sensor_pos_y', list(R_HEATMAP_SENSOR_POS_Y))
        coord_map = {
            label: (float(x), float(y))
            for label, x, y in zip(sensor_order, coord_x, coord_y)
        }
        calibration = np.array(settings.get('sensor_calibration', [1.0] * len(sensor_order)), dtype=np.float64)
        if calibration.shape[0] != len(sensor_order):
            calibration = np.ones(len(sensor_order), dtype=np.float64)

        package_count = len(unique_channels) // required_channels
        package_results = []
        display_sensor_order = ['T', 'B', 'R', 'L', 'C']

        for package_index in range(package_count):
            package_channels = unique_channels[
                package_index * required_channels:(package_index + 1) * required_channels
            ]
            package_matrix = channel_matrix[:, package_index * required_channels:(package_index + 1) * required_channels]
            channel_to_sensor = {
                channel: channel_sensor_map[idx]
                for idx, channel in enumerate(package_channels)
                if idx < len(channel_sensor_map)
            }
            sensor_index = {label: idx for idx, label in enumerate(sensor_order)}
            state = self._get_r555_package_state(package_index, len(sensor_order))
            package_sensor_id = self._get_package_sensor_id(package_index)

            configured_baselines = np.full(len(sensor_order), np.nan, dtype=np.float64)
            for channel in package_channels:
                label = channel_to_sensor.get(channel)
                if label not in sensor_index:
                    continue
                baseline_value = channel_to_baseline.get(channel, channel_to_baseline.get(str(channel)))
                if baseline_value is None:
                    continue
                configured_baselines[sensor_index[label]] = float(baseline_value)

            per_sensor_thresholds = np.zeros(len(sensor_order), dtype=np.float64)
            per_sensor_gains = np.ones(len(sensor_order), dtype=np.float64)
            if package_sensor_id in sensor_calibration_dict:
                calib_data = sensor_calibration_dict[package_sensor_id]
                per_sensor_thresholds = self._build_r555_channel_value_array(
                    sensor_order,
                    calib_data.get('thresholds', []),
                    0.0,
                )
                per_sensor_gains = self._build_r555_channel_value_array(
                    sensor_order,
                    calib_data.get('gains', []),
                    1.0,
                )

            if state['prev_values'] is None or state['prev_values'].shape[0] != len(sensor_order):
                state['prev_values'] = np.zeros(len(sensor_order), dtype=np.float64)
                if package_matrix.shape[0] > 0:
                    first_values = np.zeros(len(sensor_order), dtype=np.float64)
                    for col_idx, channel in enumerate(package_channels):
                        label = channel_to_sensor.get(channel)
                        if label in sensor_index:
                            first_values[sensor_index[label]] = float(package_matrix[0, col_idx])
                    state['prev_values'] = first_values
                    state['baseline_values'] = np.array(first_values, copy=True)
                    configured_mask = ~np.isnan(configured_baselines)
                    state['baseline_values'][configured_mask] = configured_baselines[configured_mask]

            if state['baseline_values'] is None or state['baseline_values'].shape[0] != len(sensor_order):
                state['baseline_values'] = np.array(state['prev_values'], copy=True)
                configured_mask = ~np.isnan(configured_baselines)
                state['baseline_values'][configured_mask] = configured_baselines[configured_mask]

            batch_magnitudes = []
            for row_idx in range(package_matrix.shape[0]):
                current_values = np.array(state['prev_values'], copy=True)
                for col_idx, channel in enumerate(package_channels):
                    label = channel_to_sensor.get(channel)
                    if label not in sensor_index:
                        continue
                    current_values[sensor_index[label]] = float(package_matrix[row_idx, col_idx])

                deltas = current_values - state['baseline_values']

                # Normalize channel response to relative change (%), so channels
                # with different absolute ranges contribute comparably.
                baseline_abs = np.maximum(np.abs(state['baseline_values']), 1e-9)
                relative_percent = (100.0 * deltas) / baseline_abs
                state['last_deltas'] = relative_percent

                magnitudes = np.abs(relative_percent)
                magnitudes = magnitudes * per_sensor_gains
                thresholds = global_thresholds + per_sensor_thresholds
                release_thresholds = global_release_thresholds + per_sensor_thresholds
                effective_thresholds = np.maximum(thresholds, release_thresholds)
                weights_now = np.where(magnitudes >= effective_thresholds, magnitudes, 0.0)
                batch_magnitudes.append(weights_now)

                state['prev_values'] = current_values
                state['last_sensor_values'] = current_values

            if not batch_magnitudes:
                continue

            weights = np.mean(np.vstack(batch_magnitudes), axis=0) * calibration
            state['last_weights'] = weights
            intensity = float(np.sum(weights))

            x_num = 0.0
            y_num = 0.0
            for idx, label in enumerate(sensor_order):
                pos = coord_map.get(label, (0.0, 0.0))
                x_num += weights[idx] * pos[0]
                y_num += weights[idx] * pos[1]

            cop_x = x_num / (intensity + COP_EPS)
            cop_y = y_num / (intensity + COP_EPS)

            cop_alpha = float(settings.get('cop_smooth_alpha', R_HEATMAP_COP_SMOOTH_ALPHA))
            state['smoothed_x'] = (1.0 - cop_alpha) * state['smoothed_x'] + cop_alpha * cop_x
            state['smoothed_y'] = (1.0 - cop_alpha) * state['smoothed_y'] + cop_alpha * cop_y
            state['smoothed_i'] = (1.0 - cop_alpha) * state['smoothed_i'] + cop_alpha * intensity

            i_min = float(settings.get('intensity_min', R_HEATMAP_INTENSITY_MIN))
            i_max = float(settings.get('intensity_max', R_HEATMAP_INTENSITY_MAX))
            if i_max <= i_min:
                q_i = 1.0 if state['smoothed_i'] >= i_min else 0.0
            else:
                q_i = (state['smoothed_i'] - i_min) / (i_max - i_min)
            q_i = float(np.clip(q_i, 0.0, 1.0))

            concentration = float(np.max(weights) / (intensity + COP_EPS)) if intensity > 0 else 0.0
            concentration = float(np.clip(concentration, 0.0, 1.0))
            confidence = float(np.clip(q_i * concentration, 0.0, 1.0))
            state['last_qi'] = q_i
            state['last_concentration'] = concentration
            state['last_confidence'] = confidence

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

            dx = self.heatmap_x_grid - state['smoothed_x']
            dy = self.heatmap_y_grid - state['smoothed_y']
            gaussian = np.exp(-(dx**2 / (2 * sigma_x**2) + dy**2 / (2 * sigma_y**2)))

            amplitude = state['smoothed_i'] * float(settings.get('intensity_scale', INTENSITY_SCALE)) * confidence
            heatmap_now = gaussian * amplitude

            map_alpha = float(settings.get('map_smooth_alpha', R_HEATMAP_MAP_SMOOTH_ALPHA))
            map_alpha = float(np.clip(map_alpha, 0.0, 1.0))
            state['smoothed_heatmap'] = (
                (1.0 - map_alpha) * state['smoothed_heatmap'] + map_alpha * heatmap_now
            ).astype(np.float32)
            np.clip(state['smoothed_heatmap'], 0, 1, out=state['smoothed_heatmap'])

            display_values = []
            for label in display_sensor_order:
                if label in sensor_index:
                    display_values.append(float(weights[sensor_index[label]]))
                else:
                    display_values.append(0.0)

            package_results.append(
                (
                    state['smoothed_heatmap'],
                    state['smoothed_x'],
                    state['smoothed_y'],
                    state['smoothed_i'],
                    confidence,
                    display_values,
                )
            )

        return package_results or None