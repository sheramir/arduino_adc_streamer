"""Unit tests for the PZT natural-reset event state machine.

All traces use the shared default RC parameters (``capacitance_f=150e-12``,
``rleak_ohm=1e6``, ``d33_c_per_n=600e-12``), for which the leak time constant
(150 us) is far shorter than every test's sample spacing (>=10 ms). This
makes ``alpha`` in the RC integration effectively zero, so each step's
charge delta is simply ``0.25 * v`` (``C / d33 == 0.25``) and the expected
numbers below are exact hand computations, not just "whatever the code
does".
"""

import math

import pytest

from data_processing.pzt_force_calculation import PztForceChannelIntegrator

KWARGS = dict(
    capacitance_f=150e-12,
    rleak_ohm=1e6,
    d33_c_per_n=600e-12,
    noise_threshold_v=0.01,
)


def test_press_three_regression_no_mid_event_reset_and_ends_at_zero():
    """Reproduces the traced 2026-08-11 failure and confirms the fix.

    Event A (press 2) naturally zeroes mid-tail; its own release undershoot
    forms a small residual that fully resolves to zero once that residual
    has itself gone quiet for the hold time (the quiet-hold reset is
    unconditional - see ``test_quiet_hold_reset_is_unconditional_...``).
    Event B (press 3) then pushes positive, dips briefly sub-threshold (must
    not end the event or reset), swings negative, and concludes at its own
    quiet-hold expiry - never freezing at a large residual and never
    resetting mid-event.
    """
    integ = PztForceChannelIntegrator(**KWARGS, quiet_hold_clear_s=0.05)

    # Event A: push, natural zero mid-tail, then a release undershoot whose
    # own small residual resolves to zero once it too has gone quiet.
    event_a = [
        (0.0, 0.00), (0.3, 0.01), (-0.2, 0.02), (-0.02, 0.03), (-0.15, 0.04),
        (0.0, 0.05), (0.0, 0.20),
    ]
    for voltage, timestamp in event_a:
        integ.process_centered_sample(voltage, timestamp)
    assert integ.accumulated_force_n == 0.0

    # Event B: onset, brief sub-threshold gap (shorter than the hold, must
    # not end the event), a full negative swing, then genuine quiet.
    event_b = [
        (0.3, 0.21), (0.25, 0.22), (0.0, 0.23), (-0.28, 0.25), (0.0, 0.26),
    ]
    results = [integ.process_centered_sample(v, t) for v, t in event_b]
    assert not any(step.reset_occurred for step in results)
    assert min(step.accumulated_force_n for step in results) > -0.5

    final = integ.process_centered_sample(0.0, 0.40)
    assert final.event_ended
    assert final.fallback_reset_occurred
    assert final.reset_occurred
    assert integ.accumulated_force_n == 0.0


def test_natural_zero_snaps_to_exact_zero_when_declining_into_band():
    integ = PztForceChannelIntegrator(**KWARGS, quiet_hold_clear_s=0.05)
    integ.process_centered_sample(0.0, 0.00)
    integ.process_centered_sample(0.3, 0.01)
    assert integ.accumulated_force_n == pytest.approx(0.075)

    step = integ.process_centered_sample(-0.28, 0.02)

    assert step.natural_zero_occurred
    assert step.reset_occurred
    assert step.event_ended
    assert not step.fallback_reset_occurred
    assert integ.accumulated_force_n == 0.0


