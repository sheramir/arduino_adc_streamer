"""
GUI Module
==========
GUI components and layout management for the active application views.
"""

from gui.control_panels import ControlPanelsMixin
from gui.display_panels import DisplayPanelsMixin
from gui.file_panels import FilePanelsMixin
from gui.signal_integration_panel import PressureMapPanelMixin, SignalIntegrationPanelMixin
from gui.pressure_map_widget import PressureMapWidget
from gui.sensor_panel import SensorPanelMixin
from gui.spectrum_panel import SpectrumPanelMixin
from gui.status_logging import StatusLoggingMixin

__all__ = [
    'ControlPanelsMixin',
    'DisplayPanelsMixin',
    'FilePanelsMixin',
    'PressureMapPanelMixin',
    'PressureMapWidget',
    'SensorPanelMixin',
    'SignalIntegrationPanelMixin',
    'SpectrumPanelMixin',
    'StatusLoggingMixin',
]
