import numpy as np
import pytest
from types import SimpleNamespace
from unittest.mock import patch

from constants.shear import SHEAR_SENSOR_POSITIONS
from data_processing.pressure_force_display import ForceLayer, PressureForceDisplayEngine
from data_processing.shear_detector import ShearDetector
from data_processing.pressure_map_array_generator import PressureMapArrayForcePackage, PressureMapArrayGenerator
from data_processing.pzt_force_calculation import (
    PztForceChannelIntegrator,
    calculate_pzt_force_from_voltage,
)
from data_processing.pressure_map_geometry import PressureMapGeometry


def test_live_channel_integrator_matches_batch_reconstruction():
    voltage = np.asarray([0.0, 0.15, 0.10, -0.05, 0.0], dtype=float)
    timestamps = np.arange(voltage.size, dtype=float) * 0.01
    kwargs = dict(
        capacitance_f=150e-12,
        rleak_ohm=1e6,
        d33_c_per_n=600e-12,
        noise_threshold_v=0.01,
    )
    batch = calculate_pzt_force_from_voltage(voltage, timestamps, vmid_v=0.0, **kwargs)
    live = PztForceChannelIntegrator(**kwargs)
    observed = [live.process_centered_sample(v, t).accumulated_force_n for v, t in zip(voltage, timestamps)]
    np.testing.assert_allclose(observed, batch)


def test_force_engine_uses_position_specific_capacitance():
    engine = PressureForceDisplayEngine(
        geometry=PressureMapGeometry(),
        settings={
            "center_capacitance_value": 2.0,
            "outer_capacitance_value": 1.0,
            "capacitance_unit": "nF",
        },
    )
    engine.configure_layout({"PZT1": (0, 0)})
    states = engine._packages["PZT1"].channel_states

    assert states["C"].capacitance_f == pytest.approx(2e-9)
    for position in ("T", "R", "L", "B"):
        assert states[position].capacitance_f == pytest.approx(1e-9)


def test_force_engine_processes_sample_identity_once_and_resets_completed_event():
    # noise_threshold_v=0.01 with a +-0.3 V swing keeps the event's own peak
    # force above force_zero_min_event_peak_n (0.05 N default) so the natural
    # zero fires on the exact symmetric return; quiet_hold_clear_s is
    # shortened so the test doesn't need to wait out the (1.5 s) default.
    engine = PressureForceDisplayEngine(
        geometry=PressureMapGeometry(),
        settings={"noise_threshold_v": 0.01, "quiet_hold_clear_s": 0.05},
    )
    def package(value):
        return {"PZT1": {position: value for position in SHEAR_SENSOR_POSITIONS}}

    assert engine.process_sample(1, package(0.0), 0.0)
    assert engine.process_sample(2, package(0.3), 0.01)
    before_duplicate = engine.package_results()[0].force_grid_n.copy()
    assert not engine.process_sample(2, package(0.3), 0.01)
    np.testing.assert_array_equal(engine.package_results()[0].force_grid_n, before_duplicate)

    # The equal-and-opposite swing lands the accumulator exactly on zero (a
    # natural zero, still on this active sample); the package itself only
    # resets on the following genuinely quiet sample.
    assert engine.process_sample(3, package(-0.3), 0.02)
    assert engine._packages["PZT1"].channel_states["C"].accumulated_force_n == 0.0
    assert engine._packages["PZT1"].has_force_activity

    assert engine.process_sample(4, package(0.0), 0.03)
    # Event completion clears the complete package state atomically.  The
    # package remains available for a subsequent event rather than vanishing.
    result = engine.package_results()
    assert len(result) == 1
    assert result[0].normal_force_n == 0.0
    assert result[0].shear_force_n == 0.0
    assert not np.any(result[0].force_grid_n)
    assert not engine._packages["PZT1"].has_force_activity


def test_force_engine_rejects_backward_sample_identity():
    engine = PressureForceDisplayEngine(geometry=PressureMapGeometry())
    package = {"PZT1": {position: 0.0 for position in SHEAR_SENSOR_POSITIONS}}
    engine.process_sample(5, package, 1.0)
    with pytest.raises(ValueError, match="identity moved backwards"):
        engine.process_sample(4, package, 1.1)


def test_force_engine_accumulates_world_array_increment_with_shared_generator():
    engine = PressureForceDisplayEngine(
        geometry=PressureMapGeometry(), settings={"noise_threshold_v": 0.01}
    )
    package = {
        sensor_id: {position: 0.0 for position in SHEAR_SENSOR_POSITIONS}
        for sensor_id in ("PZT1", "PZT2")
    }
    positions = {"PZT1": (0, 0), "PZT2": (0, 1)}
    engine.process_sample(1, package, 0.0, grid_positions=positions)
    package["PZT1"]["C"] = 0.1
    package["PZT2"]["C"] = 0.1
    engine.process_sample(2, package, 0.01, grid_positions=positions)
    result = engine.array_result()
    assert result is not None
    assert result.force_grid_n.shape == (
        result.y_coordinates_mm.size, result.x_coordinates_mm.size
    )
    assert set(result.package_centers) == {"PZT1", "PZT2"}