def test_quiet_hold_releases_a_residual_that_has_declined_enough():
    """A residual that has declined below `quiet_hold_release_fraction` of
    its own event's peak is zeroed once the channel has gone quiet for the
    hold time, regardless of polarity history - a real release rarely
    cancels its own charge exactly, so requiring "substantial" opposite-
    polarity evidence left small, genuinely-declined residuals stuck at a
    nonzero plateau indefinitely between presses."""
    integ = PztForceChannelIntegrator(**KWARGS, quiet_hold_clear_s=0.05)
    integ.process_centered_sample(0.0, 0.00)
    integ.process_centered_sample(0.3, 0.01)
    step = integ.process_centered_sample(-0.18, 0.02)
    # Residual (0.03) sits outside the natural-zero band (0.02) but has
    # declined to 40% of the peak (0.075) - well under the 50% default.
    assert not step.natural_zero_occurred
    assert integ.accumulated_force_n == pytest.approx(0.03)

    # Quiet run starts at t=0.03; every sample before the hold expires
    # (t < 0.08) must not reset.
    for timestamp in (0.03, 0.05, 0.06, 0.079):
        step = integ.process_centered_sample(0.0, timestamp)
        assert not step.reset_occurred
        assert integ.accumulated_force_n == pytest.approx(0.03)

    step = integ.process_centered_sample(0.0, 0.08)
    assert step.fallback_reset_occurred
    assert step.reset_occurred
    assert integ.accumulated_force_n == 0.0


def test_quiet_hold_does_not_release_a_residual_still_near_peak():
    """A monopolar push whose voltage decays quiet without ever declining
    (still sitting at ~100% of its own peak - the held-press case) must NOT
    be forced to zero at quiet_hold_clear_s; the event stays open so that
    whenever a real release signal arrives, it keeps cancelling the *same*
    accumulator instead of the channel jumping to zero and starting a fresh
    event from nothing."""
    integ = PztForceChannelIntegrator(**KWARGS, quiet_hold_clear_s=0.05)
    trace = [(0.0, 0.0), (0.3, 0.01), (0.28, 0.02), (0.25, 0.03), (0.0, 0.04)]
    for voltage, timestamp in trace:
        integ.process_centered_sample(voltage, timestamp)
    residual = integ.accumulated_force_n
    assert residual > 0.1  # well outside the zero band; nothing crossed back

    # A long quiet stretch alone - even far past quiet_hold_clear_s - must
    # not force it to zero while it hasn't actually declined.
    final = None
    for index in range(5, 20):
        final = integ.process_centered_sample(0.0, 0.01 * index)
        assert not final.event_ended
        assert not final.reset_occurred
        assert integ.accumulated_force_n == pytest.approx(residual)
    assert integ.event_active  # still open, still hysteresis-integrating

    # The real release, whenever it arrives, integrates on top of the held
    # value and can complete a natural zero directly - no jump-to-zero first.
    release = integ.process_centered_sample(-0.9, 0.20)
    assert release.natural_zero_occurred
    assert release.reset_occurred
    assert integ.accumulated_force_n == 0.0


def test_hysteresis_does_not_drift_on_sustained_quiet_band_noise():
    """Real hardware quiet-band voltage is never exactly 0 (small DC offset/
    noise around the estimated midpoint). Hysteresis must stop integrating
    that residual once a channel has been quiet for quiet_hold_clear_s - not
    keep treating it as ongoing signal - or a held/stuck residual would drift
    further from zero for as long as the event stays open, with its own peak
    growing to match and permanently defeating the "has it declined"
    check (this reproduces a bug found against real capture data, where a
    held-press release settled inside the noise band but kept drifting
    further negative for over a second instead of holding still)."""
    integ = PztForceChannelIntegrator(**KWARGS, quiet_hold_clear_s=0.05)
    integ.process_centered_sample(0.0, 0.00)
    integ.process_centered_sample(0.3, 0.01)
    assert integ.accumulated_force_n == pytest.approx(0.075)

    # Constant small sub-threshold voltage (well under the 0.01 V noise
    # threshold) sustained for far longer than quiet_hold_clear_s.
    for index in range(2, 15):
        integ.process_centered_sample(0.005, 0.01 * index)

    # Within the hysteresis window the residual (and peak) may still grow a
    # little; once past it, the accumulator must stop changing entirely.
    frozen_at = integ.accumulated_force_n
    frozen_peak = integ.event_peak_force_n
    assert frozen_at == pytest.approx(0.08125)
    for index in range(15, 40):
        step = integ.process_centered_sample(0.005, 0.01 * index)
        assert not step.stuck_decay_active  # not yet past the (separate) stuck-force hold
        assert integ.accumulated_force_n == frozen_at
        assert integ.event_peak_force_n == frozen_peak


