# Constants

This package holds shared, static configuration values for the Arduino ADC Streamer GUI: serial
protocol timing, buffer-sizing limits, 555-analyzer defaults, filtering defaults, plotting and UI
geometry, heatmap/pressure-map/shear visualization parameters, force-sensor conversion factors,
sensor-config schema limits, and PZT_RS wire-unit scaling. Every module is plain data (module-level
constants and a few tiny pure helper functions); nothing here depends on Qt or GUI state, so other
packages (`config/`, `data_processing/`, `file_operations/`, `gui/`, `serial_communication/`)
import from here freely without circular-dependency risk.

## Files

### __init__.py

Package docstring only; no exports.

### capture_archive.py

Capture-lifecycle, archive-writer, and cache-cleanup timing constants (cache subdir name,
clear-on-exit flag, capture arm/stop/drain delays, archive writer flush/queue/join timings).

- Data only: `CACHE_SUBDIR_NAME`, `CLEAR_CACHE_ON_EXIT`, `CACHE_CLEANUP_RETRY_INTERVAL_MS`,
  `CACHE_CLEANUP_MAX_ATTEMPTS`, `CAPTURE_THREAD_ARM_DELAY_SEC`, `STOP_CAPTURE_ACK_TIMEOUT_SEC`,
  `STOP_CAPTURE_ACK_RETRIES`, `STOP_CAPTURE_DRAIN_SEC`, `STOP_CAPTURE_FINAL_DRAIN_SEC`,
  `CLEAR_CAPTURE_DRAIN_SEC`, `ARCHIVE_WRITER_QUEUE_TIMEOUT_SEC`,
  `ARCHIVE_WRITER_FLUSH_SWEEP_INTERVAL`, `ARCHIVE_WRITER_GIL_YIELD_SEC`,
  `ARCHIVE_WRITER_JOIN_TIMEOUT_SEC`.

### defaults_555.py

Default RC component values and valid ranges for 555-timer ("555 analyzer") resistance-measurement mode.

- Data only: `ANALYZER555_DEFAULT_RB_OHMS`, `ANALYZER555_DEFAULT_RK_OHMS`,
  `ANALYZER555_DEFAULT_CF_FARADS`, `ANALYZER555_DEFAULT_RXMAX_OHMS`,
  `ANALYZER555_DEFAULT_CF_VALUE`, `ANALYZER555_DEFAULT_CF_UNIT`,
  `ANALYZER555_RESISTANCE_MAX_OHMS`, `ANALYZER555_CF_MIN_VALUE`, `ANALYZER555_CF_MAX_VALUE`,
  `ANALYZER555_RXMAX_MIN_OHMS`, `ANALYZER555_RXMAX_MAX_OHMS`, `ANALYZER555_BUFFER_SIZE_MAX`.

### filtering_defaults.py

Default ADC live-filtering settings: main filter type/order/cutoffs and up to three notch filters
(60/120/180 Hz mains harmonics by default).

- Data only: `FILTER_DEFAULT_ENABLED`, `FILTER_DEFAULT_MAIN_TYPE`, `FILTER_DEFAULT_ORDER`,
  `FILTER_DEFAULT_LOW_CUTOFF_HZ`, `FILTER_DEFAULT_HIGH_CUTOFF_HZ`,
  `FILTER_NOTCH1_DEFAULT_ENABLED/FREQ_HZ/Q`, `FILTER_NOTCH2_DEFAULT_ENABLED/FREQ_HZ/Q`,
  `FILTER_NOTCH3_DEFAULT_ENABLED/FREQ_HZ/Q`.

### force.py

Force-sensor serial settings, calibration sample counts, raw-count-to-Newton conversion factors,
and force-calibration tab/persistence settings.

- Data only: `FORCE_SENSOR_BAUD_RATE`, `FORCE_SENSOR_STARTUP_DELAY_SEC`,
  `FORCE_THREAD_STOP_TIMEOUT_MS`, `FORCE_CALIBRATION_SAMPLES`,
  `FORCE_STATUS_UPDATE_INTERVAL_SAMPLES`, `MAX_FORCE_SAMPLES`, `X_FORCE_SENSOR_TO_NEWTON`,
  `Z_FORCE_SENSOR_TO_NEWTON`, `FORCE_PLOT_ZERO_THRESHOLD_MN`,
  `FORCE_CALIBRATION_DEFAULT_INTEGRATION_SAMPLES`, `FORCE_CALIBRATION_SETTINGS_DIRNAME`,
  `FORCE_CALIBRATION_SETTINGS_SUBDIR`.

