"""PZT_RS wire-format constants and compatibility helpers."""

from __future__ import annotations


# PZT_RS payload layout. Source of truth is the firmware:
# Arduino_Sketches/PCB1.7_with_libraries/Teensy/libraries/PztRsController.h
# (kChannelsPerSensor, kRsValuesPerSensor, kOutputsPerSensor). These must stay
# in sync with it; tests/test_pzt_rs_wire_contract.py asserts that they do.
PZT_RS_CHANNELS_PER_SENSOR = 5
PZT_RS_RS_VALUES_PER_SENSOR = 2
PZT_RS_OUTPUTS_PER_SENSOR = PZT_RS_CHANNELS_PER_SENSOR + PZT_RS_RS_VALUES_PER_SENSOR
# Index of the first RS slot inside each per-sensor output group.
PZT_RS_FIRST_RS_SLOT = PZT_RS_CHANNELS_PER_SENSOR

# Change this in one place when switching the firmware/host RS wire scale.
# 10  -> 0.1 ohm per wire unit
# 100 -> 0.01 ohm per wire unit
PZT_RS_RS_WIRE_UNITS_PER_OHM = 100.0
PZT_RS_RS_OHMS_PER_WIRE_UNIT = 1.0 / PZT_RS_RS_WIRE_UNITS_PER_OHM


def pzt_rs_units_label_from_wire_scale(scale: float) -> str:
    """Return the archive metadata label for a given wire-scale value."""
    if scale == 10.0:
        return "deciohm"
    if scale == 100.0:
        return "centiohm"
    return f"ohm_div_{scale:g}".replace(".", "p")


PZT_RS_RS_UNITS_LABEL = pzt_rs_units_label_from_wire_scale(PZT_RS_RS_WIRE_UNITS_PER_OHM)


_PZT_RS_ARCHIVE_UNIT_TO_OHMS_SCALE = {
    "deciohm": 0.1,
    "centiohm": 0.01,
    PZT_RS_RS_UNITS_LABEL: PZT_RS_RS_OHMS_PER_WIRE_UNIT,
}


def extract_archive_rs_units(metadata) -> str | None:
    """Return the PZT_RS units label from archive metadata.

    Accepts both the nested ``{"metadata": {...}}`` header and the flat form.
    """
    if not isinstance(metadata, dict):
        return None
    inner = metadata.get("metadata")
    if isinstance(inner, dict):
        return inner.get("pzt_rs_rs_units")
    return metadata.get("pzt_rs_rs_units")


def get_pzt_rs_ohms_per_wire_unit(units_label: str | None = None) -> float | None:
    """Return the ohms-per-wire-unit scale for current or archived PZT_RS data."""
    if units_label is None:
        return PZT_RS_RS_OHMS_PER_WIRE_UNIT
    return _PZT_RS_ARCHIVE_UNIT_TO_OHMS_SCALE.get(str(units_label).strip().lower())
