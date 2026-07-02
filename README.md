# Arduino ADC Streamer

Desktop GUI and firmware workspace for streaming ADC data from MG24 and Teensy boards, visualizing ADC and spectrum data in real time, and exporting aligned capture data.

## Current App Features

- Real-time ADC plotting with selectable channels, repeat handling, baseline subtraction, and rolling window controls
- Shared live filtering for time-series and spectrum views
- Spectrum tab with FFT and Welch PSD modes
- Heatmap tab using the promoted legacy PZT/PZR heatmap calculation path, with per-package display plus array-wide point tracking
- Pressure Map tab with per-package shear/normal visualization, array adjacent-package interpolation, package-boundary shape controls, and gap tuning
- Force-sensor overlay with timestamp alignment against ADC capture timing
- Editable sensor library with both 5-channel layouts and 3x3 array layouts
- Archive-backed capture flow with full-view reload for captures larger than RAM
- CSV export, metadata export, and plot image export

## Quick Start

1. Flash one of the supported sketches from [Arduino_Sketches/README.md](Arduino_Sketches/README.md).
2. Install dependencies.

   ```bash
   uv sync --extra dev
   ```

   Or with `pip`:

   ```bash
   pip install -r requirements.txt
   ```

   The `--extra dev` install includes `pytest` in the repo `.venv` so both `uv run pytest` and `python -m pytest` work from the workspace interpreter.

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
- `constants/`: shared defaults, numeric limits, and UI/runtime tuning values
- `config/`: MCU detection, config state, sensor library helpers, and channel-selection logic
- `serial_communication/`: ADC and force connection workflows, sessions, parser, and reader threads
- `data_processing/`: binary parsing, filtering, plotting, force processing, spectrum, and capture lifecycle
- `gui/`: tab construction and UI panels for time series, spectrum, sensor, controls, files, and status views
- `file_operations/`: archive loading, export, plot export, and settings persistence helpers
- `Legacy/`: archived source copies for older heatmap, shear, and combined Display tab implementations kept for reference or rollback

### Firmware

- `Arduino_Sketches/MG24/`: MG24-based ADC streamer sketches
- `Arduino_Sketches/legacy/`: archived firmware variants kept for reference
- `Arduino_Sketches/Teensy/`: Teensy ADC and 555-resistance sketches
- `Arduino_Sketches/Teensy_MG24_SPI/`: specialized Teensy + MG24 SPI array sketches

### Configuration And Data

- `sensors_library/sensor_configurations.json`: bundled starter sensor library shipped with the repo
- `~/.adc_streamer/sensors/sensor_configurations.json`: user-edited sensor library persisted by the GUI
- `~/.adc_streamer/spectrum/`: last-used spectrum settings

### Tests And Docs

- `tests/`: current automated regression coverage
- `docs/user/`: user-facing guides for array configuration and heatmap behavior
- `docs/architecture/`: implementation notes for active subsystems
- `docs/history/`: historical refactor logs and milestone notes

## Root Files

### `adc_gui.py`

Main application entry point. Defines `ADCStreamerGUI`, a `QMainWindow` subclass composed from the mixins in `serial_communication/`, `config/`, `gui/`, `data_processing/`, and `file_operations/`, plus a `main()` function that launches the Qt application.