def test_force_engine_keeps_every_configured_package_in_static_array():
    engine = PressureForceDisplayEngine(geometry=PressureMapGeometry())
    positions = {"PZT1": (0, 0), "PZT2": (0, 1), "PZT3": (1, 0)}
    engine.configure_layout(positions)

    results = engine.package_results()
    assert [result.sensor_id for result in results] == ["PZT1", "PZT2", "PZT3"]
    assert all(not np.any(result.force_grid_n) for result in results)
    array = engine.array_result()
    assert array is not None
    assert set(array.package_centers) == set(positions)


def test_force_array_superposes_packages_without_double_counting_magnitude():
    geometry = PressureMapGeometry()
    engine = PressureForceDisplayEngine(geometry=geometry)

    def uniform(sensor_id, grid_position, level):
        return PressureMapArrayForcePackage(
            sensor_id, grid_position,
            level * np.ones((engine._y_coordinates_mm.size, engine._x_coordinates_mm.size)),
            engine._x_coordinates_mm, engine._y_coordinates_mm,
        )

    generator = PressureMapArrayGenerator(geometry=geometry)

    same_sign, magnitude, x_values, y_values, _centers = generator.compose_force_grids(
        [uniform("PZT1", (0, 0), 1.0), uniform("PZT2", (0, 1), 1.0)]
    )
    # On the midline both packages sit exactly at their Mid Boundary, where the
    # support fade is still 1.0, so their contributions pass through unscaled.
    midline_column = int(np.argmin(np.abs(x_values)))
    inside_mid = np.abs(y_values) <= geometry.mid_boundary_half_width_mm
    # Same-sign packages superpose.
    np.testing.assert_allclose(same_sign[inside_mid, midline_column], 2.0)
    np.testing.assert_allclose(magnitude, np.abs(same_sign))

    opposite, magnitude, _x, _y, _centers = generator.compose_force_grids(
        [uniform("PZT1", (0, 0), 1.0), uniform("PZT2", (0, 1), -1.0)]
    )
    # Equal and opposite package fields cancel: the superposed field is what
    # the magnitude display shows, so an overlap never double-counts.
    np.testing.assert_allclose(opposite[inside_mid, midline_column], 0.0, atol=1e-12)
    np.testing.assert_allclose(magnitude, np.abs(opposite))


def _jerk_display(sensor_id: str, grid: np.ndarray):
    return SimpleNamespace(
        sensor_id=sensor_id,
        pressure_result=SimpleNamespace(pressure_grid=np.asarray(grid, dtype=np.float64)),
    )


def test_force_engine_applies_the_exact_normalized_jerk_shape_once():
    engine = PressureForceDisplayEngine(geometry=PressureMapGeometry())
    engine.configure_layout({"PZT1": (0, 0)})
    state = engine._packages["PZT1"]
    state.normal_force_n = 0.5
    jerk_grid = np.zeros_like(state.accumulated_force_grid_n)
    jerk_grid[4, 7] = -2.0
    jerk_grid[9, 10] = 1.0

    engine.apply_jerk_shapes([_jerk_display("PZT1", jerk_grid)])

    expected = np.abs(jerk_grid) / 2.0 * 0.5
    np.testing.assert_allclose(state.accumulated_force_grid_n, expected)
    assert state.applied_load_n == 0.5
    # Re-applying an unchanged load is idempotent: the layer stack already
    # matches ``abs(normal_force_n)``.
    engine.apply_jerk_shapes([_jerk_display("PZT1", jerk_grid)])
    np.testing.assert_allclose(state.accumulated_force_grid_n, expected)
    assert state.applied_load_n == 0.5


def test_force_engine_renders_negative_force_with_the_same_magnitude_shape():
    engine = PressureForceDisplayEngine(geometry=PressureMapGeometry())
    engine.configure_layout({"PZT1": (0, 0)})
    state = engine._packages["PZT1"]
    state.normal_force_n = -0.5
    jerk_grid = np.zeros_like(state.accumulated_force_grid_n)
    jerk_grid[4, 7] = -2.0
    jerk_grid[9, 10] = 1.0

    engine.apply_jerk_shapes([_jerk_display("PZT1", jerk_grid)])

    # The raster is magnitude-only: -0.5 N paints exactly like +0.5 N while
    # the numerical readout keeps its sign.
    np.testing.assert_allclose(state.accumulated_force_grid_n, np.abs(jerk_grid) / 2.0 * 0.5)
    assert state.normal_force_n == -0.5
    assert state.applied_polarity == -1


