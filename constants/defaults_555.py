"""Default constants for 555 analyzer mode."""

from .board_compat import legacy_parameter

ANALYZER555_DEFAULT_RB_OHMS = legacy_parameter('generic_555', 'rb_ohms')
ANALYZER555_DEFAULT_RK_OHMS = legacy_parameter('generic_555', 'rk_ohms')
ANALYZER555_DEFAULT_CF_FARADS = legacy_parameter('generic_555', 'cf_farads')
ANALYZER555_DEFAULT_RXMAX_OHMS = legacy_parameter('generic_555', 'rxmax_ohms')

ANALYZER555_DEFAULT_CF_VALUE = ANALYZER555_DEFAULT_CF_FARADS / 1e-9
ANALYZER555_DEFAULT_CF_UNIT = "nF"

ANALYZER555_RESISTANCE_MAX_OHMS = legacy_parameter('generic_555', 'rb_ohms', 'maximum')
ANALYZER555_CF_MIN_VALUE = 0.0001
ANALYZER555_CF_MAX_VALUE = 1e6
ANALYZER555_RXMAX_MIN_OHMS = legacy_parameter('generic_555', 'rxmax_ohms', 'minimum')
ANALYZER555_RXMAX_MAX_OHMS = legacy_parameter('generic_555', 'rxmax_ohms', 'maximum')
ANALYZER555_BUFFER_SIZE_MAX = legacy_parameter('generic_555', 'sweeps_per_block', 'maximum')