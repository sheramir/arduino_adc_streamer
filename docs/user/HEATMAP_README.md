# Heatmap Guide

## Overview

The heatmap tab renders grouped sensor packages as a live center-of-pressure view. It is fed from the same rolling capture buffers used by the rest of the application rather than from a simulated source.

## What The Current App Supports

- live heatmap rendering for active sensor packages
- separate processing paths for piezo/PZT and 555/PZR modes
- center-of-pressure X/Y readouts
- intensity and confidence readouts
- per-channel value display
- shared package grouping with the shear view
- save/load controls for heatmap settings
- autosave and restore of the last-used heatmap settings for each mode
- optional array-wide `Point Tracking` display mode
- physical array geometry controls for `Sensor Size (mm)` and `Gap (mm)`

## Runtime Architecture

The current heatmap path is split across these files:

- `data_processing/heatmap_processor.py`: shared heatmap state and per-package setup
- `data_processing/heatmap_piezo_processor.py`: piezo/PZT intensity and CoP processing
- `data_processing/heatmap_555_processor.py`: 555/PZR displacement heatmap processing
- `data_processing/heatmap_signal_processing.py`: per-channel conditioning for heatmap magnitude extraction
- `data_processing/heatmap_point_tracker.py`: single-point selection across an array, including between-sensor pair handling
- `gui/heatmap_panel.py`: heatmap widgets, controls, save/load behavior, and rendering
- `config/config_handlers.py`: active sensor grouping and channel-selection helpers
- `adc_gui.py`: timer wiring and tab-driven update flow

## Input Requirements

Heatmap output depends on the active sensor configuration and selected device mode.

- In channel-layout mode, the app interprets compatible 5-channel packages using the active channel-to-position map.
- In array-layout mode, the app derives visible packages from the selected array sensors and their configured MUX/channel assignments.
- The shear view uses the same package grouping so both tabs stay spatially consistent.

If the current selection does not produce valid grouped sensor data, the heatmap view stays present but will not show useful package output.

## Heatmap Modes

### Piezo / PZT mode

The PZT path computes per-channel magnitudes over a recent integration window, applies the current calibration and threshold settings, and builds a center-of-pressure heatmap for each active package.

### 555 / PZR mode

The PZR path uses the 555 displacement pipeline, baseline tracking, and thresholding to build smoothed displacement heatmaps and CoP output.

## Point Tracking

When `Point Tracking` is enabled in the Heatmap settings, the array display changes from "one heatmap per visible sensor" to "one tracked pressure point across the full array."

The current rules are:

- only one tracked heatmap point is rendered across the whole array
- if multiple sensors are active at the same time, the strongest valid point is shown
- if a sensor has multiple active channels, the point is resolved inside that sensor
- between-sensor points are only allowed for neighboring horizontal or vertical pairs
- horizontal gap points use the right channel of the left sensor and the left channel of the right sensor
- vertical gap points use the bottom channel of the upper sensor and the top channel of the lower sensor
- pair tracking is intended for edge-dominant signals near the gap; if a sensor shows broader multi-channel activity, tracking falls back to an in-sensor point

This lets the display represent a touch or pressure point that falls either on a sensor face or in the physical gap between two neighboring sensors.

## Display Geometry

The heatmap display treats `Sensor Size (mm)` as the physical sensor diameter in millimeters.

- default `Sensor Size (mm)`: `4.0`
- default `Gap (mm)`: `0.5`
- default `Point Tracking`: off

`Gap (mm)` is the physical free space between adjacent sensor edges, not center-to-center spacing.

Examples:

- if one sensor is directly above another, the gap is the distance from the lower edge of the upper sensor to the upper edge of the lower sensor
- if two sensors are side by side, the gap is the distance from the right edge of the left sensor to the left edge of the right sensor

When `Gap (mm)` is greater than zero, the circles in the array display are separated visually in the same proportion as the configured sensor diameter and gap. The outermost circles are fitted close to the display frame, so the available viewport is used efficiently.

## Saved Settings

The GUI keeps separate last-used settings files for the two heatmap modes:

- `~/.adc_streamer/heatmap/last_used_heatmap_settings_PZT.json`
- `~/.adc_streamer/heatmap/last_used_heatmap_settings_PZR.json`

The Heatmap tab also lets you save or load arbitrary exported heatmap settings JSON files from the UI.

The last-used settings now persist the display geometry and point-tracking controls alongside the existing heatmap processing settings. This includes:

- `Sensor Size (mm)`
- `Gap (mm)`
- `Point Tracking`

`plus_heatmap_config.json` in the repo root is not part of the automatic startup path for the current app.

## Related Controls

The Heatmap tab exposes controls for:

- package-level thresholds and calibration
- RMS or integration windows
- DC removal mode and high-pass cutoff
- blob size and smoothing
- array display geometry (`Sensor Size (mm)` and `Gap (mm)`)
- array-wide single-point tracking (`Point Tracking`)
- mode-specific PZR controls such as displacement thresholds and CoP smoothing

## Performance Notes

The heatmap path is designed for live use:

- rendering is timer-driven in the GUI thread
- reusable buffers and coordinate grids are initialized once
- window extraction works from the rolling in-memory capture buffers
- package processing avoids unnecessary recomputation where possible

## Related Docs

- [ARRAY_CONFIGURATION_GUIDE.md](ARRAY_CONFIGURATION_GUIDE.md): configuring sensor layouts and array mappings
- [../architecture/HEATMAP_IMPLEMENTATION.md](../architecture/HEATMAP_IMPLEMENTATION.md): implementation notes and historical context
