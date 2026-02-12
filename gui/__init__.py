"""
GUI Module
==========
GUI components and layout management, including time-series and heatmap displays.
"""

from gui.control_panels import ControlPanelsMixin
from gui.display_panels import DisplayPanelsMixin
from gui.file_panels import FilePanelsMixin
from gui.heatmap_panel import HeatmapPanelMixin
from gui.spectrum_panel import SpectrumPanelMixin
from gui.gui_components import GUIComponentsMixin

__all__ = [
    'ControlPanelsMixin',
    'DisplayPanelsMixin',
    'FilePanelsMixin',
    'HeatmapPanelMixin',
    'SpectrumPanelMixin',
    'GUIComponentsMixin',
]
