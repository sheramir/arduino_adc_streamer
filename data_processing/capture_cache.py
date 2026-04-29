"""
Capture Cache Mixin
===================
Owns clear-data behavior and cache file cleanup/teardown.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox


class CaptureCacheMixin:
    """Clear-data flow and capture cache cleanup helpers."""

    def clear_data(self):
        """Clear all captured data and completely reset plot to initial state."""
        if self.is_capturing:
            QMessageBox.warning(self, "Cannot Clear", "Cannot clear data during capture. Please stop capture first.")
            return

        reply = QMessageBox.question(
            self,
            "Clear Data",
            "Are you sure you want to clear all captured data?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.drain_serial_input(0.05)

            self._reset_capture_buffer_state(reset_samples_per_sweep=True)
            self._reset_force_capture_state()
            self._reset_timing_measurements(log_timestamp_clear=True, reset_labels=True)
            self._reset_signal_processing_state(reset_shear=True)
            self._reset_full_view_state(button_enabled=False, trigger_plot_update=False)

            for curve in self._adc_curves.values():
                self.plot_widget.removeItem(curve)
            self._adc_curves.clear()

            if self._force_x_curve is not None:
                self.force_viewbox.removeItem(self._force_x_curve)
                self._force_x_curve = None
            if self._force_z_curve is not None:
                self.force_viewbox.removeItem(self._force_z_curve)
                self._force_z_curve = None

            self.plot_widget.removeItem(self.adc_legend)
            self.adc_legend = self.plot_widget.addLegend(offset=(10, 10))

            self.plot_widget.setXRange(0, 1, padding=0)
            self.plot_widget.setYRange(0, 1, padding=0)
            self.force_viewbox.setXRange(0, 1, padding=0)
            self.force_viewbox.setYRange(0, 1, padding=0)

            self.plot_widget.enableAutoRange()
            self.force_viewbox.enableAutoRange()

            self.plot_widget.setLabel('left', 'ADC Value', units='counts')
            self.plot_widget.setLabel('bottom', 'Time', units='s')
            self.plot_widget.setLabel('right', 'Force', units='N')

            self.update_plot_info_label(
                sweep_count=0,
                total_samples=0,
                force_samples=0,
                elapsed_clock_s=0.0,
            )
            self.log_status("Data cleared - plot reset to initial state")
            self.cleanup_capture_cache(block=False)

    def _delete_capture_cache_files(self, archive_path, block_timing_path, cache_dir_path):
        """Delete cache files and remove the cache directory when empty."""
        removed_files = 0
        for cache_path in [archive_path, block_timing_path]:
            if not cache_path:
                continue
            try:
                path_obj = Path(cache_path)
                if path_obj.exists() and path_obj.is_file():
                    path_obj.unlink()
                    removed_files += 1
            except Exception as e:
                self.log_status(f"WARNING: Failed to remove cache file {cache_path}: {e}")

        if cache_dir_path:
            try:
                cache_dir = Path(cache_dir_path)
                if cache_dir.exists() and cache_dir.is_dir() and not any(cache_dir.iterdir()):
                    cache_dir.rmdir()
            except Exception as e:
                self.log_status(f"WARNING: Failed to remove cache directory {cache_dir_path}: {e}")

        if removed_files > 0:
            self.log_status(f"Cache cleaned: removed {removed_files} file(s)")

    def _defer_capture_cache_cleanup(self, writer, archive_path, block_timing_path, cache_dir_path, attempts_left=100):
        """Poll for writer shutdown, then remove cache files without blocking the UI."""
        if writer is not None and writer.is_alive() and attempts_left > 0:
            QTimer.singleShot(
                100,
                lambda: self._defer_capture_cache_cleanup(
                    writer, archive_path, block_timing_path, cache_dir_path, attempts_left - 1
                ),
            )
            return

        if writer is not None and hasattr(writer, "get_status_snapshot"):
            snapshot = writer.get_status_snapshot()
            if snapshot.get("state") == "failed":
                error_text = snapshot.get("last_error") or "unknown archive writer failure"
                self.log_status(f"WARNING: Archive writer failed before cache cleanup: {error_text}")

        self._delete_capture_cache_files(archive_path, block_timing_path, cache_dir_path)

    def _close_capture_cache_handles(self, *, block=True):
        """Close open cache file handles, optionally waiting for the archive writer."""
        writer = getattr(self, '_archive_writer', None)
        try:
            if writer is not None:
                if block:
                    final_snapshot = writer.stop()
                    if final_snapshot.get("state") == "failed":
                        error_text = final_snapshot.get("last_error") or "unknown archive writer failure"
                        self.log_status(f"WARNING: Archive writer failed during close: {error_text}")
                else:
                    snapshot = writer.stop_nowait()
                    if snapshot.get("state") == "failed":
                        error_text = snapshot.get("last_error") or "unknown archive writer failure"
                        self.log_status(f"WARNING: Archive writer failed before background close: {error_text}")
        finally:
            self._archive_writer = None

        try:
            if self._block_timing_file:
                try:
                    self._block_timing_file.flush()
                except Exception:
                    pass
                try:
                    self._block_timing_file.close()
                except Exception:
                    pass
        finally:
            self._block_timing_file = None

        return writer

    def cleanup_capture_cache(self, *, block=True):
        """Delete capture cache files and remove empty cache directory."""
        archive_path = getattr(self, '_archive_path', None)
        block_timing_path = getattr(self, '_block_timing_path', None)
        cache_dir_path = getattr(self, '_cache_dir_path', None)
        writer = self._close_capture_cache_handles(block=block)

        self._archive_path = None
        self._block_timing_path = None
        self._cache_dir_path = None
        self._archive_write_count = 0
        self._block_timing_write_count = 0

        if not block and writer is not None and writer.is_alive():
            self._defer_capture_cache_cleanup(writer, archive_path, block_timing_path, cache_dir_path)
            return

        self._delete_capture_cache_files(archive_path, block_timing_path, cache_dir_path)
