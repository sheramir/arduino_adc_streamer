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

# Debounce delay for force-only plot refreshes (milliseconds)
FORCE_PLOT_DEBOUNCE_MS = 100

# Interval for checking configuration completion status (milliseconds)
CONFIG_CHECK_INTERVAL = 100

# Spectrum refresh cadence (milliseconds)
SPECTRUM_UPDATE_INTERVAL_MS = 100

# Plot update frequency during capture (update every N sweeps)
PLOT_UPDATE_FREQUENCY = 10

# Minimum wall-clock interval between live plot redraws (seconds) — controls FPS cap.
# 0.2 = 5 FPS. Raise to 0.033 for 30 FPS (only beneficial if update_plot is fast enough).
PLOT_UPDATE_INTERVAL_SEC = 0.2

# Maximum total data points rendered across all channels in a single plot update.
# Lower values improve render speed; higher values improve detail.
MAX_TOTAL_POINTS_TO_DISPLAY = 12000

# ============================================================================
# Window and Layout Settings
# ============================================================================

# Main window dimensions
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 800

# Minimum practical on-screen window size when clamping to the active monitor.
# These keep the UI usable on smaller displays while still honoring screen bounds.
WINDOW_MIN_FIT_WIDTH = 900
WINDOW_MIN_FIT_HEIGHT = 700

# Padding from the monitor edge when fitting the main window (pixels)
WINDOW_SCREEN_MARGIN_PX = 16

# Left/right splitter proportions for controls vs. visualization
CONTROL_PANEL_STRETCH = 1
VISUALIZATION_PANEL_STRETCH = 3

# Standard vertical spacing used in the main stacked control panel layout (pixels)
MAIN_PANEL_LAYOUT_SPACING = 10

# Width of startup/status separator lines logged to the status pane (characters)
STATUS_SEPARATOR_WIDTH = 70

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

# Extra delay added after a timed run before finalizing UI state (milliseconds)
TIMED_CAPTURE_FINISH_SLACK_MS = 500

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

# Capture cache subdirectory name (created inside selected data directory)
CACHE_SUBDIR_NAME = "cache"

# Automatically clear capture cache on ADC disconnect/exit
CLEAR_CACHE_ON_EXIT = True

# Retry cadence for deferred cache cleanup while the archive writer drains (milliseconds)
CACHE_CLEANUP_RETRY_INTERVAL_MS = 100

# Maximum deferred cleanup polls before giving up on automatic cache cleanup
CACHE_CLEANUP_MAX_ATTEMPTS = 100

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

# 555-mode UI ranges
ANALYZER555_RESISTANCE_MAX_OHMS = 1e9
ANALYZER555_CF_MIN_VALUE = 0.0001
ANALYZER555_CF_MAX_VALUE = 1e6
ANALYZER555_RXMAX_MIN_OHMS = 1.0
ANALYZER555_RXMAX_MAX_OHMS = 1e12

# 555-mode serial buffer limit used by the current MCU firmware
ANALYZER555_BUFFER_SIZE_MAX = 256

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

# Number of raw samples collected when zeroing the force sensor offset
FORCE_CALIBRATION_SAMPLES = 25

# Force status label refresh cadence (every N force samples)
FORCE_STATUS_UPDATE_INTERVAL_SAMPLES = 10

# Force sensor serial settings
FORCE_SENSOR_BAUD_RATE = 115200
FORCE_SENSOR_STARTUP_DELAY_SEC = 0.5
FORCE_THREAD_STOP_TIMEOUT_MS = 250

# Force sensor conversion factors (raw counts per Newton)
# Newtons = calibrated_raw / FORCE_SENSOR_TO_NEWTON
X_FORCE_SENSOR_TO_NEWTON = 44600.0
Z_FORCE_SENSOR_TO_NEWTON = 44900.0

# Plot-only force deadband. Values within +/- threshold are rendered as 0.
FORCE_PLOT_ZERO_THRESHOLD_MN = 20.0

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

