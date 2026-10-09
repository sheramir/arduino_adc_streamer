# Analysis Tab Feature Specification

Owner: Host application GUI/data-processing stack  
Status: Implemented, including MUX-timing PZT force update  
Date: 2026-07-07

## Purpose

The Analysis tab provides offline inspection of retained captures or app-exported CSV plus JSON metadata. It is read-only: loading, filtering, plotting, marker inspection, image export, and derived calculations never mutate live acquisition buffers, firmware protocol state, or runtime processing settings.

## Sources

- In-memory cache: copies the current circular capture buffer in oldest-to-newest order and uses the same display-channel labels shown in the Time Series graph when available.
- CSV plus JSON: loads files produced by the app's Save Data flow. Metadata is used for timing/configuration context, but older CSV files are tolerated when they contain usable named signal columns.

CSV compatibility rules:

- Force columns named `Force_X_N` / `Force_Z_N` are loaded as Newtons.
- Legacy raw force columns named `Force_X` / `Force_Z` are converted to Newtons using the configured load-cell constants.
- Legacy placeholder columns such as `Col1`, `Col3`, etc. are ignored when real signal labels are present.
- CSV/metadata signal-count mismatches are reported as warnings instead of blocking analysis when the CSV can still be interpreted.

Analysis is disabled while runtime acquisition is active and re-enabled after capture stops. CSV plus JSON analysis can be used before MCU connection because it does not depend on serial state.

## UI Behavior

- New visualization tab: Analysis, with nested Display and Settings sub-tabs.
- Source selector: In-memory cache or CSV plus JSON.
- File controls: browse/load CSV and metadata JSON.
- Axis selector: Time ms or Sample index.
- Zoom selector: X only, Y only, or X and Y.
- Channel checklist with All/None buttons.
- Optional processing/display toggles: Spectrum-compatible filter, shear, normal pressure, integration, calculated PZT force, and marker.
- PZT force settings: capacitance, leak resistance, d33, fallback noise threshold, quiet-window duration, noise multiplier, MUX leakage timing mode, manual MUX connected time, optional off-MUX leakage resistance, and a Calculate Vmid + Noise action.
- Analysis image export controls: select Raw signals, Integrated signals, Shear / Normal, and/or Force plots and save them as PNG images.
- Calculated-force traces use the same plot color as their source raw signal trace. For example, if `PZT3_L` is green in Raw signals, `Calculated Force - PZT3_L [N]` is also green in Force.
- Display controls, channel checklists, force-trace checklists, and image-export controls are width-stable and must remain visible inside the Analysis scroll area. Long calculated-force labels are displayed in a compact force-trace list instead of forcing horizontal overflow.
- Marker: mouse readout reports nearest displayed values for visible signal, integration, derived, and force traces. Marker readout text is elided to the visible status-label width and keeps the full text in a tooltip, so moving the marker cannot resize or horizontally shift the Analysis layout.

## Data Pipeline

1. Copy or load source arrays, timestamps, force traces, metadata, and labels into an `AnalysisSourceSnapshot`.
2. Normalize X-domain as sample index or milliseconds.
3. Optionally apply the current Spectrum filter settings to a copy of the source data.
4. Convert ADC signal counts to volts using the active configured Vref.
5. Build raw signal traces for visible channels.
6. Optionally build integrated traces independently for each visible voltage channel using Pressure-map integration and HPF settings.
7. Optionally build shear and normal-pressure traces from mapped R/L/C/T/B positional channels.
8. Build measured force traces in Newtons.
9. Optionally reconstruct calculated PZT force traces from visible voltage channels, using per-channel quiet-window Vmid/noise calibration and MUX-aware leakage timing when available.
10. Render synchronized plots with a shared X range:
    - Raw signals.
    - Integrated signals.
    - Shear / Normal derived traces.
    - Force traces, including measured load-cell force and calculated PZT force.

## PZT Force

Calculated PZT force is implemented outside the GUI in `data_processing/pzt_force_calculation.py`, with defaults in `constants/pzt_force.py`, so the calculation can be reused by future app sections.

The calculation:

- Centers voltage around a per-channel Vmid estimate, or a median fallback.
- Sets centered voltage below the per-channel noise threshold to zero before integration.
- Models leakage with MUX-aware decay exposure instead of assuming continuous leakage across the full revisit interval.
- Converts generated charge into force using `d33`.
- Resets accumulated force after complete opposite-polarity events return below the noise threshold to reduce drift.

Quiet-window calibration estimates Vmid from the first configured duration of data and uses a consistent percentile-deviation noise threshold for every channel. MAD and robust sigma remain diagnostic values.

