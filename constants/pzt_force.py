"""PZT force reconstruction defaults and unit constants."""

PZT_FORCE_DEFAULT_SETTINGS = {
    "enabled": False,
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
    "reset_after_quiet_samples": 10,
}

PZT_FORCE_CAPACITANCE_UNITS = ("pF", "nF", "F")
PZT_FORCE_MUX_TIMING_MODES = ("Auto", "Manual", "Infer from total sample rate", "Continuous")
PZT_FORCE_DEFAULT_MUX_CONNECTED_TIME_S = 0.030
PZT_FORCE_PIC_COULOMB_TO_COULOMB = 1e-12
PZT_FORCE_MAD_TO_SIGMA = 1.4826
PZT_FORCE_NOISE_PERCENTILE = 95.0