# ============================================================================
# Per-Sensor Threshold and Gain Settings (Mode-Specific)
# ============================================================================
# These settings allow individual tuning of threshold and gain for each sensor [T,B,R,L,C]
# Total threshold applied = general threshold + individual sensor threshold
# Stored as dict keyed by sensor ID (e.g., "PZR2", "PZT1", "Sensor1" for non-array)
# Default: empty dict (use global defaults from constants below when sensor not found)
PZT_SENSOR_CALIBRATION = {}  # {"PZT1": {"gains": [...], "thresholds": [...]}}
R_SENSOR_CALIBRATION = {}    # {"PZR2": {"gains": [...], "thresholds": [...]}}

# Global defaults when per-sensor settings not available
PZT_THRESHOLD_DEFAULT = 0.0
PZT_GAIN_DEFAULT = 1.0
R_THRESHOLD_DEFAULT = 0.0  # (%)
R_GAIN_DEFAULT = 1.0

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

# Default channel-to-sensor mapping for heatmap and shear.
# Order is by selected channel index: channel1..channel5 -> sensor location.
# Example: ["R", "B", "C", "L", "T"] means channel1->Right, channel2->Bottom, ...
SENSOR_LOCATION_CODES = ["T", "R", "C", "L", "B"]
DEFAULT_SENSOR_CONFIGURATION_NAME = "ARRAY_v1"
DEFAULT_SENSOR_CONFIGURATION = {
    "name": DEFAULT_SENSOR_CONFIGURATION_NAME,
    "channel_sensor_map": ["T", "L", "B", "R", "C"],
}

# Backward-compatible alias for the app's first-run active mapping.
HEATMAP_CHANNEL_SENSOR_MAP = list(DEFAULT_SENSOR_CONFIGURATION["channel_sensor_map"])

# Expected number of channels for heatmap
HEATMAP_REQUIRED_CHANNELS = 5
MAX_SENSOR_PACKAGES = 4

# Auto-baseline behavior for PZR/heatmap plotting
PZR_ZERO_BASELINE_WINDOW_SEC = 0.5
PZR_AUTO_BASELINE_DELAY_SEC = 1.5

# PZR sensor (555 analyzer mode) now uses 5 channels like PZT
# Shares the same heatmap configuration as standard piezo sensors
R_HEATMAP_CHANNEL_SENSOR_MAP = HEATMAP_CHANNEL_SENSOR_MAP
R_HEATMAP_REQUIRED_CHANNELS = HEATMAP_REQUIRED_CHANNELS
R_HEATMAP_SENSOR_POS_X = SENSOR_POS_X
R_HEATMAP_SENSOR_POS_Y = SENSOR_POS_Y
R_HEATMAP_DELTA_THRESHOLD = 1.0
R_HEATMAP_DELTA_RELEASE_THRESHOLD = 0.5
R_HEATMAP_INTENSITY_MIN = 0.0
R_HEATMAP_INTENSITY_MAX = 10.0
R_HEATMAP_AXIS_ADAPT_STRENGTH = 0.0
R_HEATMAP_MAP_SMOOTH_ALPHA = SMOOTH_ALPHA
R_HEATMAP_COP_SMOOTH_ALPHA = SMOOTH_ALPHA

# ============================================================================
# Shear / CoP Visualization Constants
# ============================================================================

# Signed integration window for shear extraction
SHEAR_INTEGRATION_WINDOW_MS = 16.0

# EMA coefficients for baseline tracking and light conditioning
SHEAR_BASELINE_ALPHA = 0.05
SHEAR_CONDITIONING_ALPHA = 0.25

# Deadband / signed calibration defaults
SHEAR_DEADBAND_THRESHOLD = 0.0
SHEAR_CHANNEL_GAINS = [1.0, 1.0, 1.0, 1.0, 1.0]  # [C, R, B, L, T]
SHEAR_CHANNEL_BASELINES = [0.0, 0.0, 0.0, 0.0, 0.0]  # [C, R, B, L, T]

