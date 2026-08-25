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
calculator falls back to the full-trace median. Before any event has started,
samples whose centered voltage is below the selected threshold are treated as
zero; once an event starts, sub-threshold samples integrate their raw voltage
(see the reset discussion below).

For each sample, the leakage decay over the elapsed time is:
``alpha = exp(-dt / (Rleak * Cpzt))``. The generated charge increment is then
estimated as ``dQ = Cpzt * beta * (v[n] - alpha * v[n-1])``, where ``beta``
optionally corrects charge that decays between physical MUX connection and the
effective ADC sample. The returned force trace is the accumulated sum of those
increments.

Reset is a natural event state machine, not a threshold-crossing trigger.
Once a sample crosses the noise threshold, an "event" starts and every
subsequent sample integrates its raw (non-thresholded) voltage, including
samples that dip back inside the noise band, so a slow release is never
clipped mid-decay. A polarity reversal during an event simply integrates the
force back down; it never zeroes the accumulator by itself. The accumulator
is zeroed by a **natural zero**: once the event's own peak force has been
reached, the force declining back inside a band around zero (proportional to
that peak, with an absolute floor) ends the event and zeroes it. A natural
zero frequently fires while the voltage is still mid-transient (a slow press
followed by a fast release spike burns through the accumulator in a fraction
of the time the voltage takes to settle), so the concluded event's own
release tail can still be running when the accumulator is already zero. A
**re-arm gate** (``rearm_pending``) opens at that instant and suppresses
every following sample - no new event may start, nothing integrates - until
voltage genuinely returns inside the noise band; only then can the next
threshold crossing start a fresh event, exactly like a first press. Without
this gate, that leftover transient would integrate as a spurious event of
its own, opposite in sign to the one that just concluded.

Going quiet (below the noise threshold) is *not* the same as being released:
a real PZT voltage decays toward baseline even while a press stays
physically held, carrying no held-force information after roughly one wall
time constant, so a channel can go quiet mid-hold with the accumulator still
sitting near its peak. A continuous quiet run lasting ``quiet_hold_clear_s``
only concludes the event - zeroing the residual - if it has declined to
within ``quiet_hold_release_fraction`` of the event's own peak (or the peak
never cleared ``force_zero_min_event_peak_n`` to begin with, i.e. there was
nothing substantial to distinguish "declined" from "held"). Otherwise the
event is left open: still hysteresis-integrating, so a real release signal
whenever it arrives keeps cancelling the *same* accumulator - matching the
sensor's own charge instead of jumping to zero and starting a fresh event
from nothing. Event bookkeeping (peak force) is cleared whenever the event
does end, so a noise tail can never pair with the next press's onset. A
separate **stuck-force fail-safe** is the eventual backstop for whatever the
quiet-hold reset leaves open (whether never concluded because still "held",
or concluded but retained because it never declined enough): once a channel
has stayed continuously quiet for a configurable hold time, its residual
decays toward zero, snapping to exact zero inside the floor band; a zero
time constant selects an instant hard reset. Because the floor is an
absolute magnitude while the decay is proportional to the current value, a
small residual crosses it (and fully resolves) much sooner than a large one
- so a quick tap fades quickly while a genuinely abandoned held press takes
longer, all without ever discarding a still-arriving release signal.

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


@dataclass(frozen=True, slots=True)
class PztForceStepResult:
    """One exactly-once update of a live, baseline-centred PZT channel."""

    delta_force_n: float
    accumulated_force_n: float
    centered_voltage_v: float
    active: bool
    reset_occurred: bool
    natural_zero_occurred: bool = False
    fallback_reset_occurred: bool = False
    event_ended: bool = False
    reset_recommended: bool = False
    stuck_decay_active: bool = False
    rearm_gate_active: bool = False