- `main()` — creates the `QApplication`, instantiates `ADCStreamerGUI`, shows it, and starts the Qt event loop.
- `ADCStreamerGUI.__init__()` — runs the state-init helpers below, builds the UI, restores last-used settings, and logs the startup message.
- `ADCStreamerGUI._init_serial_state()` — initializes ADC serial port/thread state and the `ADCConnectionWorkflow`.
- `ADCStreamerGUI._init_data_buffers()` — sets up raw/processed sample buffers, the buffer lock, filter state, and capture-buffer state.
- `ADCStreamerGUI._init_archive_state()` — initializes archive writer/path and block-timing file state.
- `ADCStreamerGUI._init_force_state()` — initializes the force serial workflow, session, and default force runtime state.
- `ADCStreamerGUI._init_timing_state()` — resets timing measurement state (without resetting labels).
- `ADCStreamerGUI._init_config_state()` — sets the device mode, builds the ADC configuration service/runner, and default config/status state.
- `ADCStreamerGUI._init_ui_state()` — initializes checkbox dicts, plot curve caches, and UI flags.
- `ADCStreamerGUI._init_timers()` — creates and wires the plot/force/signal-integration/heatmap/config-check/spectrum `QTimer`s.
- `ADCStreamerGUI._log_startup_message()` — writes the startup banner to the status log.
- `ADCStreamerGUI.init_ui()` — builds the main splitter layout from the left control panel and right visualization panel, sets the window title/status bar, and fits the window to the screen.
- `ADCStreamerGUI._fit_window_to_screen()` — clamps window geometry to the available screen size and re-centers the window.
- `ADCStreamerGUI._create_left_control_panel()` — assembles the serial/config/acquisition/run-control/file/status sections into the left panel.
- `ADCStreamerGUI._create_right_visualization_panel()` — assembles the tabbed plot section into the right panel.
- `ADCStreamerGUI.closeEvent(event)` — persists spectrum/heatmap/shear settings, disconnects serial ports, and shuts down background workers on window close.
- `ADCStreamerGUI.on_visualization_tab_changed(index)` — starts/stops spectrum updates and triggers the relevant plot refresh when the active visualization tab changes.
- `ADCStreamerGUI.get_current_visualization_tab_name()` — returns the title of the currently active visualization tab.
- `ADCStreamerGUI.is_live_visualization_only_tab()` — returns `False`; placeholder hook for tabs that should skip default time-series capture.
- `ADCStreamerGUI.should_store_capture_data()` — returns whether captured data should be persisted/archived.
- `ADCStreamerGUI.should_update_live_timeseries_display()` — returns whether the active tab is one of the live time-series/PZT-RS/Rosette tabs.
- `ADCStreamerGUI.should_update_signal_integration_display()` — returns whether the Pressure Map tab is active.
- `ADCStreamerGUI.should_update_heatmap_display()` — returns whether the Heatmap tab is active.
- `ADCStreamerGUI.trigger_signal_integration_update()` — debounced trigger that queues a pressure-map redraw when that tab is visible.
- `ADCStreamerGUI.trigger_heatmap_update()` — debounced trigger that queues a heatmap redraw at the configured `HEATMAP_FPS` interval.
- `ADCStreamerGUI.start_spectrum_updates()` / `stop_spectrum_updates()` — start or stop the periodic spectrum refresh timer.

### `excel_tests.c`

Despite the `.c` extension, this is not compiled code — it's a scratch file of Excel formulas (IDW-style weighted-average interpolation by inverse squared distance) used while prototyping the pressure-map/heatmap interpolation math before it was ported into `data_processing/`. Not part of the build or import graph.

## Recommended Documentation

- [Arduino_Sketches/README.md](Arduino_Sketches/README.md): current firmware sketch map and serial protocol summary
- [docs/user/ARRAY_CONFIGURATION_GUIDE.md](docs/user/ARRAY_CONFIGURATION_GUIDE.md): configuring bundled and custom sensor layouts
- [docs/user/HEATMAP_README.md](docs/user/HEATMAP_README.md): current heatmap modes, array point tracking, geometry controls, and saved settings behavior
- [docs/history/FORCE_SENSOR_REFACTOR_PLAN.md](docs/history/FORCE_SENSOR_REFACTOR_PLAN.md): future force-path cleanup roadmap

## Testing

Run the current automated tests with:

```bash
uv run pytest
```

The repository pytest config adds the workspace root to `sys.path`, so the plain interpreter path also works after you install the dev dependencies above:

```bash
python -m pytest
```

## Notes

- The bundled sensor library is loaded from `sensors_library/` when present, then overlaid by the user library under `~/.adc_streamer/sensors/`.
- The active GUI includes `Time Series`, `Pressure Map`, `Heatmap`, `Force Calibration`, `Spectrum`, and `Sensor` tabs, with `Sensor` last. `Rosette (RS)` appears when the active mode supports it.
- Older notes may refer to `plus_heatmap_config.json`, but this repo no longer ships that root-level sample file.
