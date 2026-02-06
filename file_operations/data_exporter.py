"""
Data Export Mixin
==================
Handles CSV and JSON data export with metadata.
"""

import csv
import json
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import QMessageBox

from config_constants import IADC_RESOLUTION_BITS


class DataExporterMixin:
    """Mixin class for data export operations."""
    
    def save_data(self):
        """Save captured data to CSV file with metadata."""
        # Determine archive info (if an archive file exists for this capture)
        archived_count = 0
        archive_path = None
        try:
            if getattr(self, '_archive_path', None):
                archive_path = Path(self._archive_path)
                if archive_path.exists():
                    # Count archived sweeps (exclude metadata first line)
                    with archive_path.open('r', encoding='utf-8') as af:
                        # Read and discard metadata
                        first = af.readline()
                        for _ in af:
                            archived_count += 1
        except Exception:
            archived_count = 0

        has_archive_data = archived_count > 0 and archive_path is not None
        if not has_archive_data and not self.raw_data:
            QMessageBox.warning(self, "No Data", "No data to save.")
            return

        # Total sweeps available for saving
        total_sweeps = archived_count if has_archive_data else len(self.raw_data)
        sweep_range_text = "All"

        # Check if range is enabled (range refers to the global sweep index across archive+memory)
        save_min = 0
        save_max = total_sweeps  # exclusive
        if self.use_range_check.isChecked():
            min_sweep = self.min_sweep_spin.value()
            max_sweep = self.max_sweep_spin.value()

            # Validate range against total_sweeps
            if min_sweep >= max_sweep:
                QMessageBox.warning(
                    self,
                    "Invalid Range",
                    f"Min sweep ({min_sweep}) must be less than max sweep ({max_sweep})."
                )
                return

            if min_sweep < 0 or min_sweep >= total_sweeps:
                QMessageBox.warning(
                    self,
                    "Invalid Range",
                    f"Min sweep ({min_sweep}) is out of bounds. Valid range: 0 to {total_sweeps - 1}."
                )
                return

            if max_sweep <= 0 or max_sweep > total_sweeps:
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

        try:
            # Determine if we have force data
            has_force_x = any(d[1] != 0 for d in self.force_data) if self.force_data else False
            has_force_z = any(d[2] != 0 for d in self.force_data) if self.force_data else False
            
            # Create a mapping of ADC timestamps to force data
            force_dict = {}
            if self.force_data:
                for timestamp, x_force, z_force in self.force_data:
                    force_dict[timestamp] = (x_force, z_force)

            # Save CSV data with force columns. We'll stream archive (if present) + in-memory data
            with open(csv_path, 'w', newline='') as f:

                writer = csv.writer(f)

                # Write header
                header = [f"CH{ch}" for ch in self.config['channels']] * self.config['repeat']
                header.extend(["Force_X", "Force_Z"])
                writer.writerow(header)

                # Determine how many sweeps will be saved (respecting range selection)
                saved_total = max(0, save_max - save_min)
                saved_index = 0  # index among saved sweeps (0..saved_total-1)
                global_idx = 0  # index across archive + in-memory
                first_sweep_len = None

                # Precompute capture duration for approximate timestamp mapping
                capture_duration = None
                if self.capture_start_time and self.capture_end_time:
                    capture_duration = self.capture_end_time - self.capture_start_time

                # Helper to find closest force sample given a normalized saved_index
                def get_closest_force(saved_idx):
                    if not force_dict or capture_duration is None or saved_total <= 0:
                        return (0.0, 0.0)
                    sweep_time = (saved_idx / saved_total) * capture_duration
                    closest_force = (0.0, 0.0)
                    min_diff = float('inf')
                    for f_time, (x, z) in force_dict.items():
                        diff = abs(f_time - sweep_time)
                        if diff < min_diff:
                            min_diff = diff
                            closest_force = (x, z)
                    return closest_force

                # Stream archived sweeps only if present; otherwise use in-memory sweeps
                if has_archive_data:
                    with archive_path.open('r', encoding='utf-8') as af:
                        # skip metadata line
                        af.readline()
                        for line in af:
                            if global_idx >= save_max:
                                break
                            if global_idx >= save_min:
                                try:
                                    sweep = json.loads(line)
                                except Exception:
                                    global_idx += 1
                                    continue

                                if first_sweep_len is None:
                                    first_sweep_len = len(sweep)

                                row = list(sweep)
                                row.extend(list(get_closest_force(saved_index)))
                                writer.writerow(row)
                                saved_index += 1
                            global_idx += 1
                else:
                    # Stream in-memory sweeps (preserve order)
                    for sweep in self.raw_data:
                        if global_idx >= save_max:
                            break
                        if global_idx >= save_min:
                            if first_sweep_len is None:
                                first_sweep_len = len(sweep)

                            row = list(sweep)
                            row.extend(list(get_closest_force(saved_index)))
                            writer.writerow(row)
                            saved_index += 1
                        global_idx += 1

            # Prepare metadata dictionary
            capture_duration_s = None
            if self.capture_start_time and self.capture_end_time:
                capture_duration_s = self.capture_end_time - self.capture_start_time
            
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
                    "buffer_total_samples": self.buffer_spin.value() * len(self.config['channels']) * self.config['repeat']
                },
                "block_timing_csv": self._block_timing_path,
                "timing": {
                    "per_channel_rate_hz": self.timing_data.get('per_channel_rate_hz'),
                    "total_rate_hz": self.timing_data.get('total_rate_hz'),
                    "arduino_sample_time_us": self.timing_data.get('arduino_sample_time_us'),
                    "arduino_sample_rate_hz": self.timing_data.get('arduino_sample_rate_hz'),
                    "buffer_gap_time_ms": self.timing_data.get('buffer_gap_time_ms')
                },
                "force_data": {
                    "available": len(self.force_data) > 0,
                    "x_force_available": has_force_x,
                    "z_force_available": has_force_z,
                    "total_force_samples": len(self.force_data),
                    "calibration_offset_x": self.force_calibration_offset['x'],
                    "calibration_offset_z": self.force_calibration_offset['z'],
                    "note": "Force data not available" if not self.force_data else "Force data synchronized with ADC samples (calibrated to zero at connection)"
                }
            }

            # Add user notes if provided
            notes = self.notes_input.toPlainText().strip()
            if notes:
                metadata["notes"] = notes

            # Save metadata as JSON
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)

            self.log_status(f"Data saved to {csv_path}")
            self.log_status(f"Metadata saved to {metadata_path}")

            QMessageBox.information(
                self,
                "Save Successful",
                f"Data saved successfully:\n{csv_path}\n{metadata_path}\n\nSweeps saved: {saved_index}"
            )

        except Exception as e:
            self.log_status(f"ERROR: Failed to save data - {e}")
            QMessageBox.critical(self, "Save Error", f"Failed to save data:\n{e}")