### heatmap.py

Heatmap visualization defaults: resolution, sensor positions/calibration/noise floor, Gaussian
blob shape, smoothing, DC-removal mode, channel mapping (derived from
`constants.sensor_config.DEFAULT_SENSOR_CONFIGURATION`), and PZR-specific (555-mode) heatmap
aliases.

- Data only: `HEATMAP_FPS`, `HEATMAP_WIDTH/HEIGHT`, `HEATMAP_COORD_EXTENT`, `SENSOR_POS_X/Y`,
  `SENSOR_CALIBRATION`, `SENSOR_NOISE_FLOOR`, `PZT_SENSOR_CALIBRATION`, `R_SENSOR_CALIBRATION`,
  `PZT_THRESHOLD_DEFAULT`, `PZT_GAIN_DEFAULT`, `R_THRESHOLD_DEFAULT`, `R_GAIN_DEFAULT`,
  `SENSOR_SIZE`, `INTENSITY_SCALE`, `COP_EPS`, `BLOB_SIGMA_X/Y`, `ELLIPSE_SHAPE_ENABLED`,
  `HEATMAP_MIRROR_DISPLAY`, `SMOOTH_ALPHA`, `HEATMAP_THRESHOLD`, `CONFIDENCE_INTENSITY_REF`,
  `SIGMA_SPREAD_FACTOR`, `AXIS_SIGMA_FACTOR`, `RMS_WINDOW_MS`, `BIAS_CALIBRATION_DURATION_SEC`,
  `HPF_CUTOFF_HZ`, `HEATMAP_DC_REMOVAL_MODE`, `REMOVE_NEGATIVES`, `HEATMAP_CHANNEL_SENSOR_MAP`,
  `HEATMAP_REQUIRED_CHANNELS`, `MAX_SENSOR_PACKAGES`, `PZR_ZERO_BASELINE_WINDOW_SEC`,
  `PZR_AUTO_BASELINE_DELAY_SEC`, `R_HEATMAP_*` aliases.

  Note: this module previously also defined a duplicate, unused set of `SHEAR_*` constants
  (signed integration window, EMA baseline coefficients, Gaussian CoP blob/arrow parameters).
  No active code imported them from here — the live shear pipeline uses `constants/shear.py`
  instead, and `Legacy/config_constants.py` keeps its own isolated literal copies (enforced by
  `tests/test_legacy_constants.py`). That dead block was removed; if you're looking for shear
  constants, see `shear.py` below.

### plotting.py

Plot rendering and timing constants: timestamp unit conversion, plot update debounce/interval,
display point/sweep caps, Rosette (RS) plot baseline/moving-average/Y-range defaults, ADC
resolution, plot export width, and the fixed plot color palette.

- Data only: `MICROSECONDS_PER_SECOND`, `PLOT_UPDATE_DEBOUNCE`, `PLOT_UPDATE_INTERVAL_SEC`,
  `MAX_TOTAL_POINTS_TO_DISPLAY`, `MAX_PLOT_SWEEPS`, `ROSETTE_BASELINE_SAMPLE_COUNT`,
  `ROSETTE_MOVING_AVERAGE_DEFAULT/MIN/MAX_SAMPLES`, `ROSETTE_FIXED_Y_MIN/MAX_DEFAULT_OHMS`,
  `ROSETTE_FIXED_Y_MIN/MAX_LIMIT_OHMS`, `ROSETTE_FIXED_Y_STEP_OHMS`,
  `ROSETTE_FIXED_Y_DECIMALS`, `IADC_RESOLUTION_BITS`, `PLOT_EXPORT_WIDTH`, `PLOT_COLORS`.

### pressure_map.py

Pressure Map tab constants: channel/position layout, HPF/signal-integration filtering defaults,
display window and Rosette overlay defaults, plot rendering/throttling, pressure-grid
interpolation parameters (decay rate, spacing, resolution, margin), and pressure-map rendering
(colormap, marker styles, package colors, Z-order, mirror display). Imports
`MAX_PLOT_SWEEPS` from `plotting.py` and `DEFAULT_NORMAL_FORCE_SENSOR_SPACING_MM` from `shear.py`.

