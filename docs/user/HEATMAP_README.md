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

## Runtime Architecture

The current heatmap path is split across these files:

- `data_processing/heatmap_processor.py`: shared heatmap state and per-package setup
- `data_processing/heatmap_piezo_processor.py`: piezo/PZT intensity and CoP processing
- `data_processing/heatmap_555_processor.py`: 555/PZR displacement heatmap processing
- `data_processing/heatmap_signal_processing.py`: per-channel conditioning for heatmap magnitude extraction
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

## Saved Settings

The GUI keeps separate last-used settings files for the two heatmap modes:

- `~/.adc_streamer/heatmap/last_used_heatmap_settings_PZT.json`
- `~/.adc_streamer/heatmap/last_used_heatmap_settings_PZR.json`

The Heatmap tab also lets you save or load arbitrary exported heatmap settings JSON files from the UI.

`plus_heatmap_config.json` in the repo root is not part of the automatic startup path for the current app.

## Related Controls

The Heatmap tab exposes controls for:

- package-level thresholds and calibration
- RMS or integration windows
- DC removal mode and high-pass cutoff
- blob size and smoothing
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
