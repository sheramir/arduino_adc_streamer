# Specs

Formal feature specifications for implemented or intended app behavior. Planning prompts and step-by-step implementation plans live in `../Plans/`.

## Files

- `MAIN_APP_SPEC.md` — overall desktop app specification: splitter-based GUI layout, left control workflow, tabbed visualization workspace, shared runtime behaviors, persistence, and acceptance criteria.
- `TIME_SERIES_TAB_SPEC.md` — Time Series tab specification: live ADC/force plotting, channel visibility, view/window controls, baseline tools, and acceptance criteria.
- `ROSETTE_TAB_SPEC.md` — Rosette tab specification: conditional `PZT_RS` visibility, resistance/force plotting, Rosette-specific controls, and acceptance criteria.
- `PRESSURE_MAP_TAB_SPEC.md` — Pressure Map tab specification: integrated live processing, shear/normal derivation, pressure-map rendering, selectable color schemes, custom/voltage legends, settings persistence, and acceptance criteria.
- `HEATMAP_TAB_SPEC.md` — Heatmap tab specification: live PZT/PZR heatmap rendering, display geometry, overlays, persistence, and acceptance criteria.
- `FORCE_CALIBRATION_TAB_SPEC.md` — Force Calibration tab specification: live calibration-row capture, sensor/source selection, table behavior, persistence, and acceptance criteria.
- `SPECTRUM_TAB_SPEC.md` — Spectrum tab specification: FFT/Welch controls, live update lifecycle, settings persistence, and acceptance criteria.
- `ANALYSIS_TAB_SPEC.md` — Analysis tab specification: offline in-memory or CSV+JSON loading, legacy CSV compatibility, raw/integrated/shear-normal/force plots, load-cell Newton conversion, calculated PZT force, matched trace colors, stable marker/layout behavior, PNG image export, settings persistence, and acceptance criteria.
- `SENSOR_TAB_SPEC.md` — Sensor tab specification: sensor-library editing, channel/array layout configuration, validation, persistence, and acceptance criteria.
