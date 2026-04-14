# Array Sensor Configuration Guide

## Overview

The sensor library supports two configuration types:

- `channel_layout`: a single 5-channel package using the logical positions `T`, `R`, `C`, `L`, and `B`
- `array_layout`: a 3x3 grid of named sensors with per-sensor MUX and channel assignments

This guide covers the current array-layout path used by the GUI.

## Current Array Model

The current editor in the Sensor tab uses:

- a `3 x 3` array grid
- sensor IDs in canonical form such as `PZT1` or `PZR2`
- optional legacy input such as `PZT_1`, which is normalized when saved
- `1..5` logical channels per sensor
- MUX IDs `1..2`
- physical channel indices `0..15`

## What Array Layouts Affect

An active array configuration is used to:

- resolve selected array sensors into physical acquisition channels
- build display labels for the time-series view
- define package grouping used by the heatmap and shear tabs
- persist the selected sensor library entry across app restarts

## Where Configurations Are Stored

- Bundled starter library: `sensors_library/sensor_configurations.json`
- User-edited library: `~/.adc_streamer/sensors/sensor_configurations.json`

The app loads the bundled library first when available, then overlays user edits from the local settings path.

## Creating Or Editing An Array Layout

1. Open the `Sensor` tab.
2. Create a new configuration or select an existing one.
3. Set the configuration type to `Array Layout`.
4. Fill the `3 x 3` array grid with sensor IDs such as `PZT1`, `PZR2`, or leave cells blank.
5. Add a MUX mapping for every sensor present in the grid.
6. Set `Channels per Sensor` to match the hardware layout.
7. Save the configuration.

## Example Layout

Example `3 x 3` grid:

```text
[PZT1] [PZT2] [PZT3]
[PZR4] [PZT5] [PZR6]
[   ]  [PZT7] [   ]
```

Example MUX mapping:

```text
PZT1 -> MUX 1, Channels 0,1,2,3,4
PZT2 -> MUX 1, Channels 5,6,7,8,9
PZT3 -> MUX 2, Channels 0,1,2,3,4
PZR4 -> MUX 2, Channels 5,6,7,8,9
```

## How Acquisition Mapping Works

During acquisition:

1. The selected array sensors are converted into the set of unique physical channels required by the active layout.
2. The MCU receives that physical channel list in acquisition order.
3. The GUI remaps the returned samples back into sensor-aware labels for display and processing.

This means the physical stream can contain shared or de-duplicated channels, while the GUI still renders the selected sensors using sensor-specific labels.

## Example JSON Shape

```json
{
  "name": "Array_V2",
  "type": "array_layout",
  "channel_sensor_map": ["T", "R", "C", "B", "L"],
  "array_layout": {
    "cells": [
      [null, "PZT7", null],
      ["PZT1", "PZR6", "PZT5"],
      ["PZR2", "PZT3", "PZR4"]
    ]
  },
  "mux_mapping": {
    "PZT1": {
      "mux": 1,
      "channels": [0, 1, 2, 3, 4]
    },
    "PZR2": {
      "mux": 2,
      "channels": [0, 1, 2, 3, 4]
    }
  },
  "channel_layout": {
    "channels_per_sensor": 5
  }
}
```

## Validation Rules

- Every populated cell must be a valid `PZTn` or `PZRn` sensor ID.
- Every sensor in the grid must have a MUX mapping.
- MUX values must stay within `1..2`.
- Physical channels must stay within `0..15`.
- `channels_per_sensor` must stay within `1..5`.

## Troubleshooting

| Issue | Likely cause | What to check |
| --- | --- | --- |
| Array config will not save | Invalid sensor ID or incomplete MUX mapping | Check every populated grid cell has a matching mapping row |
| Sensors display the wrong channels | MUX/channel assignments do not match wiring | Compare the saved mapping with the hardware wiring |
| Heatmap or shear view is empty | Selected sensors do not form valid grouped input for the active mode | Verify sensor selection, mode, and channel count |

## Related Files

- `config/sensor_config.py`: normalization, validation, and persistence helpers
- `gui/sensor_panel.py`: Sensor tab editor and save/load behavior
- `config/config_handlers.py`: mapping from selected sensors to acquisition channels
- `docs/user/HEATMAP_README.md`: how array layouts feed the heatmap path
