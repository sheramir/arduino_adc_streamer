"""Plotting and rendering constants."""

# Unit conversion used for MCU microsecond timestamps.
MICROSECONDS_PER_SECOND = 1_000_000.0

# UI Update Timing
PLOT_UPDATE_DEBOUNCE = 200
PLOT_UPDATE_INTERVAL_SEC = 0.2

# Plot rendering bounds
MAX_TOTAL_POINTS_TO_DISPLAY = 12000
MAX_PLOT_SWEEPS = 2000

# ADC Hardware Settings
IADC_RESOLUTION_BITS = 12

# Plot Export Settings
PLOT_EXPORT_WIDTH = 1920

# Plot Colors
PLOT_COLORS = [
    (255, 0, 0),
    (34, 139, 34),
    (0, 0, 255),
    (255, 140, 0),
    (138, 43, 226),
    (0, 206, 209),
    (255, 20, 147),
    (184, 134, 11),
    (75, 0, 130),
    (220, 20, 60),
    (46, 139, 87),
    (30, 144, 255),
]
