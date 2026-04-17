# Legacy Heatmap, Shear, And Display Modules

This folder preserves the previous heatmap, shear, and combined Display tab implementations for future reference or rollback.

The active application no longer imports these modules. Current runtime tabs are:

- Time Series
- Spectrum
- Sensor

The legacy regression tests import these modules through the `Legacy` package so the archived processing behavior remains executable while new implementations are developed.

Legacy-only visualization defaults live in `Legacy/config_constants.py`; active application constants remain in the root `config_constants.py`.
