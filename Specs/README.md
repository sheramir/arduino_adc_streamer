# Specs

Planning and specification documents for upcoming features. These are prompt-style implementation plans (steps, relevant files, decisions, open questions) written before code changes, not narrative documentation of existing behavior.

## Files

- `plan-forceCalibration.prompt.md` — implementation plan for a new Force Calibration tab: lets the user select a sensor family/number, capture peak force and sensor response during a measurement window, build a calibration table, and save/load calibration files per sensor family. Scopes the first slice to the tab UI and calibration-table persistence, deferring pressure-map/shear/heatmap legend integration to a future follow-up. Lists affected files, verification steps, decisions made, and open questions.
