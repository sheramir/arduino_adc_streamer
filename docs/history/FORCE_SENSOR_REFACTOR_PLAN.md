# Force Sensor Refactor Plan

This file is the handoff for future force-sensor refactoring work when hardware is available again.

It covers:
- what was already refactored around the force path
- what was intentionally left untouched
- what still needs to be changed
- the recommended order of work
- the hardware validation checklist

## Current Status

The codebase has already been cleaned up around the shared ADC/force visualization flow:

- force overlay plotting was extracted to [data_processing/force_overlay.py](C:/Code/arduino_adc_streamer/data_processing/force_overlay.py)
- clear-data and force-curve cleanup moved to [data_processing/capture_cache.py](C:/Code/arduino_adc_streamer/data_processing/capture_cache.py)
- capture lifecycle and total-sample status handling were cleaned up in:
  - [data_processing/capture_lifecycle.py](C:/Code/arduino_adc_streamer/data_processing/capture_lifecycle.py)
  - [data_processing/binary_processor.py](C:/Code/arduino_adc_streamer/data_processing/binary_processor.py)

What was intentionally not refactored yet:

- [serial_communication/force_serial.py](C:/Code/arduino_adc_streamer/serial_communication/force_serial.py)
- [serial_communication/serial_threads.py](C:/Code/arduino_adc_streamer/serial_communication/serial_threads.py) force thread path
- most GUI mutation inside the force connection flow
- force-specific connection state modeling
- force calibration/session state modeling
- hardware-backed tests for the real force sensor path

## Main Goal

Bring the force sensor path up to the same structural standard as the ADC path:

- transport/session logic should not directly own widget updates
- connection workflow should be separated from GUI mutation
- force state should be explicit instead of spread across raw instance attributes
- hardware behavior should be protected by targeted tests plus manual hardware validation

## Files To Focus On

Primary files:

- [serial_communication/force_serial.py](C:/Code/arduino_adc_streamer/serial_communication/force_serial.py)
- [serial_communication/serial_threads.py](C:/Code/arduino_adc_streamer/serial_communication/serial_threads.py)
- [data_processing/force_processor.py](C:/Code/arduino_adc_streamer/data_processing/force_processor.py)
- [data_processing/force_overlay.py](C:/Code/arduino_adc_streamer/data_processing/force_overlay.py)
- [adc_gui.py](C:/Code/arduino_adc_streamer/adc_gui.py)
- [config/config_handlers.py](C:/Code/arduino_adc_streamer/config/config_handlers.py)
- [file_operations/data_exporter.py](C:/Code/arduino_adc_streamer/file_operations/data_exporter.py)

Secondary files that may need small updates:

- [gui/control_panels.py](C:/Code/arduino_adc_streamer/gui/control_panels.py)
- [gui/display_panels.py](C:/Code/arduino_adc_streamer/gui/display_panels.py)
- [data_processing/capture_cache.py](C:/Code/arduino_adc_streamer/data_processing/capture_cache.py)
- [data_processing/capture_lifecycle.py](C:/Code/arduino_adc_streamer/data_processing/capture_lifecycle.py)

## Recommended Refactor Slices

### 1. Extract a force transport/session controller

Target:
- move serial-port ownership and thread wiring out of [force_serial.py](C:/Code/arduino_adc_streamer/serial_communication/force_serial.py)

Suggested new module:
- `serial_communication/force_session.py`

What it should own:
- open/close force serial port
- startup buffer clear
- thread creation and shutdown
- force reader signal hookups
- connection error propagation

What should stay in the GUI layer:
- button text
- port combo enable/disable
- user-facing log/status text
- whether force checkboxes should appear in the channel list

Why:
- this matches the ADC-side `adc_session.py` extraction
- it makes force transport testable without a live widget tree

### 2. Extract force connection workflow from GUI mutation

Target:
- split force connect/disconnect coordination from direct widget changes in [force_serial.py](C:/Code/arduino_adc_streamer/serial_communication/force_serial.py)

Suggested new module:
- `serial_communication/force_connection_workflow.py`

What it should own:
- connect sequence result
- disconnect sequence result
- warning aggregation during shutdown
- whether calibration should be started immediately after connect

Why:
- right now connection logic, calibration startup, logging, and widget mutation are mixed together
- this is the force-side equivalent of the ADC connection workflow extraction

### 3. Add explicit force connection state/view state helpers

Target:
- replace inline button/port-control mutations with helper-built state

Suggested new modules:
- `serial_communication/force_connection_state.py`
- optionally `serial_communication/force_view_state.py`

State to capture:
- disconnected
- connecting
- connected
- disconnecting
- error
- calibrating

Fields/UI affected:
- `force_connect_btn` text
- `force_port_combo` enabled state
- any future calibration indicator or status label

Why:
- current force UI state is implicit and fragile
- this reduces the chance of weird reconnect/disconnect edge cases

### 4. Separate force calibration/session state from raw GUI attributes

Target:
- replace force-related scattered attributes in [adc_gui.py](C:/Code/arduino_adc_streamer/adc_gui.py) with a small typed state object

Current scattered fields include:
- `force_data`
- `force_start_time`
- `force_calibration_offset`
- `force_calibrating`
- `calibration_samples`
- `_force_disconnect_in_progress`