def test_force_samples_never_generate_force_side_pressure_maps():
    engine = PressureForceDisplayEngine(geometry=PressureMapGeometry())
    sample = {"PZT1": {position: 0.0 for position in SHEAR_SENSOR_POSITIONS}}
    with patch(
        "data_processing.pressure_map_generator.PressureMapGenerator.generate",
        side_effect=AssertionError("Force sample path must not generate a map"),
    ):
        for sample_id in range(1000):
            assert engine.process_sample(sample_id, sample, sample_id * 0.001)


def test_force_engine_keeps_unapplied_load_until_a_nonzero_jerk_shape_arrives():
    engine = PressureForceDisplayEngine(geometry=PressureMapGeometry())
    engine.configure_layout({"PZT1": (0, 0)})
    state = engine._packages["PZT1"]
    state.normal_force_n = 0.04
    zero_shape = np.zeros_like(state.accumulated_force_grid_n)

    engine.apply_jerk_shapes([_jerk_display("PZT1", zero_shape)])
    # A zero Jerk shape cannot paint load; the difference between
    # ``abs(normal_force_n)`` and ``applied_load_n`` persists instead.
    assert state.applied_load_n == 0.0
    assert not np.any(state.accumulated_force_grid_n)

    nonzero_shape = zero_shape.copy()
    nonzero_shape[3, 3] = 1.0
    engine.apply_jerk_shapes([_jerk_display("PZT1", nonzero_shape)])
    assert state.applied_load_n == 0.04
    assert state.accumulated_force_grid_n[3, 3] == 0.04


def test_force_reset_clears_layers_and_accumulated_force():
    engine = PressureForceDisplayEngine(geometry=PressureMapGeometry())
    engine.configure_layout({"PZT1": (0, 0)})
    state = engine._packages["PZT1"]
    state.normal_force_n = 0.2
    state.force_layers.append(
        ForceLayer(np.ones_like(state.accumulated_force_grid_n), 0.2)
    )
    state.applied_load_n = 0.2
    state.applied_polarity = 1
    state.accumulated_force_grid_n.fill(0.1)

    engine.reset()

    state = engine._packages["PZT1"]
    assert state.normal_force_n == 0.0
    assert state.force_layers == []
    assert state.applied_load_n == 0.0
    assert state.applied_polarity == 0
    assert not np.any(state.accumulated_force_grid_n)


def test_force_engine_waits_for_staggered_channel_events_before_package_reset():
    # Center pushes and settles (fallback-eligible bipolar swing) one sample
    # before Left; each channel's own quiet_hold_clear_s countdown starts
    # from when *it* individually falls quiet, so the package must wait for
    # whichever channel resolves last.
    engine = PressureForceDisplayEngine(
        geometry=PressureMapGeometry(), settings={"noise_threshold_v": 0.01, "quiet_hold_clear_s": 0.05}
    )
    engine.configure_layout({"PZT1": (0, 0)})

    def sample(center: float, left: float):
        return {
            "PZT1": {
                "C": center, "L": left, "R": 0.0, "T": 0.0, "B": 0.0,
            }
        }

    engine.process_sample(0, sample(0.0, 0.0), 0.00)
    engine.process_sample(1, sample(0.3, 0.0), 0.01)
    engine.process_sample(2, sample(-0.2, 0.3), 0.02)   # C settles quiet from here (residual 0.025)
    engine.process_sample(3, sample(0.0, -0.2), 0.03)   # L settles quiet from here (residual 0.025)
    for index, timestamp in enumerate((0.04, 0.05, 0.06, 0.07), start=4):
        engine.process_sample(index, sample(0.0, 0.0), timestamp)
        # Neither channel has reached its own quiet_hold_clear_s yet, so the
        # package must retain state (not even Center, which resolves next).
        assert engine._packages["PZT1"].has_force_activity
        assert engine._packages["PZT1"].channel_states["C"].accumulated_force_n == pytest.approx(0.025)
        assert engine._packages["PZT1"].channel_states["L"].accumulated_force_n == pytest.approx(0.025)

    # Center resolves at t=0.03+0.05=0.08 (one sample ahead of Left); the
    # package must still not reset since Left hasn't resolved.
    engine.process_sample(8, sample(0.0, 0.0), 0.08)
    assert engine._packages["PZT1"].has_force_activity
    assert engine._packages["PZT1"].channel_states["L"].accumulated_force_n == pytest.approx(0.025)

    # Left resolves at t=0.04+0.05=0.09: only once both channels are resolved
    # does the coherent package reset fire.
    engine.process_sample(9, sample(0.0, 0.0), 0.10)
    result = engine.package_results()[0]
    assert result.normal_force_n == 0.0
    assert result.shear_force_n == 0.0
    assert not np.any(result.force_grid_n)
    assert not engine._packages["PZT1"].has_force_activity


