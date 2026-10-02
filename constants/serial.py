"""Serial/protocol/configuration timing constants."""

from .board_compat import legacy_bootstrap, legacy_parameter, legacy_mode

# Read-only legacy defaults. Active boards use their resolved profile.
# Serial Communication Settings
BAUD_RATE = legacy_bootstrap()['baud_rate']
SERIAL_TIMEOUT = 1.0
COMMAND_TERMINATOR = legacy_bootstrap()['command_terminator']

# Configuration Command Settings
CONFIG_RETRY_ATTEMPTS = 3
CONFIG_COMMAND_TIMEOUT = 1.0
CONFIG_RETRY_DELAY = 0.05
INTER_COMMAND_DELAY = 0.05

# Arduino Communication Timing
ARDUINO_RESET_DELAY = 2.0

# Buffer Optimization Settings
TARGET_LATENCY_SEC = 0.25
MAX_SAMPLES_BUFFER = 32000
USB_PACKET_SIZE = 64
DEFAULT_BUFFER_SIZE = legacy_parameter('generic_adc', 'sweeps_per_block', 'default')
# Fallback sweeps-per-block used when a configuration request carries no usable
# buffer size. Distinct from DEFAULT_BUFFER_SIZE, which seeds the UI spin box.
DEFAULT_CONFIG_BUFFER_SIZE = 128
ARRAY_PZT_MAX_MUX_PAIRS_PER_BLOCK = legacy_mode('array_pzt1')['buffer_limits']['mux_pairs']
ARRAY_PZT_RS_MAX_SWEEPS_PER_BLOCK = legacy_mode('array_pzt_pzr17', 'PZT_RS')['buffer_limits']['max_sweeps']

# UI Control Ranges and Defaults (serial-adjacent controls)
BUFFER_SIZE_MIN = legacy_parameter('generic_adc', 'sweeps_per_block', 'minimum')
BUFFER_SIZE_MAX = legacy_parameter('generic_adc', 'sweeps_per_block', 'maximum')
GROUND_PIN_MIN = legacy_parameter('generic_adc', 'ground_pin', 'minimum')
GROUND_PIN_MAX = legacy_parameter('generic_adc', 'ground_pin', 'maximum')
GROUND_PIN_DEFAULT = legacy_parameter('generic_adc', 'ground_pin', 'default')
REPEAT_COUNT_MIN = legacy_parameter('generic_adc', 'samples_per_channel', 'minimum')
REPEAT_COUNT_MAX = legacy_parameter('generic_adc', 'samples_per_channel', 'maximum')
REPEAT_COUNT_DEFAULT = legacy_parameter('generic_adc', 'samples_per_channel', 'default')
TIMED_RUN_MIN = 10
TIMED_RUN_MAX = 3600000
TIMED_RUN_DEFAULT = 1000

# Serial Reader / Protocol Constants
SERIAL_READER_IDLE_MS = 2
FORCE_READER_IDLE_MS = 10
SERIAL_READER_DEBUG_LOG_LIMIT = 10
SERIAL_PACKET_HEADER_BYTES = 4
SERIAL_PACKET_AVG_SAMPLE_TIME_BYTES = 2
SERIAL_PACKET_BLOCK_TIMESTAMP_BYTES = 8
SERIAL_PACKET_SAMPLE_COUNT_MAX = MAX_SAMPLES_BUFFER
SERIAL_PACKET_AVG_SAMPLE_TIME_MIN_US = 1
SERIAL_PACKET_AVG_SAMPLE_TIME_MAX_US = 200_000
SERIAL_PACKET_SPAN_MIN_FACTOR = 0.25
SERIAL_PACKET_SPAN_MAX_FACTOR = 12.0
SERIAL_PACKET_SPAN_TOLERANCE_US = 2000
# Longest '#' ASCII line the reader will wait to complete before resyncing.
# Matches shared_proto::kMaxCmdLen in the Teensy firmware (SharedProtocol.h).
SERIAL_ASCII_LINE_MAX_BYTES = 512

# MCU Detection Constants
MCU_DETECTION_TIMEOUT_SEC = 2.0
TEENSY_SAMPLE_RATE_MAX_HZ = legacy_parameter('teensy40_adc', 'sample_rate', 'maximum')
