"""Reusable PZT voltage-to-force reconstruction helpers.

The functions in this module are intentionally independent of the Analysis tab
and PyQt widgets so the same force reconstruction can be reused by live views,
exports, calibration tools, or future processing pipelines.

Force is reconstructed from the PZT voltage waveform by treating the measured
voltage as the voltage across a piezoelectric capacitance with an effective
leak path. The signal midpoint is preferably estimated from an initial quiet
window using ``Vmid = median(Vquiet)``. Quiet-window noise is measured with
absolute deviation from Vmid. The reported MAD and robust sigma are kept for
diagnostics, but the force threshold uses the same method for every channel:
a high-percentile absolute deviation from Vmid. This behaves better for
ADC-quantized quiet windows where MAD can jump between zero and a large value
for visually similar traces. When no explicit midpoint is supplied, the
calculator falls back to the full-trace median. Samples whose centered voltage
is below the selected threshold are set to zero before integration.

For each sample, the leakage decay over the elapsed time is:
``alpha = exp(-dt / (Rleak * Cpzt))``. The generated charge increment is then
estimated as ``dQ = Cpzt * beta * (v[n] - alpha * v[n-1])``, where ``beta``
optionally corrects charge that decays between physical MUX connection and the
effective ADC sample. The returned force trace is the accumulated sum of those
increments. After a positive/negative bipolar event returns below the noise
threshold, the accumulator is reset to reduce drift.

All low-level calculation inputs use SI units:

- voltage in volts
- timestamps in seconds
- capacitance in farads
- leak resistance in ohms
- d33 in coulombs per newton
- force output in newtons
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np

from constants.pzt_force import (
    PZT_FORCE_DEFAULT_SETTINGS,
    PZT_FORCE_MAD_TO_SIGMA,
    PZT_FORCE_NOISE_PERCENTILE,
    PZT_FORCE_PIC_COULOMB_TO_COULOMB,
)


@dataclass(slots=True)
class PztQuietBaselineEstimate:
    """Robust baseline/noise estimate from a quiet voltage window."""

    vmid_v: float
    noise_threshold_v: float
    mad_v: float
    sigma_v: float
    sample_count: int


def calculate_pzt_force_from_settings(
    voltage_v,
    time_s,
    settings: Mapping[str, object] | None = None,
    *,
    vmid_v: float | None = None,
    noise_threshold_v: float | None = None,
    leak_dt_s=None,
    pre_sample_decay_dt_s=None,
) -> np.ndarray:
    """Calculate PZT force from voltage using persisted/UI-style settings.

    Parameters
    ----------
    voltage_v:
        One-dimensional voltage samples in volts. The median voltage is treated
        as the signal midpoint and subtracted before reconstruction.
    time_s:
        Sample timestamps in seconds. Values must be the same length as
        ``voltage_v`` and strictly increasing.
    settings:
        Optional mapping with the keys from ``PZT_FORCE_DEFAULT_SETTINGS``:
        ``capacitance_value``, ``capacitance_unit``, ``rleak_ohm``,
        ``d33_pc_per_n``, and ``noise_threshold_v``. Missing keys are filled
        from the shared defaults.
    vmid_v:
        Optional explicit midpoint voltage. When omitted, the calculator falls
        back to the full-trace median.
    noise_threshold_v:
        Optional explicit centered voltage threshold. When omitted, the value
        from ``settings`` is used.

    Returns
    -------
    np.ndarray
        Reconstructed force samples in newtons.
    """
    resolved = {**PZT_FORCE_DEFAULT_SETTINGS, **dict(settings or {})}
    capacitance_f = pzt_capacitance_to_farads(
        float(resolved["capacitance_value"]),
        str(resolved["capacitance_unit"]),
    )
    d33_c_per_n = float(resolved["d33_pc_per_n"]) * PZT_FORCE_PIC_COULOMB_TO_COULOMB
    return calculate_pzt_force_from_voltage(
        voltage_v,
        time_s,
        capacitance_f=capacitance_f,
        rleak_ohm=float(resolved["rleak_ohm"]),
        d33_c_per_n=d33_c_per_n,
        noise_threshold_v=float(noise_threshold_v if noise_threshold_v is not None else resolved["noise_threshold_v"]),
        vmid_v=vmid_v,
        leak_dt_s=leak_dt_s,
        pre_sample_decay_dt_s=pre_sample_decay_dt_s,
        off_mux_rleak_ohm=_optional_positive_float(resolved.get("off_mux_rleak_ohm"))
        if bool(resolved.get("off_mux_leak_enabled", False))
        else None,
    )


def estimate_pzt_quiet_baseline(
    voltage_v,
    time_s,
    *,
    quiet_duration_s: float,
    noise_sigma_multiplier: float,
) -> PztQuietBaselineEstimate:
    """Estimate Vmid and noise threshold from an initial quiet window.

    The quiet window starts at the first timestamp and extends for
    ``quiet_duration_s`` seconds. The midpoint is the median of that window.
    Noise diagnostics include median absolute deviation:
    ``MAD = median(abs(Vquiet - Vmid))`` and
    ``sigma ~= 1.4826 * MAD``. The returned noise threshold uses the same
    percentile-deviation method for all channels:
    ``threshold = percentile(abs(Vquiet - Vmid), 95)``. The reported
    ``sigma_v`` is back-calculated as ``threshold / noise_sigma_multiplier`` so
    the UI still shows a threshold-equivalent sigma for the chosen k.
    """
    voltage = np.asarray(voltage_v, dtype=np.float64).reshape(-1)
    times = np.asarray(time_s, dtype=np.float64).reshape(-1)
    if voltage.size == 0:
        raise ValueError("PZT quiet baseline requires voltage samples")
    if times.size != voltage.size:
        raise ValueError("PZT quiet baseline timestamps must match voltage samples")
    if voltage.size > 1 and not np.all(np.diff(times) > 0.0):
        raise ValueError("PZT quiet baseline timestamps must be strictly increasing")

    duration = max(0.0, float(quiet_duration_s))
    start_s = float(times[0]) if times.size else 0.0
    if duration > 0.0:
        mask = times <= start_s + duration
        quiet = voltage[mask]
    else:
        quiet = voltage
    if quiet.size == 0:
        quiet = voltage[:1]

    vmid = float(np.median(quiet))
    absolute_deviation = np.abs(quiet - vmid)
    mad = float(np.median(absolute_deviation))
    threshold = float(np.percentile(absolute_deviation, PZT_FORCE_NOISE_PERCENTILE))
    if threshold <= 0.0:
        sigma = float(PZT_FORCE_MAD_TO_SIGMA * mad)
        threshold = float(abs(noise_sigma_multiplier) * sigma)
    else:
        sigma = float(threshold / max(abs(float(noise_sigma_multiplier)), 1e-12))
    return PztQuietBaselineEstimate(
        vmid_v=vmid,
        noise_threshold_v=threshold,
        mad_v=mad,
        sigma_v=sigma,
        sample_count=int(quiet.size),
    )


def pzt_capacitance_to_farads(value: float, unit: str) -> float:
    """Convert a capacitance value from ``pF``, ``nF``, or ``F`` to farads.

    Raises
    ------
    ValueError
        If ``unit`` is not one of the supported capacitance units.
    """
    normalized = str(unit).strip().lower()
    if normalized == "pf":
        return float(value) * 1e-12
    if normalized == "nf":
        return float(value) * 1e-9
    if normalized == "f":
        return float(value)
    raise ValueError(f"unsupported capacitance unit '{unit}'")


def validate_pzt_force_settings(capacitance_f: float, rleak_ohm: float, d33_c_per_n: float) -> None:
    """Validate low-level SI-unit parameters for PZT force reconstruction.

    Raises
    ------
    ValueError
        If capacitance, leak resistance, or d33 is not strictly positive.
    """
    if capacitance_f <= 0.0:
        raise ValueError("PZT capacitance must be greater than zero")
    if rleak_ohm <= 0.0:
        raise ValueError("leak resistance must be greater than zero")
    if d33_c_per_n <= 0.0:
        raise ValueError("d33 must be greater than zero")


def calculate_pzt_force_from_voltage(
    voltage_v,
    time_s,
    *,
    capacitance_f: float,
    rleak_ohm: float,
    d33_c_per_n: float,
    noise_threshold_v: float,
    vmid_v: float | None = None,
    leak_dt_s=None,
    pre_sample_decay_dt_s=None,
    off_mux_rleak_ohm: float | None = None,
) -> np.ndarray:
    """Reconstruct force from centered PZT voltage dynamics.

    The algorithm models the PZT and leak path as an RC system:
    ``tau = rleak_ohm * capacitance_f``. For every sample it estimates the
    generated charge increment as ``C * (v[n] - alpha * v[n-1])`` and converts
    charge to force using ``d33``.

    Before integration, the signal midpoint is estimated using the median of
    ``voltage_v``. Samples whose centered absolute voltage is below
    ``noise_threshold_v`` are set to zero and therefore do not contribute to
    the integrated force. After a bipolar event returns below threshold, the
    force accumulator is reset to reduce drift.

    Parameters
    ----------
    voltage_v:
        Voltage samples in volts.
    time_s:
        Strictly increasing sample timestamps in seconds.
    capacitance_f:
        PZT capacitance in farads.
    rleak_ohm:
        Effective leak resistance in ohms.
    d33_c_per_n:
        Piezoelectric charge constant in coulombs per newton.
    noise_threshold_v:
        Centered voltage threshold in volts. The absolute value is used.
    leak_dt_s:
        Optional MUX-connected leak exposure in seconds. If omitted, leakage is
        modeled continuously over the elapsed timestamp delta for backward
        compatibility. A scalar applies to every interval; an array may either
        match ``time_s`` length or the interval count ``len(time_s) - 1``.
    pre_sample_decay_dt_s:
        Optional physical MUX-connection-to-effective-sample decay in seconds.
        This independently corrects newly accumulated charge before the ADC
        sample; it does not replace the previous-sample leakage interval.

    Returns
    -------
    np.ndarray
        Reconstructed force samples in newtons. Empty input returns an empty
        array.

    Raises
    ------
    ValueError
        If timestamps do not match voltage length, timestamps are not strictly
        increasing, or physical parameters are not positive.
    """
    validate_pzt_force_settings(capacitance_f, rleak_ohm, d33_c_per_n)
    voltage = np.asarray(voltage_v, dtype=np.float64).reshape(-1)
    times = np.asarray(time_s, dtype=np.float64).reshape(-1)
    if voltage.size == 0:
        return np.empty(0, dtype=np.float64)
    if times.size != voltage.size:
        raise ValueError("PZT force timestamps must match voltage samples")
    if voltage.size > 1 and not np.all(np.diff(times) > 0.0):
        raise ValueError("PZT force timestamps must be strictly increasing")
    leak_intervals = _normalize_leak_intervals(leak_dt_s, voltage.size)
    pre_sample_intervals = _normalize_leak_intervals(pre_sample_decay_dt_s, voltage.size)
    if pre_sample_intervals is not None and np.any(pre_sample_intervals < 0.0):
        raise ValueError("PZT force pre_sample_decay_dt_s must not be negative")

    v_mid = float(np.median(voltage) if vmid_v is None else vmid_v)
    active_centered = voltage - v_mid
    threshold = abs(float(noise_threshold_v))
    active_centered[np.abs(active_centered) < threshold] = 0.0
    tau = float(rleak_ohm) * float(capacitance_f)
    tau_off = None
    if off_mux_rleak_ohm is not None:
        off_mux_rleak = float(off_mux_rleak_ohm)
        if off_mux_rleak <= 0.0:
            raise ValueError("off-MUX leak resistance must be greater than zero")
        tau_off = off_mux_rleak * float(capacitance_f)
    scale = float(capacitance_f) / float(d33_c_per_n)
    force = np.zeros_like(active_centered, dtype=np.float64)
    accumulator = 0.0
    event_polarity = 0
    saw_opposite_pair = False

    previous_v = float(active_centered[0])
    current_polarity = _polarity(previous_v, threshold)
    if current_polarity:
        event_polarity = current_polarity

    for index in range(1, active_centered.size):
        dt = float(times[index] - times[index - 1])
        if dt <= 0.0:
            raise ValueError("PZT force timestamps must be strictly increasing")
        leak_dt = dt if leak_intervals is None else float(leak_intervals[index - 1])
        leak_dt = min(max(leak_dt, 0.0), dt)
        decay_exponent = leak_dt / tau
        if tau_off is not None:
            decay_exponent += max(dt - leak_dt, 0.0) / tau_off
        alpha = float(np.exp(-decay_exponent))
        pre_sample_decay = (
            0.0 if pre_sample_intervals is None else float(pre_sample_intervals[index - 1])
        )
        new_charge_decay_correction = float(np.exp(pre_sample_decay / tau))
        current_v = float(active_centered[index])
        accumulator += scale * new_charge_decay_correction * (
            current_v - (alpha * previous_v)
        )

        current_polarity = _polarity(current_v, threshold)
        if current_polarity:
            if event_polarity and current_polarity != event_polarity:
                saw_opposite_pair = True
            event_polarity = current_polarity
        elif saw_opposite_pair and abs(current_v) < threshold:
            accumulator = 0.0
            event_polarity = 0
            saw_opposite_pair = False

        force[index] = accumulator
        previous_v = current_v

    return force


def _polarity(value: float, threshold: float) -> int:
    """Return thresholded signal polarity as ``-1``, ``0``, or ``1``."""
    if value > threshold:
        return 1
    if value < -threshold:
        return -1
    return 0


def _normalize_leak_intervals(leak_dt_s, sample_count: int) -> np.ndarray | None:
    """Return per-interval MUX leak exposure or ``None`` for continuous leak."""
    if leak_dt_s is None:
        return None
    interval_count = max(0, int(sample_count) - 1)
    if interval_count == 0:
        return np.empty(0, dtype=np.float64)

    values = np.asarray(leak_dt_s, dtype=np.float64).reshape(-1)
    if values.size == 1:
        return np.full(interval_count, float(values[0]), dtype=np.float64)
    if values.size == interval_count:
        return values.astype(np.float64, copy=True)
    if values.size == sample_count:
        return values[1:].astype(np.float64, copy=True)
    raise ValueError("PZT force leak_dt_s must be scalar, match timestamps, or match timestamp intervals")


def _optional_positive_float(value) -> float | None:
    try:
        if value in (None, ""):
            return None
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0.0 else None