def test_one_channel_tail_noise_does_not_reset_the_package_mid_press():
    """A single sub-threshold dip on one channel, while a press is ongoing on
    all five, must be absorbed by hysteresis (the channel's own event stays
    active) rather than being read as that channel's event concluding."""
    engine = PressureForceDisplayEngine(
        geometry=PressureMapGeometry(), settings={"noise_threshold_v": 0.01, "quiet_hold_clear_s": 0.05}
    )
    engine.configure_layout({"PZT1": (0, 0)})

    def sample(c, l, r, t, b):
        return {"PZT1": {"C": c, "L": l, "R": r, "T": t, "B": b}}

    engine.process_sample(0, sample(0.0, 0.0, 0.0, 0.0, 0.0), 0.00)
    engine.process_sample(1, sample(0.3, 0.3, 0.3, 0.3, 0.3), 0.01)
    before_dip = engine._packages["PZT1"].channel_states["L"].accumulated_force_n

    # L alone dips below threshold for one sample while the other four are
    # still mid-press.
    engine.process_sample(2, sample(0.3, 0.0, 0.3, 0.3, 0.3), 0.02)
    package = engine._packages["PZT1"]
    assert package.has_force_activity
    assert package.channel_states["L"].event_active
    assert package.channel_states["L"].accumulated_force_n == pytest.approx(before_dip)
    assert package.normal_force_n > 0.0

    engine.process_sample(3, sample(0.3, 0.3, 0.3, 0.3, 0.3), 0.03)
    assert engine._packages["PZT1"].channel_states["L"].accumulated_force_n > before_dip


def test_force_engine_gated_release_tail_holds_residual_until_package_reset():
    """Work item C4-6: reproduces finding F1 at the package-engine level. A
    channel's natural zero can fire while its own release transient is still
    supra-threshold; ``self_reset_enabled=False`` keeps the >=band residual
    on the accumulator (not zeroed) until a coherent package reset, and the
    re-arm gate must hold that residual exactly fixed - not integrate the
    still-arriving tail as a spurious opposite-sign plateau - while the
    channel keeps reporting ``active=True`` so the package completion check
    waits instead of treating the tail as quiet."""
    engine = PressureForceDisplayEngine(
        geometry=PressureMapGeometry(), settings={"noise_threshold_v": 0.1, "quiet_hold_clear_s": 0.05},
    )
    engine.configure_layout({"PZT1": (0, 0)})

    def sample(center: float):
        return {"PZT1": {"C": center, "L": 0.0, "R": 0.0, "T": 0.0, "B": 0.0}}

    engine.process_sample(0, sample(0.0), 0.00)
    engine.process_sample(1, sample(0.5), 0.01)
    channel = engine._packages["PZT1"].channel_states["C"]
    assert channel.event_peak_force_n == pytest.approx(0.125)

    # Fast release spike lands the residual within the natural-zero band
    # while voltage (-0.46 V) is still far outside the noise threshold.
    engine.process_sample(2, sample(-0.46), 0.02)
    residual = channel.accumulated_force_n
    assert 0.0 < abs(residual) <= 0.02
    assert channel.rearm_pending
    assert "C" in engine._packages["PZT1"].pending_reset_positions

    # The undershoot keeps running supra-threshold for several more samples:
    # the gate must hold the residual exactly fixed (never integrate a
    # spurious negative plateau), and the package must not treat the tail as
    # quiet/resolved while the channel is still reporting active.
    for index, timestamp in enumerate((0.03, 0.04, 0.05), start=3):
        engine.process_sample(index, sample(-0.3), timestamp)
        assert channel.accumulated_force_n == residual
        assert channel.active
        assert not engine._package_event_complete(engine._packages["PZT1"])

    # The tail finally returns inside the noise band: the gate clears and,
    # now genuinely quiet with its only nonzero channel already latched in
    # pending_reset_positions, the whole package resets coherently.
    engine.process_sample(6, sample(0.0), 0.06)
    assert not engine._packages["PZT1"].has_force_activity
    assert engine._packages["PZT1"].channel_states["C"].accumulated_force_n == 0.0


def test_force_engine_accepts_monotonic_tuple_sample_identities():
    engine = PressureForceDisplayEngine(geometry=PressureMapGeometry())
    package = {"PZT1": {position: 0.0 for position in SHEAR_SENSOR_POSITIONS}}
    assert engine.process_sample((10, 0), package, 1.0)
    assert engine.process_sample((10, 1), package, 1.1)
    with pytest.raises(ValueError, match="identity moved backwards"):
        engine.process_sample((10, 0), package, 1.2)


def test_force_engine_resets_instead_of_bridging_a_missing_repeat_observation():
    engine = PressureForceDisplayEngine(geometry=PressureMapGeometry())
    package = {"PZT1": {position: 0.0 for position in SHEAR_SENSOR_POSITIONS}}
    assert engine.process_sample((10, 0), package, 1.0, observations_per_sweep=3)
    with pytest.raises(ValueError, match="observation discontinuity"):
        engine.process_sample((10, 2), package, 1.1, observations_per_sweep=3)


