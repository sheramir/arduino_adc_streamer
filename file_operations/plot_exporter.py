"""
Plot Export Mixin
=================
Handles plot image export operations.
"""

from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import QMessageBox
from pyqtgraph.exporters import ImageExporter

from config_constants import PLOT_EXPORT_WIDTH


class PlotExporterMixin:
    """Mixin class for plot export operations."""
    
    def save_plot_image(self):
        """Save the current plot as an image."""
        # Check if we have any captured data (either in buffer or in list)
        has_data = (self.raw_data_buffer is not None and self.sweep_count > 0) or len(self.raw_data) > 0
        if not has_data:
            QMessageBox.warning(self, "No Data", "No plot to save.")
            return

        directory = Path(self.dir_input.text())
        filename = self.filename_input.text()
        # Use minute-resolution filenames (no seconds)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")

        image_path = directory / f"{filename}_{timestamp}.png"

        try:
            # Export plot as image
            exporter = ImageExporter(self.plot_widget.plotItem)
            exporter.parameters()['width'] = PLOT_EXPORT_WIDTH  # High resolution
            exporter.export(str(image_path))

            self.log_status(f"Plot image saved to {image_path}")
            QMessageBox.information(
                self,
                "Save Successful",
                f"Plot image saved successfully:\n{image_path}"
            )

        except Exception as e:
            self.log_status(f"ERROR: Failed to save plot image - {e}")
            QMessageBox.critical(self, "Save Error", f"Failed to save plot image:\n{e}")
