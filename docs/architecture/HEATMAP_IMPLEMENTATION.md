# Heatmap Implementation Notes

## Purpose

This document summarizes how the current heatmap feature is organized in the codebase and preserves a small amount of historical context from the original rollout.

## Current File Map

- `adc_gui.py`: initializes heatmap state, loads last-used settings, and drives timer-based updates
- `gui/heatmap_panel.py`: builds the heatmap tab, mode-specific controls, overlays, and settings save/load actions
- `data_processing/heatmap_processor.py`: shared state, buffers, and processor composition
- `data_processing/heatmap_piezo_processor.py`: piezo/PZT heatmap generation
- `data_processing/heatmap_555_processor.py`: 555/PZR displacement heatmap generation
- `data_processing/heatmap_signal_processing.py`: per-channel conditioning used by heatmap magnitude calculations
- `config/config_handlers.py`: sensor grouping and channel-selection helpers shared by heatmap and shear
- `config_constants.py`: default heatmap dimensions, thresholds, and related constants

## Behavior Summary

The current implementation:

- runs from live captured data instead of a simulated source
- supports both piezo/PZT and 555/PZR heatmap modes
- shares package grouping with the shear view
- persists last-used settings per visualization mode under `~/.adc_streamer/heatmap/`
- keeps the display path timer-driven while reusing preallocated heatmap buffers

## Historical Context

The original heatmap rollout introduced the heatmap tab as a modular addition across the GUI, processing, and configuration layers. The simulated-data path that existed early in development has since been removed from the active application.

For current user-facing behavior, see [../user/HEATMAP_README.md](../user/HEATMAP_README.md).
