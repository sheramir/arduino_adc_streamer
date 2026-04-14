# Arduino ADC Streamer

Desktop GUI and firmware workspace for streaming ADC data from MG24 and Teensy boards, visualizing sensor packages in real time, and exporting aligned capture data.

## Current App Features

- Real-time ADC plotting with selectable channels, repeat handling, baseline subtraction, and rolling window controls
- Shared live filtering for time-series and spectrum views
- Spectrum tab with FFT and Welch PSD modes
- Force-sensor overlay with timestamp alignment against ADC capture timing
- Heatmap and shear views for grouped multi-channel sensor packages
- Editable sensor library with both 5-channel layouts and 3x3 array layouts
- Archive-backed capture flow with full-view reload for captures larger than RAM
- CSV export, metadata export, and plot image export

## Quick Start

1. Flash one of the supported sketches from [Arduino_Sketches/README.md](Arduino_Sketches/README.md).
2. Install dependencies.

   ```bash
   uv sync
   ```

   Or with `pip`:

   ```bash
   pip install -r requirements.txt
   ```

3. Launch the GUI.

   ```bash
   python adc_gui.py
   ```

   Or with `uv`:

   ```bash
   uv run adc_gui.py
   ```

4. Connect the MCU, configure channels or sensors, and start capture from the GUI.

## Repository Layout

### Application

- `adc_gui.py`: main PyQt application entry point
- `config_constants.py`: shared defaults and numeric limits
- `config/`: MCU detection, config state, sensor library helpers, and channel-selection logic
- `serial_communication/`: ADC and force connection workflows, sessions, parser, and reader threads
- `data_processing/`: binary parsing, filtering, plotting, force processing, heatmap, shear, spectrum, and capture lifecycle
- `gui/`: tab construction and UI panels for time series, heatmap, shear, display, sensor, and spectrum views
- `file_operations/`: archive loading, export, plot export, and settings persistence helpers

### Firmware

- `Arduino_Sketches/MG24/`: MG24-based ADC streamer sketches
- `Arduino_Sketches/Teensy/`: Teensy ADC and 555-resistance sketches
- `Arduino_Sketches/Teensy_MG24_SPI/`: specialized Teensy + MG24 SPI array sketches

### Configuration And Data

- `sensors_library/sensor_configurations.json`: bundled starter sensor library shipped with the repo
- `~/.adc_streamer/sensors/sensor_configurations.json`: user-edited sensor library persisted by the GUI
- `~/.adc_streamer/heatmap/`: last-used heatmap settings saved per mode
- `~/.adc_streamer/shear/`: last-used shear settings saved per mode
- `~/.adc_streamer/spectrum/`: last-used spectrum settings

### Tests And Docs

- `tests/`: current automated regression coverage
- `docs/user/`: user-facing guides for array configuration and heatmap behavior
- `docs/architecture/`: implementation notes for active subsystems
- `docs/history/`: historical refactor logs and milestone notes

## Recommended Documentation

- [Arduino_Sketches/README.md](Arduino_Sketches/README.md): current firmware sketch map and serial protocol summary
- [docs/user/ARRAY_CONFIGURATION_GUIDE.md](docs/user/ARRAY_CONFIGURATION_GUIDE.md): configuring bundled and custom sensor layouts
- [docs/user/HEATMAP_README.md](docs/user/HEATMAP_README.md): heatmap modes, inputs, and saved settings behavior
- [docs/history/FORCE_SENSOR_REFACTOR_PLAN.md](docs/history/FORCE_SENSOR_REFACTOR_PLAN.md): future force-path cleanup roadmap

## Testing

Run the current automated tests with:

```bash
python -m pytest
```

Or:

```bash
uv run pytest
```

## Notes

- The bundled sensor library is loaded from `sensors_library/` when present, then overlaid by the user library under `~/.adc_streamer/sensors/`.
- `plus_heatmap_config.json` is a legacy root-level sample file and is not part of the automatic heatmap startup path.
