# Heatmap Tab Specification

Owner: Host application GUI/heatmap-processing stack  
Status: Implemented  
Date: 2026-07-08

## Purpose

The Heatmap tab provides a live 2D sensor-intensity display for PZT and PZR workflows. It supports per-package cards, combined display layouts, configurable color maps and overlays, and mode-specific processing settings.

## UI Behavior

- Nested inner tabs: Display and Settings.
- Display tab presents the live heatmap area, including per-package cards and combined display behavior for current layout mode.
- Settings tab includes:
  - Signal Processing controls.
  - PZR Parameters.
  - Noise Threshold controls.
  - Per-Sensor Calibration.
  - Heatmap Parameters.
- Heatmap Parameters include display geometry controls such as sensor size, gap, color map, mirror/orientation, and point tracking.
- Status text reports incompatible channel counts or other display prerequisites.

## Data Pipeline

1. Use the current live acquisition buffer.
2. Select the active processing path for PZT or PZR mode.
3. Apply configured bias-removal and threshold behavior.
4. Generate per-sensor intensities.
5. Build per-package and/or combined display images.
6. Render heatmap cards and overlays, including point tracking when enabled.

## Runtime Behavior

- The main app updates the tab when Heatmap is visible and when relevant live data arrives.
- The active display path supports both individual package display and array-oriented point tracking.
- Overlay and geometry changes affect rendering immediately without changing the raw input data.

## Persistence

- Last-used Heatmap settings autosave under the user `.adc_streamer` settings path.
- Save/load actions support explicit Heatmap settings files.
- Persisted state includes mode-specific settings and live display geometry values.

## Acceptance Criteria

- Heatmap renders live sensor intensity using the active mode pipeline.
- Users can change color map, geometry, overlays, and thresholds from the Settings tab.
- Array point tracking and display geometry remain available in supported layouts.
- Missing required channels surfaces a clear status message.

## Out Of Scope

- Force-calibration table workflows.
- Offline CSV+JSON file browsing.
