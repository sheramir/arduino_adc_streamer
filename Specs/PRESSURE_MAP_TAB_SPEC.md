# Pressure Map Tab Specification

Owner: Host application GUI/pressure-processing stack  
Status: Implemented  
Date: 2026-07-08

## Purpose

The Pressure Map tab converts recent live ADC data into integrated sensor values, derived shear/normal information, and a pressure-map visualization for single-package and array layouts. It is the live derived-view tab for pressure/shear interpretation.

## UI Behavior

- Nested inner tabs: Display and Settings.
- Display tab includes:
  - Signal Integration Controls.
  - Integrated timeline plot.
  - Pressure-map visualization widget.
  - Status label for actionable display or configuration warnings.
- Settings tab includes groups for:
  - Shear Visualization Settings.
  - Pressure Map Settings.
  - Per-Package Gain Calibration.
- Timeline/source controls support both PZT and PZR-oriented display paths, including Rosette-specific display selection where applicable.
- Pressure-map settings include package-boundary shape options and array gap/interpolation tuning.

## Data Pipeline

1. Read the recent raw ADC buffer window.
2. Convert counts to voltage.
3. Apply display-only bias removal, filtering, polarity handling, and integration.
4. Map integrated values to package positions.
5. Derive shear and normal outputs.
6. Render integrated timeline series and the pressure-map widget.
7. In array layouts, optionally combine adjacent packages into one array-level pressure surface.

## Runtime Behavior

- The tab refreshes only when active or explicitly triggered by the main app.
- Missing channel configuration or missing raw data produces user-facing status messages instead of silent failure.
- Array-mode rendering can switch between per-package and combined-array views using the current sensor layout.

## Persistence

- Pressure Map and shear settings persist under the user `.adc_streamer` settings path.
- Save/load actions support explicit settings files in addition to autosave/restore of the last-used state.

## Acceptance Criteria

- Integrated timeline and pressure-map displays update from live buffered data.
- Users can adjust display and processing settings without restarting capture.
- Array layouts can render a combined pressure surface with package-gap tuning.
- Status messaging is actionable when channels, data, or compatible selections are unavailable.

## Out Of Scope

- Offline capture analysis.
- Sensor-library editing.
