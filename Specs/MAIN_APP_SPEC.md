# Main App GUI Specification

Owner: Host application GUI/runtime stack  
Status: Implemented  
Date: 2026-07-08

## Purpose

The desktop app provides one place to connect supported MCUs and the force sensor, configure acquisition, stream and inspect live data, analyze offline captures, manage sensor layouts, and export capture artifacts. The app combines a persistent left-side control workflow with a right-side visualization workspace of tabbed views.

## Top-Level Layout

- Main window with a horizontal splitter.
- Left panel contains stacked control groups:
  - Serial Connection.
  - ADC Configuration.
  - Acquisition Settings.
  - Run Control.
  - Data Export.
  - Status & Messages.
- Right panel contains a `QTabWidget` for visualization and editing tabs.
- Status bar shows current connection state.

## Visualization Tabs

The app includes the following visualization tabs:

- Time Series.
- Rosette (RS), shown only when the active mode supports `PZT_RS`.
- Pressure Map.
- Heatmap.
- Force Calibration.
- Spectrum.
- Analysis.
- Sensor.

When Rosette mode is active, the Time Series tab is relabeled to the PZT-specific label and the Rosette tab becomes visible. When Rosette mode is inactive, the Rosette tab is hidden and focus returns to Time Series if needed.

## Shared Workflows

- Connect/disconnect ADC and force serial devices independently.
- Detect MCU type and expose only the relevant configuration controls.
- Configure channels, sensor sequences, repeat count, and sweeps per block before starting capture.
- Start and stop acquisition without leaving the main window.
- Refresh live views according to the active visualization tab instead of redrawing every tab continuously.
- Save capture data to CSV, save metadata sidecars, and export plot images.
- Record status, warnings, and errors in the status log.

## Shared Behavior

- The main window is fit to the available screen and centered on startup.
- The left control panel remains available while the user switches among visualization tabs.
- The active tab drives which periodic refresh paths run:
  - Time Series and Rosette update live traces.
  - Pressure Map updates integrated and derived pressure/shear views.
  - Heatmap updates the 2D sensor display.
  - Spectrum starts and stops its own periodic update timer on tab changes.
  - Analysis is offline/read-only and is disabled during active acquisition.
- Closing the app persists last-used Spectrum, Heatmap, Pressure Map, and Analysis settings, then disconnects serial resources and shuts down workers.

## Persistence

- Sensor-library edits persist in the user sensor configuration store.
- Last-used settings for Spectrum, Heatmap, Pressure Map, Force Calibration state, and Analysis persist under the user home `.adc_streamer` directory.
- Export directory, filenames, notes, and capture artifacts are user-managed through the Data Export section.

## Acceptance Criteria

- Users can complete connection, configuration, capture, visualization, analysis, export, and sensor-management workflows without leaving the main window.
- The left panel exposes connection, configuration, run-control, export, and status sections in a stable order.
- The right panel exposes the implemented visualization tabs, with Rosette visibility tied to compatible mode selection.
- Tab switches trigger the correct refresh behavior and do not require restarting the app.
- The app restores persisted visualization/settings state on later launches where that feature is supported.

## Out Of Scope

- Headless operation without the GUI.
- Firmware flashing workflows.
- Multi-window visualization orchestration.
