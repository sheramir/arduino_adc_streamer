# Sensors Library

This folder holds the bundled "starter" sensor library shipped with the Arduino ADC Streamer
repo. At startup, `config.sensor_config.SensorConfigStore` reads this file as the base sensor
library, then overlays any user edits persisted under `~/.adc_streamer/sensors/sensor_configurations.json`.
Sensor configs define how the 5 PZT/PZR channels of a sensor package map to physical T/R/C/L/B
positions, and optionally how multiple sensor packages are wired into a 3x3 array layout with MUX
routing (and, for PZT_RS boards, RS_MUX rosette-channel routing).

## Files

### sensor_configurations.json

Data file, not code. Top-level shape:

- `version` (int) — schema version, currently `1`.
- `selected_name` (string) — name of the configuration selected by default.
- `deleted_names` (list of strings) — bundled-config names the user has deleted locally (used by
  `SensorConfigStore` to suppress bundled entries the user removed).
- `configurations` (list of objects) — each entry is a named sensor configuration:
  - `name` (string) — unique configuration name.
  - `channel_sensor_map` (list of 5 strings) — maps ADC channel index (0-4) to a sensor position
    code (`T`, `R`, `C`, `L`, `B`).
  - `type` (string) — `"channel_layout"` for a plain 5-channel package, or `"array_layout"` for a
    multi-package 3x3 array.
  - `reverse_polarity` (bool) — whether piezo time-series and pressure-map processing should invert this package's polarity.
  - For `"array_layout"` entries only:
    - `array_layout.cells` — a 3x3 grid (list of 3 lists of 3 entries) where each cell is either
      `null` or a sensor ID string like `"PZT1"`/`"PZR2"`.
    - `mux_mapping` — per-sensor-ID object with `mux` (1 or 2), `channels` (list of up to 5 ADC
      channel indices), and `rs_channels` (list of 0-2 RS_MUX channel indices used only in PZT_RS mode).
    - `channel_layout.channels_per_sensor` — number of ADC channels each array cell/sensor uses (currently 5).

The current file defines 7 configurations: `PLUS`, `OCTO`, `ARRAY_v1_R`, `ARRAY_v1` (all plain
channel layouts), and `Array_V2`, `Single_PZT_New_grey_wire`, `Array_PCB1.7` (the latter two being
array layouts with MUX/RS_MUX routing). `selected_name` is `"Array_PCB1.7"`, and `Single_PZT_New`
is listed as deleted.

## Notes

- This is a pure data folder with no Python source — there is nothing to list under code
  files/functions. This matches the root README's description of `sensors_library/` as the
  "bundled starter sensor library shipped with the repo."
- Loading/normalization/persistence logic for this file lives in `config/sensor_config.py`
  (`SensorConfigStore`, `normalize_combined_sensor_config`, etc.), not in this folder.