Suggested new module:
- `data_processing/force_state.py` or `serial_communication/force_state.py`

Why:
- this makes calibration and capture behavior easier to reason about
- future force refactors become safer because the state shape is explicit

### 5. Split force data ingestion from force UI/status updates

Target:
- slim [data_processing/force_processor.py](C:/Code/arduino_adc_streamer/data_processing/force_processor.py)

Current responsibilities mixed there:
- calibration sample collection
- offset application
- capture-time force buffering
- runtime info-label updates
- debounce timer scheduling for overlay refresh

Suggested split:
- keep force sample/calibration logic in `force_processor.py`
- move runtime label update policy to a small helper if it stays shared with ADC state
- keep overlay rendering in [data_processing/force_overlay.py](C:/Code/arduino_adc_streamer/data_processing/force_overlay.py)

Why:
- processor code should mainly own force samples and calibration, not GUI behavior

### 6. Review force checkbox ownership in configuration UI

Target:
- [config/config_handlers.py](C:/Code/arduino_adc_streamer/config/config_handlers.py)

Current behavior:
- force checkbox creation/removal is tied into ADC channel-list update logic

Recommended change:
- consider separating force overlay checkbox management from ADC channel checkbox management
- at minimum, wrap the force checkbox add/remove logic in a small helper with one clear entry point

Why:
- it is currently coupled to ADC configuration refreshes
- this is easy to break during future config/UI work

### 7. Harden the force reader thread path

Target:
- [serial_communication/serial_threads.py](C:/Code/arduino_adc_streamer/serial_communication/serial_threads.py)

Current force reader limitations:
- assumes every valid line is simple `x,z`
- silently skips parse failures
- no explicit malformed-line counters or bounded debug visibility

Recommended improvements:
- keep silent skip behavior for noisy lines if needed, but add optional bounded debug counters
- centralize CSV parsing in a helper function
- add tests for malformed input and partial lines

Why:
- easier diagnosis when hardware output changes
- safer future protocol tweaks

### 8. Revisit force export alignment logic

Target:
- [file_operations/data_exporter.py](C:/Code/arduino_adc_streamer/file_operations/data_exporter.py)

Current risk:
- export currently aligns force data to ADC samples by nearest timestamp search over a dictionary-like structure

Recommended follow-up:
- verify export alignment behavior with real hardware timing
- if needed, replace the current nearest-search loop with a more explicit interpolation or nearest-index strategy

Why:
- this is one of the most likely places for "looks okay in UI, wrong in exported file" bugs

## Recommended Order

Best order when hardware is available:

1. Extract `force_session.py`
2. Extract `force_connection_workflow.py`
3. Add force connection/view-state helpers
4. Add typed force state object
5. Slim `force_processor.py`
6. Separate force checkbox UI ownership
7. Harden `ForceReaderThread`
8. Verify and improve export alignment

This order keeps transport and state boundaries first, then cleans up UI coupling and export behavior afterward.

## Tests To Add

Unit/integration tests to add during the refactor:

- `tests/test_force_session.py`
  - open/close behavior
  - thread start/stop orchestration
  - reader-error handoff

- `tests/test_force_connection_workflow.py`
  - successful connect result
  - disconnect result with warnings
  - calibration-start decision

- `tests/test_force_connection_state.py`
  - button text and combo enabled-state snapshots

- `tests/test_force_processor.py`
  - calibration offset computation
  - force sample buffering during capture
  - no buffering when not capturing

- `tests/test_force_reader_thread_parser.py`
  - valid CSV line
  - malformed line
  - extra-field line
  - empty line

- `tests/test_force_export_alignment.py`
  - exported rows include correct nearest force sample behavior

## Manual Hardware Validation Checklist

Run these once the real force sensor is connected:

### Connection and calibration

- connect force sensor from a clean app start
- confirm calibration starts automatically
- confirm calibration completes and logs sensible offsets
- disconnect and reconnect force sensor without restarting app

### Independent behavior

- connect only force sensor, without ADC capture running
- verify no crashes, freezes, or log spam
- ensure connect/disconnect button and port combo states remain correct

### Combined ADC + force behavior

- connect ADC and force sensor together
- configure ADC and start capture
- confirm force overlay appears and updates during capture
- stop capture and verify final status counts remain sensible
- clear data and verify force curves are removed
- start a second capture and confirm force overlay still works

### Full view and export

- capture ADC + force data
- open full view
- confirm non-force behavior remains correct
- export data and confirm force columns align plausibly with ADC timing

### Error handling

- unplug force sensor during runtime if safe to do so
- confirm disconnect path cleans up without hanging the app
- reconnect after forced error and verify recovery

## Important Constraints For Future Agent Work

- do not mix ADC serial-port ownership with force serial-port ownership
- do not rewrite the force transport and ADC transport together in one step
- do not remove current force behavior without hardware validation in the same round
- preserve GUI responsiveness during connect/disconnect/calibration
- keep each refactor slice small and testable, the same way the ADC path was handled

## Suggested Prompt To Reuse Later

When force hardware is available, a good starting prompt is:

`Use docs/history/FORCE_SENSOR_REFACTOR_PLAN.md as the force-sensor roadmap. Start with slice 1 only, explain exactly what you will change, implement it, let me test with hardware, then continue slice by slice. Do not mix ADC and force serial paths.`
