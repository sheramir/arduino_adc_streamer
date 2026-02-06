"""
GUI Components Mixin
====================
Main mixin combining all GUI component creation methods.

This module combines:
- Control panels (ControlPanelsMixin) - Serial, ADC config, acquisition, run control
- Display panels (DisplayPanelsMixin) - Plot, visualization controls, timing
- File panels (FilePanelsMixin) - File management, status display
"""

from gui.control_panels import ControlPanelsMixin
from gui.display_panels import DisplayPanelsMixin
from gui.file_panels import FilePanelsMixin


class GUIComponentsMixin(ControlPanelsMixin, DisplayPanelsMixin, FilePanelsMixin):
    """Main mixin class combining all GUI component creation methods."""
    pass
