"""Physical wiring profile for PCB_TestBoard_7953.

This file is the host-side source of truth for converting a physical-array and
PZT-sensor selection into ADS7953 routes.  Keep spatial sensor placement in the
sensor library; only fixed PCB wiring belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass


TESTBOARD_7953_MCU_NAME = "PCB_TestBoard_7953"
PZT_CHANNEL_LABELS = ("B", "L", "C", "R", "T")

# ADC position is one-based within an array pair.  The two arrays currently
# have identical sensor wiring, but their physical ADC lane numbers differ.
ARRAY_ADC_LANES: dict[int, tuple[int, int]] = {
    1: (1, 2),
    2: (3, 4),
}


@dataclass(frozen=True, slots=True)
class PztBoardRoute:
    adc_position: int
    channels: tuple[int, int, int, int, int]


PZT_SENSOR_ROUTES: dict[str, PztBoardRoute] = {
    "PZT6": PztBoardRoute(adc_position=1, channels=(0, 1, 2, 3, 4)),
    "PZT7": PztBoardRoute(adc_position=1, channels=(5, 6, 7, 8, 9)),
    "PZT1": PztBoardRoute(adc_position=2, channels=(0, 1, 2, 3, 4)),
    "PZT3": PztBoardRoute(adc_position=2, channels=(5, 6, 7, 8, 9)),
    "PZT5": PztBoardRoute(adc_position=2, channels=(10, 11, 12, 13, 14)),
}


def supported_pzt_sensors() -> tuple[str, ...]:
    """Return selectable PZT IDs in physical board order."""
    return tuple(PZT_SENSOR_ROUTES)


def build_testboard_sensor_groups(sensor_ids: list[str]) -> list[dict[str, object]]:
    """Build route groups from fixed wiring, preserving user selection order."""
    groups: list[dict[str, object]] = []
    sequence_cursor = 0
    for sensor_id in sensor_ids:
        normalized = str(sensor_id).strip().upper()
        route = PZT_SENSOR_ROUTES.get(normalized)
        if route is None:
            continue
        channels = list(route.channels)
        groups.append({
            "sensor_id": normalized,
            "mux": route.adc_position,
            "channels": channels,
            "channel_labels": list(PZT_CHANNEL_LABELS),
            "positions": list(range(sequence_cursor, sequence_cursor + len(channels))),
        })
        sequence_cursor += len(channels)
    return groups
