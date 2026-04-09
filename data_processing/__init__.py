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
- processing_stack.py: Main mixin composition layer
"""

from data_processing.binary_processor import BinaryProcessorMixin
from data_processing.adc_plotting import ADCPlottingMixin
from data_processing.capture_cache import CaptureCacheMixin
from data_processing.capture_lifecycle import CaptureLifecycleMixin
from data_processing.filter_processor import FilterProcessorMixin
from data_processing.force_overlay import ForceOverlayMixin
from data_processing.force_processor import ForceProcessorMixin
from data_processing.timing_display import TimingDisplayMixin
from data_processing.heatmap_processor import HeatmapProcessorMixin
from data_processing.shear_processor import ShearProcessorMixin
from data_processing.spectrum_processor import SpectrumProcessorMixin
from data_processing.processing_stack import DataProcessorMixin

__all__ = [
    'DataProcessorMixin',
    'ADCPlottingMixin',
    'CaptureCacheMixin',
    'CaptureLifecycleMixin',
    'BinaryProcessorMixin',
    'FilterProcessorMixin',
    'ForceOverlayMixin',
    'ForceProcessorMixin',
    'TimingDisplayMixin',
    'HeatmapProcessorMixin',
    'ShearProcessorMixin',
    'SpectrumProcessorMixin',
]
