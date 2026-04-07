# Heatmap Guide

## Overview

The heatmap tab renders grouped 5-channel sensor data as a center-of-pressure view with live intensity, coordinate readouts, and per-channel values.

The current app no longer uses a simulated heatmap source. Heatmap updates are driven by real captured data from the active buffers.

## Current Architecture

The heatmap path is split across these modules:

- `data_processing/heatmap_processor.py` - shared heatmap state and setup
- `data_processing/heatmap_piezo_processor.py` - piezo/PZT heatmap intensity processing
- `data_processing/heatmap_555_processor.py` - 555/PZR displacement heatmap processing
- `gui/heatmap_panel.py` - heatmap widgets, controls, readouts, and rendering
- `config/config_handlers.py` - sensor grouping and heatmap-related configuration helpers

## How Channel Grouping Works

Heatmap processing is based on normalized sensor package grouping.

- In array mode, the app uses the active array configuration and MUX mapping.
- In manual channel mode, the app groups channels into 5-channel sensor packages when the selection is compatible with the active sensor layout.
- The same sensor-package grouping is shared by both heatmap and shear processing so the two views interpret channel layout consistently.

## Heatmap Modes

### Piezo / PZT

The piezo heatmap computes per-channel intensities over a recent time window and builds a center-of-pressure view from the active sensor package.

### 555 / PZR

The 555 heatmap uses the 555 displacement processing path, thresholding, and per-channel baselines to compute display values and center-of-pressure.

## UI Behavior

The heatmap tab provides:

- live heatmap image rendering
- center-of-pressure X/Y readouts
- intensity readout
- per-channel sensor value display
- channel placement mapping based on the active sensor configuration
- zeroing/baseline support for compatible modes

If the current configuration does not provide valid grouped 5-channel sensor data, the heatmap view will not render useful sensor packages.

## Configuration

Heatmap behavior depends on:

- sensor layout and channel placement configuration
- selected channels or selected array sensors
- active device mode (`adc` vs `555`)
- thresholds, gains, smoothing, and calibration values from the heatmap settings UI

For array layout setup, see `ARRAY_CONFIGURATION_GUIDE.md`.

## Performance Notes

The heatmap path is designed for live use:

- rendering is timer-driven in the GUI thread
- data extraction works from the rolling capture buffers
- processing avoids unnecessary recomputation where possible
- heatmap state is initialized once and reused during capture

## Related Files

- `config_constants.py` - default heatmap constants
- `plus_heatmap_config.json` - bundled heatmap configuration data
- `../architecture/HEATMAP_IMPLEMENTATION.md` - historical implementation notes
