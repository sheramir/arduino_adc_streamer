# Plan: PZT Force Natural Reset State Machine and Analysis MUX-Connected-Time Fix

**Revision 2 — 2026-08-11.** The original plan (Parts A and B) is fully
implemented; section 1 records the as-built status with verification evidence.
The 2026-08-11 15:59 capture (3 fast presses + 2 slow presses on PZT1_C,
`analysis_20260811_1559.csv` / `_metadata.json`) exposed two residual defects
in the implemented design — section 2 traces them in the data. The remaining
work is **Part C** (post-natural-zero release-tail fix + two small residual
fixes) and **Part D** (expose the event-machine tunables in both GUIs, per
user request; resolves former open decision D2).

---

## 1. Implementation status of the original plan (all DONE)

Verified in the current working tree and in today's capture:

| Item | Status | Evidence |
| --- | --- | --- |
| **Part A** — Analysis "Auto" MUX time uses `t_connected`, not the amortized average | **Done** | `_owner_analysis_timing_metadata` now uses `setdefault` for the `_cached_avg_sample_time_sec` fallback (`data_processing/analysis_workbench.py:979-982`). Today's analysis export metadata shows `pzt_mux_connected_time_s = 2.1583e-05`, source `adc_mux_timing.t_connected_s` — the physical connected interval, matching the capture metadata. |
| **B1** — Integrator rewrite: natural-zero band, hysteresis (no mid-event clipping), quiet-hold event end, stuck-force fail-safe | **Done** | `PztForceChannelIntegrator` (`data_processing/pzt_force_calculation.py:115-375`): natural-zero band check at 301-308, quiet-hold release at 310-332, event-state clearing at 334-342, fail-safe at 346-360, `decay_toward_zero` at 187-201. The bipolar-area test of the original design was replaced during implementation by `quiet_hold_release_fraction` (release only if the residual declined to ≤ fraction × own peak; otherwise the event is presumed held and left open) — documented in the module docstring. |
| **B2** — Batch API threads the tunables, no pre-zeroing | **Done** | `calculate_pzt_force_from_voltage` accepts and threads all eight tunables (`pzt_force_calculation.py:577-584`); `calculate_pzt_force_from_settings` maps them from the settings dict (440-447). |
| **B3** — Package engine: `self_reset_enabled=False`, reset on `reset_recommended`, package-wide stuck decay | **Done** | `pressure_force_display.py`: integrators constructed with `self_reset_enabled=False` and all five event tunables (340-362), `pending_reset_positions` latch (183), `_package_event_complete` (389-412), `_package_stuck_decay_due` / `_apply_package_stuck_decay` (414-452). |
| **B4** — Fail-safe UI in both panels | **Done** | Pressure map: checkbox + hold/tau spins (`gui/signal_integration_panel.py:749-776`), settings dict (818-820), restore (2219-2221). Analysis: same widgets (`gui/analysis_panel.py:377-407`), persisted dict (807-809), restore (563-569). `reset_after_quiet_samples` removed from `constants/pzt_force.py`. |
| **B5** — Tests | **Done** | New `tests/test_pzt_force_calculation.py` (15 tests: press-3 regression, natural zero, quiet-hold release/retention, hysteresis, rising-edge, state clearing, fail-safe decay/instant/disabled/cancel, clamp, `decay_toward_zero`); `tests/test_pressure_force_display.py` and `tests/test_analysis_workbench.py` updated. |

**Not exposed in UI (former D2, now Part D):** `force_zero_band_fraction`,
`force_zero_band_min_n`, `force_zero_min_event_peak_n`,
`quiet_hold_release_fraction`, `quiet_hold_clear_s` are settings-dict only.

---

## 2. New verified findings — 2026-08-11 15:59 capture

Setup: PZT1_C, Vmid ≈ 1.6440 V, threshold 0.01 V, C = 150 pF, d33 = 600 pC/N,
Rleak = 1 MΩ, leak dt = 21.583 µs (`adc_mux_timing.t_connected_s`), all event
tunables at defaults. All timestamps below are traced directly in the exported
CSV.

### Finding F1 (primary): natural zero fires mid-release-transient; the rest of the release spike integrates as a spurious negative event

