## Plan: Analysis Tab Offline Signal Workbench

Add a new Analysis tab that operates on either the latest in-memory capture or exported CSV plus JSON metadata, reusing existing processing and plotting systems to avoid protocol or acquisition regressions. The recommended approach is to keep Analysis fully read-only, with its own local state and controls, while reusing Spectrum filter definitions and Pressure-map shear/normal/integration settings as computation inputs.

**Steps**
1. Phase 1 - Analysis scope contracts and data model: define an Analysis runtime state object (source mode, loaded arrays/timestamps, channel visibility, axis mode, marker state, filter enabled, derived overlays enabled, availability state). Source modes are In-memory cache and CSV+JSON import. Use Time ms as default x-axis. Mark Analysis as read-only with no mutation of live acquisition pipeline. Add availability gating: disabled while runtime acquisition is active (after Start until Stop), enabled before Start, enabled after Stop, and enabled before MCU connection when CSV offline source is selected.
2. Phase 1 - Source adapters (*parallel with step 3*): add a loader path for latest in-memory capture by reusing ring-buffer reordering logic from full-view archive handling; add a file loader for CSV plus JSON metadata produced by this app. The implemented loader is strict about unreadable/non-numeric data but tolerant of older app exports: when named signal columns are present, redundant `ColN` placeholder columns are ignored, and metadata signal-count mismatches are warnings rather than load-blocking errors.
3. Phase 1 - Derived signal adapters (*parallel with step 2*): expose an offline processing adapter layer that applies filter settings (Spectrum definitions), shear and normal pressure settings (Pressure-map), and integration sample settings (Pressure-map) against Analysis source arrays.
4. Phase 2 - UI tab creation (*depends on 1-3*): create AnalysisPanelMixin and register a new Analysis tab in the main visualization tabs. Build controls for source selection, file browse/load, x-axis toggle (samples/time ms), channel show/hide, enable/disable derived overlays, and filter on/off using Spectrum-style settings snapshot.
5. Phase 2 - Plot composition (*depends on 4*): render synchronized stacked plots on the same timeline: raw signal channels, integrated signal channels, shear/normal derived traces, and force channels. Keep shared x-range, support zoom/pan, and add cursor marker readout showing values at pointer for all visible curves at nearest sample.
6. Phase 2 - Overlay rendering and legends (*depends on 5*): draw optional shear top-bottom and left-right volts plus normal pressure volts on a dedicated derived plot. Draw integration values on a separate integration plot, one integrated trace per visible voltage channel, reusing the raw trace color. Toggling off a raw channel also hides its integrated trace.
7. Phase 3 - Settings persistence and safety rails (*depends on 4-6*): persist Analysis tab UI preferences in a tab-specific JSON path (last source mode, axis mode, visibility toggles, overlay toggles, marker enabled state). Persist references only for last loaded files, not raw data blobs. Guard against stale/missing files gracefully.
8. Phase 3 - Performance and lifecycle hardening (*depends on 5-7*): cache transformed arrays keyed by source fingerprint plus settings hash, throttle marker updates during mouse move, and ensure Analysis refresh only runs when Analysis tab is active.
9. Phase 4 - Documentation and spec artifact (*depends on 1-8*): add a formal spec markdown in Specs with UX behavior, data contracts, compute pipeline ordering, and acceptance criteria.

**Relevant files**
- c:/Code/arduino_adc_streamer/adc_gui.py — register Analysis mixin inheritance, state init/load/save hooks, tab-change dispatch gating.
- c:/Code/arduino_adc_streamer/gui/display_panels.py — insert Analysis tab creation and index bookkeeping in visualization tabs.
- c:/Code/arduino_adc_streamer/gui/spectrum_panel.py — reuse filter settings shape and channel toggle UX pattern.
- c:/Code/arduino_adc_streamer/gui/signal_integration_panel.py — reuse pressure-map settings access points for shear/normal/integration parameters.
- c:/Code/arduino_adc_streamer/gui/analysis_panel.py — new Analysis tab UI and interaction handlers.
- c:/Code/arduino_adc_streamer/data_processing/adc_filter_engine.py — apply Spectrum-compatible filter engine to offline arrays.
- c:/Code/arduino_adc_streamer/data_processing/signal_integrator.py — compute integration traces/values using pressure-map sample settings.
- c:/Code/arduino_adc_streamer/data_processing/shear_detector.py — compute top-bottom and left-right shear outputs in volts.
- c:/Code/arduino_adc_streamer/data_processing/normal_force_calculator.py — compute normal pressure output in volts equivalent path used by pressure-map flow.
- c:/Code/arduino_adc_streamer/file_operations/archive_loader.py — in-memory/full-view ordering and archive-compatible loading patterns.
- c:/Code/arduino_adc_streamer/file_operations/data_exporter.py — source arbitration patterns for full dataset retrieval.
- c:/Code/arduino_adc_streamer/file_operations/settings_persistence.py — reuse payload persistence helpers for Analysis settings.
- c:/Code/arduino_adc_streamer/constants/ui.py — add Analysis tab name constant.
- c:/Code/arduino_adc_streamer/docs/specifications/gui-tabs/ANALYSIS_TAB_SPEC.md — new feature specification document.

