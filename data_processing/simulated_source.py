"""
Simulated Sensor Data Source
=============================
Generates simulated 5-sensor pressure data for testing heatmap visualization.
"""

import time
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal


class SimulatedSensorThread(QThread):
    """Background thread generating simulated sensor data."""
    
    sensor_data_ready = pyqtSignal(list)  # Emits list of 5 sensor values
    
    def __init__(self, fps=30):
        super().__init__()
        self.fps = fps
        self.running = False
        self.time_offset = 0.0
        
    def run(self):
        """Generate simulated sensor data at target FPS."""
        self.running = True
        self.time_offset = time.time()
        
        frame_time = 1.0 / self.fps
        
        while self.running:
            frame_start = time.time()
            
            # Generate simulated sensor values
            sensor_values = self.generate_sensor_values()
            
            # Emit data
            self.sensor_data_ready.emit(sensor_values)
            
            # Sleep to maintain target FPS
            elapsed = time.time() - frame_start
            sleep_time = max(0, frame_time - elapsed)
            if sleep_time > 0:
                self.msleep(int(sleep_time * 1000))
    
    def generate_sensor_values(self):
        """Generate simulated 5-sensor values.
        
        Simulates a pressure point moving sinusoidally across the X axis
        with some noise added to all sensors.
        
        Returns:
            list: 5 sensor values (Top, Bottom, Right, Left, Center)
        """
        # Time-based parameters
        t = time.time() - self.time_offset
        
        # Traveling peak position (sinusoidal motion along X)
        peak_x = np.sin(t * 0.5) * 0.8  # Oscillate in range [-0.8, 0.8]
        peak_y = np.cos(t * 0.3) * 0.5  # Slower vertical motion
        
        # Base intensity with variation
        base_intensity = 500 + 300 * np.sin(t * 0.7)
        
        # Sensor positions (matching SENSOR_POS_X, SENSOR_POS_Y)
        # Top, Bottom, Right, Left, Center
        sensor_positions = [
            (0.0, -1.0),   # Top
            (0.0, 1.0),    # Bottom
            (1.0, 0.0),    # Right
            (-1.0, 0.0),   # Left
            (0.0, 0.0),    # Center
        ]
        
        sensor_values = []
        
        for sensor_x, sensor_y in sensor_positions:
            # Distance from peak to sensor
            distance = np.sqrt((sensor_x - peak_x)**2 + (sensor_y - peak_y)**2)
            
            # Gaussian falloff from peak
            sensor_response = base_intensity * np.exp(-distance**2 / 0.5)
            
            # Add noise
            noise = np.random.normal(0, 20)
            
            # Ensure non-negative with small baseline
            value = max(10, sensor_response + noise)
            
            sensor_values.append(value)
        
        return sensor_values
    
    def stop(self):
        """Stop the simulation thread."""
        self.running = False
