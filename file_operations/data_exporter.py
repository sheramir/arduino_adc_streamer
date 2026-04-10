"""
Data Export Mixin
==================
Handles CSV and JSON data export with metadata.
"""

import csv
import json
from datetime import datetime
from pathlib import Path

import numpy as np
from PyQt6.QtWidgets import QMessageBox

from config_constants import IADC_RESOLUTION_BITS


class DataExporterMixin:
    """Mixin class for data export operations."""

    def _show_save_data_notice(self, label_text: str = "Saving data...") -> None:
        """Show a modal busy notice while data export is running."""
        from PyQt6.QtCore import QEventLoop, Qt
        from PyQt6.QtWidgets import QApplication, QProgressDialog

        dialog = getattr(self, "_save_data_progress_dialog", None)
        if dialog is None:
            dialog = QProgressDialog(label_text, None, 0, 0, self)
            dialog.setWindowTitle("Saving Data")
            dialog.setCancelButton(None)
            dialog.setWindowModality(Qt.WindowModality.WindowModal)
            dialog.setMinimumDuration(0)
            dialog.setAutoClose(False)
            dialog.setAutoReset(False)
            self._save_data_progress_dialog = dialog

        dialog.setLabelText(label_text)
        dialog.setRange(0, 0)
        dialog.setValue(0)
        dialog.show()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def _update_save_data_notice(self, label_text: str) -> None:
        """Refresh the export progress notice text if it is visible."""
        from PyQt6.QtCore import QEventLoop
        from PyQt6.QtWidgets import QApplication

        dialog = getattr(self, "_save_data_progress_dialog", None)
        if dialog is None:
            return

        dialog.setLabelText(label_text)
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def _hide_save_data_notice(self) -> None:
        """Hide the temporary export progress notice."""
        from PyQt6.QtCore import QEventLoop
        from PyQt6.QtWidgets import QApplication

        dialog = getattr(self, "_save_data_progress_dialog", None)
        if dialog is not None:
            dialog.hide()

        if QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def _has_exportable_sweeps(self, data) -> bool:
        try:
            return data is not None and len(data) > 0
        except Exception:
            return False

    def _load_export_source_data(self, archive_path: Path | None):
        if archive_path is not None and archive_path.exists() and hasattr(self, 'load_archive_data'):
            if hasattr(self, '_finalize_archive_if_active'):
                self._finalize_archive_if_active()
            sweeps, timestamps = self.load_archive_data()
            if self._has_exportable_sweeps(sweeps):
                return (
                    np.asarray(sweeps, dtype=np.float32),
                    np.asarray(timestamps, dtype=np.float64) if self._has_exportable_sweeps(timestamps) else None,
                    'archive',
                )

        if self._has_exportable_sweeps(getattr(self, 'raw_data', None)):
            timestamps = getattr(self, 'sweep_timestamps', None)
            timestamp_array = None
            if self._has_exportable_sweeps(timestamps):
                timestamp_array = np.asarray(timestamps, dtype=np.float64)
            return np.asarray(self.raw_data, dtype=np.float32), timestamp_array, 'full_view'

        if (
            getattr(self, 'raw_data_buffer', None) is None
            or getattr(self, 'sweep_timestamps_buffer', None) is None
            or getattr(self, 'samples_per_sweep', 0) <= 0
        ):
            return None, None, None

        with self.buffer_lock:
            current_sweep_count = int(getattr(self, 'sweep_count', 0))
            current_write_index = int(getattr(self, 'buffer_write_index', 0))
            actual_sweeps = min(current_sweep_count, int(getattr(self, 'MAX_SWEEPS_BUFFER', current_sweep_count)))

            if actual_sweeps <= 0:
                return None, None, None

            if actual_sweeps < self.MAX_SWEEPS_BUFFER:
                ordered_data = self.raw_data_buffer[:actual_sweeps].copy()
                ordered_timestamps = self.sweep_timestamps_buffer[:actual_sweeps].copy()
            else:
                write_pos = current_write_index % self.MAX_SWEEPS_BUFFER
                ordered_data = np.concatenate([
                    self.raw_data_buffer[write_pos:],
                    self.raw_data_buffer[:write_pos],
                ])
                ordered_timestamps = np.concatenate([
                    self.sweep_timestamps_buffer[write_pos:],
                    self.sweep_timestamps_buffer[:write_pos],
                ])

        return ordered_data.astype(np.float32, copy=False), ordered_timestamps.astype(np.float64, copy=False), 'buffer'
    
    def save_data(self):
        """Save captured data to CSV file with metadata."""
        archive_path = None
        try:
            if getattr(self, '_archive_path', None):
                candidate_path = Path(self._archive_path)
                if candidate_path.exists():
                    archive_path = candidate_path
        except Exception:
            archive_path = None

        notice_visible = False

        def hide_notice():
            nonlocal notice_visible
            if notice_visible:
                self._hide_save_data_notice()
                notice_visible = False

        self._show_save_data_notice("Preparing data export...")
        notice_visible = True

        try:
            source_sweeps, source_timestamps, export_source = self._load_export_source_data(archive_path)
            if not self._has_exportable_sweeps(source_sweeps):
                hide_notice()
                QMessageBox.warning(self, "No Data", "No data to save.")
                return

            total_sweeps = len(source_sweeps)
            sweep_range_text = "All"

            # Check if range is enabled (range refers to the global sweep index across archive+memory)
            save_min = 0
            save_max = total_sweeps  # exclusive
            if self.use_range_check.isChecked():
                min_sweep = self.min_sweep_spin.value()
                max_sweep = self.max_sweep_spin.value()

                # Validate range against total_sweeps
                if min_sweep >= max_sweep:
                    hide_notice()
                    QMessageBox.warning(
                        self,
                        "Invalid Range",
                        f"Min sweep ({min_sweep}) must be less than max sweep ({max_sweep})."
                    )
                    return

                if min_sweep < 0 or min_sweep >= total_sweeps:
                    hide_notice()
                    QMessageBox.warning(
                        self,
                        "Invalid Range",
                        f"Min sweep ({min_sweep}) is out of bounds. Valid range: 0 to {total_sweeps - 1}."
                    )
                    return

                if max_sweep <= 0 or max_sweep > total_sweeps:
                    hide_notice()
                    QMessageBox.warning(
                        self,
                        "Invalid Range",
                        f"Max sweep ({max_sweep}) is out of bounds. Valid range: 1 to {total_sweeps}."
                    )
                    return

                save_min = min_sweep
                save_max = max_sweep
                sweep_range_text = f"{save_min} to {save_max - 1}"
                self.log_status(f"Saving sweep range: {sweep_range_text} (global indices)")

            # Prepare file paths
            directory = Path(self.dir_input.text())
            filename = self.filename_input.text()
            # Use minute-resolution filenames (no seconds)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M")

            csv_path = directory / f"{filename}_{timestamp}.csv"
            metadata_path = directory / f"{filename}_{timestamp}_metadata.json"

            is_555_mode = (getattr(self, 'device_mode', 'adc') == '555') or ('555' in (self.current_mcu or ''))
            repeat_count = max(1, int(self.config.get('repeat', 1)))
            if self.is_array_pzt1_mode():
                header = []
                for channel in self.config['channels']:
                    for _ in range(repeat_count):
                        header.extend([f"M1_Ch{channel}", f"M2_Ch{channel}"])
            else:
                header = [f"CH{ch}" for ch in self.config['channels']] * repeat_count

            # Determine if we have force data
            has_force_x = any(d[1] != 0 for d in self.force_data) if self.force_data else False
            has_force_z = any(d[2] != 0 for d in self.force_data) if self.force_data else False
            
            # Create a mapping of ADC timestamps to force data
            force_dict = {}
            if self.force_data:
                for timestamp, x_force, z_force in self.force_data:
                    force_dict[timestamp] = (x_force, z_force)

            selected_sweeps = np.asarray(source_sweeps[save_min:save_max], dtype=np.float32).copy()
            selected_timestamps = None
            if source_timestamps is not None and len(source_timestamps) >= save_max:
                selected_timestamps = np.asarray(source_timestamps[save_min:save_max], dtype=np.float64).copy()

            applied_filter_to_csv = False
            if hasattr(self, 'should_filter_adc_data') and self.should_filter_adc_data():
                if not is_555_mode and hasattr(self, 'filter_dataset_copy'):
                    self._update_save_data_notice("Applying ADC filter for export...")
                    selected_sweeps = self.filter_dataset_copy(
                        selected_sweeps,
                        sweep_timestamps_sec=selected_timestamps,
                    )
                    applied_filter_to_csv = True
                elif is_555_mode:
                    applied_filter_to_csv = False

            first_sweep_len = int(selected_sweeps.shape[1]) if selected_sweeps.ndim == 2 and len(selected_sweeps) > 0 else 0
            saved_total = int(len(selected_sweeps))

            # Save CSV data with force columns from the selected ordered dataset.
            self._update_save_data_notice("Writing CSV data...")
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:

                writer = csv.writer(f)

                # Write header
                if is_555_mode:
                    header.insert(0, "Timestamp_s")
                header.extend(["Force_X", "Force_Z"])
                writer.writerow(header)

                # Determine how many sweeps will be saved (respecting range selection)
                saved_index = 0  # index among saved sweeps (0..saved_total-1)

                # Precompute capture duration for approximate timestamp mapping
                capture_duration = None
                if self.timing_state.capture_start_time and self.timing_state.capture_end_time:
                    capture_duration = self.timing_state.capture_end_time - self.timing_state.capture_start_time

                # Approximate row timestamp in seconds from capture start (fallback only)
                def get_row_timestamp(saved_idx):
                    if capture_duration is None or saved_total <= 1:
                        return None
                    # Spread timestamps across the measured capture duration
                    return (saved_idx / (saved_total - 1)) * capture_duration

                # Helper to find closest force sample given the sweep timestamp (seconds)
                def get_closest_force(sweep_time_s):
                    if not force_dict or sweep_time_s is None:
                        return (0.0, 0.0)
                    closest_force = (0.0, 0.0)
                    min_diff = float('inf')
                    for f_time, (x, z) in force_dict.items():
                        diff = abs(f_time - sweep_time_s)
                        if diff < min_diff:
                            min_diff = diff
                            closest_force = (x, z)
                    return closest_force

                def resolve_sweep_time(saved_idx):
                    if selected_timestamps is not None and saved_idx < len(selected_timestamps):
                        try:
                            return float(selected_timestamps[saved_idx])
                        except Exception:
                            pass
                    return get_row_timestamp(saved_idx)

                for saved_index, sweep in enumerate(selected_sweeps):
                    row_time = resolve_sweep_time(saved_index)
                    row = np.asarray(sweep).tolist()
                    if is_555_mode:
                        timestamp_to_write = row_time if row_time is not None else 0.0
                        row.insert(0, float(timestamp_to_write))
                    row.extend(list(get_closest_force(row_time)))
                    writer.writerow(row)

                saved_index = saved_total

            # Prepare metadata dictionary
            capture_duration_s = None
            if self.timing_state.capture_start_time and self.timing_state.capture_end_time:
                capture_duration_s = self.timing_state.capture_end_time - self.timing_state.capture_start_time
            
            metadata = {
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "mcu_type": self.current_mcu if self.current_mcu else "Unknown",
                "total_captured_sweeps": self.sweep_count,
                "saved_sweeps": saved_index,
                "sweep_range": sweep_range_text,
                "total_samples": saved_index * (first_sweep_len if first_sweep_len else 0),
                "capture_duration_seconds": capture_duration_s,
                "configuration": {
                    "channels": self.config['channels'],
                    "repeat_count": self.config['repeat'],
                    "ground_pin": self.config['ground_pin'],
                    "use_ground_sample": self.config['use_ground'],
                    "adc_resolution_bits": IADC_RESOLUTION_BITS,
                    "voltage_reference": self.config['reference'],
                    "osr": self.config['osr'],
                    "gain": self.config['gain'],
                    "buffer_sweeps_per_block": self.buffer_spin.value(),
                    "buffer_total_samples": self.buffer_spin.value() * self.get_effective_samples_per_sweep()
                },
                "block_timing_csv": self._block_timing_path,
                "timing": {
                    "per_channel_rate_hz": self.timing_state.timing_data.get('per_channel_rate_hz'),
                    "total_rate_hz": self.timing_state.timing_data.get('total_rate_hz'),
                    "arduino_sample_time_us": self.timing_state.timing_data.get('arduino_sample_time_us'),
                    "arduino_sample_rate_hz": self.timing_state.timing_data.get('arduino_sample_rate_hz'),
                    "buffer_gap_time_ms": self.timing_state.timing_data.get('buffer_gap_time_ms')
                },
                "force_data": {
                    "available": len(self.force_data) > 0,
                    "x_force_available": has_force_x,
                    "z_force_available": has_force_z,
                    "total_force_samples": len(self.force_data),
                    "calibration_offset_x": self.force_calibration_offset['x'],
                    "calibration_offset_z": self.force_calibration_offset['z'],
                    "note": "Force data not available" if not self.force_data else "Force data synchronized with ADC samples (calibrated to zero at connection)"
                },
                "row_timestamp": {
                    "included_in_csv": bool(is_555_mode),
                    "column_name": "Timestamp_s" if is_555_mode else None,
                    "source": "selected_sweep_timestamps_with_linear_fallback" if selected_timestamps is not None else "capture_duration_linear_fallback"
                },
                "export_source": export_source,
            }

            if hasattr(self, 'build_filter_metadata'):
                metadata["filtering"] = self.build_filter_metadata(
                    applied=applied_filter_to_csv,
                    sweep_timestamps_sec=selected_timestamps,
                )
                metadata["filtering"]["applied_to_csv"] = bool(applied_filter_to_csv)

            # Add user notes if provided
            notes = self.notes_input.toPlainText().strip()
            if notes:
                metadata["notes"] = notes

            # Save metadata as JSON
            self._update_save_data_notice("Writing metadata...")
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)

            self.log_status(f"Data saved to {csv_path}")
            self.log_status(f"Metadata saved to {metadata_path}")

            hide_notice()
            QMessageBox.information(
                self,
                "Save Successful",
                f"Data saved successfully:\n{csv_path}\n{metadata_path}\n\nSweeps saved: {saved_index}"
            )

        except Exception as e:
            self.log_status(f"ERROR: Failed to save data - {e}")
            hide_notice()
            QMessageBox.critical(self, "Save Error", f"Failed to save data:\n{e}")
        finally:
            hide_notice()
