"""
Configuration constants for ADC Streamer GUI application.

This file contains all configurable parameters used throughout the application.
Modify these values to adjust serial communication, timing, UI layout, and plotting behavior.
"""

# ============================================================================
# Serial Communication Settings
# ============================================================================

# Serial port baud rate (must match Arduino configuration)
# Tested values: 460800 (recommended), 576000, 921600
# Note: Higher speeds may require better USB cables and shorter cable lengths
BAUD_RATE = 460800

# Serial port read timeout in seconds
SERIAL_TIMEOUT = 1.0

# Command terminator string (Arduino expects *** at end of each command)
COMMAND_TERMINATOR = "***"

# ============================================================================
# Configuration Command Settings
# ============================================================================

# Number of retry attempts for configuration commands
CONFIG_RETRY_ATTEMPTS = 3

# Timeout for waiting for command acknowledgment (seconds)
CONFIG_COMMAND_TIMEOUT = 1.0

# Delay between retry attempts (seconds)
CONFIG_RETRY_DELAY = 0.05

# Delay between consecutive configuration commands (seconds)
INTER_COMMAND_DELAY = 0.05

# ============================================================================
# Arduino Communication Timing
# ============================================================================

# Delay after opening serial port to allow Arduino to reset (seconds)
ARDUINO_RESET_DELAY = 2.0

# ============================================================================
# UI Update Timing
# ============================================================================

# Debounce delay for plot updates to prevent excessive redraws (milliseconds)
PLOT_UPDATE_DEBOUNCE = 200

# Interval for checking configuration completion status (milliseconds)
CONFIG_CHECK_INTERVAL = 100

# Plot update frequency during capture (update every N sweeps)
PLOT_UPDATE_FREQUENCY = 10

# ============================================================================
# Window and Layout Settings
# ============================================================================

# Main window dimensions
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 800

# Default scrolling window size (number of sweeps to display during capture)
DEFAULT_WINDOW_SIZE = 1000

# Maximum number of columns for channel checkboxes layout
MAX_PLOT_COLUMNS = 6

# ============================================================================
# Plot Export Settings
# ============================================================================

# Width of exported plot images (pixels)
PLOT_EXPORT_WIDTH = 1920

# ============================================================================
# Plot Colors
# ============================================================================

# Color palette for plotting multiple channels (RGB tuples)
# Colors are assigned to channels in order, cycling if more channels than colors
PLOT_COLORS = [
    (255, 0, 0),      # Red
    (34, 139, 34),    # Forest Green
    (0, 0, 255),      # Blue
    (255, 140, 0),    # Dark Orange
    (138, 43, 226),   # Blue Violet
    (0, 206, 209),    # Dark Turquoise
    (255, 20, 147),   # Deep Pink
    (184, 134, 11),   # Dark Goldenrod
    (75, 0, 130),     # Indigo
    (220, 20, 60),    # Crimson
    (46, 139, 87),    # Sea Green
    (30, 144, 255)    # Dodger Blue
]
