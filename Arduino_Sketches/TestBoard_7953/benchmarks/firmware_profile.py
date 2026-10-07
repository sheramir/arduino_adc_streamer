"""Decode bounded firmware profiling summaries without touching wire framing."""

from __future__ import annotations

import json
import math
from pathlib import Path

PHASES = (
    "prepare", "session", "transfer", "validate", "encode", "capacity",
    "usb_write", "acquisition", "foreground", "bookkeeping", "period", "gap", "run_prepare",
)
SCALARS = (
    "clock_hz", "attempts", "written", "aborted", "invalid_foreground",
    "frequency_changes", "probe_cycles_min", "probe_cycles_max", "write_calls",
    "capacity_min", "capacity_max", "capacity_below_frame",
)


def _integers(value: str) -> list[int]:
    tokens = value.split(",")
    if not all(token.isascii() and token.isdigit() for token in tokens):
        raise ValueError(f"Invalid profile integer list: {value!r}")
    return [int(token) for token in tokens]


def _quantile_upper(bounds: list[int], bins: list[int], fraction: float):
    target = math.ceil(sum(bins) * fraction)
    if not target:
        return None
    seen = 0
    for index, count in enumerate(bins):
        seen += count
        if seen >= target:
            return bounds[index] if index < len(bounds) else None
    raise ValueError("Incomplete profile histogram")


def decode_profile(status: dict[str, str]) -> dict:
    available = status.get("profile_available", "false") == "true"
    enabled = status.get("profile_enabled", "false") == "true"
    result = dict(available=available, enabled=enabled)
    if not enabled:
        return result
    version = status.get("profile_version")
    if not available or version not in ("1", "2") or status.get("running") != "false":
        raise ValueError("Missing/unsupported stopped firmware profile")
    try:
        scalar_lists = {key: _integers(status[f"profile_{key}"]) for key in SCALARS}
        if any(len(values) != 1 for values in scalar_lists.values()):
            raise ValueError("Invalid profile scalar width")
        scalars = {key: values[0] for key, values in scalar_lists.items()}
        discarded = _integers(status["profile_discarded"]) if version == "2" else [0]
        if len(discarded) != 1:
            raise ValueError("Invalid profile discarded scalar width")
        scalars["discarded"] = discarded[0]
        bounds = _integers(status["profile_bounds_us"])
        if len(bounds) != 16 or bounds != sorted(set(bounds)) or bounds[0] < 1:
            raise ValueError("Invalid profile histogram bounds")
        if scalars["clock_hz"] <= 0:
            raise ValueError("Invalid profiling clock")
        if scalars["attempts"] != scalars["written"] + scalars["discarded"] + scalars["aborted"]:
            raise ValueError("Inconsistent profile sweep counts")
        if scalars["frequency_changes"] or scalars["invalid_foreground"]:
            raise ValueError("Profile clock changed or foreground interval spanned a counter wrap")
        if scalars["capacity_below_frame"] > scalars["write_calls"]:
            raise ValueError("Invalid profile capacity counts")
        phases = {}
        for name in PHASES:
            values = _integers(status[f"profile_{name}"])
            if len(values) != 5 + len(bounds) + 1:
                raise ValueError(f"Invalid profile phase width: {name}")
            count, total, maximum, over100, over1000, *bins = values
            if (sum(bins) != count or not 0 <= over1000 <= over100 <= count
                    or not maximum <= total <= maximum * count):
                raise ValueError(f"Inconsistent profile phase: {name}")
            ticks_per_us = 1 if name in ("period", "gap") else scalars["clock_hz"] / 1_000_000
            phases[name] = dict(
                count=count, total_ticks=total, max_ticks=maximum, histogram=bins,
                mean_us=total / count / ticks_per_us if count else None,
                max_us=maximum / ticks_per_us if count else None,
                p95_upper_us=_quantile_upper(bounds, bins, .95),
                p99_upper_us=_quantile_upper(bounds, bins, .99),
                over_100us=over100, over_1ms=over1000,
                ticks_unit="us" if name in ("period", "gap") else "cycles",
            )
        if phases["bookkeeping"]["count"] != scalars["attempts"]:
            raise ValueError("Incomplete profile bookkeeping count")
        tails = []
        for index in range(8):
            raw = status.get(f"profile_tail{index}")
            if raw is None:
                break
            values = _integers(raw)
            if len(values) != 8 or values[0] <= 100:
                raise ValueError("Invalid profile tail snapshot")
            names = ("period_us", "gap_us", "previous_acquisition_us", "previous_encode_us",
                     "previous_capacity_us", "previous_usb_write_us", "previous_bookkeeping_us", "foreground_us")
            tails.append({name: value if pos < 2 else value * 1_000_000 / scalars["clock_hz"]
                          for pos, (name, value) in enumerate(zip(names, values))})
        result.update(scalars, histogram_bounds_us=bounds, phases=phases,
                      longest_periods=sorted(tails, key=lambda item: item["period_us"], reverse=True),
                      scope="whole run including warm-up; elapsed cycles include interrupts")
        return result
    except KeyError as exc:
        raise ValueError(f"Missing profile field: {exc.args[0]}") from exc


def save_profile(path: Path, status: dict[str, str], *, received_frames: int,
                 requested: str, **labels) -> dict:
    """Persist original fields even if parsing/count reconciliation fails."""
    record = dict(labels, requested=requested, received_frames=received_frames,
                  raw_status={k: v for k, v in status.items() if k.startswith("profile_")},
                  running=status.get("running"))
    error = None
    try:
        summary = decode_profile(status)
        if summary["enabled"] != (requested == "on"):
            raise ValueError("Firmware profiling mode does not match the requested mode")
        if summary["enabled"] and summary["aborted"]:
            raise ValueError(f"Firmware profiling recorded {summary['aborted']} aborted sweeps")
        if summary["enabled"] and summary["written"] != received_frames:
            raise ValueError(f"Written/received frame count mismatch: {summary['written']} / {received_frames}")
        record["summary"] = summary
    except ValueError as exc:
        record["error"] = str(exc)
        error = exc
    with path.open("a", encoding="utf-8") as destination:
        destination.write(json.dumps(record, allow_nan=False) + "\n")
    if error:
        raise error
    return summary