- **Slow press 4:** onset t≈8237 ms, peak ≈ **+1.434 N** (t≈8976). The fast
  release spike cancels the accumulator quickly; at **t=9094.8** the force
  enters the natural-zero band (max(0.1 × 1.434, 0.02) ≈ 0.143 N) and is
  zeroed, **ending the event and clearing event state — while the centered
  voltage is still ≈ −0.44 V** (raw 1.2007 V). The remaining undershoot starts
  a *fresh* negative event integrating 0 → **−0.4126 N** (t≈9375). That event
  is monopolar with |F| ≈ its own peak, so the quiet-hold release test
  (`|F| ≤ 0.5 × peak`) correctly reads "not declined" and retains it. The
  stuck fail-safe engages exactly 1.000 s after quiet (first decay step at
  t=10227.0; step size matches τ = 1 s), but press 5 (onset t≈10280) cancels
  the decay.
- **Slow press 5:** peak ≈ +1.466 N (t≈10993), natural zero at t=11124.5,
  tail integrates to **−0.663 N** (t≈11438) and plateaus. A small negative
  blip at t≈12.2–12.4 s starts a new event and re-arms the quiet timer
  (−0.663 → −0.677 → −0.646); the fail-safe decay resumes at t=13395.1
  (1.0 s after that blip's quiet start) and the capture ends mid-fade at
  −0.35 N.
- **Fast press 3** shows the same defect at small scale: natural zero at
  t≈6826, post-zero tail integrates to −0.035 N, second event end zeroes it
  at t=6840.9.

**Why slow presses are far worse:** a slow press's accumulated force is
dominated by the leak-replenishment term summed over ~1 s of sustained
positive voltage, while the release is a fast spike whose C·dV term burns
through the accumulator in tens of milliseconds. The zero band is therefore
reached when only a small fraction of the release undershoot has elapsed, and
everything after it lands in the spurious event. Fast presses have nearly
symmetric press/release transients, so the crossing lands near the end of the
undershoot and the leftover is tens of mN.

Every observed symptom — the plateau levels, the exact 1 s delays before the
slow fades, the tail at capture end — is this one mechanism plus the
fail-safe working as designed on the spurious residual. The natural-zero,
quiet-hold, and fail-safe machinery all behaved per spec; the spec is missing
a rule for the *remainder of the transient whose event just concluded*.

**Polarity note.** The presses in this capture happen to drive the force
positive, so the traces above read "positive event, negative tail" — but the
defect and its fix are strictly sign-symmetric. A genuine *negative* event
(force goes low, stays low, returns toward zero) is equally valid and shows
the mirrored failure: its natural zero fires while the release transient is
still supra-threshold in the *positive* direction, and the leftover tail
integrates a spurious positive plateau. Everything in Part C is therefore
specified on magnitudes (|F|, |v|) with no assumption about which polarity an
event or its release tail has.

### Finding F2 (secondary): stale previous voltage creates a permanent ~1.25 mN shelf after quiet-hold releases

After presses 2 and 3, the force sits at exactly **+0.001252596 N** between
events (t≈4.84–6.55 s and 6.84–8.24 s). Mechanism: when the quiet-hold
release ends an event, `previous_centered_voltage_v` keeps the last
hysteresis-integrated sub-threshold voltage (here ≈ −5 mV;
`pzt_force_calculation.py:362`). The next quiet sample computes
`0 − α·v_prev` → a one-shot increment of ≈ (C/d33)·5 mV ≈ +1.25 mN
(matches the data to 3 digits). It then persists indefinitely because the
fail-safe engage condition requires `|F| > force_zero_band_min_n` (0.02 N)
(`pzt_force_calculation.py:356`), which a sub-floor residual never satisfies —
so it neither decays nor snaps.

---

## 3. Part C — post-natural-zero re-arm gate and residual fixes

User-specified target behavior (agreed), stated polarity-neutrally: during an
event, |F| grows away from zero (positive *or* negative), then declines back;
it may transiently overshoot through zero *during* the event, but once the
accumulator has been zeroed it stays at exactly 0 until a genuinely new event
begins. The leftover of a release transient whose event already concluded
must not integrate — in either direction. A negative event (compression sign
convention: force goes low, stays low, returns to zero) is handled
identically to a positive one; the gate only suppresses the tail of an
already-concluded transient, whatever its sign.

### Work item C1: re-arm gate after a natural zero

`data_processing/pzt_force_calculation.py`:

- New integrator field `rearm_pending: bool = False` (cleared in `reset()`).
- **Set** whenever a natural zero ends an event (`natural_zero_occurred`),
  in both `self_reset_enabled` modes.
- **While set:** the sample is fully suppressed — no event may start, no
  integration occurs (`sample_voltage` treated as 0, accumulator unchanged),
  timestamps/`previous_centered_voltage_v` update as usual (prev becomes 0,
  so the eventual re-armed event starts from a clean baseline reference).
  `active` keeps reporting the raw threshold state so the package engine's
  quiet bookkeeping still sees the tail as "not quiet".
- **Cleared** by the first sample with `|v| < threshold` (voltage back inside
  the noise band). That sample also starts the quiet run (`quiet_since_s`)
  for the fail-safe. The next threshold crossing after that starts a fresh
  event exactly like a first press.
- Report the state via a new `PztForceStepResult.rearm_gate_active: bool`
  field (for tests and diagnostics).
- No new tunable: the gate is a correctness fix, always on. (Optional
  polarity-flip re-arm is deferred — see D5.)

Package mode (`self_reset_enabled=False`) needs no engine change: the gated
channel's accumulator simply holds its ≤band residual (the natural zero
already latched `reset_recommended` → `pending_reset_positions`), the channel
stays `active` during the tail so `_package_event_complete` waits, and the
coherent package reset fires once the tail quiets — same timing as today but
without corrupting the accumulator first.

