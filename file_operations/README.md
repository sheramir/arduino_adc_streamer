# File Operations

This package holds the GUI's file I/O mixins: loading full captures back from the on-disk JSONL
archive, exporting captured sweeps to CSV with metadata (including force-sensor alignment and
optional ADC filtering), exporting the current plot as a PNG image, and small generic JSON
settings-persistence helpers used by other GUI panels (shear, spectrum, etc.). The main window
mixes in `ArchiveLoaderMixin`, `DataExporterMixin`, and `PlotExporterMixin` from here.

## Files

### __init__.py

Package entry point that re-exports the three mixin classes for convenient importing.

- No functions/classes of its own; re-exports `DataExporterMixin`, `PlotExporterMixin`, `ArchiveLoaderMixin`.

### archive_loader.py

Mixin for loading/viewing archived capture data and entering "Full View" mode, including
reconstructing timestamps from either embedded per-sweep timestamps or a CSV block-timing
sidecar, and finalizing the background archive writer before reading it back.

- `ArchiveLoaderMixin` — mixin class for archive loading operations.
  - `_show_full_view_loading_notice()` — show a modal "Building Full View..." progress dialog.
  - `_hide_full_view_loading_notice()` — hide that dialog and restore the cursor.
  - `_apply_full_view_time_range(timestamps)` — set the plot/force view X-range to the full capture span.
  - `_capture_exceeds_memory_buffer()` — True when the sweep count has overflowed the in-memory ring buffer.
  - `_finalize_archive_if_active()` — block until the background archive writer thread has fully
    flushed and closed.
  - `load_archive_data()` — read the JSONL archive file (metadata header + per-line sweep
    records in new or legacy format), reconstruct timestamps (embedded, CSV sidecar, or uniform
    fallback), rescale PZT_RS RS values to ohms, and return `(sweeps, timestamps)`.
  - `full_graph_view()` — show the complete Start->Stop capture: read straight from the in-memory
    ring buffer for short captures, or fall back to loading the full archive when the capture
    exceeded the buffer; updates plot, force overlay, and the info label.

### data_exporter.py

Mixin handling the full CSV + metadata-JSON export workflow: choosing the best data source
(archive vs. in-memory full view vs. ring buffer), aligning the nearest force sample to each
exported row, optional ADC filtering at export time, sweep-range-limited export, and writing both
the CSV rows and a detailed metadata JSON sidecar.

- `DataExporterMixin` — mixin class for data export operations.
  - `_show_save_data_notice(label_text)` / `_update_save_data_notice(label_text)` /
    `_hide_save_data_notice()` — manage a modal "Saving Data" progress dialog during export.
  - `_has_exportable_sweeps(data)` — True when a sweep collection is non-empty.
  - `_choose_best_export_source(candidates)` — pick the candidate `(sweeps, timestamps, source_name)`
    with the most sweeps, logging which shorter sources were ignored.
  - `_load_export_source_data(archive_path)` — gather candidates from archive, in-memory full
    view, and the live ring buffer, then delegate to `_choose_best_export_source`.
  - `_parse_archive_sweep_record(line)` — parse one archive JSONL line into `(samples, timestamp_s)`.
  - `_read_archive_metadata(archive_path)` — parse the archive's first-line metadata header.
  - `_iter_archive_sweep_records(archive_path)` — generator yielding archived sweeps without
    loading the whole capture into memory.
  - `_count_archive_sweeps(archive_path)` / `_archive_has_sweeps(archive_path)` — count or check
    presence of valid sweep records by streaming the file.
  - `_archive_row_time(timestamp_s, saved_index, saved_total, capture_duration_s)` — resolve a
    row's timestamp from the embedded value or a linear capture-duration fallback.
  - `_write_archive_csv_rows(...)` — stream archived sweeps to the CSV writer in bounded chunks,
    optionally applying the ADC filter and rounding PZT_RS RS columns, attaching nearest force values per row.
  - `save_data()` — top-level Save Data handler: determine export source and sweep range,
    build the CSV header from display-channel specs, optionally filter, write the CSV file and a
    metadata JSON file (configuration, timing, force-data, filtering, row-timestamp provenance, notes).

### force_export_alignment.py

Pure helpers for converting raw force-sensor counts to Newtons and aligning each exported ADC row
to the nearest-in-time force sample.

- `ForceExportSeries` (frozen dataclass) — sorted force timestamps plus calibrated X/Z force arrays in Newtons.
- `build_force_export_series(force_samples)` — sort raw `(timestamp, x_raw, z_raw)` force samples
  by time and convert to Newtons using `X_FORCE_SENSOR_TO_NEWTON`/`Z_FORCE_SENSOR_TO_NEWTON`;
  returns None if there's no usable data.
- `build_export_row_timestamps(selected_timestamps, saved_total, capture_duration_s)` — return
  per-row timestamps from measured sweep times, or a linear `linspace` fallback over the capture duration.
- `get_nearest_force_values(force_series, sweep_time_s)` — binary-search the force series for the
  nearest-in-time sample and return its `(x_force, z_force)` in Newtons, or `(0.0, 0.0)` if unavailable.

### plot_exporter.py

Mixin for saving the current time-series plot as a high-resolution PNG image.

- `PlotExporterMixin` — mixin class for plot export operations.
  - `save_plot_image()` — validate there is data to export, build a timestamped filename, and use
    `pyqtgraph`'s `ImageExporter` (at `PLOT_EXPORT_WIDTH` resolution) to save the plot widget as a PNG.

### settings_persistence.py

Small generic JSON settings save/load helpers shared by GUI panels (e.g. shear and spectrum
settings) that persist their own configuration files.

- `save_settings_payload(file_path, payload, log_callback=None, success_message=None)` — write a
  dict as indented JSON to `file_path`, creating parent directories as needed, and optionally log success.
- `load_settings_payload(file_path, payload_key=None)` — read a JSON file and optionally unwrap a
  nested payload key; returns `(path, payload)`.

## Notes

- `data_exporter.py` and `archive_loader.py` both call `self.scale_pzt_rs_rosette_samples_inplace`
  and rely heavily on host-window attributes (`self.config`, `self.raw_data`, `self.buffer_lock`,
  etc.) defined outside this package — these mixins are not usable standalone.
- The root README's "Repository Layout" description ("archive loading, export, plot export, and
  settings persistence helpers") matches this folder's contents accurately.
