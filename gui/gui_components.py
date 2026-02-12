"""
GUI Components Mixin
====================
Main mixin combining all GUI component creation methods.

This module combines:
- Control panels (ControlPanelsMixin) - Serial, ADC config, acquisition, run control
- Display panels (DisplayPanelsMixin) - Plot, visualization controls, timing
- File panels (FilePanelsMixin) - File management, status display
- Heatmap panel (HeatmapPanelMixin) - 2D pressure heatmap visualization
"""

from gui.control_panels import ControlPanelsMixin
from gui.display_panels import DisplayPanelsMixin
from gui.file_panels import FilePanelsMixin
from gui.heatmap_panel import HeatmapPanelMixin
from gui.spectrum_panel import SpectrumPanelMixin


class GUIComponentsMixin(ControlPanelsMixin, DisplayPanelsMixin, FilePanelsMixin, HeatmapPanelMixin, SpectrumPanelMixin):
    """Main mixin class combining all GUI component creation methods."""
    pass
