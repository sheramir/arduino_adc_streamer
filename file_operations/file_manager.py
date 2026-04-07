"""
File Operations Mixin
======================
Main mixin combining all file I/O operations.

This module combines:
- Data export (DataExporterMixin) - CSV/JSON export
- Plot export (PlotExporterMixin) - Image export
- Archive loading (ArchiveLoaderMixin) - Archive viewing
"""

from file_operations.data_exporter import DataExporterMixin
from file_operations.plot_exporter import PlotExporterMixin
from file_operations.archive_loader import ArchiveLoaderMixin


class FileOperationsMixin(DataExporterMixin, PlotExporterMixin, ArchiveLoaderMixin):
    """Compatibility wrapper combining the file-operation mixins."""