def test_no_natural_zero_on_the_rising_edge():
    """A slow rise must never trip the natural-zero band (self-gating + min-peak gate)."""
    integ = PztForceChannelIntegrator(**KWARGS, quiet_hold_clear_s=0.05)
    integ.process_centered_sample(0.0, 0.0)
    natural_zero_seen = False
    for index in range(1, 12):
        step = integ.process_centered_sample(0.011 + 0.001 * index, 0.01 * index)
        natural_zero_seen = natural_zero_seen or step.natural_zero_occurred
        assert integ.event_peak_force_n < integ.force_zero_min_event_peak_n
    assert not natural_zero_seen


def test_hysteresis_integrates_raw_voltage_through_a_mid_event_dip():
    """A sample inside the noise band mid-event must not be clipped to zero."""
    integ = PztForceChannelIntegrator(**KWARGS, quiet_hold_clear_s=0.05)
    integ.process_centered_sample(0.0, 0.0)
    integ.process_centered_sample(0.3, 0.01)

    dip_step = integ.process_centered_sample(0.005, 0.02)  # inside +-10 mV band

    assert not dip_step.active
    assert dip_step.delta_force_n == pytest.approx(0.25 * 0.005)
    assert integ.accumulated_force_n == pytest.approx(0.075 + 0.25 * 0.005)

    integ.process_centered_sample(0.3, 0.03)
    clipped_equivalent = 0.075 + 0.0 + 0.075  # the same trace with the dip zeroed
    # Hysteresis keeps more of the true signal than clipping would have.
    assert integ.accumulated_force_n > clipped_equivalent


def test_quiet_hold_clears_event_state_so_next_press_matches_a_first_press():
    integ = PztForceChannelIntegrator(**KWARGS, quiet_hold_clear_s=0.05)
    for voltage, timestamp in [(0.0, 0.0), (0.3, 0.01), (-0.28, 0.02)]:
        integ.process_centered_sample(voltage, timestamp)
    assert integ.accumulated_force_n == 0.0  # natural zero, exact
    assert not integ.event_active
    assert integ.event_peak_force_n == 0.0

    # The natural zero fired while voltage was still supra-threshold, so the
    # re-arm gate is open; it must clear on a genuinely sub-threshold sample
    # before the next press can start like a first press (work item C1).
    gate_clear = integ.process_centered_sample(0.0, 0.03)
    assert gate_clear.rearm_gate_active
    assert not integ.rearm_pending

    fresh = PztForceChannelIntegrator(**KWARGS, quiet_hold_clear_s=0.05)
    fresh.process_centered_sample(0.0, 0.0)

    second_press = [(0.3, 0.20), (-0.28, 0.21)]
    reused_results = [integ.process_centered_sample(v, t) for v, t in second_press]
    fresh_results = [fresh.process_centered_sample(v, t) for v, t in second_press]

    assert [r.accumulated_force_n for r in reused_results] == pytest.approx(
        [r.accumulated_force_n for r in fresh_results]
    )


# --- Stuck-force fail-safe -------------------------------------------------
#
# Since the quiet-hold reset above is unconditional, every channel that goes
# quiet at all is already zeroed well before `stuck_force_quiet_hold_s`
# (clamped >= `quiet_hold_clear_s`) could ever elapse. The fail-safe can
# therefore only matter for a channel that arrives already carrying a
# residual with its event already concluded (e.g. state restored from a
# snapshot, or driven directly by the package engine's own decay_toward_zero
# calls) - so these tests seed that state directly rather than reaching it
# through process_centered_sample, mirroring how the package engine actually
# drives per-channel decay for the live Force Display.

