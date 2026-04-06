"""
Heatmap Processor Mixin
=======================
Coordinates heatmap processing with separate piezo and 555-specific modules.
"""

import numpy as np

from config_constants import (
    BIAS_CALIBRATION_DURATION_SEC,
    HPF_CUTOFF_HZ,
    HEATMAP_REQUIRED_CHANNELS,
    MAX_SENSOR_PACKAGES,
    HEATMAP_WIDTH,
    HEATMAP_HEIGHT,
)

from data_processing.heatmap_555_processor import Heatmap555ProcessorMixin
from data_processing.heatmap_piezo_processor import PiezoHeatmapProcessorMixin
from data_processing.heatmap_signal_processing import HeatmapSignalProcessor


class HeatmapProcessorMixin(PiezoHeatmapProcessorMixin, Heatmap555ProcessorMixin):
    """Coordinator mixin for processing sensor data into heatmap visualizations."""

    def init_heatmap_processing_state(self):
        """Initialize heatmap-related processing state for the main GUI."""
        self.smoothed_cop_x = [0.0 for _ in range(MAX_SENSOR_PACKAGES)]
        self.smoothed_cop_y = [0.0 for _ in range(MAX_SENSOR_PACKAGES)]
        self.smoothed_intensity = [0.0 for _ in range(MAX_SENSOR_PACKAGES)]
        self.active_sensor_package_count = 1

        self.heatmap_buffers = [
            np.zeros((HEATMAP_HEIGHT, HEATMAP_WIDTH), dtype=np.float32)
            for _ in range(MAX_SENSOR_PACKAGES)
        ]

        # Pre-compute coordinate grids for Gaussian blob
        y_coords = np.linspace(-1, 1, HEATMAP_HEIGHT).reshape(-1, 1)
        x_coords = np.linspace(-1, 1, HEATMAP_WIDTH).reshape(1, -1)
        self.heatmap_y_grid = np.tile(y_coords, (1, HEATMAP_WIDTH))
        self.heatmap_x_grid = np.tile(x_coords, (HEATMAP_HEIGHT, 1))

        self.heatmap_signal_processors = [
            HeatmapSignalProcessor(
                channel_count=HEATMAP_REQUIRED_CHANNELS,
                bias_duration_sec=BIAS_CALIBRATION_DURATION_SEC,
                hpf_cutoff_hz=HPF_CUTOFF_HZ,
            )
            for _ in range(MAX_SENSOR_PACKAGES)
        ]
        self.last_heatmap_sweep_count = 0
        self.reset_555_heatmap_state()