### PZT MUX Leakage Timing

The current force model must distinguish two time intervals:

- `sample_dt_s`: elapsed time between consecutive samples of the same displayed PZT trace. This is the force/charge accumulation interval and remains derived from the trace timestamps.
- `leak_dt_s`: time during that interval when the piezo is actually connected to the MUX output/leak path. This is the interval used in the RC decay term.

The decay factor must be calculated as:

```text
alpha = exp(-(leak_dt_s / tau_on) - (off_leak_dt_s / tau_off))
tau_on = Rleak * Cpzt
tau_off = Rdisconnected * Cpzt
off_leak_dt_s = max(sample_dt_s - leak_dt_s, 0)
```

When disconnected leakage is disabled or `Rdisconnected` is blank/infinite, the off-time term is omitted:

```text
alpha = exp(-leak_dt_s / tau_on)
```

This replaces the previous continuous-leak assumption:

```text
alpha = exp(-sample_dt_s / tau_on)
```

The generated charge increment still uses the timestamp-to-timestamp interval to compare consecutive voltage observations:

```text
dQ = Cpzt * (v[n] - alpha * v[n-1])
dF = dQ / d33
```

For example, if a piezo is connected for 30 ms, four other sensor channels are sampled for 120 ms, and sweep transmission takes 200 ms, then the same-channel revisit interval is about 320 ms but the default leak exposure is 30 ms. With `tau_on = 1 s`, `alpha` must be `exp(-0.030) = 0.970`, not `exp(-0.320) = 0.726`, unless the hardware has a real off-MUX leak path.

### Timing Extraction

Analysis currently builds per-column trace timestamps from `AnalysisSourceSnapshot.timestamps_s` plus sample-column offsets. Those timestamps are still the source of `sample_dt_s`.

For in-memory cache analysis:

- `AnalysisSourceSnapshot.timestamps_s` is copied from `sweep_timestamps_buffer`, reordered oldest-to-newest.
- `sample_rate_hz` is resolved from `_get_filter_total_sample_rate_hz()` when available, otherwise from sweep timestamp spacing.
- The live binary ingest path stores `avg_sample_time_us` in `timing_state.arduino_sample_times` and `_cached_avg_sample_time_sec`; this value is the best available automatic estimate of one physical sample/MUX dwell interval.
- The live binary ingest path also records `mcu_block_gap_us` and `buffer_gap_time_ms`, but these describe block/sweep gaps or transfer idle time. They must not be used as the default leak exposure while the piezo is disconnected from the mux output.

For CSV plus JSON analysis:

- Signal data and labels are loaded from the CSV.
- Sweep timestamps come from `Timestamp_s` when present, otherwise from `capture_duration_seconds`, otherwise from row indices.
- `sample_rate_hz` is resolved from metadata timing keys `arduino_sample_rate_hz` or `total_rate_hz`, otherwise from median sweep spacing and signal-column count.
- Existing metadata includes `timing.arduino_sample_time_us`, `timing.arduino_sample_rate_hz`, `timing.total_rate_hz`, `timing.buffer_gap_time_ms`, and `configuration.exported_signal_columns`.
- Existing metadata may include `block_timing_csv`, whose rows contain `avg_dt_us`, `block_start_us`, `block_end_us`, and `mcu_gap_us`. If the referenced file exists, Analysis may use its median `avg_dt_us` as an automatic MUX connected-time estimate. If the file is absent, the JSON `timing.arduino_sample_time_us` value is the next automatic source.
- The human-readable `Timestamp` CSV column is not sufficient for precise PZT timing unless paired with relative seconds or metadata timing.

Automatic MUX connected-time resolution order:

1. User-selected manual MUX connected time, when timing mode is Manual.
2. In-memory `_cached_avg_sample_time_sec` or latest `timing_state.arduino_sample_times`.
3. CSV+JSON `block_timing_csv` median `avg_dt_us`, when the sidecar path exists and parses.
4. CSV+JSON `metadata.timing.arduino_sample_time_us`.
5. `1 / sample_rate_hz`, only when the user explicitly selects "Infer from total sample rate" and accepts that this is a fallback approximation.

If none of these sources is available, calculated PZT force must show an actionable Analysis status message and must not silently fall back to using the same-channel revisit interval as leak time.

### Analysis PZT Timing Settings

Add the following persisted settings under the existing `pzt_force` settings object:

