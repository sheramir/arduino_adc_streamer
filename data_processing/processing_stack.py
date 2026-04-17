"""
Processing Stack
================
Composition layer for the focused data-processing mixins.
"""

from data_processing.capture_lifecycle import CaptureLifecycleMixin
from data_processing.capture_cache import CaptureCacheMixin
from data_processing.adc_plotting import ADCPlottingMixin
from data_processing.force_overlay import ForceOverlayMixin
from data_processing.timing_display import TimingDisplayMixin
from serial_communication.serial_parser import SerialParserMixin
from data_processing.binary_processor import BinaryProcessorMixin
from data_processing.filter_processor import FilterProcessorMixin
from data_processing.force_processor import ForceProcessorMixin
from data_processing.signal_integration_processor import SignalIntegrationProcessorMixin


class DataProcessorMixin(
    ForceOverlayMixin,
    SignalIntegrationProcessorMixin,
    CaptureCacheMixin,
    TimingDisplayMixin,
    ADCPlottingMixin,
    CaptureLifecycleMixin,
    FilterProcessorMixin,
    SerialParserMixin,
    BinaryProcessorMixin,
    ForceProcessorMixin,
):
    """Main mixin class for data processing, visualization, timing, and capture lifecycle."""
