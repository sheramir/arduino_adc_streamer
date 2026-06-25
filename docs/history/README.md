# history

Historical milestone notes and forward-looking handoff/roadmap documents. These record what was done at a point in time or what remains to be done later; they are not current architecture references (see `docs/architecture/` for that).

## Files

- `ARRAY_CONFIG_STEP1_COMPLETION.md` — completion report for Step 1 of array sensor configuration: implemented the array-layout GUI editor in the Sensor tab (3x4 matrix input, MUX configuration table, channels-per-sensor control), validation functions in `sensor_config.py`, and dual-mode (channel_layout vs array_layout) persistence. Lists planned Step 2 (acquisition integration) and Step 3 (display integration) as next steps. Note: the array grid described here is 3x4, while the current `docs/user/ARRAY_CONFIGURATION_GUIDE.md` describes a 3x3 grid — reflects how the feature evolved after this step.
- `FORCE_SENSOR_REFACTOR_PLAN.md` — handoff/roadmap for future force-sensor refactoring work to be done once hardware is available again. Covers what was already refactored (force overlay, capture cache/lifecycle cleanup), what was intentionally left untouched (force serial transport, connection state modeling), a recommended 8-slice refactor order, tests to add, and a manual hardware validation checklist.

## Subfolders

- `refactoring_log/` — phase-by-phase completion reports from the original mixin-based modularization of `adc_gui.py`, plus a few related update/optimization summaries. See `refactoring_log/README.md`.