# Gaussian CoP blob and arrow visualization
SHEAR_GAUSSIAN_SIGMA_X = 0.18
SHEAR_GAUSSIAN_SIGMA_Y = 0.18
SHEAR_INTENSITY_SCALE = 0.2
SHEAR_ARROW_SCALE = 0.35
SHEAR_ARROW_HEAD_LENGTH_BASE_PX = 12.0
SHEAR_ARROW_HEAD_LENGTH_AMPLIFIER = 12.0
SHEAR_ARROW_THICKNESS_AMPLIFIER = 30.0

# Confidence scoring reference magnitude
SHEAR_CONFIDENCE_SIGNAL_REF = 0.02

# Shear panel view geometry
SHEAR_VIEW_EXTENT = 1.25
SHEAR_SENSOR_RADIUS = 0.72

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

# ============================================================================
# Sensor Configuration Library Constants
# ============================================================================

# Bundled sensor-library JSON format version
SENSOR_CONFIG_FILE_VERSION = 1

# Pretty-print indentation for persisted sensor configuration JSON files
SENSOR_CONFIG_JSON_INDENT = 2

# Fixed-size editable sensor mapping uses 5 logical positions: T, R, C, L, B
SENSOR_CONFIG_CHANNEL_COUNT = 5

# Default array editor dimensions in the sensor configuration UI
SENSOR_CONFIG_ARRAY_ROWS = 3
SENSOR_CONFIG_ARRAY_COLS = 3
SENSOR_CONFIG_ARRAY_CELL_CHANNELS_MAX = 5

# Supported MUX numbering and channel index range for bundled array configs
SENSOR_CONFIG_MUX_MIN = 1
SENSOR_CONFIG_MUX_MAX = 2
SENSOR_CONFIG_CHANNEL_MIN = 0
SENSOR_CONFIG_CHANNEL_MAX = 15

# ============================================================================
# Serial Reader / Protocol Constants
# ============================================================================

# Idle sleep between ADC serial polling iterations (milliseconds)
SERIAL_READER_IDLE_MS = 2

# Idle sleep between force serial polling iterations (milliseconds)
FORCE_READER_IDLE_MS = 10

# Maximum number of binary packet debug messages emitted per capture session
SERIAL_READER_DEBUG_LOG_LIMIT = 10

# Binary packet framing sizes
SERIAL_PACKET_HEADER_BYTES = 4
SERIAL_PACKET_AVG_SAMPLE_TIME_BYTES = 2
SERIAL_PACKET_BLOCK_TIMESTAMP_BYTES = 8

# ============================================================================
# MCU Detection Constants
# ============================================================================

# Timeout while waiting for the MCU identification response (seconds)
MCU_DETECTION_TIMEOUT_SEC = 2.0

# Poll interval while waiting for the MCU identification response (seconds)
MCU_DETECTION_POLL_INTERVAL_SEC = 0.01

# Teensy sample-rate spinbox upper bound (Hz)
TEENSY_SAMPLE_RATE_MAX_HZ = 1000000

# ============================================================================
# Capture Lifecycle Timing
# ============================================================================

# Short delay after arming the reader thread before issuing the run command (seconds)
CAPTURE_THREAD_ARM_DELAY_SEC = 0.05

# Stop-command acknowledgement timeout and retry policy
STOP_CAPTURE_ACK_TIMEOUT_SEC = 0.2
STOP_CAPTURE_ACK_RETRIES = 1

# Serial drain timings used around capture stop/clear (seconds)
STOP_CAPTURE_DRAIN_SEC = 0.15
STOP_CAPTURE_FINAL_DRAIN_SEC = 0.02
CLEAR_CAPTURE_DRAIN_SEC = 0.05

# ============================================================================
# Archive Writer Timing
# ============================================================================

# Queue poll timeout while the archive writer waits for new work (seconds)
ARCHIVE_WRITER_QUEUE_TIMEOUT_SEC = 0.1

# Flush the archive file every N written sweeps
ARCHIVE_WRITER_FLUSH_SWEEP_INTERVAL = 1000

# Brief sleep between archive queue items to give the GUI thread more GIL time (seconds)
ARCHIVE_WRITER_GIL_YIELD_SEC = 0.002

# Maximum wait when stopping the archive writer synchronously (seconds)
ARCHIVE_WRITER_JOIN_TIMEOUT_SEC = 15.0