@dataclass(slots=True)
class PztForceChannelIntegrator:
    """Stateful counterpart of :func:`calculate_pzt_force_from_voltage`.

    ``process_centered_sample`` deliberately accepts voltage after the
    application's shared time-series median-baseline stage.  It must therefore
    never estimate or subtract another midpoint.
    """

    capacitance_f: float
    rleak_ohm: float
    d33_c_per_n: float
    noise_threshold_v: float
    off_mux_rleak_ohm: float | None = None
    # When False (the live package engine, `pressure_force_display.py`), the
    # integrator still runs the full event/stuck machinery and reports its
    # conditions, but never zeroes its own accumulator; the caller decides
    # when to apply a coherent reset across several channels.
    self_reset_enabled: bool = True
    force_zero_band_fraction: float = PZT_FORCE_DEFAULT_SETTINGS["force_zero_band_fraction"]
    force_zero_band_min_n: float = PZT_FORCE_DEFAULT_SETTINGS["force_zero_band_min_n"]
    force_zero_min_event_peak_n: float = PZT_FORCE_DEFAULT_SETTINGS["force_zero_min_event_peak_n"]
    quiet_hold_release_fraction: float = PZT_FORCE_DEFAULT_SETTINGS["quiet_hold_release_fraction"]
    quiet_hold_clear_s: float = PZT_FORCE_DEFAULT_SETTINGS["quiet_hold_clear_s"]
    stuck_force_failsafe_enabled: bool = PZT_FORCE_DEFAULT_SETTINGS["stuck_force_failsafe_enabled"]
    stuck_force_quiet_hold_s: float = PZT_FORCE_DEFAULT_SETTINGS["stuck_force_quiet_hold_s"]
    stuck_force_decay_tau_s: float = PZT_FORCE_DEFAULT_SETTINGS["stuck_force_decay_tau_s"]
    previous_centered_voltage_v: float = 0.0
    previous_timestamp_s: float | None = None
    accumulated_force_n: float = 0.0
    active: bool = False
    initialized: bool = False
    # Per-event state (see module docstring for the natural-reset design).
    event_active: bool = False
    event_peak_force_n: float = 0.0
    quiet_since_s: float | None = None
    # Set when a natural zero ends an event; suppresses the rest of that
    # release transient (still supra-threshold) from starting a new event or
    # integrating, until voltage genuinely returns inside the noise band.
    rearm_pending: bool = False

    def __post_init__(self) -> None:
        validate_pzt_force_settings(
            self.capacitance_f, self.rleak_ohm, self.d33_c_per_n
        )
        if not np.isfinite(self.noise_threshold_v):
            raise ValueError("PZT force noise threshold must be finite")
        if self.off_mux_rleak_ohm is not None and (
            not np.isfinite(self.off_mux_rleak_ohm) or self.off_mux_rleak_ohm <= 0.0
        ):
            raise ValueError("off-MUX leak resistance must be greater than zero")
        for name in (
            "force_zero_band_fraction", "force_zero_band_min_n",
            "force_zero_min_event_peak_n", "quiet_hold_release_fraction",
            "quiet_hold_clear_s", "stuck_force_quiet_hold_s", "stuck_force_decay_tau_s",
        ):
            value = float(getattr(self, name))
            if not np.isfinite(value) or value < 0.0:
                raise ValueError(f"PZT force {name} must be finite and non-negative")
        # stuck_force_quiet_hold_s must be at least quiet_hold_clear_s so the
        # fail-safe never engages before the event it depends on has ended.
        self.stuck_force_quiet_hold_s = max(
            float(self.stuck_force_quiet_hold_s), float(self.quiet_hold_clear_s)
        )

    def reset(self) -> None:
        """Clear physical state without changing the validated parameters."""
        self.previous_centered_voltage_v = 0.0
        self.previous_timestamp_s = None
        self.accumulated_force_n = 0.0
        self.active = False
        self.initialized = False
        self.event_active = False
        self.event_peak_force_n = 0.0
        self.quiet_since_s = None
        self.rearm_pending = False

    def decay_toward_zero(self, dt_s: float, tau_s: float) -> bool:
        """Multiply the accumulator toward zero; snap to exact 0 inside the floor.

        ``tau_s <= 0`` selects an instant hard reset. Returns whether the
        accumulator is (now) within the ``force_zero_band_min_n`` floor.
        """
        tau = float(tau_s)
        if tau <= 0.0:
            self.accumulated_force_n = 0.0
        else:
            self.accumulated_force_n *= float(np.exp(-float(dt_s) / tau))
        if abs(self.accumulated_force_n) <= self.force_zero_band_min_n:
            self.accumulated_force_n = 0.0
            return True
        return False

    def process_centered_sample(
        self,
        centered_voltage_v: float,
        timestamp_s: float,
        *,
        leak_dt_s: float | None = None,
        pre_sample_decay_dt_s: float | None = None,
    ) -> PztForceStepResult:
        """Process one new sample and return its force-state transition.

        The first sample establishes the previous voltage/timestamp and has no
        charge interval to integrate.  Subsequent calls require a strictly
        increasing timestamp, which prevents accidental integration across a
        restart or unordered ring-buffer snapshot.
        """
        voltage = float(centered_voltage_v)
        timestamp = float(timestamp_s)
        if not np.isfinite(voltage) or not np.isfinite(timestamp):
            raise ValueError("PZT force samples and timestamps must be finite")
        threshold = abs(float(self.noise_threshold_v))
        is_active_sample = _polarity(voltage, threshold) != 0
        self.active = is_active_sample

        if not self.initialized:
            active_voltage = voltage if is_active_sample else 0.0
            self.previous_centered_voltage_v = active_voltage
            self.previous_timestamp_s = timestamp
            if is_active_sample:
                self.event_active = True
                self.event_peak_force_n = 0.0
                self.quiet_since_s = None
            else:
                self.quiet_since_s = timestamp
            self.initialized = True
            return PztForceStepResult(0.0, 0.0, active_voltage, is_active_sample, False)

        previous_timestamp = self.previous_timestamp_s
        assert previous_timestamp is not None
        wall_dt = timestamp - previous_timestamp
        if not np.isfinite(wall_dt) or wall_dt <= 0.0:
            raise ValueError("PZT force timestamps must be strictly increasing")
        leak_dt = wall_dt if leak_dt_s is None else float(leak_dt_s)
        if not np.isfinite(leak_dt):
            raise ValueError("PZT force leak_dt_s must be finite")
        leak_dt = min(max(leak_dt, 0.0), wall_dt)
        pre_sample_dt = 0.0 if pre_sample_decay_dt_s is None else float(pre_sample_decay_dt_s)
        if not np.isfinite(pre_sample_dt) or pre_sample_dt < 0.0:
            raise ValueError("PZT force pre_sample_decay_dt_s must be finite and non-negative")

        if self.rearm_pending:
            # The event already concluded via a natural zero while this
            # release transient was still supra-threshold; suppress the
            # remainder of that transient (no new event, no integration)
            # until voltage genuinely returns inside the noise band.
            if not is_active_sample:
                self.rearm_pending = False
                if self.quiet_since_s is None:
                    self.quiet_since_s = timestamp
            self.previous_centered_voltage_v = 0.0
            self.previous_timestamp_s = timestamp
            return PztForceStepResult(
                0.0, self.accumulated_force_n, 0.0, is_active_sample, False,
                rearm_gate_active=True,
            )

        # Hysteresis: while an event is active, integrate the raw centered
        # voltage (never zero a mid-event sample inside the noise band) so a
        # slow release is not clipped. This only applies for up to
        # quiet_hold_clear_s of continuous quiet: a real PZT transient
        # settles far faster than that, so a channel still sub-threshold
        # after the full hold is not "mid-transition" - it is quiet, and its
        # raw voltage is measurement noise around a DC offset, not signal.
        # Integrating that noise indefinitely (while the event stays open
        # awaiting a possible late release, see the quiet-hold branch below)
        # would otherwise accumulate unbounded drift, since the residual and
        # its own peak grow together and the event never looks "declined".
        # Outside that window (or outside any event), sub-threshold samples
        # are treated as exactly zero.
        if is_active_sample:
            if not self.event_active:
                self.event_active = True
                self.event_peak_force_n = 0.0
            self.quiet_since_s = None
        elif not self.event_active and self.quiet_since_s is None:
            self.quiet_since_s = timestamp
        hysteresis_active = self.event_active and (
            self.quiet_since_s is None
            or (timestamp - self.quiet_since_s) < self.quiet_hold_clear_s
        )
        sample_voltage = voltage if (is_active_sample or hysteresis_active) else 0.0

        tau_on = float(self.rleak_ohm) * float(self.capacitance_f)
        decay_exponent = leak_dt / tau_on
        if self.off_mux_rleak_ohm is not None:
            tau_off = float(self.off_mux_rleak_ohm) * float(self.capacitance_f)
            decay_exponent += max(wall_dt - leak_dt, 0.0) / tau_off
        alpha = float(np.exp(-decay_exponent))
        correction = float(np.exp(pre_sample_dt / tau_on))
        prior_force = self.accumulated_force_n
        self.accumulated_force_n += (
            float(self.capacitance_f) / float(self.d33_c_per_n)
        ) * correction * (sample_voltage - alpha * self.previous_centered_voltage_v)

        natural_zero_occurred = False
        fallback_reset_occurred = False
        event_ended = False
        reset_occurred = False
        stuck_decay_active = False

        if self.event_active:
            self.event_peak_force_n = max(self.event_peak_force_n, abs(self.accumulated_force_n))
            if not is_active_sample and self.quiet_since_s is None:
                self.quiet_since_s = timestamp

            if self.event_peak_force_n >= self.force_zero_min_event_peak_n:
                band = max(
                    self.force_zero_band_fraction * self.event_peak_force_n,
                    self.force_zero_band_min_n,
                )
                if abs(self.accumulated_force_n) <= band:
                    natural_zero_occurred = True
                    event_ended = True

            if not event_ended and self.quiet_since_s is not None:
                if (timestamp - self.quiet_since_s) >= self.quiet_hold_clear_s:
                    # A real PZT voltage decays toward baseline even while a
                    # press stays physically held (it carries no held-force
                    # information after roughly one wall time constant), so
                    # "gone quiet" alone does not mean "released" - a channel
                    # can go quiet mid-hold with the accumulated force still
                    # sitting near its peak. Only conclude the event here if
                    # the residual has genuinely declined; a small blip that
                    # never built up much force (peak below the min-event
                    # gate) is released unconditionally since there is
                    # nothing meaningful left to distinguish "declined" from
                    # "held" for it. Otherwise, leave the event open (still
                    # hysteresis-integrating) so a real release signal keeps
                    # cancelling the same accumulator instead of starting a
                    # fresh event from zero; the stuck-force fail-safe below
                    # is the eventual backstop if no release ever arrives.
                    if self.event_peak_force_n < self.force_zero_min_event_peak_n or (
                        abs(self.accumulated_force_n)
                        <= self.quiet_hold_release_fraction * self.event_peak_force_n
                    ):
                        event_ended = True
                        fallback_reset_occurred = True

            if event_ended:
                if self.self_reset_enabled and (natural_zero_occurred or fallback_reset_occurred):
                    self.accumulated_force_n = 0.0
                    reset_occurred = True
                # Clear event bookkeeping so a tail crossing can never pair
                # with the next press's onset; the continuous quiet run
                # (quiet_since_s) is retained for the stuck-force fail-safe.
                self.event_active = False
                self.event_peak_force_n = 0.0
                if natural_zero_occurred:
                    # The rest of this release transient may still be
                    # supra-threshold; suppress it (both self-reset modes)
                    # so it cannot integrate as a spurious opposite-sign
                    # event - see `rearm_pending` above.
                    self.rearm_pending = True

        reset_recommended = natural_zero_occurred or fallback_reset_occurred

        if (
            self.self_reset_enabled
            and self.stuck_force_failsafe_enabled
            # Deliberately not gated on `event_active`: a held press that
            # never declines enough to conclude via the ordinary path above
            # (see the comment there) still needs an eventual backstop, and
            # `quiet_since_s` already reflects the current continuous quiet
            # run regardless of whether the event was formally ended.
            and self.quiet_since_s is not None
            and (timestamp - self.quiet_since_s) >= self.stuck_force_quiet_hold_s
            and self.accumulated_force_n != 0.0
        ):
            stuck_decay_active = True
            if self.decay_toward_zero(wall_dt, self.stuck_force_decay_tau_s):
                reset_occurred = True

        # No event => baseline reference is 0: a stale sub-threshold prev
        # voltage must never seed a spurious increment on the next quiet
        # sample (`0 - alpha * v_prev`).
        self.previous_centered_voltage_v = 0.0 if event_ended else sample_voltage
        self.previous_timestamp_s = timestamp
        return PztForceStepResult(
            self.accumulated_force_n - prior_force,
            self.accumulated_force_n,
            sample_voltage,
            is_active_sample,
            reset_occurred,
            natural_zero_occurred,
            fallback_reset_occurred,
            event_ended,
            reset_recommended,
            stuck_decay_active,
        )