def test_stuck_force_failsafe_decays_a_seeded_residual_and_snaps_to_zero():
    integ = PztForceChannelIntegrator(
        **KWARGS,
        quiet_hold_clear_s=0.05,
        stuck_force_failsafe_enabled=True,
        stuck_force_quiet_hold_s=0.1,
        stuck_force_decay_tau_s=0.05,
    )
    integ.process_centered_sample(0.0, 0.0)
    integ.accumulated_force_n = 0.075
    integ.event_active = False
    integ.quiet_since_s = 0.0

    reset_step = None
    saw_decay = False
    for index in range(1, 40):
        timestamp = 0.01 * index
        step = integ.process_centered_sample(0.0, timestamp)
        saw_decay = saw_decay or step.stuck_decay_active
        if step.reset_occurred:
            reset_step = step
            break

    assert saw_decay
    assert reset_step is not None
    assert reset_step.stuck_decay_active
    assert integ.accumulated_force_n == 0.0


def test_stuck_force_failsafe_tau_zero_is_an_instant_reset():
    integ = PztForceChannelIntegrator(
        **KWARGS,
        quiet_hold_clear_s=0.05,
        stuck_force_failsafe_enabled=True,
        stuck_force_quiet_hold_s=0.1,
        stuck_force_decay_tau_s=0.0,
    )
    integ.process_centered_sample(0.0, 0.0)
    integ.accumulated_force_n = 0.075
    integ.event_active = False
    integ.quiet_since_s = 0.0

    step = None
    for index in range(1, 40):
        step = integ.process_centered_sample(0.0, 0.01 * index)
        if step.stuck_decay_active:
            break

    assert step is not None
    assert step.stuck_decay_active
    assert step.reset_occurred
    assert integ.accumulated_force_n == 0.0


def test_stuck_force_failsafe_disabled_retains_residual_indefinitely():
    integ = PztForceChannelIntegrator(
        **KWARGS,
        quiet_hold_clear_s=0.05,
        stuck_force_failsafe_enabled=False,
        stuck_force_quiet_hold_s=0.1,
        stuck_force_decay_tau_s=0.05,
    )
    integ.process_centered_sample(0.0, 0.0)
    integ.accumulated_force_n = 0.075
    integ.event_active = False
    integ.quiet_since_s = 0.0
    for index in range(1, 200):
        integ.process_centered_sample(0.0, 0.01 * index)
    assert integ.accumulated_force_n == pytest.approx(0.075)


def test_new_active_sample_cancels_decay_and_integrates_on_top():
    integ = PztForceChannelIntegrator(
        **KWARGS,
        quiet_hold_clear_s=0.05,
        stuck_force_failsafe_enabled=True,
        stuck_force_quiet_hold_s=0.1,
        stuck_force_decay_tau_s=0.05,
    )
    integ.process_centered_sample(0.0, 0.0)
    integ.accumulated_force_n = 0.075
    integ.event_active = False
    integ.quiet_since_s = 0.0
    for index in range(1, 15):
        step = integ.process_centered_sample(0.0, 0.01 * index)
        if step.stuck_decay_active:
            break
    decayed_value = integ.accumulated_force_n
    assert 0.0 < decayed_value < 0.075

    resumed = integ.process_centered_sample(0.3, 0.01 * 16)
    assert resumed.accumulated_force_n == pytest.approx(decayed_value + 0.25 * 0.3)


def test_stuck_force_quiet_hold_is_clamped_to_at_least_quiet_hold_clear():
    integ = PztForceChannelIntegrator(
        **KWARGS, quiet_hold_clear_s=0.5, stuck_force_quiet_hold_s=0.1,
    )
    assert integ.stuck_force_quiet_hold_s == pytest.approx(0.5)


def test_decay_toward_zero_multiplies_and_snaps_within_the_floor():
    integ = PztForceChannelIntegrator(**KWARGS, force_zero_band_min_n=0.02)
    integ.accumulated_force_n = 1.0

    within_band = integ.decay_toward_zero(1.0, 1.0)

    assert not within_band
    assert integ.accumulated_force_n == pytest.approx(math.exp(-1.0))

    integ.accumulated_force_n = 0.019
    assert integ.decay_toward_zero(1.0, 1.0)
    assert integ.accumulated_force_n == 0.0


