"""
Data Processing Module
======================
ADC and force data processing, plotting, timing calculations, and spectrum generation.

Module structure:
- serial_parser.py: Parse ASCII serial messages
- binary_processor.py: Process binary ADC data blocks
- adc_filter_engine.py: Plain ADC-only filter design and block-processing engine
- filter_processor.py: Real-time IIR filter pipeline (raw -> processed)
- force_processor.py: Process force sensor data
- processing_stack.py: Main mixin composition layer
"""

from data_processing.binary_processor import BinaryProcessorMixin
from data_processing.adc_plotting import ADCPlottingMixin
from data_processing.capture_cache import CaptureCacheMixin
from data_processing.capture_lifecycle import CaptureLifecycleMixin
from data_processing.filter_processor import FilterProcessorMixin
from data_processing.force_overlay import ForceOverlayMixin
from data_processing.force_processor import ForceProcessorMixin
from data_processing.shear_detector import ShearDetector, ShearResult
from data_processing.signal_integrator import SignalIntegrator
from data_processing.signal_integration_processor import SignalIntegrationProcessorMixin
from data_processing.timing_display import TimingDisplayMixin
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
    'ShearDetector',
    'ShearResult',
    'SignalIntegrator',
    'SignalIntegrationProcessorMixin',
    'TimingDisplayMixin',
    'SpectrumProcessorMixin',
]