def test_stuck_force_failsafe_tau_zero_resets_the_whole_package_instantly():
    """Replaces the old sample-count ``reset_after_quiet_samples`` net.

    A package quiet for ``stuck_force_quiet_hold_s`` with residual force
    outside the zero band resets all five channels together, coherently,
    once ``tau == 0`` selects an instant reset.
    """
    engine = PressureForceDisplayEngine(
        geometry=PressureMapGeometry(),
        settings={"stuck_force_quiet_hold_s": 0.05, "stuck_force_decay_tau_s": 0.0, "quiet_hold_clear_s": 0.02},
    )
    engine.configure_layout({"PZT1": (0, 0)})
    state = engine._packages["PZT1"]
    state.has_force_activity = True
    # Package Normal/Shear are derived from channel accumulators, so the
    # retained-until-reset value must be seeded at the channel level.
    state.channel_states["C"].accumulated_force_n = 0.5
    state.channel_states["L"].accumulated_force_n = 0.1
    state.channel_states["R"].accumulated_force_n = -0.1
    state.accumulated_force_grid_n.fill(0.5)
    quiet = {"PZT1": {position: 0.0 for position in SHEAR_SENSOR_POSITIONS}}

    for sample_id in range(1, 6):
        engine.process_sample(sample_id, quiet, sample_id * 0.011)
        assert engine._packages["PZT1"].normal_force_n == 0.5
        assert engine._packages["PZT1"].shear_x_n == -0.1

    engine.process_sample(6, quiet, 6 * 0.011)
    state = engine._packages["PZT1"]
    assert state.normal_force_n == 0.0
    assert state.shear_x_n == 0.0
    assert state.shear_y_n == 0.0
    assert not state.has_force_activity
    assert not np.any(state.accumulated_force_grid_n)
    assert all(not channel.initialized for channel in state.channel_states.values())


def test_stuck_force_failsafe_decays_all_five_channels_by_the_same_factor():
    """Residual force decays exponentially; shear ratios stay intact until
    each channel individually crosses the zero-band floor and snaps to
    exact zero, then the package reset fires once every channel is zero."""
    engine = PressureForceDisplayEngine(
        geometry=PressureMapGeometry(),
        settings={
            "stuck_force_quiet_hold_s": 0.03, "stuck_force_decay_tau_s": 0.05,
            "quiet_hold_clear_s": 0.02, "force_zero_band_min_n": 0.02,
        },
    )
    engine.configure_layout({"PZT1": (0, 0)})
    state = engine._packages["PZT1"]
    state.has_force_activity = True
    state.channel_states["C"].accumulated_force_n = 0.5
    state.channel_states["L"].accumulated_force_n = 0.1
    quiet = {"PZT1": {position: 0.0 for position in SHEAR_SENSOR_POSITIONS}}

    seen_partial_decay = False
    for sample_id in range(1, 20):
        engine.process_sample(sample_id, quiet, sample_id * 0.011)
        state = engine._packages["PZT1"]
        c_force = state.channel_states["C"].accumulated_force_n
        l_force = state.channel_states["L"].accumulated_force_n
        if 0.0 < c_force < 0.5 and l_force > 0.0:
            seen_partial_decay = True
            assert l_force / c_force == pytest.approx(0.2, rel=1e-6)
        if not state.has_force_activity:
            break

    assert seen_partial_decay
    assert not engine._packages["PZT1"].has_force_activity


def test_stuck_force_failsafe_disabled_retains_residual_indefinitely():
    engine = PressureForceDisplayEngine(
        geometry=PressureMapGeometry(),
        settings={"stuck_force_failsafe_enabled": False, "stuck_force_quiet_hold_s": 0.01},
    )
    engine.configure_layout({"PZT1": (0, 0)})
    state = engine._packages["PZT1"]
    state.has_force_activity = True
    state.channel_states["C"].accumulated_force_n = 0.5
    quiet = {"PZT1": {position: 0.0 for position in SHEAR_SENSOR_POSITIONS}}

    for sample_id in range(1, 50):
        engine.process_sample(sample_id, quiet, sample_id * 0.011)

    assert engine._packages["PZT1"].normal_force_n == 0.5