def test_decay_toward_zero_tau_zero_is_instant():
    integ = PztForceChannelIntegrator(**KWARGS)
    integ.accumulated_force_n = 5.0

    assert integ.decay_toward_zero(1.0, 0.0)
    assert integ.accumulated_force_n == 0.0


# --- Part C: re-arm gate after a natural zero -------------------------------
#
# Reproduces the 2026-08-11 15:59 capture findings F1/F2: a natural zero can
# fire while the release transient is still supra-threshold (a slow press's
# accumulator is dominated by leak-replenishment summed over ~1 s, while its
# release is a fast spike that crosses the zero band in tens of ms). Without
# the gate, the still-arriving remainder of that transient integrates as a
# spurious opposite-sign event (F1) and can leave a stale previous-voltage
# reference that seeds a permanent shelf (F2).

def test_natural_zero_mid_release_transient_gates_the_rest_of_the_tail():
    """Work item C4-1 (finding F1): a slow ramp followed by a fast release
    spike lands the natural zero while the undershoot is still
    supra-threshold. Every following sample of that same undershoot must be
    fully suppressed - accumulator pinned at exact 0, no new event - until
    voltage genuinely returns inside the noise band."""
    integ = PztForceChannelIntegrator(**KWARGS, quiet_hold_clear_s=0.05)
    integ.process_centered_sample(0.0, 0.0)

    # Slow ramp: sustained supra-threshold voltage; the RC tau (150 us) is
    # far shorter than the 10 ms sample spacing, so each sample re-integrates
    # close to the full raw voltage (leak-replenishment dominates), building
    # the peak to 0.4 N over 32 samples.
    for index in range(1, 33):
        integ.process_centered_sample(0.05, 0.01 * index)
    assert integ.event_peak_force_n == pytest.approx(0.4)

    # Fast release spike crosses the natural-zero band in one step, while
    # voltage (-1.48 V) is still far outside the noise threshold.
    zero_step = integ.process_centered_sample(-1.48, 0.33)
    assert zero_step.natural_zero_occurred
    assert zero_step.reset_occurred
    assert integ.accumulated_force_n == 0.0
    assert integ.rearm_pending

    # The physical undershoot keeps running supra-threshold for several more
    # samples - without the gate these would integrate a spurious negative
    # plateau (finding F1). Every one must be fully suppressed.
    for index in range(34, 40):
        step = integ.process_centered_sample(-0.9, 0.01 * index)
        assert step.active  # raw threshold state still reported (not quiet)
        assert step.rearm_gate_active
        assert not step.natural_zero_occurred
        assert integ.accumulated_force_n == 0.0
        assert not integ.event_active

    # The tail finally returns inside the noise band: gate clears and the
    # continuous quiet run (for the stuck-force fail-safe) starts here.
    clear_step = integ.process_centered_sample(0.0, 0.40)
    assert clear_step.rearm_gate_active
    assert not integ.rearm_pending
    assert integ.quiet_since_s == pytest.approx(0.40)


def test_rearm_gate_is_sign_symmetric():
    """Work item C4-3b: the same slow-press/release scenario mirrored in
    polarity produces the exact negation of the positive-event trace - the
    natural zero, gate engagement, and gate release all land on the same
    samples regardless of which sign the event carries."""
    trace = (
        [(0.0, 0.0)]
        + [(0.05, 0.01 * i) for i in range(1, 33)]
        + [(-1.48, 0.33)]
        + [(-0.9, 0.01 * i) for i in range(34, 40)]
        + [(0.0, 0.40)]
    )
    positive = PztForceChannelIntegrator(**KWARGS, quiet_hold_clear_s=0.05)
    negative = PztForceChannelIntegrator(**KWARGS, quiet_hold_clear_s=0.05)

    for (v, t) in trace:
        pos_step = positive.process_centered_sample(v, t)
        neg_step = negative.process_centered_sample(-v, t)
        assert neg_step.accumulated_force_n == pytest.approx(-pos_step.accumulated_force_n)
        assert neg_step.natural_zero_occurred == pos_step.natural_zero_occurred
        assert neg_step.rearm_gate_active == pos_step.rearm_gate_active
        assert neg_step.active == pos_step.active


