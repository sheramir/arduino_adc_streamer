"""
File Operations Mixin
======================
Main mixin combining all file I/O operations.

This module combines:
- Data export (DataExporterMixin) - CSV/JSON export
- Plot export (PlotExporterMixin) - Image export
- Archive loading (ArchiveLoaderMixin) - Archive viewing
- Directory selection (defined here)
"""

from pathlib import Path
from PyQt6.QtWidgets import QFileDialog

from file_operations.data_exporter import DataExporterMixin
from file_operations.plot_exporter import PlotExporterMixin
from file_operations.archive_loader import ArchiveLoaderMixin


class FileOperationsMixin(DataExporterMixin, PlotExporterMixin, ArchiveLoaderMixin):
    """Main mixin class combining all file operations."""
    
    def browse_directory(self):
        """Browse for output directory."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Output Directory",
            self.dir_input.text()
        )
        if directory:
            self.dir_input.setText(directory)
