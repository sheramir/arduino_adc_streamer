# Arduino ADC Streamer

Desktop GUI and firmware workspace for high-speed sensor acquisition, plotting, force sensing, heatmap visualization, and export.

## Quick Start

1. Upload the recommended firmware from `Arduino_Sketches/MG24/ADC_Streamer_binary_scan/`.
2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the GUI:
   ```bash
   python adc_gui.py
   # or
   uv run adc_gui.py
   ```

## Repository Layout

### Application
- `adc_gui.py` - main GUI entry point
- `config/` - board detection, configuration, and buffer helpers
- `serial_communication/` - ADC and force serial communication
- `data_processing/` - capture, plotting, filtering, heatmap, shear, and spectrum logic
- `gui/` - panel construction and GUI widgets
- `file_operations/` - export and archive loading

### Firmware
- `Arduino_Sketches/` - MG24, Teensy, and SPI sketch variants

### Tests
- `tests/` - current automated test modules

### Documentation
- `docs/user/ARRAY_CONFIGURATION_GUIDE.md` - configuring array sensor layouts
- `docs/user/HEATMAP_README.md` - current heatmap behavior and usage
- `docs/architecture/HEATMAP_IMPLEMENTATION.md` - implementation notes
- `docs/history/` - historical refactor and phase-completion notes

## Main Features

- Real-time ADC plotting with configurable windowing
- Full-view loading from archive cache when captures exceed RAM
- Live force overlay synchronized against ADC capture timing
- Heatmap views for grouped 5-channel sensors and array sensor layouts
- Shear / center-of-pressure view for MG-24 piezo layouts
- Shared filtering pipeline for time series and spectrum views
- CSV export, plot export, and cached archive capture

## Configuration Files

These bundled config files intentionally remain at the repository root because the app loads them from there:

- `sensor_configurations.json`
- `sensors.json`
- `plus_heatmap_config.json`

## Notes

- Historical docs were moved under `docs/history/` to keep the root focused on the runnable app and active project files.
- The root-level `tests/` directory now contains the real automated tests; old one-off diagnostic scripts were removed.
