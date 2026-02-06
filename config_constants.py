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
DEFAULT_WINDOW_SIZE = 10000
# Hard cap for sweeps shown during live plotting (keeps UI responsive)
MAX_PLOT_SWEEPS = 2000

# Maximum number of columns for channel checkboxes layout
MAX_PLOT_COLUMNS = 6

# ============================================================================
# Buffer Optimization Settings
# ============================================================================

# Target latency for buffered blocks (seconds)
# Used to calculate optimal sweeps per block
TARGET_LATENCY_SEC = 0.25  # ~250ms target

# Maximum samples buffer capacity on Arduino
MAX_SAMPLES_BUFFER = 32000

# USB CDC packet size (bytes) - used for optimizing block transfers
USB_PACKET_SIZE = 64

# Default buffer size (sweeps per block)
DEFAULT_BUFFER_SIZE = 1

# ============================================================================
# UI Control Ranges and Defaults
# ============================================================================

# Ground pin spinner range
GROUND_PIN_MIN = 0
GROUND_PIN_MAX = 18
GROUND_PIN_DEFAULT = 0

# Repeat count range and default
REPEAT_COUNT_MIN = 1
REPEAT_COUNT_MAX = 16  # Arduino limitation
REPEAT_COUNT_DEFAULT = 1

# Buffer size (sweeps per block) range
BUFFER_SIZE_MIN = 1
BUFFER_SIZE_MAX = 10000

# Timed run range and default (milliseconds)
TIMED_RUN_MIN = 10
TIMED_RUN_MAX = 3600000  # 1 hour
TIMED_RUN_DEFAULT = 1000

# Sweep range spinners
SWEEP_RANGE_MIN = 0
SWEEP_RANGE_MAX = 999999
SWEEP_RANGE_DEFAULT_MAX = 1000

# Window size spinner range
WINDOW_SIZE_MIN = 10
WINDOW_SIZE_MAX = 10000

# UI element heights (pixels)
NOTES_INPUT_HEIGHT = 60
STATUS_TEXT_HEIGHT = 150
CHANNEL_SCROLL_HEIGHT = 80

# ============================================================================
# ADC Hardware Settings
# ============================================================================

# IADC fixed resolution for XIAO MG24 (used for display scaling only, not sent to Arduino)
IADC_RESOLUTION_BITS = 12

# ============================================================================
# Plot Export Settings
# ============================================================================

# Width of exported plot images (pixels)
PLOT_EXPORT_WIDTH = 1920

# ============================================================================
# Memory Management Settings
# ============================================================================

# Maximum number of timing samples to keep in memory (rolling window)
# Applies to: buffer_receipt_times, arduino_sample_times, buffer_gap_times
# Higher values = more accurate long-term statistics, but more memory usage
MAX_TIMING_SAMPLES = 1000

# Maximum number of data sweeps to keep in memory (rolling window)
# Applies to: raw_data (ADC sweeps)
# Higher values = more data available for analysis/export, but more memory usage
MAX_SWEEPS_IN_MEMORY = 50000

# Maximum number of force samples to keep in memory (rolling window)
# Applies to: force_data
# Higher values = more force data for analysis, but more memory usage
MAX_FORCE_SAMPLES = 50000

# Maximum number of log lines to keep in status text window
# Prevents excessive memory usage from log accumulation during long sessions
MAX_LOG_LINES = 1000

# ============================================================================
# Heatmap Display Constants
# ============================================================================

# Heatmap update rate
HEATMAP_FPS = 30  # Target frame rate for heatmap updates

# Heatmap resolution
HEATMAP_WIDTH = 160  # Heatmap resolution width
HEATMAP_HEIGHT = 80  # Heatmap resolution height

# Sensor positions in normalized coordinates [-1, 1]
# Order: Top, Bottom, Right, Left, Center
SENSOR_POS_X = [0.0, 0.0, 1.0, -1.0, 0.0]  # X positions
SENSOR_POS_Y = [-1.0, 1.0, 0.0, 0.0, 0.0]  # Y positions

# Sensor calibration scaling factors (to normalize sensor responses)
SENSOR_CALIBRATION = [1.0, 1.5, 2.5, 1.0, 2.0]  # Per-sensor scale factors

# Physical size between endpoint sensors (for reference)
SENSOR_SIZE = 100.0  # mm or arbitrary units

# Intensity mapping
INTENSITY_SCALE = 0.001  # Scale factor to map signal to blob amplitude
COP_EPS = 1e-6  # Small epsilon to avoid division by zero in CoP calculation

# Gaussian blob parameters
BLOB_SIGMA_X = 0.3  # Horizontal spread (in normalized coordinates)
BLOB_SIGMA_Y = 0.2  # Vertical spread (in normalized coordinates)

# Smoothing parameter (exponential moving average)
SMOOTH_ALPHA = 0.2  # 0 = no smoothing, 1 = no history

# Expected number of channels for heatmap
HEATMAP_REQUIRED_CHANNELS = 5

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
