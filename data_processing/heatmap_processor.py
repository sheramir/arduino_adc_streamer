"""
Heatmap Processor Mixin
=======================
Coordinates heatmap processing with separate piezo and 555-specific modules.
"""

import numpy as np

from config_constants import (
    HEATMAP_WIDTH,
    HEATMAP_HEIGHT,
)

from data_processing.heatmap_555_processor import Heatmap555ProcessorMixin
from data_processing.heatmap_piezo_processor import PiezoHeatmapProcessorMixin


class HeatmapProcessorMixin(Heatmap555ProcessorMixin, PiezoHeatmapProcessorMixin):
    """Coordinator mixin for processing sensor data into heatmap visualizations."""
    
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