def test_stuck_force_failsafe_new_active_sample_cancels_decay():
    engine = PressureForceDisplayEngine(
        geometry=PressureMapGeometry(),
        settings={"stuck_force_quiet_hold_s": 0.02, "stuck_force_decay_tau_s": 0.05,
                  "quiet_hold_clear_s": 0.02, "noise_threshold_v": 0.01},
    )
    engine.configure_layout({"PZT1": (0, 0)})
    state = engine._packages["PZT1"]
    state.has_force_activity = True
    state.channel_states["C"].accumulated_force_n = 0.5
    quiet = {"PZT1": {position: 0.0 for position in SHEAR_SENSOR_POSITIONS}}

    for sample_id in range(1, 6):
        engine.process_sample(sample_id, quiet, sample_id * 0.011)
    decayed = engine._packages["PZT1"].channel_states["C"].accumulated_force_n
    assert 0.0 < decayed < 0.5

    active = {"PZT1": {**{p: 0.0 for p in SHEAR_SENSOR_POSITIONS}, "C": 0.3}}
    engine.process_sample(6, active, 6 * 0.011)

    resumed = engine._packages["PZT1"].channel_states["C"].accumulated_force_n
    assert resumed == pytest.approx(decayed + 0.25 * 0.3)


def test_active_channel_restarts_the_package_quiet_timer():
    """An active sample interrupts the package-wide quiet run (restarting the
    countdown, not continuing toward the old hold) and also starts a fresh
    per-channel event for that channel - which, since the quiet-hold reset is
    unconditional, concludes and gets the package coherently reset via the
    ordinary per-channel path, without needing to wait out the (longer)
    stuck-force hold at all."""
    engine = PressureForceDisplayEngine(
        geometry=PressureMapGeometry(),
        settings={"stuck_force_quiet_hold_s": 0.05, "stuck_force_decay_tau_s": 0.0,
                  "quiet_hold_clear_s": 0.02, "noise_threshold_v": 0.01},
    )
    engine.configure_layout({"PZT1": (0, 0)})
    state = engine._packages["PZT1"]
    state.has_force_activity = True
    state.channel_states["C"].accumulated_force_n = 0.5
    quiet = {"PZT1": {position: 0.0 for position in SHEAR_SENSOR_POSITIONS}}
    active = {"PZT1": {**{p: 0.0 for p in SHEAR_SENSOR_POSITIONS}, "C": 0.1}}

    for sample_id in range(1, 4):
        engine.process_sample(sample_id, quiet, sample_id * 0.011)
    assert engine._packages["PZT1"].quiet_since_s is not None

    # A single active sample interrupts the package-wide quiet run: the
    # countdown must restart from here, not continue toward the old hold.
    # It also integrates fresh charge on top of the retained residual.
    engine.process_sample(4, active, 4 * 0.011)
    assert engine._packages["PZT1"].quiet_since_s is None
    restarted_force = engine._packages["PZT1"].channel_states["C"].accumulated_force_n
    assert restarted_force > 0.5

    for sample_id in range(5, 7):
        engine.process_sample(sample_id, quiet, sample_id * 0.011)
        # Not yet elapsed even the short per-channel quiet_hold_clear_s: still retained.
        assert engine._packages["PZT1"].normal_force_n == pytest.approx(restarted_force)

    for sample_id in range(7, 15):
        engine.process_sample(sample_id, quiet, sample_id * 0.011)
        if engine._packages["PZT1"].normal_force_n == 0.0:
            break
    assert engine._packages["PZT1"].normal_force_n == 0.0
    assert not engine._packages["PZT1"].has_force_activity


def test_stuck_force_failsafe_is_independent_per_configured_package():
    engine = PressureForceDisplayEngine(
        geometry=PressureMapGeometry(),
        settings={"stuck_force_quiet_hold_s": 0.02, "stuck_force_decay_tau_s": 0.0,
                  "quiet_hold_clear_s": 0.02, "noise_threshold_v": 0.01},
    )
    engine.configure_layout({"PZT1": (0, 0), "PZT3": (0, 1)})
    engine._packages["PZT1"].has_force_activity = True
    engine._packages["PZT1"].channel_states["C"].accumulated_force_n = 0.5
    quiet = {position: 0.0 for position in SHEAR_SENSOR_POSITIONS}

    for sample_id in range(1, 8):
        engine.process_sample(
            sample_id,
            {"PZT1": quiet, "PZT3": {**quiet, "C": 0.3}},
            sample_id * 0.011,
        )
    assert engine._packages["PZT1"].normal_force_n == 0.0
    # PZT3 kept accumulating the whole time; it was never quiet, so its own
    # fail-safe never engaged and its residual survives untouched.
    assert engine._packages["PZT3"].has_force_activity
    assert engine._packages["PZT3"].normal_force_n > 0.0


def _spot_shape(reference: np.ndarray, row: int, column: int, value: float = 1.0) -> np.ndarray:
    shape = np.zeros_like(reference)
    shape[row, column] = value
    return shape


def test_package_normal_force_is_derived_from_channel_accumulators():
    engine = PressureForceDisplayEngine(
        geometry=PressureMapGeometry(), settings={"noise_threshold_v": 0.01}
    )
    engine.configure_layout({"PZT1": (0, 0)})

    def sample(value):
        return {"PZT1": {position: value for position in SHEAR_SENSOR_POSITIONS}}

    engine.process_sample(1, sample(0.0), 0.00)
    engine.process_sample(2, sample(0.1), 0.01)
    engine.process_sample(3, sample(0.12), 0.02)

    state = engine._packages["PZT1"]
    expected = sum(channel.accumulated_force_n for channel in state.channel_states.values())
    # The channel integrators are the only physical integrators; the package
    # value is derived from their current state, never accumulated again.
    assert state.normal_force_n == pytest.approx(expected)


