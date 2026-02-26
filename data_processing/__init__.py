"""
Data Processing Module
======================
ADC and force data processing, plotting, timing calculations, and heatmap generation.

Module structure:
- serial_parser.py: Parse ASCII serial messages
- binary_processor.py: Process binary ADC data blocks
- filter_processor.py: Real-time IIR filter pipeline (raw -> processed)
- force_processor.py: Process force sensor data
- heatmap_piezo_processor.py: Piezoelectric heatmap processing pipeline
- heatmap_555_processor.py: 555 resistance displacement heatmap pipeline
- heatmap_processor.py: Coordinator mixin composing both heatmap pipelines
- simulated_source.py: Simulated sensor data source for testing
- data_processor.py: Main mixin combining all functionality
"""

from data_processing.binary_processor import BinaryProcessorMixin
from data_processing.filter_processor import FilterProcessorMixin
from data_processing.force_processor import ForceProcessorMixin
from data_processing.heatmap_processor import HeatmapProcessorMixin
from data_processing.spectrum_processor import SpectrumProcessorMixin
from data_processing.simulated_source import SimulatedSensorThread
from data_processing.data_processor import DataProcessorMixin

__all__ = [
    'DataProcessorMixin',
    'BinaryProcessorMixin',
    'FilterProcessorMixin',
    'ForceProcessorMixin',
    'HeatmapProcessorMixin',
    'SpectrumProcessorMixin',
    'SimulatedSensorThread',
]