### Work item C2: clear stale previous voltage at event end

At every event end (natural zero and quiet-hold release), after the step's
own integration, set `previous_centered_voltage_v = 0.0`. This removes the F2
shelf at its source: the sample after a quiet-hold release integrates
`0 − α·0 = 0` instead of `−α·v_prev`. (For the natural-zero path C1 already
forces prev = 0 while gated; C2 makes the invariant uniform: *no event ⇒
baseline reference is 0*.)

### Work item C3: fail-safe engages on any nonzero residual (defense in depth)

- Integrator: change the engage condition
  `abs(accumulated_force_n) > force_zero_band_min_n` →
  `accumulated_force_n != 0.0` (`pzt_force_calculation.py:356`).
  `decay_toward_zero` already snaps anything inside the floor to exact 0 on
  its first call, so a sub-floor residual from any future path resolves after
  the quiet hold instead of persisting forever.
- Package engine: mirror in `_package_stuck_decay_due`
  (`pressure_force_display.py:436-437`):
  `any(state.accumulated_force_n != 0.0 for ...)`.
- C2 removes the only known source; C3 guarantees no residual class can ever
  be permanent again.

### Work item C4: tests (extend `tests/test_pzt_force_calculation.py` + display tests)

1. **Slow-press regression (F1):** synthetic slow ramp (sustained
   supra-threshold positive voltage ≫ RC τ so replenishment dominates) +
   fast release spike. Assert: natural zero fires during the release; every
   subsequent sample while the undershoot is still supra-threshold leaves the
   accumulator at exactly 0 with `rearm_gate_active=True`; no negative
   plateau forms.
2. **Re-arm:** after the tail returns sub-threshold, the gate clears; a
   following press integrates from 0 with prev-voltage 0 and behaves
   identically to a first press (compare step-by-step against a fresh
   integrator).
3. **Mid-event overshoot still allowed:** a genuinely bipolar event whose
   force crosses through zero *before* any natural zero keeps integrating
   (unchanged behavior pin).
3b. **Polarity mirror:** run tests 1–3 with the voltage trace negated (a
   negative event with a positive release tail) and assert the force trace is
   exactly the negation of the positive-event result — natural zero at the
   same sample, gate engaged/released at the same samples, 0 between events.
4. **F2 regression:** event ending via quiet-hold release with a nonzero
   final sub-threshold voltage → every subsequent quiet sample stays exactly
   0.0 (no ~mN shelf).
5. **Sub-floor snap (C3):** accumulator seeded below `force_zero_band_min_n`,
   quiet for the fail-safe hold → snapped to exact 0.
6. **Package engine (`tests/test_pressure_force_display.py`):** a channel in
   the gated state holds its residual until the coherent package reset; the
   package force never develops the F1 negative plateau; package quiet/stuck
   bookkeeping treats the gated tail as not-quiet.

### Acceptance for Part C (manual, on the 15:59 capture)

- Slow presses 4 and 5: force rises to ≈ +1.4/+1.5 N, returns, is zeroed
  once near the crossing, and stays at exactly 0 until the next press — no
  −0.41 / −0.66 N plateaus, no 1 s fail-safe fades.