- Data only: `SIGNAL_INTEGRATION_*` family (channel count/position order/ground index/PZT1 MUX
  count, HPF filter settings, integration window, display window, plot rendering/throttling,
  history sizing, Y-range padding), `PRESSURE_MAP_*` / `PRESSURE_*` aliases and canonical names
  (channel count, plot FPS, quadrant labels, grid margin/resolution/decay, sensor spacing/circle
  diameter UI ranges, colormap/marker/package colors, Z-order, `DEFAULT_PRESSURE_MIRROR`).

### pzt_rs.py

Defines and documents the single source of truth for the PZT_RS Rosette wire-value scale (ohms
per wire unit) and provides forward/backward-compatible conversion between the current scale and
legacy archive unit labels (`deciohm`, `centiohm`).

- `PZT_RS_RS_WIRE_UNITS_PER_OHM` / `PZT_RS_RS_OHMS_PER_WIRE_UNIT` — current wire-unit-to-ohm scale (module constants).
- `pzt_rs_units_label_from_wire_scale(scale)` — return the archive metadata label
  (`"deciohm"`/`"centiohm"`/generic) for a given wire-scale value.
- `PZT_RS_RS_UNITS_LABEL` — the label for the currently configured scale (module constant).
- `get_pzt_rs_ohms_per_wire_unit(units_label=None)` — return ohms-per-wire-unit for the current
  scale, or look up the scale for an archived unit label; returns None if unrecognized.

### runtime.py

Two memory/rolling-window constants shared across the app.

- Data only: `MAX_TIMING_SAMPLES`, `MAX_SWEEPS_IN_MEMORY`.

### sensor_config.py

Schema defaults and validation limits for the editable sensor library (5-channel packages and
3x3 array layouts). Consumed by `config.sensor_config` for normalization/persistence.

- Data only: `SENSOR_LOCATION_CODES`, `DEFAULT_SENSOR_CONFIGURATION_NAME`,
  `SENSOR_CONFIG_REVERSE_POLARITY_KEY`, `DEFAULT_SENSOR_REVERSE_POLARITY`,
  `SENSOR_POLARITY_NORMAL_MULTIPLIER`, `SENSOR_POLARITY_REVERSED_MULTIPLIER`,
  `SENSOR_REVERSE_POLARITY_LABEL`, `DEFAULT_SENSOR_CONFIGURATION`, `SENSOR_CONFIG_FILE_VERSION`,
  `SENSOR_CONFIG_JSON_INDENT`, `SENSOR_CONFIG_CHANNEL_COUNT`, `SENSOR_CONFIG_ARRAY_ROWS/COLS`,
  `SENSOR_CONFIG_ARRAY_CELL_CHANNELS_MAX`, `SENSOR_CONFIG_MUX_MIN/MAX`,
  `SENSOR_CONFIG_CHANNEL_MIN/MAX`.

### serial.py

Serial communication and ADC configuration-protocol constants: baud rate, command timeouts,
buffer-optimization limits, UI control ranges for buffer/ground/repeat/timed-run, serial packet
framing sizes, and MCU-detection timing.

- Data only: `BAUD_RATE`, `SERIAL_TIMEOUT`, `COMMAND_TERMINATOR`, `CONFIG_RETRY_ATTEMPTS`,
  `CONFIG_COMMAND_TIMEOUT`, `CONFIG_RETRY_DELAY`, `INTER_COMMAND_DELAY`, `ARDUINO_RESET_DELAY`,
  `TARGET_LATENCY_SEC`, `MAX_SAMPLES_BUFFER`, `USB_PACKET_SIZE`, `DEFAULT_BUFFER_SIZE`,
  `ARRAY_PZT_MAX_MUX_PAIRS_PER_BLOCK`, `ARRAY_PZT_RS_MAX_SWEEPS_PER_BLOCK`,
  `BUFFER_SIZE_MIN/MAX`, `GROUND_PIN_MIN/MAX/DEFAULT`, `REPEAT_COUNT_MIN/MAX/DEFAULT`,
  `TIMED_RUN_MIN/MAX/DEFAULT`, `TIMED_CAPTURE_FINISH_SLACK_MS`, `SERIAL_READER_IDLE_MS`,
  `FORCE_READER_IDLE_MS`, `SERIAL_READER_DEBUG_LOG_LIMIT`, `SERIAL_PACKET_*` framing sizes,
  `MCU_DETECTION_TIMEOUT_SEC`, `MCU_DETECTION_POLL_INTERVAL_SEC`, `TEENSY_SAMPLE_RATE_MAX_HZ`.