def test_bipolar_swing_that_stays_outside_the_band_never_gates():
    """Work item C4-3 (unchanged-behavior pin): a genuinely bipolar event
    whose swings never land inside the natural-zero band keeps integrating
    on the same accumulator and never opens the re-arm gate."""
    integ = PztForceChannelIntegrator(**KWARGS, quiet_hold_clear_s=0.05)
    trace = [(0.0, 0.0), (0.3, 0.01), (-0.9, 0.02), (0.3, 0.03)]
    results = [integ.process_centered_sample(v, t) for v, t in trace]
    assert not any(r.natural_zero_occurred for r in results)
    assert not any(r.rearm_gate_active for r in results)
    assert integ.event_active
    assert not integ.rearm_pending


def test_natural_zero_during_hysteresis_clears_previous_voltage_no_shelf():
    """Work item C4-4 / C2 (finding F2): a natural zero can also fire while
    still hysteresis-integrating a small sub-threshold voltage (mid-release,
    before quiet_hold_clear_s has elapsed) rather than a large supra-
    threshold one. That voltage must not be left behind in
    ``previous_centered_voltage_v``, or the next quiet sample computes a
    spurious one-shot increment (``0 - alpha * v_prev``) that then persists
    forever, since a sub-floor residual never satisfied the old stuck-force
    engage condition (see the C3 test below)."""
    integ = PztForceChannelIntegrator(
        **{**KWARGS, "noise_threshold_v": 0.1}, quiet_hold_clear_s=1.0,
    )
    integ.process_centered_sample(0.0, 0.00)
    integ.process_centered_sample(0.5, 0.01)
    assert integ.accumulated_force_n == pytest.approx(0.125)

    # Small sub-threshold voltage, hysteresis-integrated (well inside
    # quiet_hold_clear_s), gradually declining the residual into the band.
    step = None
    for timestamp in (0.02, 0.03, 0.04, 0.05, 0.06):
        step = integ.process_centered_sample(-0.09, timestamp)
        if step.natural_zero_occurred:
            break

    assert step.natural_zero_occurred
    assert step.centered_voltage_v == pytest.approx(-0.09)  # nonzero at the trigger sample
    assert integ.accumulated_force_n == 0.0
    assert integ.previous_centered_voltage_v == 0.0  # C2: no stale sub-threshold reference

    for timestamp in (0.07, 0.20, 1.50):
        quiet_step = integ.process_centered_sample(0.0, timestamp)
        assert integ.accumulated_force_n == 0.0
        assert quiet_step.accumulated_force_n == 0.0


def test_stuck_force_failsafe_engages_on_a_sub_floor_residual():
    """Work item C4-5 / C3: a residual already below ``force_zero_band_min_n``
    must still resolve via the fail-safe once quiet - under the old
    ``abs(accumulated_force_n) > force_zero_band_min_n`` engage condition it
    would never satisfy the check and would persist forever."""
    integ = PztForceChannelIntegrator(
        **KWARGS, quiet_hold_clear_s=0.05,
        stuck_force_failsafe_enabled=True, stuck_force_quiet_hold_s=0.1,
        stuck_force_decay_tau_s=0.05, force_zero_band_min_n=0.02,
    )
    integ.process_centered_sample(0.0, 0.0)
    integ.accumulated_force_n = 0.001  # sub-floor: never trips the old ">" engage condition
    integ.event_active = False
    integ.quiet_since_s = 0.0

    step = None
    for index in range(1, 40):
        step = integ.process_centered_sample(0.0, 0.01 * index)
        if step.reset_occurred:
            break

    assert step is not None
    assert step.stuck_decay_active
    assert step.reset_occurred
    assert integ.accumulated_force_n == 0.0
