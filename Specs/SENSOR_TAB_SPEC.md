# Sensor Tab Specification

Owner: Host application GUI/sensor-library stack  
Status: Implemented  
Date: 2026-07-08

## Purpose

The Sensor tab manages named sensor configurations used by the rest of the app. It supports simple five-position channel layouts and larger array layouts with MUX/channel assignment metadata.

## UI Behavior

- Active Sensor Configuration group includes:
  - Sensor configuration selector.
  - Editable configuration name.
  - Type selector: Channel Layout or Array Layout.
  - Reverse-polarity toggle.
  - Add New, Delete, and Save actions.
- Editor tabs:
  - Channel Layout tab for T/L/C/R/B mapping with numeric inputs and a live mapping preview.
  - Array Layout tab for a 3×3 matrix of named sensor positions, MUX configuration table, warning label, and channels-per-sensor control.
- Status label reports validation and save/delete feedback.

## Runtime Behavior

- Selecting a configuration repopulates the active editor fields.
- Renaming, type changes, position changes, and MUX-table edits update the in-memory configuration state.
- Validation prevents invalid or duplicate names and surfaces actionable warnings in the status area.
- At least one sensor configuration must remain available.

## Persistence

- Sensor configurations are loaded from the bundled library and overlaid by the user sensor library.
- Saving writes user-editable sensor configuration data to the persistent sensor store under the user home `.adc_streamer` path.

## Acceptance Criteria

- Users can create, edit, save, and delete supported sensor configurations from the GUI.
- Channel-layout editing preserves a five-position mapping workflow.
- Array-layout editing supports 3×3 placement plus MUX/channel metadata.
- Validation errors are surfaced without corrupting the active saved library.

## Out Of Scope

- Live plotting or analysis of sensor data.
- Calibration dataset capture.
