"""
Normal-force computation for shear-removed five-sensor piezo signals.

This module implements Step 5 of the Shear & Pressure Map pipeline. It accepts
residual signals from ``ShearDetector`` after noise thresholding and shear
removal, determines whether the remaining normal force is compression, tension,
or none, shifts the outer-sensor baseline for centroid stability, and returns a
signed total force plus a global force-center readout.

Dependencies:
    Python math utilities, collection mappings, dataclasses, and
    constants.shear.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from constants.shear import (
    DEFAULT_NORMAL_FORCE_SENSOR_SPACING_MM,
    NORMAL_FORCE_DENOMINATOR_EPSILON,
    NORMAL_FORCE_SENSOR_COUNT,
    SHEAR_FORCE_TYPE_COMPRESSION,
    SHEAR_FORCE_TYPE_NONE,
    SHEAR_FORCE_TYPE_TENSION,
    SHEAR_OUTER_SENSOR_POSITIONS,
    SHEAR_POSITION_BOTTOM,
    SHEAR_POSITION_CENTER,
    SHEAR_POSITION_LEFT,
    SHEAR_POSITION_RIGHT,
    SHEAR_POSITION_TOP,
    SHEAR_SENSOR_POSITIONS,
    SHEAR_ZERO_VALUE,
)


@dataclass(frozen=True, slots=True)
class NormalForceResult:
    """Result of normal-force and global centroid computation.

    Args:
        residual: Input shear-removed residual signals by sensor position.
        normalized: Baseline-shifted signals used for centroid and pressure-map
            generation.
        force_type: One of ``compression``, ``tension``, or ``none``.
        baseline_offset: Uniform outer-sensor baseline ``U`` subtracted from
            every sensor.
        baseline_force: Integrated baseline force ``5 * U`` added back to the
            normalized sum.
        total_force: Signed total normal force. Positive means compression and
            negative means tension.
        x_mm: Global x centroid in millimeters.
        y_mm: Global y centroid in millimeters.
        sensor_spacing_mm: Center-to-outer sensor spacing used for the centroid.

    Usage example:
        result = NormalForceCalculator().compute({"C": 10, "L": 4, "R": 4, "T": 4, "B": 4})
        assert result.force_type == "compression"
    """

    residual: dict[str, float]
    normalized: dict[str, float]
    force_type: str
    baseline_offset: float
    baseline_force: float
    total_force: float
    x_mm: float
    y_mm: float
    sensor_spacing_mm: float


class NormalForceCalculator:
    """Compute normal force magnitude, type, and global force position.

    Args:
        sensor_spacing_mm: Center-to-outer spacing in millimeters. This is the
            distance from ``C`` to any outer sensor, not the full package width.

    Usage example:
        calculator = NormalForceCalculator(sensor_spacing_mm=1.75)
        result = calculator.compute({"C": 7, "L": 9, "R": 2, "T": 5, "B": 3})
    """

    def __init__(self, sensor_spacing_mm: float = DEFAULT_NORMAL_FORCE_SENSOR_SPACING_MM) -> None:
        self.sensor_spacing_mm = float(sensor_spacing_mm)

    def compute(self, residual_signals: Mapping[str, float]) -> NormalForceResult:
        """Compute force type, total force, normalized signals, and centroid.

        Args:
            residual_signals: Mapping keyed by ``C``, ``L``, ``R``, ``T``, and
                ``B`` after shear removal. Missing positions are treated as zero.

        Returns:
            NormalForceResult containing signed total force, force type,
            baseline-shifted signals, and centroid coordinates.

        Raises:
            TypeError: If a supplied signal value cannot be converted to float.
        """
        residual = self._normalize_signals(residual_signals)
        force_type = self._determine_force_type(residual)
        baseline_offset = self._baseline_offset(residual, force_type)
        normalized = {
            position: residual[position] - baseline_offset
            for position in SHEAR_SENSOR_POSITIONS
        }
        baseline_force = float(NORMAL_FORCE_SENSOR_COUNT) * baseline_offset
        total_force = sum(normalized.values()) + baseline_force
        x_mm = self._axis_position(
            positive_value=normalized[SHEAR_POSITION_RIGHT],
            negative_value=normalized[SHEAR_POSITION_LEFT],
            center_value=normalized[SHEAR_POSITION_CENTER],
        )
        y_mm = self._axis_position(
            positive_value=normalized[SHEAR_POSITION_TOP],
            negative_value=normalized[SHEAR_POSITION_BOTTOM],
            center_value=normalized[SHEAR_POSITION_CENTER],
        )

        return NormalForceResult(
            residual=residual,
            normalized=normalized,
            force_type=force_type,
            baseline_offset=baseline_offset,
            baseline_force=baseline_force,
            total_force=total_force,
            x_mm=x_mm,
            y_mm=y_mm,
            sensor_spacing_mm=self.sensor_spacing_mm,
        )

    def _normalize_signals(self, residual_signals: Mapping[str, float]) -> dict[str, float]:
        return {
            position: float(residual_signals.get(position, SHEAR_ZERO_VALUE))
            for position in SHEAR_SENSOR_POSITIONS
        }

    def _determine_force_type(self, residual: Mapping[str, float]) -> str:
        center_value = residual[SHEAR_POSITION_CENTER]
        if center_value > SHEAR_ZERO_VALUE:
            return SHEAR_FORCE_TYPE_COMPRESSION
        if center_value < SHEAR_ZERO_VALUE:
            return SHEAR_FORCE_TYPE_TENSION
        return self._infer_force_type_from_outer_sensors(residual)

    def _infer_force_type_from_outer_sensors(self, residual: Mapping[str, float]) -> str:
        outer_values = [residual[position] for position in SHEAR_OUTER_SENSOR_POSITIONS]
        positive_values = [value for value in outer_values if value > SHEAR_ZERO_VALUE]
        negative_values = [value for value in outer_values if value < SHEAR_ZERO_VALUE]

        if not positive_values and not negative_values:
            return SHEAR_FORCE_TYPE_NONE
        if len(positive_values) > len(negative_values):
            return SHEAR_FORCE_TYPE_COMPRESSION
        if len(negative_values) > len(positive_values):
            return SHEAR_FORCE_TYPE_TENSION

        # Opposite-sign outer values should already be removed by the shear
        # stage. If a tie remains, use signed magnitude so larger residual
        # evidence controls the inferred type instead of arbitrary position.
        positive_magnitude = sum(positive_values)
        negative_magnitude = sum(abs(value) for value in negative_values)
        if positive_magnitude > negative_magnitude:
            return SHEAR_FORCE_TYPE_COMPRESSION
        if negative_magnitude > positive_magnitude:
            return SHEAR_FORCE_TYPE_TENSION
        return SHEAR_FORCE_TYPE_NONE

    def _baseline_offset(self, residual: Mapping[str, float], force_type: str) -> float:
        outer_values = [residual[position] for position in SHEAR_OUTER_SENSOR_POSITIONS]
        if force_type == SHEAR_FORCE_TYPE_COMPRESSION:
            return min(outer_values)
        if force_type == SHEAR_FORCE_TYPE_TENSION:
            return max(outer_values)
        return SHEAR_ZERO_VALUE

    def _axis_position(self, positive_value: float, negative_value: float, center_value: float) -> float:
        denominator = positive_value + negative_value + center_value
        if abs(denominator) <= NORMAL_FORCE_DENOMINATOR_EPSILON:
            return SHEAR_ZERO_VALUE
        raw_position = self.sensor_spacing_mm * (positive_value - negative_value) / denominator
        return self._clamp_to_sensor_spacing(raw_position)

    def _clamp_to_sensor_spacing(self, value: float) -> float:
        return max(-self.sensor_spacing_mm, min(self.sensor_spacing_mm, value))