- `mux_timing_mode`: `"auto"` by default. Supported values: `"auto"`, `"manual"`, `"infer_from_total_sample_rate"`, and `"continuous"`.
- `mux_connected_time_s`: manual leak exposure per sample, default `0.030` seconds.
- `mux_connected_time_source`: diagnostic string written at calculation time, not edited directly by the user.
- `off_mux_leak_enabled`: default `false`.
- `off_mux_rleak_ohm`: disconnected/off-MUX leak resistance, default blank or `null`.

UI behavior:

- In Settings > PZT Force Settings, show a compact "MUX timing" control with the mode selector and a connected-time numeric input in ms.
- Show the connected-time input only for Manual mode, but keep its value persisted.
- Show optional off-MUX leak controls behind a checkbox named for disconnected leakage.
- Auto mode should display a read-only resolved source/value when a source is available, for example `Auto: 30.000 ms from avg_sample_time_us`.
- Continuous mode is retained only for hardware where the leak path is physically across the piezo at all times. Its status/readout must make clear that it uses the full timestamp delta for decay.
- When Auto cannot resolve a connected time, the UI/status must ask the user to choose Manual or Infer from total sample rate.

### Implementation Notes

- Extend `calculate_pzt_force_from_settings()` and `calculate_pzt_force_from_voltage()` to accept either a scalar `leak_dt_s` or an array matching `time_s`.
- Keep `time_s` validation strictly increasing; it still defines `sample_dt_s`.
- Clamp `leak_dt_s` into `[0, sample_dt_s]` for each step and report/warn when clamping occurs.
- Preserve the old behavior only when `mux_timing_mode == "continuous"`, where `leak_dt_s = sample_dt_s`.
- Add an Analysis helper that resolves PZT leak timing from snapshot metadata and owner/live state, returning `(leak_dt_s, source_label, warnings)`.
- Add metadata export fields for future captures: `timing.pzt_mux_connected_time_us` when known and `timing.pzt_mux_connected_time_source`. Existing exports remain supported through the fallback order above.

## Persistence

The tab persists UI preferences under `~/.adc_streamer/analysis/last_used_analysis_settings.json`, including source mode, axis mode, zoom mode, overlay toggles, marker enabled state, channel visibility, image-export selections, PZT force settings, PZT MUX timing settings, per-channel PZT baseline/noise calibration, and last file references. Raw capture arrays are not persisted.

## Acceptance Criteria

- The Analysis tab appears in the visualization tabs.
- In-memory loading shows the latest retained capture after Stop.
- CSV plus JSON loading works before MCU connection for valid app exports.
- Older CSV exports with named signal columns plus redundant `ColN` placeholders load without error; placeholder columns are hidden, and metadata-count mismatches are warnings.
- Invalid CSV/metadata files show actionable failures and preserve the prior valid state.
- Channel visibility changes redraw without reloading the source.
- Optional filtering uses the current Spectrum filter widget settings on a data copy.
- Shear, normal pressure, and integration overlays can be independently toggled.
- Integration is plotted separately from raw signals, and each integrated trace uses the same color as its source raw trace.
- Shear and normal pressure are plotted together on their own derived plot.
- Hiding a raw signal channel also hides that channel's integrated and calculated-force traces.
- Calculated PZT force traces use the same color as their corresponding raw signal traces.
- Measured load-cell force is displayed in Newtons.
- Calculated PZT force can use per-channel quiet-window Vmid/noise calibration, and below-threshold voltage does not contribute to force integration.
- Calculated PZT force uses MUX-aware leakage timing: same-channel timestamp deltas define observation spacing, while the RC decay term uses resolved MUX connected time unless Continuous mode is selected.
- In-memory calculated PZT force can resolve MUX connected time from live `avg_sample_time_us` timing when available.
- CSV plus JSON calculated PZT force can resolve MUX connected time from block timing sidecar `avg_dt_us` or metadata `timing.arduino_sample_time_us` when available.
- When MUX connected time cannot be resolved automatically, Analysis does not silently use revisit interval as leak time; it shows a status message and provides Manual and Infer-from-rate settings.
- Raw, integrated, shear/normal, and force plots share X range and support X-only, Y-only, and X+Y zoom modes.
- User can export selected Analysis plots to PNG images.
- Marker readout reports nearest values for visible traces without changing the page width or causing horizontal jiggle while the cursor moves.
- Analysis controls and dynamic channel/force-trace lists remain inside the visible scroll area when calculated PZT force is enabled.
- Capture start disables Analysis controls; capture finish re-enables them.

## Out Of Scope

- Real-time Analysis streaming.
- Firmware or serial protocol changes.
- New export formats.
- Persisting raw offline data blobs in settings.
