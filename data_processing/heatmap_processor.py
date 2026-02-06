"""
Heatmap Processor Mixin
=======================
Handles center-of-pressure calculation and 2D heatmap generation from sensor data.
"""

import numpy as np

from config_constants import (
    HEATMAP_WIDTH, HEATMAP_HEIGHT, SENSOR_POS_X, SENSOR_POS_Y,
    SENSOR_CALIBRATION, INTENSITY_SCALE, COP_EPS, BLOB_SIGMA_X,
    BLOB_SIGMA_Y, SMOOTH_ALPHA
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
    
    def calculate_cop_and_intensity(self, sensor_values):
        """Calculate center of pressure and intensity from sensor values.
        
        Args:
            sensor_values: List or array of 5 sensor values
            
        Returns:
            tuple: (cop_x, cop_y, intensity)
        """
        # Apply calibration scaling
        calibrated = np.array(sensor_values, dtype=np.float32) * np.array(SENSOR_CALIBRATION, dtype=np.float32)
        
        # Ensure non-negative weights
        weights = np.maximum(calibrated, 0.0)
        
        # Calculate total intensity
        intensity = np.sum(weights)
        
        # Calculate center of pressure
        total_weight = np.sum(weights) + COP_EPS
        cop_x = np.sum(np.array(SENSOR_POS_X, dtype=np.float32) * weights) / total_weight
        cop_y = np.sum(np.array(SENSOR_POS_Y, dtype=np.float32) * weights) / total_weight
        
        # Apply exponential moving average smoothing
        self.smoothed_cop_x = SMOOTH_ALPHA * cop_x + (1 - SMOOTH_ALPHA) * self.smoothed_cop_x
        self.smoothed_cop_y = SMOOTH_ALPHA * cop_y + (1 - SMOOTH_ALPHA) * self.smoothed_cop_y
        self.smoothed_intensity = SMOOTH_ALPHA * intensity + (1 - SMOOTH_ALPHA) * self.smoothed_intensity
        
        return self.smoothed_cop_x, self.smoothed_cop_y, self.smoothed_intensity
    
    def generate_heatmap(self, cop_x, cop_y, intensity):
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
        gaussian = np.exp(-(dx**2 / (2 * BLOB_SIGMA_X**2) + dy**2 / (2 * BLOB_SIGMA_Y**2)))
        
        # Scale by intensity
        amplitude = intensity * INTENSITY_SCALE
        self.heatmap_buffer[:] = gaussian * amplitude
        
        # Clip to reasonable range
        np.clip(self.heatmap_buffer, 0, 1, out=self.heatmap_buffer)
        
        return self.heatmap_buffer
    
    def process_sensor_data_for_heatmap(self, sensor_values):
        """Complete processing pipeline: sensor values -> heatmap.
        
        Args:
            sensor_values: List or array of 5 sensor values
            
        Returns:
            tuple: (heatmap_array, cop_x, cop_y, intensity, sensor_values)
        """
        # Calculate CoP and intensity
        cop_x, cop_y, intensity = self.calculate_cop_and_intensity(sensor_values)
        
        # Generate heatmap
        heatmap = self.generate_heatmap(cop_x, cop_y, intensity)
        
        return heatmap, cop_x, cop_y, intensity, sensor_values
