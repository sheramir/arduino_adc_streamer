"""Helpers for selecting a single tracked point across an array heatmap."""

from __future__ import annotations

from dataclasses import dataclass

from constants.heatmap import SENSOR_POS_X, SENSOR_POS_Y
from data_processing.heatmap_signal_processing import HEATMAP_SENSOR_LABEL_ORDER

PAIR_RESIDUAL_RATIO = 0.25
ACTIVE_LABEL_RATIO = 0.25


@dataclass(frozen=True, slots=True)
class PointTrackingTarget:
    kind: str
    score: float
    intensity: float
    center_x: float
    center_y: float
    sensor_ids: tuple[str, ...]
    active_labels: tuple[str, ...]


def _build_label_weights(sensor_values) -> dict[str, float]:
    weights = {}
    values = list(sensor_values or [])
    for index, label in enumerate(HEATMAP_SENSOR_LABEL_ORDER):
        value = float(values[index]) if index < len(values) else 0.0
        weights[label] = max(0.0, value)
    return weights


def _dominant_active_labels(weights: dict[str, float]) -> tuple[str, ...]:
    if not weights:
        return ()
    max_value = max(float(value) for value in weights.values())
    if max_value <= 0.0:
        return ()
    threshold = max(1e-6, max_value * ACTIVE_LABEL_RATIO)
    return tuple(
        label
        for label in HEATMAP_SENSOR_LABEL_ORDER
        if float(weights.get(label, 0.0)) >= threshold
    )


def _is_edge_pair_dominant(sensor, edge_label: str) -> bool:
    edge_weight = float(sensor["weights"].get(edge_label, 0.0))
    if edge_weight <= 0.0:
        return False

    residual = sum(
        float(value)
        for label, value in sensor["weights"].items()
        if label != edge_label
    )
    return residual <= (edge_weight * PAIR_RESIDUAL_RATIO)


def _sensor_candidate(center, weights, sensor_id, sensor_diameter_mm: float) -> PointTrackingTarget | None:
    active_labels = _dominant_active_labels(weights)
    if not active_labels:
        return None

    total = sum(weights[label] for label in active_labels)
    if total <= 0.0:
        return None

    radius = max(0.0, float(sensor_diameter_mm) * 0.5)
    local_x = 0.0
    local_y = 0.0
    for index, label in enumerate(HEATMAP_SENSOR_LABEL_ORDER):
        weight = weights.get(label, 0.0)
        if weight <= 0.0:
            continue
        local_x += weight * float(SENSOR_POS_X[index]) * radius
        local_y += weight * float(SENSOR_POS_Y[index]) * radius

    return PointTrackingTarget(
        kind="sensor",
        score=total,
        intensity=total,
        center_x=float(center[0]) + (local_x / total),
        center_y=float(center[1]) + (local_y / total),
        sensor_ids=(str(sensor_id),),
        active_labels=active_labels,
    )


def _horizontal_pair_candidate(left_sensor, right_sensor, sensor_diameter_mm: float) -> PointTrackingTarget | None:
    if not _is_edge_pair_dominant(left_sensor, "R") or not _is_edge_pair_dominant(right_sensor, "L"):
        return None

    left_weight = float(left_sensor["weights"]["R"])
    right_weight = float(right_sensor["weights"]["L"])
    total = left_weight + right_weight
    if total <= 0.0:
        return None

    radius = max(0.0, float(sensor_diameter_mm) * 0.5)
    left_edge = float(left_sensor["center"][0]) + radius
    right_edge = float(right_sensor["center"][0]) - radius
    center_x = ((left_edge * left_weight) + (right_edge * right_weight)) / total
    center_y = (
        (float(left_sensor["center"][1]) * left_weight)
        + (float(right_sensor["center"][1]) * right_weight)
    ) / total
    return PointTrackingTarget(
        kind="pair",
        score=total,
        intensity=total,
        center_x=center_x,
        center_y=center_y,
        sensor_ids=(str(left_sensor["sensor_id"]), str(right_sensor["sensor_id"])),
        active_labels=("R", "L"),
    )


