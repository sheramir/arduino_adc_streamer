"""
Shear force detection for calibrated five-sensor piezo packages.

This module implements the shear extraction stage of the Shear & Pressure Map
pipeline. It accepts calibrated scalar signals keyed by sensor position
(``C``, ``L``, ``R``, ``T``, ``B``), identifies opposite-sign outer pairs, and
returns both the extracted shear vector and residual signals with the lateral
component removed.

Dependencies:
    Python math utilities and constants.shear.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from collections.abc import Mapping

from constants.shear import (
    SHEAR_DEFAULT_ANGLE_DEG,
    SHEAR_POSITION_BOTTOM,
    SHEAR_POSITION_CENTER,
    SHEAR_POSITION_LEFT,
    SHEAR_POSITION_RIGHT,
    SHEAR_POSITION_TOP,
    SHEAR_SENSOR_POSITIONS,
    SHEAR_ZERO_VALUE,
)


@dataclass(frozen=True, slots=True)
class ShearResult:
    """Result of shear extraction for one five-sensor sample.

    Args:
        calibrated: Input calibrated force-like signal by sensor position.
        strain_vector: Estimated shear strain component by sensor position.
        residual: Input signal after subtracting the estimated shear component.
        b_lr: Horizontal shear component. Positive points rightward.
        b_tb: Vertical shear component. Positive points upward.
        shear_magnitude: Magnitude of the lateral shear vector.
        shear_angle_deg: Direction in degrees, where 0 is right and 90 is up.
        has_shear: Whether any opposite-sign outer pair was detected.
        lr_pair: Whether the L/R pair contributed shear.
        tb_pair: Whether the T/B pair contributed shear.

    Usage example:
        result = ShearDetector().detect({"C": 5, "L": -3, "R": 4, "T": 0, "B": 0})
        assert result.b_lr == 3.0
    """

    calibrated: dict[str, float]
    strain_vector: dict[str, float]
    residual: dict[str, float]
    b_lr: float
    b_tb: float
    shear_magnitude: float
    shear_angle_deg: float
    has_shear: bool
    lr_pair: bool
    tb_pair: bool


class ShearDetector:
    """Detect and remove shear components from calibrated sensor signals.

    The detector models lateral shear as the equal-and-opposite part of each
    outer sensor pair. The center channel does not contribute to shear removal.
    Opposite-sign pairs are reduced by the smaller absolute magnitude so the
    pair residual becomes same-sign or zero.

    Usage example:
        detector = ShearDetector()
        result = detector.detect({"C": 5.0, "L": -3.0, "R": 4.0, "T": 0.0, "B": 0.0})
    """

    def detect(self, calibrated_signals: Mapping[str, float]) -> ShearResult:
        """Detect shear and return residual signals with shear removed.

        Args:
            calibrated_signals: Mapping keyed by ``C``, ``L``, ``R``, ``T``,
                and ``B``. Missing positions are treated as zero.

        Returns:
            ShearResult with components, vector magnitude/angle, strain vector,
            and residual signals.

        Raises:
            TypeError: If a supplied value cannot be converted to ``float``.
        """
        calibrated = self._normalize_signals(calibrated_signals)
        left = calibrated[SHEAR_POSITION_LEFT]
        right = calibrated[SHEAR_POSITION_RIGHT]
        top = calibrated[SHEAR_POSITION_TOP]
        bottom = calibrated[SHEAR_POSITION_BOTTOM]

        lr_pair = self._has_opposite_sign_pair(left, right)
        tb_pair = self._has_opposite_sign_pair(top, bottom)

        b_lr = self._horizontal_component(left, right) if lr_pair else SHEAR_ZERO_VALUE
        b_tb = self._vertical_component(top, bottom) if tb_pair else SHEAR_ZERO_VALUE

        magnitude = math.hypot(b_lr, b_tb)
        angle_deg = (
            math.degrees(math.atan2(b_tb, b_lr))
            if magnitude > SHEAR_ZERO_VALUE
            else SHEAR_DEFAULT_ANGLE_DEG
        )

        # Lateral shear appears as equal-and-opposite contributions on each
        # opposing pair. Subtract only that common opposite-sign part so the
        # remaining pair signals represent normal force or an unbalanced tail.
        strain_vector = {
            SHEAR_POSITION_CENTER: SHEAR_ZERO_VALUE,
            SHEAR_POSITION_LEFT: -b_lr,
            SHEAR_POSITION_RIGHT: b_lr,
            SHEAR_POSITION_TOP: b_tb,
            SHEAR_POSITION_BOTTOM: -b_tb,
        }
        residual = {
            position: calibrated[position] - strain_vector[position]
            for position in SHEAR_SENSOR_POSITIONS
        }

        return ShearResult(
            calibrated=calibrated,
            strain_vector=strain_vector,
            residual=residual,
            b_lr=b_lr,
            b_tb=b_tb,
            shear_magnitude=magnitude,
            shear_angle_deg=angle_deg,
            has_shear=bool(lr_pair or tb_pair),
            lr_pair=lr_pair,
            tb_pair=tb_pair,
        )

    def _normalize_signals(self, calibrated_signals: Mapping[str, float]) -> dict[str, float]:
        return {
            position: float(calibrated_signals.get(position, SHEAR_ZERO_VALUE))
            for position in SHEAR_SENSOR_POSITIONS
        }

    def _has_opposite_sign_pair(self, first_value: float, second_value: float) -> bool:
        return (
            first_value != SHEAR_ZERO_VALUE
            and second_value != SHEAR_ZERO_VALUE
            and math.copysign(1.0, first_value) != math.copysign(1.0, second_value)
        )

    def _horizontal_component(self, left: float, right: float) -> float:
        return math.copysign(min(abs(left), abs(right)), right)

    def _vertical_component(self, top: float, bottom: float) -> float:
        return math.copysign(min(abs(top), abs(bottom)), top)
