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
# 555 Analyzer Constants
# ============================================================================

# Default 555 model parameters
ANALYZER555_DEFAULT_RB_OHMS = 470.0
ANALYZER555_DEFAULT_RK_OHMS = 0.0
ANALYZER555_DEFAULT_CF_FARADS = 0.022e-6  # 22 nF
ANALYZER555_DEFAULT_RXMAX_OHMS = 65500.0

# GUI defaults for Cf entry
ANALYZER555_DEFAULT_CF_VALUE = 22.0
ANALYZER555_DEFAULT_CF_UNIT = "nF"

# ============================================================================
# Filtering Constants
# ============================================================================

FILTER_DEFAULT_ENABLED = False
FILTER_DEFAULT_MAIN_TYPE = "none"  # one of: none, lowpass, highpass, bandpass
FILTER_DEFAULT_ORDER = 2
FILTER_DEFAULT_LOW_CUTOFF_HZ = 5.0
FILTER_DEFAULT_HIGH_CUTOFF_HZ = 200.0

# Up to 3 notch filters (enable/frequency/Q)
FILTER_NOTCH1_DEFAULT_ENABLED = True
FILTER_NOTCH1_DEFAULT_FREQ_HZ = 60.0
FILTER_NOTCH1_DEFAULT_Q = 30.0

FILTER_NOTCH2_DEFAULT_ENABLED = True
FILTER_NOTCH2_DEFAULT_FREQ_HZ = 120.0
FILTER_NOTCH2_DEFAULT_Q = 30.0

FILTER_NOTCH3_DEFAULT_ENABLED = False
FILTER_NOTCH3_DEFAULT_FREQ_HZ = 180.0
FILTER_NOTCH3_DEFAULT_Q = 30.0

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

# Force sensor conversion factors (raw counts per Newton)
# Newtons = calibrated_raw / FORCE_SENSOR_TO_NEWTON
X_FORCE_SENSOR_TO_NEWTON = 44600.0
Z_FORCE_SENSOR_TO_NEWTON = 44900.0

# Maximum number of log lines to keep in status text window
# Prevents excessive memory usage from log accumulation during long sessions
MAX_LOG_LINES = 1000

# ============================================================================
# Heatmap Display Constants
# ============================================================================

# Heatmap update rate
HEATMAP_FPS = 30  # Target frame rate for heatmap updates

# Heatmap resolution (square display)
HEATMAP_WIDTH = 160  # Heatmap resolution width
HEATMAP_HEIGHT = 160  # Heatmap resolution height

# Sensor positions in normalized coordinates [-1, 1]
# Order: Top, Bottom, Right, Left, Center
SENSOR_POS_X = [0.0, 0.0, 1.0, -1.0, 0.0]  # X positions
SENSOR_POS_Y = [-1.0, 1.0, 0.0, 0.0, 0.0]  # Y positions

# Sensor calibration scaling factors (to normalize sensor responses)
SENSOR_CALIBRATION = [1.0, 1.0, 1.0, 1.0, 1.0]  # Per-sensor scale factors

# Per-sensor baseline noise floor (RMS) to subtract after magnitude calculation
SENSOR_NOISE_FLOOR = [0.01, 0.01, 0.01, 0.01, 0.01]

# Physical size between endpoint sensors (for reference)
SENSOR_SIZE = 0.5

# Intensity mapping
INTENSITY_SCALE = 0.005  # Scale factor to map signal to blob amplitude
COP_EPS = 1e-6  # Small epsilon to avoid division by zero in CoP calculation

# Gaussian blob parameters
BLOB_SIGMA_X = 0.15  # Horizontal spread (in normalized coordinates)
BLOB_SIGMA_Y = 0.15  # Vertical spread (in normalized coordinates)

# Smoothing parameter (exponential moving average)
SMOOTH_ALPHA = 0.8  # 0 = no smoothing, 1 = no history

# Magnitude threshold for heatmap (values below are set to 0)
HEATMAP_THRESHOLD = 18.0

# Confidence calculation parameters
CONFIDENCE_INTENSITY_REF = 100.0
SIGMA_SPREAD_FACTOR = 1.5

# Axis-based sigma modulation (0 = off)
AXIS_SIGMA_FACTOR = 0.5

# RMS calculation window (milliseconds)
RMS_WINDOW_MS = 20

# DC removal settings
BIAS_CALIBRATION_DURATION_SEC = 2.0
HPF_CUTOFF_HZ = 0.5
HEATMAP_DC_REMOVAL_MODE = "highpass"  # "bias" or "highpass"

# Channel-to-sensor mapping for heatmap (order of selected channels)
# Example: ["R", "B", "C", "L", "T"] means channel1->Right, channel2->Bottom, ...
# Configuration for PLUS sensors: HEATMAP_CHANNEL_SENSOR_MAP = ["R", "B", "C", "L", "T"]
# Configuration for Single Octo sensors: HEATMAP_CHANNEL_SENSOR_MAP = ["R", "C", "B", "L", "T"]
HEATMAP_CHANNEL_SENSOR_MAP = ["B", "R", "C", "L", "T"]

# Expected number of channels for heatmap
HEATMAP_REQUIRED_CHANNELS = 5

# 555 analyzer 4-sensor displacement heatmap mapping (no center sensor)
# Channel order maps to sensor labels used by the 555 heatmap pipeline.
R_HEATMAP_CHANNEL_SENSOR_MAP = ["R", "B", "L", "T"]
R_HEATMAP_REQUIRED_CHANNELS = 4

# 555 sensor geometry (normalized coordinates in heatmap space)
# Sensor indices 1..4 follow R_HEATMAP_CHANNEL_SENSOR_MAP order.
R_HEATMAP_SENSOR_POS_X = [1.0, 0.0, -1.0, 0.0]
R_HEATMAP_SENSOR_POS_Y = [0.0, -1.0, 0.0, 1.0]

# 555 displacement heatmap defaults
R_HEATMAP_DELTA_THRESHOLD = 1.0
R_HEATMAP_DELTA_RELEASE_THRESHOLD = 1.0
R_HEATMAP_INTENSITY_MIN = 10.0
R_HEATMAP_INTENSITY_MAX = 200.0
R_HEATMAP_AXIS_ADAPT_STRENGTH = 0.5
R_HEATMAP_MAP_SMOOTH_ALPHA = 0.2

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