def calculate_pzt_force_from_settings(
    voltage_v,
    time_s,
    settings: Mapping[str, object] | None = None,
    *,
    sensor_position: str | None = None,
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
        ``center_capacitance_value``, ``outer_capacitance_value``,
        ``capacitance_unit``, ``rleak_ohm``,
        ``d33_pc_per_n``, and ``noise_threshold_v``. Missing keys are filled
        from the shared defaults.
    vmid_v:
        Optional explicit midpoint voltage. When omitted, the calculator falls
        back to the full-trace median.
    noise_threshold_v:
        Optional explicit centered voltage threshold. When omitted, the value
        from ``settings`` is used.
    sensor_position:
        Logical sensor position in its PZT package. ``"C"`` selects the
        center capacitance; every other position selects the outer value.

    Returns
    -------
    np.ndarray
        Reconstructed force samples in newtons.
    """
    supplied = dict(settings or {})
    resolved = {**PZT_FORCE_DEFAULT_SETTINGS, **supplied}
    capacitance_f = pzt_capacitance_to_farads(
        pzt_capacitance_value_for_position(supplied, sensor_position),
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
        force_zero_band_fraction=float(resolved["force_zero_band_fraction"]),
        force_zero_band_min_n=float(resolved["force_zero_band_min_n"]),
        force_zero_min_event_peak_n=float(resolved["force_zero_min_event_peak_n"]),
        quiet_hold_release_fraction=float(resolved["quiet_hold_release_fraction"]),
        quiet_hold_clear_s=float(resolved["quiet_hold_clear_s"]),
        stuck_force_failsafe_enabled=bool(resolved["stuck_force_failsafe_enabled"]),
        stuck_force_quiet_hold_s=float(resolved["stuck_force_quiet_hold_s"]),
        stuck_force_decay_tau_s=float(resolved["stuck_force_decay_tau_s"]),
    )


def pzt_capacitance_value_for_position(
    settings: Mapping[str, object] | None,
    sensor_position: str | None,
) -> float:
    """Return the capacitance configured for one PZT package position.

    ``C`` uses ``center_capacitance_value`` and all other positions use
    ``outer_capacitance_value``. A settings mapping saved before this split
    has only ``capacitance_value``; that value remains the fallback for both.
    """
    supplied = dict(settings or {})
    legacy_value = supplied.get(
        "capacitance_value", PZT_FORCE_DEFAULT_SETTINGS["capacitance_value"]
    )
    key = (
        "center_capacitance_value"
        if str(sensor_position or "").strip().upper() == "C"
        else "outer_capacitance_value"
    )
    return float(supplied.get(key, legacy_value))


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
    if not all(np.isfinite(value) for value in (capacitance_f, rleak_ohm, d33_c_per_n)):
        raise ValueError("PZT force parameters must be finite")
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
    force_zero_band_fraction: float = PZT_FORCE_DEFAULT_SETTINGS["force_zero_band_fraction"],
    force_zero_band_min_n: float = PZT_FORCE_DEFAULT_SETTINGS["force_zero_band_min_n"],
    force_zero_min_event_peak_n: float = PZT_FORCE_DEFAULT_SETTINGS["force_zero_min_event_peak_n"],
    quiet_hold_release_fraction: float = PZT_FORCE_DEFAULT_SETTINGS["quiet_hold_release_fraction"],
    quiet_hold_clear_s: float = PZT_FORCE_DEFAULT_SETTINGS["quiet_hold_clear_s"],
    stuck_force_failsafe_enabled: bool = PZT_FORCE_DEFAULT_SETTINGS["stuck_force_failsafe_enabled"],
    stuck_force_quiet_hold_s: float = PZT_FORCE_DEFAULT_SETTINGS["stuck_force_quiet_hold_s"],
    stuck_force_decay_tau_s: float = PZT_FORCE_DEFAULT_SETTINGS["stuck_force_decay_tau_s"],
) -> np.ndarray:
    """Reconstruct force from centered PZT voltage dynamics.

    The algorithm models the PZT and leak path as an RC system:
    ``tau = rleak_ohm * capacitance_f``. For every sample it estimates the
    generated charge increment as ``C * (v[n] - alpha * v[n-1])`` and converts
    charge to force using ``d33``.

    Before integration, the signal midpoint is estimated using the median of
    ``voltage_v``. Before any event has started, samples whose centered
    absolute voltage is below ``noise_threshold_v`` are treated as zero; once
    an event starts, sub-threshold samples integrate their raw voltage
    (hysteresis). The accumulator is reset by the natural-zero/fallback/
    stuck-force-fail-safe machinery documented on
    :class:`PztForceChannelIntegrator`.

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
    centered_voltage = voltage - v_mid
    threshold = abs(float(noise_threshold_v))
    force = np.zeros_like(centered_voltage, dtype=np.float64)
    integrator = PztForceChannelIntegrator(
        capacitance_f=float(capacitance_f),
        rleak_ohm=float(rleak_ohm),
        d33_c_per_n=float(d33_c_per_n),
        noise_threshold_v=threshold,
        off_mux_rleak_ohm=off_mux_rleak_ohm,
        force_zero_band_fraction=float(force_zero_band_fraction),
        force_zero_band_min_n=float(force_zero_band_min_n),
        force_zero_min_event_peak_n=float(force_zero_min_event_peak_n),
        quiet_hold_release_fraction=float(quiet_hold_release_fraction),
        quiet_hold_clear_s=float(quiet_hold_clear_s),
        stuck_force_failsafe_enabled=bool(stuck_force_failsafe_enabled),
        stuck_force_quiet_hold_s=float(stuck_force_quiet_hold_s),
        stuck_force_decay_tau_s=float(stuck_force_decay_tau_s),
    )
    # The live integrator is the single implementation of the RC equation.
    # Supplying pre-centred samples here preserves the public batch API while
    # avoiding a second baseline calculation in the streaming caller.
    integrator.process_centered_sample(float(centered_voltage[0]), float(times[0]))
    for index in range(1, centered_voltage.size):
        step = integrator.process_centered_sample(
            float(centered_voltage[index]),
            float(times[index]),
            leak_dt_s=None if leak_intervals is None else float(leak_intervals[index - 1]),
            pre_sample_decay_dt_s=(
                None if pre_sample_intervals is None else float(pre_sample_intervals[index - 1])
            ),
        )
        force[index] = step.accumulated_force_n

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
