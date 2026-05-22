"""Touch material classifier demo constants.

This module defines configurable material labels and demo behavior for the
Pressure Map material-classifier GUI demonstration.
"""

from __future__ import annotations

# Material labels displayed by the classifier bars.
TOUCH_MATERIALS: tuple[str, ...] = (
    "Wood",
    "Fabric",
    "Leather",
    "Cardboard",
    "Sponge",
)

# 1-based material index sequence used by the demo engine.
# Entries can repeat and will wrap at sequence end.
TOUCH_MATERIAL_SEQUENCE: tuple[int, ...] = (1, 2, 3, 4, 5, 3, 2, 4)

# Score model.
TOUCH_CLASSIFIER_SCORE_MIN = 0.0
TOUCH_CLASSIFIER_SCORE_MAX = 100.0
TOUCH_CLASSIFIER_DOMINANT_MIN = 70.0
TOUCH_CLASSIFIER_DOMINANT_MAX = 95.0
TOUCH_CLASSIFIER_SMOOTHING_ALPHA = 0.68
TOUCH_CLASSIFIER_FLUCTUATION_STD = 2.4

# Trigger timing model.
TOUCH_CLASSIFIER_TRIGGER_DELAY_SEC = 0.5
TOUCH_CLASSIFIER_HOLD_AFTER_NOISE_SEC = 0.5
TOUCH_CLASSIFIER_REPEAT_WINDOW_SEC = 2.0
TOUCH_CLASSIFIER_DEFAULT_ENABLED = False

# UI colors.
TOUCH_CLASSIFIER_ACTIVE_COLOR = "#1D8F4E"
TOUCH_CLASSIFIER_INACTIVE_COLOR = "#7A7A7A"
