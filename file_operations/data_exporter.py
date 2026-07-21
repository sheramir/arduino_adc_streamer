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

from constants.plotting import IADC_RESOLUTION_BITS
from constants.pzt_rs import get_pzt_rs_ohms_per_wire_unit
from data_processing.force_state import get_force_runtime_state
from file_operations.force_export_alignment import (
    build_export_row_timestamps,
    build_force_export_series,
    format_export_clock_time,
    get_nearest_force_values,
    resolve_export_start_datetime,
)
from file_operations.export_metadata import build_vmid_noise_metadata


class DataExporterMixin:
    """Mixin class for data export operations."""

    @staticmethod
    def _round_timing_value(value):
        """Return a JSON-safe timing value rounded to at most three decimals."""
        if value is None:
            return None
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return None
        if not np.isfinite(numeric_value):
            return None
        return round(numeric_value, 3)

    def _build_capture_timing_metadata(self, signal_header):
        """Build non-duplicated, capture-wide ADC timing metadata.

        Active acquisition time comes from MCU block timestamps. Effective rates include
        the MCU-measured gaps between acquisition blocks, which makes them representative
        of the data stream over the whole capture rather than a single recent block.
        """
        timing = self.timing_state
        active_duration_us = int(getattr(timing, "adc_active_capture_duration_us", 0) or 0)
        emitted_sample_count = int(getattr(timing, "adc_emitted_sample_count", 0) or 0)
        block_count = int(getattr(timing, "adc_block_count", 0) or 0)
        gap_total_us = int(getattr(timing, "adc_block_gap_total_us", 0) or 0)
        gap_count = int(getattr(timing, "adc_block_gap_count", 0) or 0)

        active_sample_interval_us = None
        effective_total_rate_hz = None
        if active_duration_us > 0 and emitted_sample_count > 0:
            active_sample_interval_us = active_duration_us / emitted_sample_count
            total_capture_span_us = active_duration_us + gap_total_us
            if total_capture_span_us > 0:
                effective_total_rate_hz = (emitted_sample_count * 1_000_000.0) / total_capture_span_us

        per_channel_rates = {}
        samples_per_sweep = 0
        try:
            samples_per_sweep = int(self.get_effective_samples_per_sweep())
        except (AttributeError, TypeError, ValueError):
            samples_per_sweep = 0

        if effective_total_rate_hz is not None and samples_per_sweep > 0:
            try:
                display_specs = self.get_display_channel_specs()
            except (AttributeError, TypeError):
                display_specs = []
            for spec in display_specs or []:
                label = str(spec.get("label", "")).strip()
                sample_indices = spec.get("sample_indices", [])
                if not label or not sample_indices:
                    continue
                per_channel_rates[label] = self._round_timing_value(
                    effective_total_rate_hz * (len(sample_indices) / samples_per_sweep)
                )

        # A normal export has display specs, but retain useful rate metadata for a
        # minimal/legacy export harness where only signal names are available.
        if not per_channel_rates and effective_total_rate_hz is not None and signal_header:
            fallback_rate = effective_total_rate_hz / len(signal_header)
            per_channel_rates = {
                str(label): self._round_timing_value(fallback_rate)
                for label in signal_header
            }

        ground_sample_enabled = bool(self.config.get("use_ground", False))
        return {
            "adc_active_sample_interval_us": self._round_timing_value(active_sample_interval_us),
            "adc_mean_block_capture_time_us": self._round_timing_value(
                active_duration_us / block_count if block_count > 0 else None
            ),
            "adc_effective_total_sample_rate_hz": self._round_timing_value(effective_total_rate_hz),
            "per_channel_sample_rates_hz": per_channel_rates,
            "adc_mean_block_gap_ms": self._round_timing_value(
                (gap_total_us / gap_count) / 1_000.0 if gap_count > 0 else None
            ),
            "ground_sample_enabled": ground_sample_enabled,
            "adc_timing_includes_ground_samples": ground_sample_enabled,
            "ground_sample_timing_note": (
                "Active ADC timing includes ground reads and their channel-switching overhead; "
                "ground readings are not exported as signal samples."
                if ground_sample_enabled
                else "Ground sampling was disabled, so no ground-read time is included."
            ),
            "timing_source": "Capture-wide MCU block timestamps",
        }

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

    def _choose_best_export_source(self, candidates):
        """Pick the fullest available export source, preferring complete data."""
        valid_candidates = [candidate for candidate in candidates if self._has_exportable_sweeps(candidate[0])]
        if not valid_candidates:
            return None, None, None

        source_sweeps, source_timestamps, export_source = max(
            valid_candidates,
            key=lambda candidate: int(len(candidate[0])),
        )

        if len(valid_candidates) > 1:
            candidate_lengths = {
                candidate[2]: int(len(candidate[0]))
                for candidate in valid_candidates
            }
            max_length = int(len(source_sweeps))
            shorter_sources = [
                f"{name}={length}"
                for name, length in candidate_lengths.items()
                if length < max_length
            ]
            if shorter_sources:
                self.log_status(
                    "Export source selection: using "
                    f"{export_source} with {max_length} sweeps; ignoring shorter source(s): "
                    + ", ".join(shorter_sources)
                )

        return source_sweeps, source_timestamps, export_source

    def _load_export_source_data(self, archive_path: Path | None):
        candidates = []

        if archive_path is not None and archive_path.exists() and hasattr(self, 'load_archive_data'):
            if hasattr(self, '_finalize_archive_if_active'):
                self._finalize_archive_if_active()
            sweeps, timestamps = self.load_archive_data()
            if self._has_exportable_sweeps(sweeps):
                candidates.append((
                    np.asarray(sweeps, dtype=np.float32),
                    np.asarray(timestamps, dtype=np.float64) if self._has_exportable_sweeps(timestamps) else None,
                    'archive',
                ))

        if self._has_exportable_sweeps(getattr(self, 'raw_data', None)):
            timestamps = getattr(self, 'sweep_timestamps', None)
            timestamp_array = None
            if self._has_exportable_sweeps(timestamps):
                timestamp_array = np.asarray(timestamps, dtype=np.float64)
            candidates.append((np.asarray(self.raw_data, dtype=np.float32), timestamp_array, 'full_view'))

        if (
            getattr(self, 'raw_data_buffer', None) is None
            or getattr(self, 'sweep_timestamps_buffer', None) is None
            or getattr(self, 'samples_per_sweep', 0) <= 0
        ):
            return self._choose_best_export_source(candidates)

        with self.buffer_lock:
            current_sweep_count = int(getattr(self, 'sweep_count', 0))
            current_write_index = int(getattr(self, 'buffer_write_index', 0))
            actual_sweeps = min(current_sweep_count, int(getattr(self, 'MAX_SWEEPS_BUFFER', current_sweep_count)))

            if actual_sweeps <= 0:
                return self._choose_best_export_source(candidates)

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

        candidates.append((
            ordered_data.astype(np.float32, copy=False),
            ordered_timestamps.astype(np.float64, copy=False),
            'buffer',
        ))
        return self._choose_best_export_source(candidates)

    def _parse_archive_sweep_record(self, line: str):
        """Parse one archive line and return ``(samples, timestamp_s)`` or ``None``."""
        try:
            sweep_data = json.loads(line)
        except json.JSONDecodeError:
            return None

        if isinstance(sweep_data, dict) and 'samples' in sweep_data:
            samples = sweep_data.get('samples')
            if not isinstance(samples, list):
                return None
            ts_val = sweep_data.get('timestamp_s')
            timestamp_s = float(ts_val) if isinstance(ts_val, (int, float)) else None
            return samples, timestamp_s

        if isinstance(sweep_data, list):
            return sweep_data, None

        return None

    def _read_archive_metadata(self, archive_path: Path) -> dict:
        """Return the parsed archive metadata header when available."""
        try:
            with archive_path.open('r', encoding='utf-8') as handle:
                first_line = handle.readline().strip()
        except Exception:
            return {}

        if not first_line:
            return {}

        try:
            metadata = json.loads(first_line)
        except json.JSONDecodeError:
            return {}

        return metadata if isinstance(metadata, dict) else {}

    def _iter_archive_sweep_records(self, archive_path: Path):
        """Yield archived sweeps without materializing the full capture in memory."""
        with archive_path.open('r', encoding='utf-8') as handle:
            handle.readline()  # metadata
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                parsed = self._parse_archive_sweep_record(line)
                if parsed is not None:
                    yield parsed

    def _count_archive_sweeps(self, archive_path: Path) -> int:
        """Count valid sweep records in the archive without loading sample arrays."""
        count = 0
        for _samples, _timestamp_s in self._iter_archive_sweep_records(archive_path):
            count += 1
        return count

    def _archive_has_sweeps(self, archive_path: Path) -> bool:
        """Return True when the archive contains at least one valid sweep record."""
        for _samples, _timestamp_s in self._iter_archive_sweep_records(archive_path):
            return True
        return False

    def _archive_row_time(self, timestamp_s, saved_index: int, saved_total: int, capture_duration_s):
        if timestamp_s is not None:
            return float(timestamp_s)
        if capture_duration_s is None or saved_total <= 1:
            return None
        return float(capture_duration_s) * (float(saved_index) / float(saved_total - 1))

    def _write_archive_csv_rows(
        self,
        *,
        writer,
        archive_path: Path,
        save_min: int,
        save_max: int | None,
        saved_total: int,
        is_555_mode: bool,
        force_series,
        capture_duration_s,
        export_start_datetime,
        apply_filter: bool,
        rs_round_indices: list | None = None,
        export_column_indices: list[int] | None = None,
    ):
        """Stream archived sweeps to CSV, optionally filtering in bounded chunks."""
        chunk_size = 4096
        chunk_sweeps = []
        chunk_row_times = []
        saved_index = 0
        first_sweep_len = 0
        filter_runtime = None
        total_fs_hz = 0.0
        archive_metadata = self._read_archive_metadata(archive_path)
        archive_rs_units = (
            archive_metadata.get('metadata', {}).get('pzt_rs_rs_units')
            if isinstance(archive_metadata.get('metadata'), dict)
            else archive_metadata.get('pzt_rs_rs_units')
        )

        if apply_filter:
            total_fs_hz = float(self._get_filter_total_sample_rate_hz())
            if total_fs_hz <= 0:
                raise ValueError('Sample rate unavailable for ADC filtering.')

        def flush_chunk():
            nonlocal chunk_sweeps, chunk_row_times, saved_index, first_sweep_len, filter_runtime
            if not chunk_sweeps:
                return

            data = np.asarray(chunk_sweeps, dtype=np.float32)
            archive_rs_scale = get_pzt_rs_ohms_per_wire_unit(archive_rs_units)
            if archive_rs_scale is not None and hasattr(self, 'scale_pzt_rs_rosette_samples_inplace'):
                self.scale_pzt_rs_rosette_samples_inplace(
                    data,
                    channels=self.config.get('channels', []),
                    repeat_count=self.config.get('repeat', 1),
                    scale_override=archive_rs_scale,
                )
            if first_sweep_len <= 0 and data.ndim == 2 and len(data) > 0:
                first_sweep_len = len(export_column_indices) if export_column_indices else int(data.shape[1])

            if apply_filter:
                timestamp_array = None
                if all(row_time is not None for row_time in chunk_row_times):
                    timestamp_array = np.asarray(chunk_row_times, dtype=np.float64)

                if filter_runtime is None:
                    channels = list(self.config.get('channels', []))
                    repeat_count = max(1, int(self.config.get('repeat', 1)))
                    filter_index_map = self._build_filter_stream_map()
                    channel_rates = self._estimate_filter_channel_rates(
                        total_fs_hz,
                        sweep_timestamps_sec=timestamp_array,
                        index_map=filter_index_map,
                    )
                    filter_runtime = self.adc_filter_engine.build_runtime_plan(
                        self._copy_filter_settings_snapshot(),
                        total_fs_hz,
                        channels,
                        repeat_count,
                        sweep_timestamps_sec=timestamp_array,
                        channel_fs_by_channel=channel_rates,
                        index_map=filter_index_map,
                    )
                    self.adc_filter_engine.reset_runtime_states(filter_runtime)

                data = self.adc_filter_engine.filter_block(filter_runtime, data.astype(np.float32, copy=True))

            for sweep, row_time in zip(data, chunk_row_times):
                row = np.asarray(sweep).tolist()
                if rs_round_indices:
                    for _i in rs_round_indices:
                        if _i < len(row):
                            row[_i] = round(row[_i], 2)
                if export_column_indices:
                    row = [row[index] for index in export_column_indices if 0 <= index < len(row)]
                row.insert(0, format_export_clock_time(export_start_datetime, row_time))
                if is_555_mode:
                    row.insert(1, float(row_time if row_time is not None else 0.0))
                row.extend(list(get_nearest_force_values(force_series, row_time)))
                writer.writerow(row)
                saved_index += 1

            chunk_sweeps = []
            chunk_row_times = []

        for global_index, (samples, timestamp_s) in enumerate(self._iter_archive_sweep_records(archive_path)):
            if global_index < save_min:
                continue
            if save_max is not None and global_index >= save_max:
                break

            row_time = self._archive_row_time(timestamp_s, saved_index, saved_total, capture_duration_s)
            chunk_sweeps.append(samples)
            chunk_row_times.append(row_time)

            if len(chunk_sweeps) >= chunk_size:
                flush_chunk()

        flush_chunk()
        return saved_index, first_sweep_len
    
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
            range_export_enabled = bool(self.use_range_check.isChecked())
            archive_total_sweeps = None
            if archive_path is not None:
                if hasattr(self, '_finalize_archive_if_active'):
                    self._update_save_data_notice("Finalizing complete archive before export...")
                    self._finalize_archive_if_active()
                if range_export_enabled:
                    self._update_save_data_notice("Counting archived sweeps for range validation...")
                    archive_total_sweeps = self._count_archive_sweeps(archive_path)

            source_sweeps, source_timestamps, memory_export_source = self._load_export_source_data(None)
            memory_total_sweeps = len(source_sweeps) if self._has_exportable_sweeps(source_sweeps) else 0
            export_source = None
            captured_sweeps = int(getattr(self, 'sweep_count', 0) or 0)
            estimated_total_sweeps = max(captured_sweeps, memory_total_sweeps)
            total_sweeps = (
                max(archive_total_sweeps, memory_total_sweeps)
                if archive_total_sweeps is not None
                else estimated_total_sweeps
            )

            archive_has_sweeps = (
                archive_total_sweeps > 0
                if archive_total_sweeps is not None
                else archive_path is not None and self._archive_has_sweeps(archive_path)
            )

            if archive_path is not None and archive_has_sweeps:
                export_source = 'archive'
                if archive_total_sweeps is not None and archive_total_sweeps < captured_sweeps:
                    self.log_status(
                        "WARNING: Archive contains fewer sweeps than capture counter "
                        f"({archive_total_sweeps} of {captured_sweeps}); exporting archived sweeps only"
                    )
            else:
                export_source = memory_export_source

            if export_source != 'archive' and not self._has_exportable_sweeps(source_sweeps):
                hide_notice()
                QMessageBox.warning(self, "No Data", "No data to save.")
                return

            sweep_range_text = "All"

            # Check if range is enabled (range refers to the global sweep index across archive+memory)
            save_min = 0
            save_max = total_sweeps if range_export_enabled else None  # exclusive; None means all archive rows
            if range_export_enabled:
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
            if self.is_array_pzt1_mode() or self.is_array_pzt_rs_mode():
                all_specs = list(self.get_display_channel_specs())
                if self.is_array_pzt_rs_mode():
                    all_specs.extend(self.get_rosette_display_channel_specs())
                col_label_map = {}
                for spec in all_specs:
                    for col_idx in spec.get('sample_indices', []):
                        col_label_map[col_idx] = spec.get('label', f"Col{col_idx}")
                total_cols = self.get_effective_samples_per_sweep(repeat_count=repeat_count)
                export_column_indices = [index for index in sorted(col_label_map) if 0 <= index < total_cols]
                if export_column_indices:
                    header = [col_label_map[index] for index in export_column_indices]
                else:
                    header = [col_label_map.get(i, f"Col{i}") for i in range(total_cols)]
                    export_column_indices = None
            else:
                header = [f"CH{ch}" for ch in self.config['channels']] * repeat_count
                export_column_indices = None

            signal_header = list(header)
            exported_samples_per_sweep = len(signal_header)

            force_state = get_force_runtime_state(self)
            force_series = build_force_export_series(force_state.data)
            archive_metadata = self._read_archive_metadata(archive_path) if archive_path is not None else {}
            archive_metadata_block = archive_metadata.get("metadata", {})
            archive_start_time_iso = None
            if isinstance(archive_metadata_block, dict):
                archive_start_time_iso = archive_metadata_block.get("start_time")
            elif isinstance(archive_metadata, dict):
                archive_start_time_iso = archive_metadata.get("start_time")

            export_start_datetime = resolve_export_start_datetime(
                capture_start_time_s=getattr(self.timing_state, "capture_start_time", None),
                archive_start_time_iso=archive_start_time_iso if export_source == "archive" else None,
            )

            # Determine if we have force data
            has_force_x = bool(force_series is not None and np.any(force_series.x_force != 0.0))
            has_force_z = bool(force_series is not None and np.any(force_series.z_force != 0.0))

            selected_sweeps = None
            selected_timestamps = None
            if export_source != 'archive':
                selected_sweeps = np.asarray(source_sweeps[save_min:save_max], dtype=np.float32).copy()
                selected_end = len(source_sweeps) if save_max is None else save_max
                if source_timestamps is not None and len(source_timestamps) >= selected_end:
                    selected_timestamps = np.asarray(source_timestamps[save_min:selected_end], dtype=np.float64).copy()

            applied_filter_to_csv = False
            if hasattr(self, 'should_filter_adc_data') and self.should_filter_adc_data():
                if not is_555_mode and export_source == 'archive':
                    applied_filter_to_csv = True
                elif not is_555_mode and hasattr(self, 'filter_dataset_copy'):
                    self._update_save_data_notice("Applying ADC filter for export...")
                    selected_sweeps = self.filter_dataset_copy(
                        selected_sweeps,
                        sweep_timestamps_sec=selected_timestamps,
                    )
                    applied_filter_to_csv = True
                elif is_555_mode:
                    applied_filter_to_csv = False

            saved_total = int((save_max - save_min) if save_max is not None else max(total_sweeps - save_min, 0))
            first_sweep_len = (
                int(selected_sweeps.shape[1])
                if selected_sweeps is not None and selected_sweeps.ndim == 2 and len(selected_sweeps) > 0
                else 0
            )
            if exported_samples_per_sweep > 0:
                first_sweep_len = exported_samples_per_sweep

            rs_round_indices = (
                self.get_pzt_rs_rosette_sample_indices()
                if self.is_array_pzt_rs_mode()
                else []
            )

            # Save CSV data with force columns from the selected ordered dataset.
            self._update_save_data_notice("Writing CSV data...")
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:

                writer = csv.writer(f)

                # Write header
                header.insert(0, "Timestamp")
                if is_555_mode:
                    header.insert(1, "Timestamp_s")
                header.extend(["Force_X_N", "Force_Z_N"])
                writer.writerow(header)

                # Precompute capture duration for approximate timestamp mapping
                capture_duration = None
                if self.timing_state.capture_start_time and self.timing_state.capture_end_time:
                    capture_duration = self.timing_state.capture_end_time - self.timing_state.capture_start_time

                if export_source == 'archive':
                    saved_index, first_sweep_len = self._write_archive_csv_rows(
                        writer=writer,
                        archive_path=archive_path,
                        save_min=save_min,
                        save_max=save_max,
                        saved_total=saved_total,
                        is_555_mode=is_555_mode,
                        force_series=force_series,
                        capture_duration_s=capture_duration,
                        export_start_datetime=export_start_datetime,
                        apply_filter=bool(applied_filter_to_csv),
                        rs_round_indices=rs_round_indices,
                        export_column_indices=export_column_indices,
                    )
                else:
                    # Determine how many sweeps will be saved (respecting range selection)
                    saved_index = 0  # index among saved sweeps (0..saved_total-1)

                    row_timestamps = build_export_row_timestamps(
                        selected_timestamps=selected_timestamps,
                        saved_total=saved_total,
                        capture_duration_s=capture_duration,
                    )

                    for saved_index, sweep in enumerate(selected_sweeps):
                        row_time = None
                        if row_timestamps is not None and saved_index < len(row_timestamps):
                            row_time = float(row_timestamps[saved_index])
                        row = np.asarray(sweep).tolist()
                        if rs_round_indices:
                            for _i in rs_round_indices:
                                if _i < len(row):
                                    row[_i] = round(row[_i], 2)
                        if export_column_indices:
                            row = [row[index] for index in export_column_indices if 0 <= index < len(row)]
                        row.insert(0, format_export_clock_time(export_start_datetime, row_time))
                        if is_555_mode:
                            timestamp_to_write = row_time if row_time is not None else 0.0
                            row.insert(1, float(timestamp_to_write))
                        row.extend(list(get_nearest_force_values(force_series, row_time)))
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
                    "buffer_total_samples": self.buffer_spin.value() * exported_samples_per_sweep,
                    "exported_signal_columns": list(signal_header),
                },
                "block_timing_csv": self._block_timing_path,
                "timing": self._build_capture_timing_metadata(signal_header),
                "force_data": {
                    "available": len(force_state.data) > 0,
                    "x_force_available": has_force_x,
                    "z_force_available": has_force_z,
                    "total_force_samples": len(force_state.data),
                    "csv_units": "N",
                    "calibration_offset_x": force_state.calibration_offset['x'],
                    "calibration_offset_z": force_state.calibration_offset['z'],
                    "note": "Force data not available" if not force_state.data else "Force data synchronized with ADC samples and exported in Newtons (calibrated to zero at connection)"
                },
                "row_timestamp": {
                    "included_in_csv": True,
                    "column_name": "Timestamp",
                    "format": "HH:MM:SS.ffffff",
                    "relative_seconds_column_name": "Timestamp_s" if is_555_mode else None,
                    "absolute_time_available": bool(export_start_datetime is not None),
                    "absolute_start_time_source": (
                        "archive_metadata.start_time"
                        if export_source == "archive" and archive_start_time_iso
                        else "timing_state.capture_start_time"
                        if getattr(self.timing_state, "capture_start_time", None) is not None
                        else None
                    ),
                    "row_offset_source": (
                        "archive_sweep_timestamps_with_linear_fallback"
                        if export_source == "archive"
                        else "selected_sweep_timestamps_with_linear_fallback"
                        if selected_timestamps is not None
                        else "capture_duration_linear_fallback"
                    ),
                },
                "export_source": export_source,
                "pzt_vmid_noise": build_vmid_noise_metadata(
                    signal_header,
                    getattr(self, "analysis_state", None),
                    measured_from_in_memory_capture=(
                        getattr(getattr(self, "analysis_snapshot", None), "source_id", None) == "in_memory"
                    ),
                ),
            }

            if hasattr(self, 'build_filter_metadata'):
                metadata["filtering"] = self.build_filter_metadata(
                    applied=applied_filter_to_csv,
                    sweep_timestamps_sec=selected_timestamps,
                )
                # Rates describe acquisition timing, not filter settings. Keep one
                # authoritative copy in ``timing`` instead of duplicating them here.
                metadata["filtering"].pop("total_sample_rate_hz", None)
                metadata["filtering"].pop("per_channel_sample_rates_hz", None)
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
