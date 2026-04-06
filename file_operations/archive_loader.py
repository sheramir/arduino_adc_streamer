"""
Archive Loader Mixin
====================
Handles loading and viewing archived data.
"""

import csv
import json
from pathlib import Path


class ArchiveLoaderMixin:
    """Mixin class for archive loading operations."""

    def _capture_exceeds_memory_buffer(self) -> bool:
        """Return True when the capture has overflowed the in-memory ring buffer."""
        try:
            with self.buffer_lock:
                return int(self.sweep_count) > int(self.MAX_SWEEPS_BUFFER)
        except Exception:
            return False

    def _finalize_archive_if_active(self) -> None:
        """Block until the background archive writer has fully drained and closed."""
        writer = getattr(self, '_archive_writer', None)
        if writer is None:
            return

        try:
            if writer.is_alive():
                self.log_status("Waiting for archive save to finish before loading full view...")
            writer.stop()
        except Exception as e:
            self.log_status(f"WARNING: Failed to finalize archive writer cleanly: {e}")
        finally:
            self._archive_writer = None
    
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
            archive_timestamps = []  # timestamps embedded per sweep (new-format archives)
            
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

                            # New format: {"timestamp_s": float, "samples": [...]}
                            if isinstance(sweep_data, dict) and 'samples' in sweep_data:
                                sweeps.append(sweep_data.get('samples', []))
                                ts_val = sweep_data.get('timestamp_s')
                                archive_timestamps.append(ts_val if isinstance(ts_val, (int, float)) else None)

                            # Legacy format: raw list of samples per sweep
                            elif isinstance(sweep_data, list):
                                sweeps.append(sweep_data)
                                archive_timestamps.append(None)

                            # Unknown format: skip
                            else:
                                archive_timestamps.append(None)
                                continue
                        except json.JSONDecodeError:
                            continue
            
            # Prefer per-sweep timestamps embedded in archive (if present for all sweeps)
            if len(archive_timestamps) == len(sweeps) and all(ts is not None for ts in archive_timestamps):
                timestamps = [float(ts) for ts in archive_timestamps]

            # Otherwise reconstruct timestamps from the CSV timing sidecar
            elif self._block_timing_path and Path(self._block_timing_path).exists():
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
        """Show the complete Start->Stop capture window in full view.

        Short captures are loaded directly from the in-memory circular buffer for
        responsiveness. When the capture exceeds the ring-buffer capacity, full
        view falls back to the persisted archive so older sweeps that have already
        rolled out of memory are still included.
        """
        import numpy as np

        if self.is_capturing:
            self.log_status("Cannot activate full view during capture")
            return

        if self._capture_exceeds_memory_buffer():
            self._finalize_archive_if_active()
            sweeps, timestamps = self.load_archive_data()
            if not sweeps or not timestamps:
                self.log_status("WARNING: Full archive unavailable; falling back to buffered data only")
            else:
                self.raw_data = np.asarray(sweeps, dtype=np.float32)
                self.sweep_timestamps = np.asarray(timestamps, dtype=np.float64)
                actual_sweeps = len(self.raw_data)
                self.is_full_view = True
                self.full_view_btn.setEnabled(False)

                self.update_plot()
                self.update_force_plot()

                total_samples = actual_sweeps * self.raw_data.shape[1] if self.raw_data.ndim == 2 else actual_sweeps
                force_samples = len(self.force_data)
                time_range = float(self.sweep_timestamps[-1] - self.sweep_timestamps[0]) if len(self.sweep_timestamps) > 1 else 0.0

                self.plot_info_label.setText(
                    f"ADC - Sweeps: {actual_sweeps} (FULL VIEW) | Samples: {total_samples} | "
                    f"Time: {time_range:.2f}s  |  Force: {force_samples} samples"
                )
                self.log_status(f"Full view active from archive: {actual_sweeps} sweeps, {time_range:.2f}s")
                return

        active_buffer = self.get_active_data_buffer()
        if active_buffer is None:
            self.log_status("No data buffer available for full view")
            return

        with self.buffer_lock:
            current_sweep_count = self.sweep_count
            write_pos = self.buffer_write_index  # already wrapped to [0, MAX_SWEEPS_BUFFER)
            actual_sweeps = min(current_sweep_count, self.MAX_SWEEPS_BUFFER)

            if actual_sweeps == 0:
                self.log_status("No captured data to display in full view")
                return

            # Re-order the circular buffer so index 0 is the oldest sweep.
            if actual_sweeps < self.MAX_SWEEPS_BUFFER:
                # Buffer has not wrapped: valid data lives in [0, actual_sweeps).
                ordered_data = active_buffer[:actual_sweeps].copy()
                ordered_timestamps = self.sweep_timestamps_buffer[:actual_sweeps].copy()
            else:
                # Buffer has wrapped: oldest starts at write_pos.
                ordered_data = np.concatenate(
                    [active_buffer[write_pos:], active_buffer[:write_pos]]
                )
                ordered_timestamps = np.concatenate(
                    [self.sweep_timestamps_buffer[write_pos:],
                     self.sweep_timestamps_buffer[:write_pos]]
                )

        # Store as numpy arrays; update_plot's full-view branch handles these via
        # np.asarray (zero-copy when dtype already matches).
        self.raw_data = ordered_data          # shape: (actual_sweeps, samples_per_sweep)
        self.sweep_timestamps = ordered_timestamps  # shape: (actual_sweeps,)

        self.is_full_view = True
        self.full_view_btn.setEnabled(False)

        self.update_plot()
        self.update_force_plot()

        # Update info label
        total_samples = actual_sweeps * ordered_data.shape[1] if ordered_data.ndim == 2 else actual_sweeps
        force_samples = len(self.force_data)
        time_range = float(ordered_timestamps[-1] - ordered_timestamps[0]) if len(ordered_timestamps) > 1 else 0.0

        self.plot_info_label.setText(
            f"ADC - Sweeps: {actual_sweeps} (FULL VIEW) | Samples: {total_samples} | "
            f"Time: {time_range:.2f}s  |  Force: {force_samples} samples"
        )
        self.log_status(f"Full view active: {actual_sweeps} sweeps, {time_range:.2f}s")
