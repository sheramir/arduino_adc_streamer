"""
Force Feedback Helpers
======================
Helpers for user-facing force-processing feedback that should stay out of
sample-ingestion and calibration flow.
"""

from __future__ import annotations

from constants.force import FORCE_STATUS_UPDATE_INTERVAL_SAMPLES


def log_first_force_sample(owner, *, state, x_force: float, z_force: float) -> None:
    """Log the first raw sample seen from the force reader."""
    if state.raw_samples_seen != 1:
        return

    owner.log_status(
        f"First force sample received: x={x_force:.3f}, z={z_force:.3f}"
    )


def log_force_calibration_ready(owner, *, state) -> None:
    """Log the final calibration offsets and readiness state."""
    owner.log_status(
        "Force calibration complete: "
        f"X offset={state.calibration_offset['x']:.1f}, "
        f"Z offset={state.calibration_offset['z']:.1f}"
    )
    owner.log_status("Force sensors ready (calibrated to zero)")


def maybe_update_force_capture_status(owner, *, force_sample_count: int) -> None:
    """Refresh the shared ADC/force plot status label at a bounded interval."""
    if force_sample_count <= 0:
        return
    if force_sample_count % FORCE_STATUS_UPDATE_INTERVAL_SAMPLES != 0:
        return
    if not hasattr(owner, "plot_info_label"):
        return

    samples_per_sweep = max(0, int(getattr(owner, "samples_per_sweep", 0) or 0))
    total_samples = int(getattr(owner, "sweep_count", 0) or 0) * samples_per_sweep
    owner.plot_info_label.setText(
        f"ADC - Sweeps: {owner.sweep_count} | Samples: {total_samples}  |  "
        f"Force: {force_sample_count} samples"
    )


def schedule_force_plot_refresh(owner) -> None:
    """Debounce a force-only plot refresh when fresh force samples arrive."""
    try:
        if not owner.force_plot_timer.isActive():
            owner.force_plot_timer.start(owner.force_plot_debounce_ms)
    except Exception:
        pass
