"""
Archive Loader Mixin
====================
Handles loading and viewing archived data.
"""

import csv
import json
from pathlib import Path

from PyQt6.QtWidgets import QApplication


class ArchiveLoaderMixin:
    """Mixin class for archive loading operations."""
    
    def load_archive_data(self):
        """Load all sweep data from archive file for full view.
        Returns (sweeps_list, timestamps_list) or (None, None) on error.
        """
        if not self._archive_path or not Path(self._archive_path).exists():
            return None, None
        
        try:
            self.log_status("Loading full data from archive...")
            sweeps = []
            timestamps = []
            
            with open(self._archive_path, 'r', encoding='utf-8') as f:
                # First line is metadata - skip it
                first_line = f.readline()
                if first_line.strip():
                    try:
                        metadata = json.loads(first_line)
                        # Could extract useful info from metadata if needed
                    except json.JSONDecodeError:
                        pass
                
                # Read all sweep lines
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            sweep_data = json.loads(line)
                            sweeps.append(sweep_data)
                        except json.JSONDecodeError:
                            continue
            
            # Reconstruct timestamps from sweeps using the CSV timing sidecar
            if self._block_timing_path and Path(self._block_timing_path).exists():
                try:
                    with open(self._block_timing_path, 'r', encoding='utf-8', newline='') as f:
                        reader = csv.reader(f)
                        header = next(reader, None)  # Skip header row

                        # The CSV columns are: sample_count, samples_per_sweep, sweeps_in_block,
                        # avg_dt_us, block_start_us, block_end_us, mcu_gap_us
                        for row in reader:
                            if len(row) < 6:
                                continue

                            try:
                                samples_per_sweep = int(row[1])
                                sweeps_in_block = int(row[2])
                                avg_dt_us = float(row[3])
                                block_start_us = int(row[4])
                            except (ValueError, TypeError):
                                continue

                            # Initialize reference if missing
                            if not hasattr(self, 'first_sweep_timestamp_us'):
                                self.first_sweep_timestamp_us = block_start_us

                            base_us = self.first_sweep_timestamp_us

                            # Build timestamps for each sweep in this block
                            for i in range(sweeps_in_block):
                                ts_us = block_start_us + (i * samples_per_sweep * avg_dt_us)
                                ts_sec = (ts_us - base_us) / 1e6
                                timestamps.append(ts_sec)
                except Exception:
                    # Fall back to legacy behavior if parsing fails
                    pass
            
            # Fallback: if no timing data or insufficient timestamps, use uniform spacing
            if len(timestamps) < len(sweeps):
                if self.sweep_timestamps:
                    # Use last known sample rate
                    avg_dt = (self.sweep_timestamps[-1] - self.sweep_timestamps[0]) / max(1, len(self.sweep_timestamps) - 1)
                    last_t = self.sweep_timestamps[-1] if self.sweep_timestamps else 0
                    for i in range(len(timestamps), len(sweeps)):
                        timestamps.append(last_t + (i - len(self.sweep_timestamps) + 1) * avg_dt)
                else:
                    # Just use indices
                    timestamps = list(range(len(sweeps)))
            
            self.log_status(f"Loaded {len(sweeps)} sweeps from archive")
            return sweeps, timestamps
            
        except Exception as e:
            self.log_status(f"ERROR: Failed to load archive: {e}")
            return None, None
    
    def full_graph_view(self):
        """Show full data view by loading ALL data from archive file."""
        if self.is_capturing:
            self.log_status("Cannot activate full view during capture")
            return
        
        if not self._archive_path:
            self.log_status("No archive file available for full view")
            return
        
        # Load all data from archive
        self.log_status("Activating full view - loading from archive...")
        QApplication.processEvents()  # Update UI
        
        all_sweeps, all_timestamps = self.load_archive_data()
        if all_sweeps is None:
            self.log_status("Failed to load archive data")
            return
        
        # Temporarily store current data
        backup_raw_data = self.raw_data
        backup_timestamps = self.sweep_timestamps
        
        # Replace with full archive data
        self.raw_data = all_sweeps
        self.sweep_timestamps = all_timestamps
        
        # Mark that we're in full view mode
        self.is_full_view = True
        self.full_view_btn.setEnabled(False)
        
        # Update plots
        self.update_plot()
        self.update_force_plot()
        
        # Update info label
        total_samples = sum(len(sweep) for sweep in self.raw_data)
        force_samples = len(self.force_data)
        time_range = self.sweep_timestamps[-1] - self.sweep_timestamps[0] if len(self.sweep_timestamps) > 1 else 0
        
        self.plot_info_label.setText(
            f"ADC - Sweeps: {len(self.raw_data)} (FULL VIEW) | Samples: {total_samples} | Time: {time_range:.2f}s  |  Force: {force_samples} samples"
        )
        
        self.log_status(f"Full view active: {len(self.raw_data)} sweeps, {time_range:.2f}s")
