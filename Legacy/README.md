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
