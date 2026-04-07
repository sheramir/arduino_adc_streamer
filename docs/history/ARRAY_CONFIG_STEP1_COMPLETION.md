# Step 1: Array Sensor Configuration Layout Implementation - COMPLETED

## Summary

Successfully implemented the array sensor configuration GUI in the Sensor tab, enabling users to configure a 3×4 matrix of PZT/PZR sensors with MUX assignments and channel mappings.

## Files Modified

### 1. **sensor_config.py**
- **Added**: Array configuration constants
  - `ARRAY_ROWS = 4`
  - `ARRAY_COLS = 3`
  - `ARRAY_CELL_CHANNELS_MAX = 5`

- **Added**: Array validation functions
  - `validate_sensor_id()` - Validates PZT_N/PZR_N format
  - `normalize_array_cell()` - Normalizes and validates cell values
  - `normalize_array_layout()` - Validates 3×4 matrix structure
  - `normalize_mux_mapping()` - Validates MUX configuration
  - `get_sensors_from_array_layout()` - Extracts all sensor IDs from array
  - `normalize_array_config()` - Complete array configuration validation

- **Modified**: `_read_sensor_configs_file()`
  - Now supports both `channel_layout` and `array_layout` configuration types
  - Auto-detects configuration type and normalizes accordingly

- **Modified**: `SensorConfigStore` class
  - Updated `load()` method to handle both configuration types
  - Updated `save()` method to persist both types
  - Maintains backward compatibility with existing channel_layout configs

### 2. **gui/sensor_panel.py**
- **Added**: Array layout editor widgets
  - 3×4 QLineEdit grid for array matrix
  - QTableWidget for MUX configuration
  - QSpinBox for channels per sensor

- **Added**: Configuration type selector
  - Dropdown to choose between "Channel Layout" and "Array Layout"
  - Auto-switches editor tabs based on config type

- **Modified**: `create_sensor_tab()`
  - Added QTabWidget to switch between Channel Layout and Array Layout editors
  - Displays appropriate editor based on config type

- **Added**: New methods
  - `_create_channel_layout_editor()` - Channel layout editor widget
  - `_create_array_layout_editor()` - Array layout editor widget
  - `_load_channel_layout_into_editor()` - Load channel config into UI
  - `_load_array_layout_into_editor()` - Load array config into UI
  - `_refresh_mux_table()` - Refresh MUX configuration table
  - `_save_channel_layout_from_editor()` - Save channel config
  - `_save_array_layout_from_editor()` - Save array config
  - `get_active_array_layout()` - Get active array configuration
  - `get_active_array_sensors()` - Get sensors in active array

- **Added**: Event handlers
  - `on_sensor_type_changed()` - Handle config type switching
  - `on_save_sensor_config_clicked()` - Save configuration
  - `on_array_cell_edited()` - Handle array matrix edits
  - `on_array_channels_per_sensor_changed()` - Handle channels per sensor change

- **Modified**: Existing methods for dual-mode support
  - `_refresh_sensor_tab_ui()` - Handles both config types
  - `_load_active_sensor_into_editor()` - Routes to appropriate editor
  - `get_active_channel_sensor_map()` - Returns empty for array layouts
  - `on_add_sensor_config_clicked()` - Creates both config types
  - `save_sensor_configurations()` - Persists both types

## Key Features

### 1. Configuration Type Management
- Create new configurations as either "Channel Layout" or "Array Layout"
- Switch between configs seamlessly
- Store both types in the same persistence system

### 2. Array Layout Editor
- **3×4 Matrix Grid**: Input sensor IDs (PZT_N, PZR_N) or leave empty
- **Validation**: Ensures proper format and prevents typos
- **Visual Feedback**: Clear placeholder text for each position

### 3. MUX Configuration Table
- **Auto-populated**: Table rows auto-generated from array sensors
- **Editable Columns**: MUX number and channels per sensor
- **Read-only Sensor Column**: Prevents accidental sensor renames

### 4. Channels Per Sensor
- **Spinner Control**: Set 1–5 channels per sensor
- **Default**: 5 channels (typical for 5-position sensor)

### 5. Data Persistence
- **Auto-save**: Configurations saved when "Save" button clicked
- **Auto-load**: Last active configuration loads on GUI startup
- **JSON Format**: Human-readable config files in ~/.adc_streamer/
- **Backward Compatible**: Existing channel_layout configs unchanged

### 6. Configuration Validation
- Validates sensor IDs (must be PZT_N or PZR_N)
- Checks MUX numbers (1 or 2)
- Validates channel ranges (0–9)
- Prevents duplicate channels in same MUX
- Ensures all sensors have MUX mappings

## Configuration Storage

### Location
```
~/.adc_streamer/sensors/sensor_configurations.json
```

### Example File Content
```json
{
  "version": 1,
  "selected_name": "My Array Setup",
  "deleted_names": [],
  "configurations": [
    {
      "name": "My Array Setup",
      "type": "array_layout",
      "array_layout": {
        "cells": [
          ["PZT_1", "PZT_2", "PZT_3"],
          ["PZR_1", "PZR_2", null],
          ["PZT_5", "PZR_3", null],
          [null, null, null]
        ]
      },
      "mux_mapping": {
        "PZT_1": {"mux": 1, "channels": [0, 1, 2, 3, 4]},
        "PZT_2": {"mux": 2, "channels": [0, 1, 2, 3, 4]}
      },
      "channel_layout": {"channels_per_sensor": 5}
    }
  ]
}
```

## User Workflow

1. **Open Sensor Tab** → See configuration selector
2. **Click "Add New"** → Choose config type
3. **Select "Array Layout"** → Switch to Array editor
4. **Layout Array** → Enter sensor IDs in 3×4 grid
5. **Configure MUX** → Set MUX and channels for each sensor
6. **Set Channels** → Specify channels per sensor (1–5)
7. **Click "Save"** → Persist configuration
8. **Switch Configs** → Select different config from dropdown

## Integration Points (For Future Steps)

### Step 2: Acquisition Settings Integration
- Modify `control_panels.py` to detect MCU type "Array*"
- Replace "Channel Selection" input with "Sensor Selection"
- Auto-generate channel list from selected sensors

### Step 3: Display Integration
- Modify time series display to show "PZT1_1", "PZT1_2", etc.
- Update heatmap to visualize physical array layout
- Update shear panel with sensor geometry

## Testing Checklist

- ✅ Configuration saves without errors
- ✅ Configuration loads on GUI restart
- ✅ Array layout validation works (rejects invalid sensor IDs)
- ✅ MUX configuration table respects constraints
- ✅ Switching between Channel/Array layout types
- ✅ Adding/deleting configurations
- ✅ Renaming configurations
- ✅ Both config types coexist in same file

## Documentation

- **ARRAY_CONFIGURATION_GUIDE.md** - User guide with examples and troubleshooting

## Next Steps

1. **Step 2**: Integrate array configurations into Acquisition Settings
   - Create sensor selector in acquisition tab
   - Auto-generate channel list from selected sensors
   - Pass sensor aliases to data processor

2. **Step 3**: Update display pipelines
   - Rename channels in time series display
   - Visualize array geometry in heatmap
   - Update shear processor with sensor info

3. **Advanced**: Visual array editor
   - Drag-and-drop sensor placement
   - Live preview of array geometry
   - Quick MUX assignment buttons

