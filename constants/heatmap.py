"""Heatmap visualization defaults."""

from constants.sensor_config import (
    DEFAULT_SENSOR_CONFIGURATION,
    SENSOR_CONFIG_ARRAY_COLS,
    SENSOR_CONFIG_ARRAY_ROWS,
)


# ============================================================================
# Heatmap Display Constants
# ============================================================================

# Heatmap update rate
HEATMAP_FPS = 30

# Heatmap resolution (square display)
HEATMAP_WIDTH = 160
HEATMAP_HEIGHT = 160

# Normalized coordinate extent used to render the heatmap image. Sensor/circle
# geometry still uses radius 1.0; this larger image domain lets blobs spill
# outside the circle without being clipped at the image edge.
HEATMAP_COORD_EXTENT = 1.5

# Sensor positions in normalized coordinates [-1, 1]
# Order: Top, Bottom, Right, Left, Center
SENSOR_POS_X = [0.0, 0.0, 1.0, -1.0, 0.0]
SENSOR_POS_Y = [-1.0, 1.0, 0.0, 0.0, 0.0]

# Sensor calibration scaling factors (to normalize sensor responses)
SENSOR_CALIBRATION = [1.0, 1.0, 1.0, 1.0, 1.0]

# Per-sensor baseline noise floor (RMS) to subtract after magnitude calculation
SENSOR_NOISE_FLOOR = [0.01, 0.01, 0.01, 0.01, 0.01]

# Per-sensor threshold and gain settings keyed by sensor ID.
PZT_SENSOR_CALIBRATION = {}
R_SENSOR_CALIBRATION = {}

# Global defaults when per-sensor settings are not available.
PZT_THRESHOLD_DEFAULT = 0.0
PZT_GAIN_DEFAULT = 1.0
R_THRESHOLD_DEFAULT = 0.0
R_GAIN_DEFAULT = 1.0

# Physical size between endpoint sensors (for reference)
SENSOR_SIZE = 0.5

# Intensity mapping
INTENSITY_SCALE = 0.005
COP_EPS = 1e-6

# Gaussian blob parameters
BLOB_SIGMA_X = 0.15
BLOB_SIGMA_Y = 0.15
ELLIPSE_SHAPE_ENABLED = True
HEATMAP_MIRROR_DISPLAY = False

# Smoothing parameter (exponential moving average)
SMOOTH_ALPHA = 0.8

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
HEATMAP_DC_REMOVAL_MODE = "highpass"
REMOVE_NEGATIVES = False

# Default channel-to-sensor mapping for archived heatmap and shear.
HEATMAP_CHANNEL_SENSOR_MAP = list(DEFAULT_SENSOR_CONFIGURATION["channel_sensor_map"])

# Expected number of channels for heatmap
HEATMAP_REQUIRED_CHANNELS = 5
MAX_SENSOR_PACKAGES = SENSOR_CONFIG_ARRAY_ROWS * SENSOR_CONFIG_ARRAY_COLS

# Auto-baseline behavior for PZR/heatmap plotting
PZR_ZERO_BASELINE_WINDOW_SEC = 0.5
PZR_AUTO_BASELINE_DELAY_SEC = 1.5

# PZR sensor (555 analyzer mode) uses 5 channels like PZT.
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
