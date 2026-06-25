# Legacy Heatmap, Shear, And Display Modules

This folder preserves the previous heatmap, shear, and combined Display tab implementations for future reference or rollback.

The active application now contains promoted copies of the legacy heatmap GUI and
processing code under `gui/`, `data_processing/`, and `constants/`. The files in
this folder remain archived source copies for reference or rollback.

Current runtime tabs include:

- Time Series
- Pressure Map
- Heatmap
- Spectrum
- Sensor

The legacy regression tests import these modules through the `Legacy` package so the archived processing behavior remains executable while new implementations are developed.

Legacy-only visualization defaults live in `Legacy/config_constants.py`; active application constants remain in the root `config_constants.py`.

## Files

- `__init__.py` — empty package marker file.
- `config_constants.py` — legacy-only constants for the archived heatmap/shear/Display modules: heatmap resolution and FPS, piezo sensor positions/calibration/noise-floor, Gaussian blob and smoothing parameters, confidence-scoring parameters, RMS window and DC-removal settings, 555/PZR-specific thresholds and smoothing, and shear integration/calibration/visualization constants. Imports `DEFAULT_SENSOR_CONFIGURATION` from the active `constants.sensor_config` module to build the default channel-to-sensor map.

## Subfolders

- `data_processing/` — archived heatmap (piezo and 555/PZR) and shear/CoP signal-processing pipelines. See `data_processing/README.md` for a per-file function listing.
- `gui/` — archived PyQt6 mixins building the 2D Heatmap, Shear, and combined Display tabs and their settings panels. See `gui/README.md` for a per-file function listing.
- `__pycache__/` — Python bytecode cache, not source; ignored.
