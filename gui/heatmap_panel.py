"""
Heatmap Panel GUI Component
============================
Provides UI components for real-time 2D heatmap visualization.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox
)
from PyQt6.QtCore import Qt
import pyqtgraph as pg
import numpy as np

from config_constants import HEATMAP_WIDTH, HEATMAP_HEIGHT


class HeatmapPanelMixin:
    """Mixin providing heatmap visualization panel components."""
    
    def create_heatmap_tab(self):
        """Create the heatmap visualization tab.
        
        Returns:
            QWidget: Widget containing heatmap display and readouts
        """
        heatmap_widget = QWidget()
        layout = QVBoxLayout()
        
        # Create heatmap display
        heatmap_display = self.create_heatmap_display()
        layout.addWidget(heatmap_display, stretch=3)
        
        # Create readouts panel
        readouts_panel = self.create_heatmap_readouts()
        layout.addWidget(readouts_panel, stretch=1)
        
        heatmap_widget.setLayout(layout)
        return heatmap_widget
    
    def create_heatmap_display(self):
        """Create the pyqtgraph heatmap image display.
        
        Returns:
            QGroupBox: Group box containing heatmap plot
        """
        group = QGroupBox("2D Pressure Heatmap")
        layout = QVBoxLayout()
        
        # Create GraphicsLayoutWidget for heatmap
        self.heatmap_plot_widget = pg.GraphicsLayoutWidget()
        self.heatmap_plot = self.heatmap_plot_widget.addPlot()
        
        # Configure plot
        self.heatmap_plot.setAspectLocked(False)
        self.heatmap_plot.showAxis('left', False)
        self.heatmap_plot.showAxis('bottom', False)
        self.heatmap_plot.setMouseEnabled(x=False, y=False)
        
        # Create ImageItem for heatmap
        self.heatmap_image = pg.ImageItem()
        self.heatmap_plot.addItem(self.heatmap_image)
        
        # Set colormap (using built-in 'viridis'-like colormap)
        colormap = pg.colormap.get('viridis')
        self.heatmap_image.setColorMap(colormap)
        
        # Add colorbar
        self.heatmap_colorbar = pg.ColorBarItem(
            values=(0, 1),
            colorMap=colormap,
            width=15,
            interactive=False
        )
        self.heatmap_colorbar.setImageItem(self.heatmap_image)
        self.heatmap_plot_widget.addItem(self.heatmap_colorbar)
        
        # Initialize with empty data
        empty_heatmap = np.zeros((HEATMAP_HEIGHT, HEATMAP_WIDTH), dtype=np.float32)
        self.heatmap_image.setImage(empty_heatmap, autoLevels=False, levels=(0, 1))
        
        # Status label for channel warnings
        self.heatmap_status_label = QLabel("")
        self.heatmap_status_label.setStyleSheet("color: red; font-weight: bold;")
        self.heatmap_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        layout.addWidget(self.heatmap_plot_widget)
        layout.addWidget(self.heatmap_status_label)
        group.setLayout(layout)
        
        return group
    
    def create_heatmap_readouts(self):
        """Create numeric readout displays for CoP and sensor values.
        
        Returns:
            QGroupBox: Group box containing readout labels
        """
        group = QGroupBox("Sensor Readouts")
        layout = QVBoxLayout()
        
        # Center of Pressure readouts
        cop_layout = QHBoxLayout()
        cop_layout.addWidget(QLabel("Center of Pressure:"))
        
        self.cop_x_label = QLabel("X: 0.000")
        self.cop_x_label.setStyleSheet("font-weight: bold; font-family: monospace;")
        cop_layout.addWidget(self.cop_x_label)
        
        self.cop_y_label = QLabel("Y: 0.000")
        self.cop_y_label.setStyleSheet("font-weight: bold; font-family: monospace;")
        cop_layout.addWidget(self.cop_y_label)
        
        cop_layout.addStretch()
        layout.addLayout(cop_layout)
        
        # Intensity readout
        intensity_layout = QHBoxLayout()
        intensity_layout.addWidget(QLabel("Intensity:"))
        
        self.intensity_label = QLabel("0.0")
        self.intensity_label.setStyleSheet("font-weight: bold; font-family: monospace;")
        intensity_layout.addWidget(self.intensity_label)
        
        intensity_layout.addStretch()
        layout.addLayout(intensity_layout)
        
        # Sensor values readouts
        sensors_layout = QHBoxLayout()
        sensors_layout.addWidget(QLabel("Sensors [T, B, R, L, C]:"))
        
        self.sensor_labels = []
        sensor_names = ['T', 'B', 'R', 'L', 'C']
        for name in sensor_names:
            label = QLabel(f"{name}: 0")
            label.setStyleSheet("font-family: monospace;")
            self.sensor_labels.append(label)
            sensors_layout.addWidget(label)
        
        sensors_layout.addStretch()
        layout.addLayout(sensors_layout)
        
        group.setLayout(layout)
        return group
    
    def update_heatmap_display(self, heatmap, cop_x, cop_y, intensity, sensor_values):
        """Update heatmap visualization with new data.
        
        Args:
            heatmap: 2D numpy array (HEATMAP_HEIGHT x HEATMAP_WIDTH)
            cop_x: Center of pressure X coordinate
            cop_y: Center of pressure Y coordinate
            intensity: Overall pressure intensity
            sensor_values: List of 5 sensor values
        """
        # Update heatmap image
        self.heatmap_image.setImage(heatmap.T, autoLevels=False, levels=(0, 1))
        
        # Update readouts
        self.cop_x_label.setText(f"X: {cop_x:+.3f}")
        self.cop_y_label.setText(f"Y: {cop_y:+.3f}")
        self.intensity_label.setText(f"{intensity:.1f}")
        
        # Update sensor values
        sensor_names = ['T', 'B', 'R', 'L', 'C']
        for i, (name, value) in enumerate(zip(sensor_names, sensor_values)):
            self.sensor_labels[i].setText(f"{name}: {value:.0f}")
    
    def show_heatmap_channel_warning(self, current_channels):
        """Display warning message when channel count is incorrect.
        
        Args:
            current_channels: Current number of selected channels
        """
        message = f"⚠ Heatmap requires exactly 5 channels (currently {current_channels} selected)"
        self.heatmap_status_label.setText(message)
    
    def clear_heatmap_channel_warning(self):
        """Clear channel warning message."""
        self.heatmap_status_label.setText("")
