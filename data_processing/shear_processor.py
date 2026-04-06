"""
Shear Processor Mixin
=====================
Coordinates live extraction of 5-channel piezo data into shear / CoP outputs.
"""

from __future__ import annotations

from typing import Dict

import numpy as np

from config_constants import HEATMAP_CHANNEL_SENSOR_MAP, HEATMAP_HEIGHT, HEATMAP_REQUIRED_CHANNELS, HEATMAP_WIDTH, MAX_SENSOR_PACKAGES
from data_processing.shear_cop_processor import (
    SHEAR_SENSOR_ORDER,
    ShearCoPProcessor,
    generate_gaussian_blob,
    shift_residuals_to_positive,
)


class ShearProcessorMixin:
    """Mixin for real-time shear / CoP computation from the MG-24 channel window."""

    def init_shear_processing_state(self) -> None:
        self.shear_processors = [ShearCoPProcessor() for _ in range(MAX_SENSOR_PACKAGES)]
        self.last_shear_sweep_count = 0
        self.shear_heatmap_buffers = [
            np.zeros((HEATMAP_HEIGHT, HEATMAP_WIDTH), dtype=np.float32)
            for _ in range(MAX_SENSOR_PACKAGES)
        ]

    def reset_shear_processing_state(self) -> None:
        for processor in getattr(self, "shear_processors", []):
            processor.reset()
        self.last_shear_sweep_count = 0
        for buffer in getattr(self, "shear_heatmap_buffers", []):
            buffer.fill(0)

    def _extract_shear_sensor_samples(self, settings: Dict[str, object]):
        extract_result = self._extract_heatmap_window_data(settings.get("integration_window_ms", 16.0))
        if extract_result is None:
            return None

        data_array, _, avg_sample_time_us = extract_result
        channels = self.config.get("channels", [])
        repeat_count = self.config.get("repeat", 1)
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
            for channel in channels:
                if channel not in unique_channels:
                    unique_channels.append(channel)

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

        channel_sensor_map = list(settings.get("channel_sensor_map", HEATMAP_CHANNEL_SENSOR_MAP))
        package_sensor_streams = []

        for package_index in range(package_count):
            sensor_streams = {name: np.array([], dtype=np.float64) for name in SHEAR_SENSOR_ORDER}
            if array_sensor_groups:
                group = array_sensor_groups[package_index]
                package_channels = list(group.get('channels', []))
                package_positions = list(group.get('positions', []))
            else:
                package_channels = list(standard_package_channels[package_index])
                package_positions = []

            for channel_index, channel in enumerate(package_channels):
                if package_positions:
                    positions = [int(package_positions[channel_index])] if channel_index < len(package_positions) else []
                else:
                    positions = [idx for idx, seq_channel in enumerate(channels) if seq_channel == channel]
                channel_data_list = []
                for pos in positions:
                    start_idx = pos * repeat_count
                    end_idx = start_idx + repeat_count
                    if end_idx > data_array.shape[1]:
                        continue
                    channel_data_list.append(data_array[:, start_idx:end_idx].reshape(-1))

                if not channel_data_list or channel_index >= len(channel_sensor_map):
                    continue

                sensor_name = channel_sensor_map[channel_index]
                sensor_streams[sensor_name] = np.concatenate(channel_data_list).astype(np.float64, copy=False)
            package_sensor_streams.append(sensor_streams)

        total_sample_rate_hz = 1_000_000.0 / float(avg_sample_time_us) if avg_sample_time_us > 0 else 0.0
        per_channel_rate_hz = total_sample_rate_hz / max(len(channels), 1)
        return package_sensor_streams, per_channel_rate_hz

    def compute_shear_visualization(self, settings: Dict[str, object]):
        sample_result = self._extract_shear_sensor_samples(settings)
        if sample_result is None:
            return None

        package_sensor_streams, sample_rate_hz = sample_result
        if sample_rate_hz <= 0:
            return None

        package_results = []
        for package_index, sensor_streams in enumerate(package_sensor_streams):
            result = self.shear_processors[package_index].process(sensor_streams, sample_rate_hz, settings)
            display_radius = float(getattr(self, "SHEAR_SENSOR_RADIUS", 1.0))
            display_cop_x = float(result.cop_x) * display_radius
            display_cop_y = float(result.cop_y) * display_radius

            residual_weights = shift_residuals_to_positive(result.residual_values)
            residual_intensity = float(sum(residual_weights.values()))
            signal_ref = max(float(settings.get("confidence_signal_ref", 0.02)), 1e-9)
            amplitude = float(np.clip((residual_intensity / signal_ref) * float(settings.get("intensity_scale", 1.0)), 0.0, 1.0))
            blob = generate_gaussian_blob(
                self.shear_x_grid,
                self.shear_y_grid,
                display_cop_x,
                display_cop_y,
                float(settings.get("blob_sigma_x", 0.18)),
                float(settings.get("blob_sigma_y", 0.18)),
                amplitude,
            )
            if amplitude > 0.0:
                tail_threshold = max(0.02 * amplitude, 1e-4)
                blob[blob < tail_threshold] = 0.0
            np.clip(blob, 0.0, 1.0, out=blob)
            self.shear_heatmap_buffers[package_index][:, :] = blob.astype(np.float32, copy=False)
            package_results.append((self.shear_heatmap_buffers[package_index], result))
        return package_results
