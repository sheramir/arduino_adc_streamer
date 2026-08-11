"""PZT force reconstruction defaults and unit constants."""

PZT_FORCE_DEFAULT_SETTINGS = {
    "enabled": False,
    # The center sensor can use a different capacitance from the four outer
    # sensors in each five-channel PZT package. Both defaults preserve the
    # previous single-value behavior.
    "center_capacitance_value": 150.0,
    "outer_capacitance_value": 150.0,
    # Retained only to read settings saved by releases with one Cpzt value.
    # New settings persist the center/outer values above.
    "capacitance_value": 150.0,
    "capacitance_unit": "pF",
    "rleak_ohm": 1_000_000.0,
    "d33_pc_per_n": 600.0,
    "noise_threshold_v": 0.01,
    "quiet_duration_s": 2.0,
    "noise_sigma_multiplier": 5.0,
    "mux_timing_mode": "auto",
    "mux_connected_time_s": 0.030,
    "mux_connected_time_source": "",
    "off_mux_leak_enabled": False,
    "off_mux_rleak_ohm": None,
    "channel_calibration": {},
    # Visualization-only default for new settings. Persisted user values keep
    # their existing value when loaded.
    "display_max_force_n": 0.25,
    # Natural-reset event-machine tunables (PztForceChannelIntegrator).
    "force_zero_band_fraction": 0.1,
    "force_zero_band_min_n": 0.02,
    "force_zero_min_event_peak_n": 0.05,
    # At quiet-hold expiry, the residual must have declined to within this
    # fraction of the event's own peak before it is released/zeroed; a
    # residual still near peak is presumed a held press whose voltage has
    # merely decayed quiet, not a real release, and is left for the
    # stuck-force fail-safe below to eventually resolve.
    "quiet_hold_release_fraction": 0.5,
    "quiet_hold_clear_s": 0.15,
    # Stuck-force fail-safe (replaces reset_after_quiet_samples).
    "stuck_force_failsafe_enabled": True,
    "stuck_force_quiet_hold_s": 1.0,
    "stuck_force_decay_tau_s": 1.0,
}

PZT_FORCE_CAPACITANCE_UNITS = ("pF", "nF", "F")
PZT_FORCE_MUX_TIMING_MODES = ("Auto", "Manual", "Infer from total sample rate", "Continuous")
PZT_FORCE_DEFAULT_MUX_CONNECTED_TIME_S = 0.030
PZT_FORCE_PIC_COULOMB_TO_COULOMB = 1e-12
PZT_FORCE_MAD_TO_SIGMA = 1.4826
PZT_FORCE_NOISE_PERCENTILE = 95.0