### shear.py

Shear/center-of-pressure (CoP) visualization constants: sensor position labels, normal-force
computation constants, settings persistence file names, calibration/threshold UI ranges, static
sensor-layout geometry (millimeters), layout appearance colors, and dynamic arrow rendering controls.

- Data only: `SHEAR_POSITION_*`, `SHEAR_SENSOR_POSITIONS`, `SHEAR_OUTER_SENSOR_POSITIONS`,
  `SHEAR_HORIZONTAL/VERTICAL_*_INDEX`, `SHEAR_ZERO_VALUE`, `SHEAR_DEFAULT_ANGLE_DEG`,
  `SHEAR_FULL_CIRCLE_DEG`, `SHEAR_FORCE_TYPE_*`, `NORMAL_FORCE_SENSOR_COUNT`,
  `NORMAL_FORCE_DENOMINATOR_EPSILON`, `DEFAULT_NORMAL_FORCE_SENSOR_SPACING_MM`,
  `SHEAR_SETTINGS_*` (version/keys/dirnames/filenames/filter), `DEFAULT_SHEAR_NOISE_THRESHOLD`
  and range, `DEFAULT_SHEAR_CALIBRATION_GAIN` and range, `DEFAULT_CIRCLE_DIAMETER_MM`,
  `DEFAULT_SENSOR_SPACING_MM`, `SHEAR_LAYOUT_*` geometry/appearance, `SHEAR_*_Z` Z-order values,
  `DEFAULT_ARROW_*` and `SHEAR_ARROW_*` dynamic arrow controls, `SHEAR_READOUT_*` formatting.

### ui.py

Window/layout geometry, UI update timing intervals, tab display names, and spinner/log-line
limits used across the main GUI.

- Data only: `FORCE_PLOT_DEBOUNCE_MS`, `CONFIG_CHECK_INTERVAL`, `SPECTRUM_UPDATE_INTERVAL_MS`,
  `PLOT_UPDATE_FREQUENCY`, `WINDOW_WIDTH/HEIGHT`, `WINDOW_MIN_FIT_WIDTH/HEIGHT`,
  `WINDOW_SCREEN_MARGIN_PX`, `CONTROL_PANEL_STRETCH`, `VISUALIZATION_PANEL_STRETCH`,
  `MAIN_PANEL_LAYOUT_SPACING`, `STATUS_SEPARATOR_WIDTH`, `DEFAULT_WINDOW_SIZE`,
  `MAX_PLOT_COLUMNS`, `TIME_SERIES_TAB_NAME`, `PZT_RS_PZT_TAB_NAME`, `ROSETTE_TAB_NAME`,
  `PRESSURE_MAP_TAB_NAME`, `HEATMAP_TAB_NAME`, `FORCE_CALIBRATION_TAB_NAME`, `SPECTRUM_TAB_NAME`,
  `SENSOR_TAB_NAME`, `SWEEP_RANGE_MIN/MAX/DEFAULT_MAX`, `WINDOW_SIZE_MIN/MAX`,
  `NOTES_INPUT_HEIGHT`, `STATUS_TEXT_HEIGHT`, `CHANNEL_SCROLL_HEIGHT`, `MAX_LOG_LINES`.

## Notes

- `heatmap.py` previously also carried a dead "Shear / CoP Visualization Constants" section
  duplicating concerns better covered by `shear.py`. It was unused by any active import and has
  been removed; shear-related constants now live solely in `shear.py` for active code (and in
  `Legacy/config_constants.py` for the archived shear pipeline).
- `pressure_map.py` imports from both `plotting.py` and `shear.py`, and re-exports many
  `SIGNAL_INTEGRATION_*` constants under `PRESSURE_MAP_*`/`PRESSURE_*` aliases for the same
  values — this is intentional naming-migration scaffolding ("Legacy SIGNAL_INTEGRATION_* names
  are retained for compatibility during refactor" per the module docstring), not duplication to fix.
