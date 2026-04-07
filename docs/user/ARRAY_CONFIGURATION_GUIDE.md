# Array Sensor Configuration Guide

## Overview

The Array Configuration system allows you to organize multiple PZT (Piezoelectric) and PZR (Piezoelectric Resistor) sensors in a 3×4 matrix layout, with flexible MUX (multiplexer) assignments and channel mappings.

## Configuration Structure

### 1. Array Layout (3×4 Matrix)

The physical arrangement of sensors in a grid:
- **3 Columns** (horizontal)
- **4 Rows** (vertical)
- Total of 12 potential sensor positions

Each cell can contain:
- **Sensor ID**: Format `PZT_N` or `PZR_N` (e.g., `PZT_1`, `PZR_2`)
- **Empty**: Leave blank if no sensor at that position

**Example Array Layout:**
```
[PZT_1]  [PZT_2]  [PZT_3]
[PZR_1]  [PZR_2]  [Empty]
[PZT_5]  [PZR_3]  [PZT_8]
[Empty]  [PZT_9]  [Empty]
```

### 2. Channel Layout

Specifies the number of channels per sensor:
- **Channels per Sensor**: 1–5 (default: 5)
- This defines how many physical ADC channels each sensor uses

### 3. MUX Configuration

For each sensor in the array, configure:
- **MUX Number**: Which MUX board (1 or 2)
- **Channels**: Comma-separated list of physical channels (0–9) on that MUX

**Example MUX Configuration:**
```
PZT_1:  MUX=1, Channels=0,1,2,3,4
PZT_2:  MUX=2, Channels=0,1,2,3,4
PZT_3:  MUX=2, Channels=5,6,7,8,9
PZR_1:  MUX=1, Channels=5,6,7,8,9
```

**Channel Mapping Semantics:**
- The array of physical channels is passed to the MCU as-is
- During acquisition, if you select **PZT_1** and **PZT_3** from the same MUX, the Arduino reads **all unique channels** from both sensors simultaneously
- The Python GUI displays only the selected sensors' channels, labeled as `PZT1_1`, `PZT1_2`, ... `PZT3_1`, `PZT3_2`, etc.

## Using Array Configurations in the GUI

### Step 1: Create a New Array Configuration

1. Open the **Sensor** tab
2. Click **"Add New"** button
3. In the **Type** dropdown, select **"Array Layout"**
4. A new configuration with default blank array is created

### Step 2: Configure Array Layout

1. Click on the **"Array Layout"** tab (appears in the editor area)
2. In the **"Array Layout (3×4)"** grid, enter sensor IDs:
   - Click each cell to enter `PZT_N` or `PZR_N`
   - Leave empty for unused positions
3. Click **"Save"** to confirm

### Step 3: Configure MUX Assignments

1. In the **"MUX Configuration"** section of the Array Layout tab:
   - The table auto-populates with all sensors from your array
   - For each sensor, set:
     - **MUX (1-2)**: Which MUX board
     - **Channels**: Comma-separated physical channels (0–9)
2. Example: `PZT_1` on MUX 1 with channels `5,6,7,8,9`
3. Click **"Save"** to confirm

### Step 4: Set Channels per Sensor

1. In **"Channels per Sensor"** spinner (default: 5)
   - Set the number of channels each sensor reports
   - Used for data interpretation during acquisition
2. Click **"Save"** to confirm

### Step 5: Save Configuration

1. Click **"Save"** button to persist the configuration
2. Configuration is saved locally (`~/.adc_streamer/sensors/sensor_configurations.json`)
3. Last active configuration auto-loads on GUI restart

## Example: Complete Array Configuration

**Setup:**
- 4 PZT sensors in a 2×2 pattern
- Each sensor has 5 channels
- Sensors on MUX 1: PZT_1, PZT_2
- Sensors on MUX 2: PZT_3, PZT_4

### Array Layout:
```
[PZT_1]  [PZT_2]  [Empty]
[PZT_3]  [PZT_4]  [Empty]
[Empty]  [Empty]  [Empty]
[Empty]  [Empty]  [Empty]
```

### MUX Configuration:
```
Sensor    | MUX | Channels
----------|-----|------------------
PZT_1     |  1  | 0,1,2,3,4
PZT_2     |  1  | 5,6,7,8,9
PZT_3     |  2  | 0,1,2,3,4
PZT_4     |  2  | 5,6,7,8,9
```

### Channels Per Sensor: 5

## Data Flow During Acquisition

1. **Configuration Phase**:
   - Arduino receives channel configuration
   - Based on MUX assignments, Arduino selects which channels to read
   - Example: If firmware detects MUX 1 has channels [0,1,2,3,4,5,6,7,8,9], it reconfigures both PZT_1 and PZT_2 simultaneously

2. **Acquisition Phase**:
   - Arduino reads selected channels from both MUXes
   - Data blocks contain 12 channels (5 from PZT_1 + 5 from PZT_2 on MUX 1, then 5 from PZT_3 + 5 from PZT_4 on MUX 2)

3. **Display Phase**:
   - Python GUI receives raw 12-channel data
   - Remaps channels to sensor names using MUX configuration
   - Time series plot displays: `PZT1_1`, `PZT1_2`, ..., `PZT3_1`, `PZT3_2`, etc.
   - Heatmap/Shear panels show only selected sensors

## Configuration File Format

Array configurations are stored in JSON format:

```json
{
  "name": "My Array Setup",
  "type": "array_layout",
  "array_layout": {
    "cells": [
      ["PZT_1", "PZT_2", "PZT_3"],
      ["PZR_1", "PZR_2", null],
      ["PZT_5", "PZR_3", "PZT_8"],
      [null, "PZT_9", null]
    ]
  },
  "mux_mapping": {
    "PZT_1": {
      "mux": 1,
      "channels": [0, 1, 2, 3, 4]
    },
    "PZT_2": {
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

- All sensor IDs must match `PZT_N` or `PZR_N` format (N > 0)
- MUX numbers must be 1 or 2
- Channels must be integers 0–9 (10 channels per MUX)
- No duplicate channel assignments within a single MUX
- All sensors in the array must have MUX mappings

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| "Save" button doesn't work | Invalid MUX table entry | Check all MUX entries are valid integers |
| Array not loading | Configuration corrupted | Delete config and recreate |
| Channels misaligned in time series | MUX/channel mapping error | Verify MUX table matches wiring |

## Future Steps

1. **Acquisition Integration** (Step 2):
   - Modify acquisition settings to show sensor selector instead of raw channels
   - Auto-generate channel list from selected sensors

2. **Display Integration** (Step 3):
   - Update time series plot to use `SensorN_ChannelN` naming
   - Update heatmap to visualize array geometry

3. **Advanced Features**:
   - Save/load array configurations from files
   - Visual array editor with drag-and-drop
   - Sensor geometry visualization for heatmap overlay

