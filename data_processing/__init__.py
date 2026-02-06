"""
Data Processing Module
======================
ADC and force data processing, plotting, timing calculations, and heatmap generation.

Module structure:
- serial_parser.py: Parse ASCII serial messages
- binary_processor.py: Process binary ADC data blocks
- force_processor.py: Process force sensor data
- heatmap_processor.py: Calculate CoP and generate 2D heatmaps
- simulated_source.py: Simulated sensor data source for testing
- data_processor.py: Main mixin combining all functionality
"""

from data_processing.binary_processor import BinaryProcessorMixin
from data_processing.force_processor import ForceProcessorMixin
from data_processing.heatmap_processor import HeatmapProcessorMixin
from data_processing.simulated_source import SimulatedSensorThread
from data_processing.data_processor import DataProcessorMixin

__all__ = [
    'DataProcessorMixin',
    'BinaryProcessorMixin',
    'ForceProcessorMixin',
    'HeatmapProcessorMixin',
    'SimulatedSensorThread',
]