**Verification**
1. Unit tests for source adapters: in-memory ring-buffer reorder, CSV+JSON parse/validate, timestamp normalization, and graceful error messages.
2. Unit tests for derived overlays: filter parity with Spectrum settings payload, shear/normal outputs for known synthetic vectors, integration output for fixed sample-window fixtures.
3. UI-level test/manual script: open Analysis, load in-memory source, toggle channels and overlays, switch x-axis mode, confirm synchronized zoom and pan across stacked plots.
4. Marker behavior check: pointer updates value readout at nearest sample for visible traces; no stutter on large datasets.
5. Regression checks: capture/live tabs unaffected while Analysis operations run; no mutation to live config/acquisition state.
6. Run tests with repository invocation rule: use PYTHONPATH=. when calling pytest in this repo.

**Decisions**
- Default data source: last in-memory/cache capture.
- Default x-axis: time in milliseconds.
- Analysis tab behavior: read-only; it must not modify live acquisition or shared runtime settings.
- Analysis availability: offline-only. It is unavailable during active runtime acquisition after Start and becomes available again after Stop. For CSV offline analysis, it is available before Start and before MCU connection.
- Included scope: time-series and force synchronized plotting, channel visibility controls, Spectrum-defined filtering, shear/normal/integration overlays, zoom, marker readout, x-axis mode toggle.
- Zoom behavior: user can zoom in/out on X-axis only, Y-axis only, or both axes.
- Excluded scope: real-time streaming inside Analysis, protocol/firmware changes, and new export formats.
- CSV compatibility: older app exports with real signal labels and extra generated `ColN` placeholders remain loadable; the placeholders are hidden from Analysis and metadata mismatch is surfaced as a warning.
- Image export: Analysis can save selected raw, integrated, shear/normal, and force plots as PNG files.

**Further Considerations**
1. File schema strictness: prefer strict validation for app-native CSV+JSON pair with a fallback compatibility mode for minor field-name drift.
2. Large capture handling: keep downsampling optional for rendering only; preserve full-resolution arrays for marker and computation accuracy.
3. Pressure-map dependency strategy: read pressure-map settings snapshot at Analysis load time and provide a manual refresh action if settings change later.

## Spec Draft: ANALYSIS_TAB_SPEC.md

Title: Analysis Tab Feature Specification
Owner: Host application (GUI/data processing)
Status: Draft
Date: 2026-06-26

1. Purpose
Provide an offline Analysis tab for post-capture signal investigation using either latest in-memory capture or exported CSV plus JSON metadata from this app. The tab must support synchronized multi-trace visualization and derived computations without affecting live acquisition.

2. Data Sources
- Source A: Last in-memory/cache capture currently retained by the app.
- Source B: CSV data file plus paired JSON metadata file generated by this app.
- Source A is default on tab entry.
- Invalid or missing source files show actionable error text and retain previous valid state.

3. Main Capabilities
- Display channel time-series signals.
- Display force sensor traces beneath the signal graph on the same timeline.
- Show or hide individual signal channels.
- Apply filters using definitions/settings used by Spectrum functionality.
- Apply shear calculations (top-bottom, left-right) using Pressure-map settings and plot shear values in volts.
- Apply normal pressure calculation using Pressure-map settings and plot normal pressure value in volts.
- Show integration values according to integration sample settings from Pressure-map.
- Provide zoom and pan on graphs.
- Provide zoom in/out modes for X-axis only, Y-axis only, or both axes.
- Provide cursor marker readout at mouse pointer location with nearest-sample values.
- X-axis mode toggle between sample number and time ms.

4. Non-Functional Requirements
- Read-only behavior relative to live acquisition and runtime processing state.
- Reuse existing processing components where available to ensure parity.
- Responsive interaction on large captures with caching and redraw throttling.
- Availability gating: Analysis interactions are disabled during active runtime capture and enabled only in offline states.

5. UI Structure
- New top-level visualization tab name: Analysis.
- Control group:
  - Data source selector (In-memory, CSV plus JSON)
  - Load/browse actions for file source
  - X-axis toggle (Time ms, Sample index)
  - Zoom mode selector (X only, Y only, X and Y)
  - Channel visibility checklist
  - Toggle group for filter, shear overlays, normal pressure overlay, integration overlay
- Plot area:
  - Upper plot: selected signal channels and optional derived overlays
  - Lower plot: force sensor traces
  - Shared x-axis range and synchronized navigation
  - Marker crosshair/readout panel

6. Data and Compute Pipeline
- Load source arrays and timestamps.
- Normalize axis domain for selected x-axis mode.
- Optional filter stage using Spectrum filter settings.
- Derived stages:
  - Shear top-bottom and left-right (volts)
  - Normal pressure (volts path consistent with current pressure-map processing)
  - Integration metrics using Pressure-map integration sample count
- Render visible traces and marker values from current transformed snapshot.

7. State and Persistence
- Persist Analysis UI preferences only (source mode, axis mode, visibility/toggle state, last-used file references).
- Do not persist loaded capture arrays inside settings.

8. Acceptance Criteria
- Before Start, user can enter Analysis and inspect latest in-memory data without configuration.
- User can load a valid CSV plus JSON pair and see synchronized plots.
- Channel toggles update visibility without changing data source.
- Spectrum-compatible filtering changes displayed traces as expected.
- Shear, normal pressure, and integration overlays appear/disappear based on toggles and settings.
- Zoom/pan are functional and synchronized between upper/lower plots.
- Zoom in/out supports X-only, Y-only, and X+Y modes.
- Marker readout reports nearest values for all visible traces.
- Switching x-axis mode updates scales without data corruption.
- No changes occur to live capture behavior while using Analysis.
- After Start (while runtime acquisition is active), Analysis is unavailable/disabled.
- After Stop, Analysis becomes available again.
- Before MCU connection, user can still perform CSV offline analysis.

9. Out of Scope
- Firmware/protocol modifications.
- Real-time streaming computation inside Analysis.
- New export file formats.
