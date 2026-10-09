# Force Calibration Tab Specification

Owner: Host application GUI/force-calibration stack  
Status: Implemented  
Date: 2026-07-08

## Purpose

The Force Calibration tab captures live sensor-derived values alongside the connected force-sensor reading so users can build calibration datasets for PZT, PZR, and Rosette sensor families.

## UI Behavior

- Control group titled `Calibration Controls`.
- Controls include:
  - Sensor Family selector: PZT, PZR, Rosette.
  - Sensor Number selector.
  - Signal Source selector for the supported live source paths.
  - Start Measure / Stop Measure action.
  - Clear Table action.
  - Save Calibration and Load Calibration actions.
- Status label indicates whether the force sensor is connected and whether measurement is ready.
- Results table includes columns for Sensor, Source, T/B/L/R/C, Total, Shear T-B, Shear L-R, and Timestamp.

## Runtime Behavior

- Measurement start is disabled until the force sensor is connected.
- During capture, the selected source path resolves current live sensor values and updates the active row.
- Stopping measurement commits or discards the in-progress row according to available data and current state.
- Changing family/source affects which rows are displayed and which live resolver path is used.

## Persistence

- Calibration datasets can be saved to and loaded from JSON files.
- The last-used calibration state is autosaved and restored for the user.

## Acceptance Criteria

- Users can record live calibration rows for supported sensor families.
- The Start/Stop action is gated by force-sensor connection status.
- Saved calibration files round-trip the recorded rows.
- The table headers and displayed rows remain consistent with the selected family and source.

## Out Of Scope

- Real-time visualization of full captures beyond the active measurement window.
- Offline analysis plotting.
