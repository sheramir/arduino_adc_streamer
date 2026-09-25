"""PCB_TestBoard_7953 lane-aware acquisition routing helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from config.testboard_7953_board import ARRAY_ADC_LANES


TESTBOARD_MCU_NAME = "PCB_TestBoard_7953"

TESTBOARD_ARRAY_BOTH = "both"
TESTBOARD_ARRAY_1 = "1"
TESTBOARD_ARRAY_2 = "2"

TESTBOARD_SCAN_INTERLEAVED = "interleaved"
TESTBOARD_SCAN_ARRAY = "array"
TESTBOARD_SCAN_ADC = "adc"

TESTBOARD_ARRAY_LABELS = {
    "Both arrays": TESTBOARD_ARRAY_BOTH,
    "Array 1": TESTBOARD_ARRAY_1,
    "Array 2": TESTBOARD_ARRAY_2,
}

TESTBOARD_SCAN_ORDER_LABELS = {
    "Interleaved ADCs": TESTBOARD_SCAN_INTERLEAVED,
    "Array-at-a-time": TESTBOARD_SCAN_ARRAY,
    "ADC-at-a-time": TESTBOARD_SCAN_ADC,
}


def is_testboard_7953(mcu_name: str | None) -> bool:
    return (mcu_name or "").strip().lower() == TESTBOARD_MCU_NAME.lower()


def normalize_testboard_array_selection(value: str | None) -> str:
    text = (value or TESTBOARD_ARRAY_BOTH).strip()
    if text in TESTBOARD_ARRAY_LABELS:
        return TESTBOARD_ARRAY_LABELS[text]
    normalized = text.lower().replace("_", " ")
    if normalized in ("1", "array 1", "array1"):
        return TESTBOARD_ARRAY_1
    if normalized in ("2", "array 2", "array2"):
        return TESTBOARD_ARRAY_2
    return TESTBOARD_ARRAY_BOTH


def normalize_testboard_scan_order(value: str | None) -> str:
    text = (value or TESTBOARD_SCAN_INTERLEAVED).strip()
    if text in TESTBOARD_SCAN_ORDER_LABELS:
        return TESTBOARD_SCAN_ORDER_LABELS[text]
    normalized = text.lower().replace("_", " ").replace("-", " ")
    if normalized in ("array", "array at a time", "array hop"):
        return TESTBOARD_SCAN_ARRAY
    if normalized in ("adc", "adc at a time", "adc sequential"):
        return TESTBOARD_SCAN_ADC
    return TESTBOARD_SCAN_INTERLEAVED


def selected_testboard_arrays(selection: str | None) -> tuple[int, ...]:
    normalized = normalize_testboard_array_selection(selection)
    if normalized == TESTBOARD_ARRAY_1:
        return (1,)
    if normalized == TESTBOARD_ARRAY_2:
        return (2,)
    return (1, 2)


def physical_lanes_for_mapping(mapping_lane: int, selection: str | None) -> tuple[int, ...]:
    """Resolve a pair-local mapping lane to physical ADC lanes.

    Lanes 1/2 are mirrored to lanes 3/4 when array 2 is selected. Explicit
    legacy lanes 3/4 remain absolute array-2 routes.
    """
    lane = int(mapping_lane)
    arrays = selected_testboard_arrays(selection)
    if lane in (1, 2):
        return tuple(ARRAY_ADC_LANES[array_number][lane - 1] for array_number in arrays)
    if lane in (3, 4) and 2 in arrays:
        return (lane,)
    return ()


def _unique_routes(routes: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for adc_lane, channel in routes:
        route = (int(adc_lane), int(channel))
        if route in seen:
            continue
        if route[0] not in (1, 2, 3, 4) or not 0 <= route[1] <= 15:
            continue
        seen.add(route)
        result.append(route)
    return result


def build_testboard_routes(
    sensor_groups: Iterable[Mapping[str, object]],
    *,
    array_selection: str | None,
) -> list[tuple[int, int]]:
    """Build requested lane/channel membership without imposing scan order."""
    groups = list(sensor_groups)
    routes: list[tuple[int, int]] = []
    for group in groups:
        lanes = physical_lanes_for_mapping(
            int(group.get("mux", 1)), array_selection
        )
        for lane in lanes:
            for channel in group.get("channels", []):
                routes.append((lane, int(channel)))
    return _unique_routes(routes)


def _round_robin_lanes(
    routes_by_lane: dict[int, list[tuple[int, int]]], lanes: Iterable[int]
) -> list[tuple[int, int]]:
    ordered: list[tuple[int, int]] = []
    lane_list = list(lanes)
    depth = 0
    while True:
        added = False
        for lane in lane_list:
            lane_routes = routes_by_lane.get(lane, [])
            if depth < len(lane_routes):
                ordered.append(lane_routes[depth])
                added = True
        if not added:
            return ordered
        depth += 1


def order_testboard_routes(
    routes: Iterable[tuple[int, int]], scan_order: str | None
) -> list[tuple[int, int]]:
    """Order route membership exactly as firmware samples and transmits it."""
    unique = _unique_routes(routes)
    routes_by_lane = {
        lane: [route for route in unique if route[0] == lane]
        for lane in (1, 2, 3, 4)
    }
    normalized = normalize_testboard_scan_order(scan_order)
    if normalized == TESTBOARD_SCAN_ADC:
        return [route for lane in (1, 2, 3, 4) for route in routes_by_lane[lane]]
    if normalized == TESTBOARD_SCAN_ARRAY:
        return (
            _round_robin_lanes(routes_by_lane, (1, 2))
            + _round_robin_lanes(routes_by_lane, (3, 4))
        )
    return _round_robin_lanes(routes_by_lane, (1, 2, 3, 4))


def format_testboard_routes(routes: Iterable[tuple[int, int]]) -> str:
    return ",".join(f"{int(adc_lane)}:{int(channel)}" for adc_lane, channel in routes)