def test_shear_is_derived_from_current_state_not_integrated():
    engine = PressureForceDisplayEngine(
        geometry=PressureMapGeometry(), settings={"noise_threshold_v": 0.01}
    )
    engine.configure_layout({"PZT1": (0, 0)})

    def sample(left, right):
        return {"PZT1": {"C": 0.0, "L": left, "R": right, "T": 0.0, "B": 0.0}}

    engine.process_sample(1, sample(0.0, 0.0), 0.00)
    engine.process_sample(2, sample(0.10, -0.08), 0.01)
    engine.process_sample(3, sample(0.05, -0.02), 0.02)

    state = engine._packages["PZT1"]
    current_forces = {
        position: state.channel_states[position].accumulated_force_n
        for position in SHEAR_SENSOR_POSITIONS
    }
    expected = ShearDetector().detect(current_forces)
    assert state.shear_x_n == expected.b_lr
    assert state.shear_y_n == expected.b_tb


def test_loading_adds_layers_with_the_exact_delta_magnitude():
    engine = PressureForceDisplayEngine(geometry=PressureMapGeometry())
    engine.configure_layout({"PZT1": (0, 0)})
    state = engine._packages["PZT1"]
    shape_a = _spot_shape(state.accumulated_force_grid_n, 2, 2)
    shape_b = _spot_shape(state.accumulated_force_grid_n, 5, 5, 2.0)

    state.normal_force_n = 0.20
    engine.apply_jerk_shapes([_jerk_display("PZT1", shape_a)])
    state.normal_force_n = 0.30
    engine.apply_jerk_shapes([_jerk_display("PZT1", shape_b)])

    assert len(state.force_layers) == 2
    assert state.force_layers[0].remaining_force_n == pytest.approx(0.20)
    assert state.force_layers[1].remaining_force_n == pytest.approx(0.10)
    np.testing.assert_allclose(
        state.accumulated_force_grid_n,
        shape_a * 0.20 + (shape_b / 2.0) * 0.10,
    )


def test_unloading_removes_the_exact_stored_loading_shape():
    engine = PressureForceDisplayEngine(geometry=PressureMapGeometry())
    engine.configure_layout({"PZT1": (0, 0)})
    state = engine._packages["PZT1"]
    shape_a = _spot_shape(state.accumulated_force_grid_n, 2, 2)
    shape_b = _spot_shape(state.accumulated_force_grid_n, 5, 5)

    state.normal_force_n = 0.30
    engine.apply_jerk_shapes([_jerk_display("PZT1", shape_a)])
    state.normal_force_n = 0.20
    # Release happens while the current Jerk frame shows a different shape.
    # Removal must use the stored loading shape, never paint with shape B.
    engine.apply_jerk_shapes([_jerk_display("PZT1", shape_b)])

    np.testing.assert_allclose(state.accumulated_force_grid_n, shape_a * 0.20)
    assert state.accumulated_force_grid_n[5, 5] == 0.0
    assert len(state.force_layers) == 1
    assert state.force_layers[0].remaining_force_n == pytest.approx(0.20)


def test_complete_unload_returns_exact_black_without_a_jerk_shape():
    engine = PressureForceDisplayEngine(geometry=PressureMapGeometry())
    engine.configure_layout({"PZT1": (0, 0)})
    state = engine._packages["PZT1"]

    state.normal_force_n = 0.10
    engine.apply_jerk_shapes([_jerk_display("PZT1", _spot_shape(state.accumulated_force_grid_n, 2, 2))])
    state.normal_force_n = 0.30
    engine.apply_jerk_shapes([_jerk_display("PZT1", _spot_shape(state.accumulated_force_grid_n, 5, 5))])

    state.normal_force_n = 0.0
    engine.apply_jerk_shapes([SimpleNamespace(sensor_id="PZT1", pressure_result=None)])

    assert state.force_layers == []
    assert state.applied_load_n == 0.0
    # Exact zeros, not merely small values: full unload must be exact black.
    assert np.count_nonzero(state.accumulated_force_grid_n) == 0