- Between all events the force is exactly 0.0 (no +0.00125 N shelf).
- Fast presses 1–3: unchanged shapes; press 3's small −0.035 N tail is gone.
- Genuine bipolar behavior inside an event is unchanged, and behavior is
  sign-symmetric: a negative event ends at exactly 0 the same way (pinned by
  test C4-3b; this capture contains only positive events).

---

## 4. Part D — expose event-machine tunables in both GUIs (resolves D2)

User request: parameters a user may need to tune (e.g. the force zero floor)
must be controllable from every GUI that uses the force calculation — the
Analysis tab and the Pressure Map. Five settings, same keys/defaults as
`constants/pzt_force.py`; both existing calculation paths already read them
from the settings dict (`pzt_force_calculation.py:440-447` for Analysis,
`pressure_force_display.py:356-360` for the live map), so **only the panels
and persistence need work — no engine changes**.

| Setting key | Default | Proposed label / suffix | Spin range / decimals |
| --- | --- | --- | --- |
| `force_zero_band_min_n` | 0.02 | "Zero floor:" / " N" | 0–1e6 / 4 |
| `force_zero_band_fraction` | 0.1 | "Zero band:" / " × peak" | 0–1 / 3 |
| `force_zero_min_event_peak_n` | 0.05 | "Min event peak:" / " N" | 0–1e6 / 4 |
| `quiet_hold_release_fraction` | 0.5 | "Quiet release:" / " × peak" | 0–1 / 3 |
| `quiet_hold_clear_s` | 0.15 | "Quiet hold:" / " s" | 0–3600 / 3 |

Tooltips must explain each in press terms; "Zero floor" additionally notes it
is also the fail-safe snap band.

### Work item D1: Pressure Map settings (`gui/signal_integration_panel.py`)

- Add the five `QDoubleSpinBox`es to `_create_pzt_force_settings_group`
  (new grid rows below the current row 4), widget names
  `force_pzt_zero_floor_spin`, `force_pzt_zero_band_fraction_spin`,
  `force_pzt_min_event_peak_spin`, `force_pzt_quiet_release_spin`,
  `force_pzt_quiet_hold_spin`.
- Append them to the change-signal loop (currently lines 794-803) so edits
  rebuild the force engine, add the five keys to `_pzt_force_settings()`
  (807-821), and add `_set_spin_value` restore calls next to the stuck-force
  ones (~2219-2221).

### Work item D2: Analysis panel (`gui/analysis_panel.py`)

- Same five spinboxes in the Analysis "PZT force" group (rows below the
  stuck-force row 6), wired to `on_analysis_settings_changed`.
- Add the five keys to the persisted `pzt_force` settings dict (~800-810)
  and to the settings-restore path (~560-570), with
  `PZT_FORCE_DEFAULT_SETTINGS` fallbacks for old saved settings.

### Work item D3: tests

- Settings round-trip in both panels' existing coverage
  (`tests/test_analysis_workbench.py` / panel round-trip tests): the five
  keys survive save → restore, and defaults apply when a legacy settings
  payload lacks them.
- Pressure map: `_pzt_force_settings()` emits the five keys; engine rebuild
  receives an edited value (spot-check one, e.g. `force_zero_band_min_n`).

---

## 5. Open decisions

- **D1 — resolved** (rev 1): monopolar residuals are handled by the
  stuck-force fail-safe, user-toggleable.
- **D2 — resolved by Part D:** all five event tunables get UI in both panels.
- **D3 — defaults:** unchanged (`0.1 / 0.02 N / 0.05 N / 0.5 / 0.15 s`;
  fail-safe 1 s hold / 1 s tau). Revisit after Part C removes the spurious
  residuals, since the fail-safe will then rarely engage.
- **D4 — held-press fade:** unchanged (fail-safe intentionally fades a held
  press once its voltage has decayed; toggle off to retain).
- **D5 — new, deferred:** re-arm the gate on a polarity flip so a genuine
  opposite-direction press applied *during* a release tail (before the
  voltage re-enters the noise band, a ~100 ms window in this capture) is not
  absorbed. Not needed for any observed capture; implement only if hardware
  runs show back-to-back opposite presses.

## 6. Suggested commit order

1. **C1 + C2 + C3 + C4** — one commit: the gate, the prev-voltage clear, the
   fail-safe engage change, and their tests (integrator + package engine).
2. **D1 + D2 + D3** — one commit: the ten spinboxes (five per panel),
   persistence, and round-trip tests.
