---
name: gui-feature-slice
description: Add or modify PyQt GUI features in the arduino_adc_streamer repo while preserving its mixin-based architecture. Use when changing tabs, controls, widgets, labels, persisted settings, live visualization behavior, or GUI-triggered workflows that span adc_gui.py, gui/, config/, data_processing/, file_operations/, and serial_communication/.
---

# GUI Feature Slice

Add GUI work as a narrow vertical slice instead of letting `adc_gui.py` turn back into a grab-bag.

## Start Here

Read these first:

- `adc_gui.py`
- `gui/__init__.py`
- `README.md`
- [references/gui-surface-map.md](references/gui-surface-map.md)

If the feature touches sensors or arrays, also read:

- `docs/user/ARRAY_CONFIGURATION_GUIDE.md`

## Workflow

1. Start from the visible behavior.
   Name the exact user-facing change: new control, modified panel behavior, new tab logic, saved setting, or display/output change.

2. Place code by responsibility.
   Use these boundaries:
   - widget construction and signal wiring: `gui/`
   - app composition and timer orchestration: `adc_gui.py`
   - transport/session/connect-disconnect behavior: `serial_communication/`
   - calculation, filtering, plotting data prep: `data_processing/`
   - config modeling and mapping: `config/`
   - persistence and export: `file_operations/`
   - numeric names and defaults: `constants/`

3. Keep `adc_gui.py` thin.
   It can coordinate mixins, timers, and top-level state initialization. It should not absorb new business rules that belong in a processor, workflow, state helper, or persistence module.

4. Follow the active panel path.
   Find the current mixin or widget first, then make the smallest supporting changes below it. Avoid adding new parallel pathways unless the feature truly introduces a new subsystem.

5. Preserve settings behavior deliberately.
   If the UI change should survive restart, update the existing save/load path rather than inventing a one-off file.

6. Verify both the visible behavior and the underlying state path.
   In this repo, many GUI changes are really state, routing, or processing changes with a widget attached.

## Common Routes

- Time-series changes often touch `gui/display_panels.py`, `data_processing/adc_plotting.py`, and plotting constants.
- Spectrum changes usually involve `gui/spectrum_panel.py`, `data_processing/spectrum_processor.py`, and saved settings.
- Sensor tab changes usually involve `gui/sensor_panel.py`, `config/sensor_config.py`, and channel mapping helpers.
- Pressure-map changes usually involve `gui/signal_integration_panel.py`, `gui/pressure_map_widget.py`, `data_processing/signal_integration_processor.py`, and `data_processing/pressure_map_generator.py`.
- Force-overlay changes often cross `gui/display_panels.py`, `data_processing/force_overlay.py`, `data_processing/force_processor.py`, and force connection state/workflow files.

## Guardrails

- Do not add new UI state in multiple places when a typed state/helper already exists.
- Do not couple widget mutation directly into transport/session code unless the repo already requires it and the task is only a minimal fix.
- Do not put persistence logic in widget construction code.
- Do not forget tests when a “GUI-only” change actually changes processing, routing, or export behavior.

## Verification

Run the smallest relevant tests for the touched slice. Common starting points:

- `tests/test_signal_integration_panel.py`
- `tests/test_pressure_map_widget.py`
- `tests/test_adc_plotting.py`
- `tests/test_settings_persistence.py`
- `tests/test_sensor_config.py`
- `tests/test_force_channel_checkboxes.py`

Use `$targeted-test-selector` for tighter selection from the actual changed files.
