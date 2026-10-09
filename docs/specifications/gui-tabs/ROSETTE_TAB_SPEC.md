# Rosette Tab Specification

Owner: Host application GUI/live plotting stack  
Status: Implemented, conditional on `PZT_RS` mode  
Date: 2026-07-08

## Purpose

The Rosette tab provides a dedicated live view for Rosette resistance traces and aligned force data when the active sensor/mode supports `PZT_RS`. It separates Rosette-specific visualization from the main PZT time-series view.

## Availability

- The tab is hidden by default.
- The tab becomes visible only when the active mode is `PZT_RS`.
- When visible, the Time Series tab is relabeled to the PZT-specific tab label and the Rosette tab appears beside it.

## UI Behavior

- Plot group titled `Rosette Time Series`.
- Dual-axis plot:
  - Left axis for resistance.
  - Right axis for force in Newtons.
- Rosette info label shows sweep and sample counts.
- Rosette Visualization Controls include:
  - Dynamic Rosette checklist with All/None buttons.
  - Subtract Baseline and Zero Signals controls.
  - Optional moving average with sample-count control.
  - Y-range mode: Adaptive or Fixed, with fixed min/max controls shown only in Fixed mode.
  - Force visibility toggles for X Force and Z Force.

## Runtime Behavior

- Rosette plots synchronize their force overlay X range one-way from the Rosette plot to avoid autorange feedback loops.
- Baseline subtraction and moving average are display-only behaviors.
- If Rosette mode is turned off while the Rosette tab is active, focus returns to the Time Series tab.

## Persistence

- This tab uses current GUI/runtime state and mode visibility rather than a dedicated tab-specific settings file.

## Acceptance Criteria

- The Rosette tab appears only for compatible mode selection.
- Rosette trace visibility changes redraw the plot without affecting non-Rosette tabs.
- Fixed Y range shows and honors min/max settings only in Fixed mode.
- X and Z force overlays can be shown or hidden independently.

## Out Of Scope

- Pressure-map or heatmap rendering.
- Offline analysis workflows.