def _vertical_pair_candidate(upper_sensor, lower_sensor, sensor_diameter_mm: float) -> PointTrackingTarget | None:
    if not _is_edge_pair_dominant(upper_sensor, "B") or not _is_edge_pair_dominant(lower_sensor, "T"):
        return None

    upper_weight = float(upper_sensor["weights"]["B"])
    lower_weight = float(lower_sensor["weights"]["T"])
    total = upper_weight + lower_weight
    if total <= 0.0:
        return None

    radius = max(0.0, float(sensor_diameter_mm) * 0.5)
    upper_edge = float(upper_sensor["center"][1]) + radius
    lower_edge = float(lower_sensor["center"][1]) - radius
    center_x = (
        (float(upper_sensor["center"][0]) * upper_weight)
        + (float(lower_sensor["center"][0]) * lower_weight)
    ) / total
    center_y = ((upper_edge * upper_weight) + (lower_edge * lower_weight)) / total
    return PointTrackingTarget(
        kind="pair",
        score=total,
        intensity=total,
        center_x=center_x,
        center_y=center_y,
        sensor_ids=(str(upper_sensor["sensor_id"]), str(lower_sensor["sensor_id"])),
        active_labels=("B", "T"),
    )


def resolve_point_tracking_target(
    package_results,
    sensor_ids,
    sensor_positions,
    sensor_centers,
    sensor_diameter_mm: float,
) -> PointTrackingTarget | None:
    """Return the strongest single point to render across the full array."""
    package_results = list(package_results or [])
    sensor_ids = list(sensor_ids or [])
    sensor_positions = list(sensor_positions or [])
    sensor_centers = list(sensor_centers or [])

    sensors = []
    limit = min(
        len(package_results),
        len(sensor_ids),
        len(sensor_positions),
        len(sensor_centers),
    )
    if limit <= 0:
        return None

    for index in range(limit):
        result = package_results[index]
        sensor_values = result[5] if len(result) > 5 else []
        weights = _build_label_weights(sensor_values)
        active_labels = _dominant_active_labels(weights)
        if not active_labels:
            continue
        sensors.append(
            {
                "sensor_id": str(sensor_ids[index]),
                "position": sensor_positions[index],
                "center": sensor_centers[index],
                "weights": weights,
                "active_labels": active_labels,
            }
        )

    if not sensors:
        return None

    sensor_by_position = {
        tuple(sensor["position"]): sensor
        for sensor in sensors
        if sensor["position"] is not None
    }

    pair_candidates = []
    paired_sensor_ids = set()
    for sensor in sensors:
        position = sensor["position"]
        if position is None:
            continue
        row, col = position

        right_neighbor = sensor_by_position.get((row, col + 1))
        if right_neighbor is not None:
            candidate = _horizontal_pair_candidate(sensor, right_neighbor, sensor_diameter_mm)
            if candidate is not None:
                pair_candidates.append(candidate)
                paired_sensor_ids.update(candidate.sensor_ids)

        lower_neighbor = sensor_by_position.get((row + 1, col))
        if lower_neighbor is not None:
            candidate = _vertical_pair_candidate(sensor, lower_neighbor, sensor_diameter_mm)
            if candidate is not None:
                pair_candidates.append(candidate)
                paired_sensor_ids.update(candidate.sensor_ids)

    sensor_candidates = []
    for sensor in sensors:
        if sensor["sensor_id"] in paired_sensor_ids:
            continue
        candidate = _sensor_candidate(
            sensor["center"],
            sensor["weights"],
            sensor["sensor_id"],
            sensor_diameter_mm,
        )
        if candidate is not None:
            sensor_candidates.append(candidate)

    candidates = pair_candidates + sensor_candidates
    if not candidates:
        return None

    return max(
        candidates,
        key=lambda candidate: (
            float(candidate.score),
            1 if candidate.kind == "pair" else 0,
            float(candidate.intensity),
        ),
    )