def test_unloading_removes_layers_lifo():
    engine = PressureForceDisplayEngine(geometry=PressureMapGeometry())
    engine.configure_layout({"PZT1": (0, 0)})
    state = engine._packages["PZT1"]
    shape_a = _spot_shape(state.accumulated_force_grid_n, 2, 2)
    shape_b = _spot_shape(state.accumulated_force_grid_n, 5, 5)

    state.normal_force_n = 0.10
    engine.apply_jerk_shapes([_jerk_display("PZT1", shape_a)])
    state.normal_force_n = 0.30
    engine.apply_jerk_shapes([_jerk_display("PZT1", shape_b)])
    state.normal_force_n = 0.15
    engine.apply_jerk_shapes([_jerk_display("PZT1", shape_b)])

    assert len(state.force_layers) == 2
    assert state.force_layers[0].remaining_force_n == pytest.approx(0.10)
    assert state.force_layers[1].remaining_force_n == pytest.approx(0.05)
    np.testing.assert_allclose(
        state.accumulated_force_grid_n, shape_a * 0.10 + shape_b * 0.05
    )


def test_polarity_crossing_clears_old_layers_and_starts_a_new_event():
    engine = PressureForceDisplayEngine(geometry=PressureMapGeometry())
    engine.configure_layout({"PZT1": (0, 0)})
    state = engine._packages["PZT1"]
    shape_a = _spot_shape(state.accumulated_force_grid_n, 2, 2)
    shape_b = _spot_shape(state.accumulated_force_grid_n, 5, 5)

    state.normal_force_n = -0.10
    engine.apply_jerk_shapes([_jerk_display("PZT1", shape_a)])
    assert state.applied_polarity == -1

    state.normal_force_n = 0.15
    engine.apply_jerk_shapes([_jerk_display("PZT1", shape_b)])

    # Compression and tension history must not mix in one layer stack.
    assert state.applied_polarity == 1
    assert len(state.force_layers) == 1
    assert state.force_layers[0].remaining_force_n == pytest.approx(0.15)
    np.testing.assert_allclose(state.accumulated_force_grid_n, shape_b * 0.15)


def test_identical_shapes_coalesce_into_a_single_layer():
    engine = PressureForceDisplayEngine(geometry=PressureMapGeometry())
    engine.configure_layout({"PZT1": (0, 0)})
    state = engine._packages["PZT1"]
    shape_a = _spot_shape(state.accumulated_force_grid_n, 2, 2)

    for load in (0.10, 0.20, 0.35):
        state.normal_force_n = load
        engine.apply_jerk_shapes([_jerk_display("PZT1", shape_a)])

    # Slow monotonic loading must not grow the stack by one layer per frame.
    assert len(state.force_layers) == 1
    assert state.force_layers[0].remaining_force_n == pytest.approx(0.35)
    np.testing.assert_allclose(state.accumulated_force_grid_n, shape_a * 0.35)


def test_layer_sum_tracks_applied_load_after_every_apply():
    engine = PressureForceDisplayEngine(geometry=PressureMapGeometry())
    engine.configure_layout({"PZT1": (0, 0)})
    state = engine._packages["PZT1"]
    shapes = [
        _spot_shape(state.accumulated_force_grid_n, 2, 2),
        _spot_shape(state.accumulated_force_grid_n, 5, 5),
        _spot_shape(state.accumulated_force_grid_n, 8, 8),
    ]

    sequence = [0.10, 0.25, 0.18, 0.40, 0.05, 0.33, 0.0, -0.2, -0.05]
    for step, normal in enumerate(sequence):
        state.normal_force_n = normal
        engine.apply_jerk_shapes([_jerk_display("PZT1", shapes[step % len(shapes)])])
        layer_sum = sum(layer.remaining_force_n for layer in state.force_layers)
        assert layer_sum == pytest.approx(state.applied_load_n)
        assert state.applied_load_n == pytest.approx(abs(normal))
        assert np.all(state.accumulated_force_grid_n >= 0.0)


def test_constant_baseline_offset_ramps_and_engine_reset_clears_it():
    """Documents the runaway mechanism the baseline-change hooks exist to stop.

    A non-decaying centered offset above the noise threshold (a wrong or stale
    Time Series baseline) integrates leak-corrected charge forever.  The engine
    cannot distinguish it from a real sustained load, so the GUI must reset the
    engine whenever the shared baseline changes or disappears.
    """
    engine = PressureForceDisplayEngine(
        geometry=PressureMapGeometry(), settings={"noise_threshold_v": 0.01}
    )
    engine.configure_layout({"PZT1": (0, 0)})
    offset_sample = {"PZT1": {position: 0.05 for position in SHEAR_SENSOR_POSITIONS}}

    checkpoints = []
    for sample_id in range(1, 31):
        engine.process_sample(sample_id, offset_sample, sample_id * 0.01)
        if sample_id in (10, 30):
            checkpoints.append(engine._packages["PZT1"].normal_force_n)

    # The offset never goes quiet, so the quiet reset cannot fire, and the
    # reconstructed force keeps ramping.
    assert checkpoints[0] > 0.0
    assert checkpoints[1] > checkpoints[0]
    assert engine._packages["PZT1"].has_force_activity

    engine.reset()
    assert engine._packages["PZT1"].normal_force_n == 0.0
