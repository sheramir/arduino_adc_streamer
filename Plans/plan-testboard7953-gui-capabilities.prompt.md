## Plan: TestBoard_7953 GUI Capabilities and Two-Array Display

Status: IMPLEMENTED - automated validation passed; hardware acceptance pending.
Date: 2026-10-02
Workspace: `C:/Code/arduino_adc_streamer/`

Maintenance note (2026-10-02): the subsequent
[board-registry refactor](plan-boardRegistry-jsonProfiles-refactor.prompt.md)
supersedes this plan's Python-owned wiring/defaults and read-only electrical editor.
Board values now live in `config/boards/profiles/testboard_7953.json`; wiring lives
in sensor JSON. Existing acquisition/display behavior is preserved.

Update the Python GUI to recognize the active `Arduino_Sketches/TestBoard_7953`
firmware and expose the controls appropriate to this PZT-only board. Support
sampling array 1, array 2, or both with one common PZT selection. Each signal
visualization shows one array at a time; a shared Display Array selector changes
the visible array during acquisition without restarting the scan.

Extend the sensor library with a TestBoard configuration describing two similar
arrays, their spatial layout, and their physical ADC associations. Preserve the
existing behavior of MG24, Teensy, 555, and PCB1.x Array boards.

Implementation completed on 2026-10-02 following the user's authorization.
The sections below preserve the agreed requirements and implementation approach.

**Implementation and validation record**

- Added canonical/alias detection, PZT-only ADC and acquisition controls, fixed
  Vmid/manual constraints, settling-repeat semantics and status verification.
- Added the bundled two-array sensor configuration using the Array_PCB1.7 grid,
  schema migration, fixed electrical-map validation and editor preservation.
- Added immutable acquisition descriptors and shared runtime array switching,
  retaining complete buffers and array-qualified processing/calibration identity.
- Updated archive/CSV export/reload and independent Analysis array selection,
  including package-specific shear/normal overlays and captured voltage scaling.
- Guarded delayed Spectrum results after a display switch; added scrolling to
  keep acquisition controls readable on smaller windows.
- Full automated suite: `.\.venv\Scripts\python.exe -m pytest tests -q`:
  **871 passed, 34 subtests passed**. New TestBoard suite contains 53 cases,
  including physical route sentinels, status completeness, sparse/full routes,
  5 V export/reload after disconnect, view switching and calibration identity.
- Reviewed the rendered GUI at small-window size with readable acquisition fields.
  Documentation updated in the array guide and GUI/config READMEs.
- Physical ADS7953 connection timing is unavailable from the current firmware.
  Decay tab supports array-qualified voltage preview and gates physical decay
  characterization; Analysis automatic physical connection timing reports
  unavailable rather than using MG24 or emitted-sample timing.
- Firmware was not changed. Hardware acceptance in verification item 8 remains
  pending, including >RAM archive capture and requested-versus-measured SPI clock.


**Current behavior and gaps**

- `config/mcu_profile.py`, `config/testboard_scan.py`, and
  `config/testboard_7953_board.py` recognize `PCB_TestBoard_7953`, whereas active
  firmware returns `# TestBoard_7953`. Unify detection before extending controls.
- Existing TestBoard helpers already provide fixed PZT wiring, sparse
  `(ADC, input)` routing, three payload orders, and physical-array selection.
  Extend those helpers rather than creating another board integration path.
- The current TestBoard profile hides the entire ADC Configuration section and
  both repeat/buffer controls. The visible scan-order control defaults to
  `interleaved`; voltage-reference/SPI-clock/sequencing controls are missing.
- The service skips TestBoard reference configuration and assigns `vdd` to array
  boards. Voltage helpers do not recognize 2.5/5 V. The update must configure and
  propagate the actual ADS7953 input span into displays and calculations.
- Time Series currently builds traces for both arrays. Pressure Map chooses the
  first selected physical lane. Neither implements the requested common runtime
  display selection.
- The sensor library has one layout/map per configuration and no array-count or
  physical-array metadata. TestBoard electrical routing currently bypasses the
  editable `mux_mapping` in favor of the fixed board profile.
- Firmware already supports all required commands. `channelrepeat` performs
  settling conversions and retains only the last result; it does not expand the
  payload. One binary frame contains one complete sweep.

**Required GUI behavior**

| Area | TestBoard behavior |
| --- | --- |
| Board detection | Recognize `TestBoard_7953` from `mcu`; accept historical `PCB_TestBoard_7953` as a compatibility alias |
| Operating mode | PZT only; hide mode selection, PZR inputs, and PZR/555/RS controls |
| ADC Configuration | Show only Voltage Reference and SPI CLK |
| Voltage Reference | Choices 2.5 V and 5 V; accepted initial default 2.5 V, matching firmware |
| SPI CLK | Display MHz; default 20 MHz; accepted firmware range 0.1-30 MHz; send integer Hz |
| OSR / Gain | Hidden and excluded from TestBoard command generation and verification |
| Acquisition arrays | Choose 1, 2, or both; accepted default both |
| PZT selection | One PZT-number input; require at least one populated PZT; no channel-number input |
| Both-array sampling | Apply exactly the same selected PZT numbers to both arrays |
| Vmid | Label `Use Vmid Sample`; boolean toggle only; accepted default false; no pin-number widget |
| Repeat Count | Integer 1-3, default 1; maps to `channelrepeat`, with one retained sample per route |
| Sweeps per block | Hidden; internal frame/sweep setting fixed to 1 |
| Sequence | `manual` / `auto1`, accepted default manual; selectable only when Vmid sampling is false |
| Vmid enabled | Set sequence to manual and disable its selector; turning Vmid off enables the selector but leaves manual selected |
| Auto-1 repeat | Effective repeat is 1; disable repeat editing and show 1 while Auto-1 is active; preserve the requested manual repeat for return to manual |
| Scan order | Default `adc`; no editable GUI control; `interleaved`, `array`, and `adc` remain available through the Python board configuration variables |
| Display Array | One shared left-panel selector; both sampled means 1/2 choices and initial default 1; one sampled means show/lock to that array |
| Runtime changes | Display Array remains enabled during capture; acquisition-setting changes require stopping and reconfiguration |

Use a short repeat tooltip explaining that only the final conversion is kept.
Use a sequence tooltip to explain Auto-1's effective repeat of 1. Vmid sampling
is an optional discarded conversion, not an additional visible signal. Mandatory
firmware Vmid parking remains active even when the toggle is false.

**Steps**

1. **Unify board detection and model capabilities/defaults.**

   Use one TestBoard identity helper for canonical and historical MCU names in
   profiles, connection handling, routing, processing, and archive recognition.
   Keep the reported identifier in capture metadata; resolve both to the same
   capabilities. Avoid relying on a generic `Array*` or `Teensy*` prefix.

   Extend the typed configuration, snapshot, request, last-sent, and status models
   with TestBoard SPI clock in Hz, requested manual channel repeat, sequence,
   Vmid sampling, and array selection. Keep the legacy `repeat` field at 1 for
   TestBoard payload interpretation. Model display-array selection separately
   from device configuration so a view change cannot mark the board unconfigured.

   Put board-specific configurable defaults/limits in
   `config/testboard_7953_board.py`, including a documented
   `TESTBOARD_DEFAULT_SCAN_ORDER = "adc"`. This is the variables configuration
   file for changing scan order; do not invent another settings file just for it.
   Load and validate that value when building a TestBoard acquisition request.
   Reject invalid scan-order values rather than silently reverting to interleaved.
   Persisted view/acquisition values must not override the config-file scan order.

   Split profile/view-state flags that currently combine repeat and buffer
   visibility. Add separate flags for SPI clock, sequence, Vmid toggle/pin,
   reference choices, repeat limits, and Display Array. Restore ordinary controls,
   labels, ranges, and defaults when another board is connected. Keep `adc_gui.py`
   limited to initialization and orchestration. *Foundation for steps 2-5.*

2. **Extend the sensor schema and add the TestBoard configuration.**

   Add `array_count`, defaulting to 1 for old entries, and an `arrays` mapping
   keyed by physical array number. For this board, both arrays share the existing
   top-level `array_layout`, `channel_sensor_map`, and pair-local `mux_mapping`.
   Each array entry supplies its physical ADC pair. This records the two-array
   association without duplicating identical layouts or renumbering PZTs.

   Planned complete TestBoard entry using the confirmed Array_PCB1.7 spatial grid:

   ```json
   {
     "name": "TestBoard_7953",
     "type": "array_layout",
     "board_profile": "TestBoard_7953",
     "reverse_polarity": false,
     "channel_sensor_map": ["B", "L", "C", "R", "T"],
     "array_count": 2,
     "arrays": {
       "1": {"adc_lanes": [1, 2]},
       "2": {"adc_lanes": [3, 4]}
     },
     "array_layout": {
       "cells": [
         [null, "PZT7", null],
         ["PZT1", "PZT6", "PZT5"],
         [null, "PZT3", null]
       ]
     },
     "mux_mapping": {
       "PZT6": {"mux": 1, "channels": [0, 1, 2, 3, 4]},
       "PZT7": {"mux": 1, "channels": [5, 6, 7, 8, 9]},
       "PZT1": {"mux": 2, "channels": [0, 1, 2, 3, 4]},
       "PZT3": {"mux": 2, "channels": [5, 6, 7, 8, 9]},
       "PZT5": {"mux": 2, "channels": [10, 11, 12, 13, 14]}
     },
     "channel_layout": {"channels_per_sensor": 5}
   }
   ```

   `mux` remains the compatible serialized field for pair-local ADC position
   1/2; show `ADC` terminology for this board in the Sensor tab. Resolve physical
   lanes through `arrays[array_id].adc_lanes[mux - 1]`: PZT6 on array 1 uses
   ADC1, and PZT6 on array 2 uses ADC3. PZT1 uses ADC2/ADC4. Never treat `mux: 2`
   as a globally absolute ADC2 when displaying array 2.

   Normalize/save/clone/edit the new fields without dropping them. Validate array
   count and IDs, ADC associations, complete five-channel groups, duplicate
   physical routes, and reserved input 15. Keep existing single-array entries
   working without the new fields. Update the schema version and support loading
   version-1 libraries. Preserve user overrides, selected names, and deleted-name
   behavior when merging the bundled and user libraries.

   Keep `config/testboard_7953_board.py` as the fixed electrical wiring reference.
   Validate the TestBoard JSON wiring against it before creating routes; reject
   a mismatch instead of allowing an edited spatial layout to silently change
   board wiring. Use the validated configuration's array associations/layout for
   routing and view grouping. Show fixed TestBoard wiring read-only in the editor;
   maintain editable spatial placement and the existing polarity option.

   Select the compatible TestBoard library entry on detection, restoring the
   previous non-TestBoard choice when returning to another board. Do not silently
   use Array_PCB1.7 wiring when a compatible TestBoard entry is unavailable.
   The user confirmed that the board uses the same sensor arrays as Array_PCB1.7.
   Reuse its spatial grid for both arrays and preserve its channel-position and
   polarity settings. Physical ADC assignments remain TestBoard-specific as shown
   above. *Depends on step 1.*

3. **Implement the board-specific control panel and configuration workflow.**

   Adapt existing panel construction and MCU view-state application to the behavior
   table. Restore the ADC Configuration section for TestBoard, with only its two
   relevant controls. Convert MHz to integer Hz explicitly and validate restored
   values as well as widget input. Keep Vmid/sequence constraints in a shared
   normalization helper used by GUI events, snapshots, and loaded settings.

   Extend `ADCConfigurationService` with an explicit TestBoard configuration
   branch. While stopped, send and acknowledge the following settings using the
   existing command/session infrastructure:

   ```text
   mode PZT*
   ref 2.5*                       # or ref 5*
   spiclock 20000000*              # validated Hz from the MHz control
   array both*                    # or array 1* / array 2*
   scanorder adc*                 # from the board configuration variables
   adcchannels <ADC:input,...>*    # routes from arrays plus common PZT selection
   channelrepeat 1*               # requested manual repeat, 1..3
   vmid false*                    # boolean only
   adcseq manual*                 # or auto1 only when Vmid sampling is false
   status*
   ```

   The exact independent command ordering may follow firmware requirements;
   configure array gating before its routes and normalize Vmid/sequence before
   sending. Explicit PZT configuration recovers from a pre-existing firmware mode
   without presenting a GUI choice. Do not send generic `repeat`, `buffer`,
   `channels`, OSR, gain, conversion/sampling-speed, rate, or 555 tuning commands
   in this branch.

   Extend status parsing to handle actual `# key=value` output, including
   `adcchannels` values that contain colons. Parse `vref`, `spi_clock_hz`, `array`,
   `scanorder`, `adcseq`, requested/effective repeat, requested/effective Vmid,
   fixed Vmid channel, route count, and engine. Normalize `5.0` to the same span
   as `5`. Verify firmware-reported board fields and route order/membership instead
   of synthesizing success from the request. A bare `#OK` is not an echoed value.
   Abort configuration on failure or mismatch and leave Start unavailable; do not
   replace absent status with values that falsely claim verification.

   Keep SPI engine outside the requested GUI scope. Read its actual status for
   metadata; no new engine selector or automatic performance-engine change is
   required. Keep the existing binary header/trailer and run/stop behavior:
   successful `run` transitions directly to binary data without a text ACK.

   Add 2.5/5 V handling wherever reference values feed conversion or calibration.
   Treat these values as the board's selectable full-scale input spans and use the
   ADS7953 12-bit count range, preserving other boards' scaling. Distinguish
   requested SPI clock from measured wire clock in metadata. *Depends on steps
   1-2.*

4. **Separate acquired routes from the currently visible array.**

   Build one canonical acquisition descriptor from the successfully configured
   routes. It owns every `(array_id, sensor_id, ADC, input, placement,
   payload_index)` association and remains unchanged for the capture. Route
   ordering must match firmware for all three config-file scan orders, including
   sparse selections and nonascending PZT input order.

   For N distinct selected five-channel PZTs, expect `5 * N` words per sweep for
   one array and `10 * N` for both. Full population is 25/50 words. Repeat 2/3,
   Auto-1 sequencing, and optional Vmid conversions do not change these counts.
   Neither ADC input number alone nor PZT number alone is a globally unique key.

   Split the current display-spec helper into complete acquisition specs and a
   view projection filtered by `display_array_id`. Export, archive metadata,
   sample-rate calculation, and filter input must use complete acquisition specs.
   Rendering and visible channel/package selectors use the projection, preserving
   absolute payload indices. Apply the same identity model to package groups used
   by heatmap and pressure-map processing; remove the first-lane shortcut.

   Retain both arrays in raw/processed buffers, filtering, archive/cache, and
   baseline/noise processing. Key stateful calculations by array and sensor/route:
   baselines, Vmid/noise estimates, integration, calculated force, ghost-removal
   calibration, decay, peak/point tracking, and shear histories must not share
   state between identically named PZTs. Check algorithm assumptions that were
   valid for MG24 multiplexing before applying them to ADS7953; use board-specific
   route/timing metadata, and mark unavailable physical timing as unavailable
   rather than using unrelated MG24 defaults.

   Process required continuous state for both acquired arrays so display switching
   can immediately show valid history. Keep expensive rendering limited to the
   chosen array. Shared force-sensor time alignment remains capture-wide, while
   sensor-response calculations/calibration targets include array identity.
   *Depends on steps 1-3; foundation for step 5.*

5. **Add the common Display Array selector and refresh every applicable view.**

   Put `Display Array` in the common left panel. Enable choices 1 and 2 when both
   arrays are sampled; for single-array captures force the sampled array and
   disable the other choice. Initialize new both-array sessions to array 1.
   Keep this control enabled when the acquisition controls are disabled.

   Changing it only updates view state: send no serial commands, do not rerun
   Configure/Start/Stop, do not change sweep width, and do not clear captured data
   or processing history. Refresh Time Series, Spectrum, Heatmap, Pressure Map,
   PZT decay, and sensor-response/calibration displays that use the live source.
   PZR/Rosette-only signal views remain unavailable for TestBoard. Keep the Sensor
   library editor's array metadata distinct from the runtime display choice.

   Rebuild visible channel/package checkboxes and legends from the selected-array
   specs, retaining meaningful selection choices per array and stable local sensor
   colors. Identify the current array in plot titles/labels. Invalidate rendered
   curves, spectrum caches, and spatial overlays on a switch; retain calculation
   state keyed by array. Guard asynchronous result application so work for the
   previous array cannot overwrite the current view.

   For stopped/full-view data, use the captured descriptor's available arrays
   rather than whichever board/settings are currently connected. Offline Analysis
   uses its own source descriptor and must offer the same one-array view through
   a source-aware selector when that source contains both arrays. Keep the shared
   control correct for the active source and avoid allowing live display changes
   to rewrite an offline source snapshot. *Depends on step 4.*

6. **Preserve identities through settings, capture, export, and reload.**

   Reuse shared JSON persistence helpers for any persisted TestBoard acquisition
   defaults and sensor-library fields; do not persist duplicate state in widgets.
   Store requested manual repeat separately from effective repeat. Keep display
   selection as view state; this plan uses a fresh-session default of array 1
   rather than a persisted last-view choice.

   Record an immutable capture descriptor in the existing archive header and CSV
   metadata: MCU identity, board/config name and version, array count, sampled
   arrays, PZT selections, ordered routes/payload indices, layout/channel labels,
   reference span/ADC resolution, requested clock, reported engine, sequence,
   requested/effective repeat, Vmid flags/fixed channel, and scan order. Record a
   display choice only as optional view metadata, not acquisition membership.

   CSV exports include all captured arrays regardless of the display selector;
   use unambiguous labels such as `A1_PZT6_B` and `A2_PZT6_B`. Plot-image exports
   show the current array and identify it in their labels/metadata. Archive reload
   and Analysis CSV loading rebuild mappings from the saved descriptor instead of
   current widgets, MCU identity, or an edited library. Preserve legacy archive
   loading; if old TestBoard data lacks sufficient route identity, report the
   limitation instead of guessing an array association. *Depends on steps 4-5.*

7. **Add focused regressions and update documentation.**

   Add synthetic board frames/status transcripts with distinct values on every
   route, including repeated input/PZT numbers across arrays. Test the behavior
   matrix below. Extend the existing focused suites before introducing any new
   end-to-end harness. Update GUI/config docs and the array guide to remove the
   obsolete hidden-repeat and first-array-only descriptions. Explain the new
   schema, fixed ADC wiring, PZT selection, config-file scan order, and live view
   switching. *Depends on steps 1-6.*

**Relevant files**

All paths are relative to `C:/Code/arduino_adc_streamer/`.

| File or folder | Planned role |
| --- | --- |
| `config/testboard_7953_board.py`, `config/testboard_scan.py` | Unified identity, board defaults/limits, fixed wiring validation, ordered array-aware routes |
| `config/mcu_profile.py`, `config/mcu_state.py`, `config/mcu_view_state.py`, `config/mcu_detector.py` | Board capabilities, control visibility/ranges, connection-specific defaults |
| `config/adc_config_state.py`, `config/config_snapshot.py`, `config/config_handlers.py` | Typed settings, invariant normalization, request building, acquisition/view spec separation |
| `config/adc_configuration_service.py`, `config/adc_configuration_runner.py`, `config/config_view_state.py` | Board-specific command application, verification, failure/start gating |
| `config/sensor_config.py`, `constants/sensor_config.py`, `sensors_library/sensor_configurations.json` | Schema extension/migration, bundled TestBoard two-array entry, library merge/save |
| `gui/control_panels.py`, `gui/sensor_panel.py` | Requested controls, common Display Array, sensor schema/editor preservation and ADC terminology |
| `serial_communication/adc_connection_workflow.py`, `serial_communication/adc_connection_state.py`, `serial_communication/adc_serial.py`, `serial_communication/adc_session.py`, `serial_communication/serial_parser.py` | MCU aliases, typed reported settings, command ACK/status handling |
| `serial_communication/serial_threads.py`, `data_processing/binary_processor.py`, `data_processing/capture_lifecycle.py` | Existing frame parsing, fixed sweep width, complete buffers and capture descriptors |
| `gui/display_panels.py`, `gui/spectrum_panel.py`, `data_processing/adc_plotting.py`, `data_processing/spectrum_processor.py` | One-array traces, visible selectors, spectrum refresh, correct voltage scaling |
| `gui/heatmap_panel.py`, `gui/signal_integration_panel.py`, `gui/pzt_decay_panel.py`, `gui/force_calibration_panel.py` | Array-aware spatial/derived views, state keys, calibration target identity |
| `data_processing/signal_integration_processor.py`, `data_processing/heatmap_piezo_processor.py`, `data_processing/pressure_map_array_generator.py`, `data_processing/pressure_force_display.py` | Array-specific package input/history and selected-array output |
| `data_processing/processing_stack.py`, `data_processing/filter_processor.py`, `data_processing/pzt_ghost_removal.py`, `data_processing/pzt_force_calculation.py`, `data_processing/pzt_decay.py`, `data_processing/adc_mux_timing.py` | Audit complete-route inputs, array-separated state, board-specific scaling/timing assumptions |
| `gui/analysis_panel.py`, `data_processing/analysis_workbench.py` | Source-aware offline array selection and recorded mappings |
| `file_operations/settings_persistence.py`, `file_operations/export_metadata.py`, `file_operations/data_exporter.py`, `file_operations/archive_loader.py`, `data_processing/archive_writer.py` | Settings reuse, immutable descriptors, both-array exports/reload |
| `adc_gui.py`, `gui/__init__.py`, `constants/ui.py`, `constants/serial.py` | Thin composition, any focused helper/mixin wiring, shared labels and legacy defaults |
| `Arduino_Sketches/TestBoard_7953/include/ConfigurableParameters.h`, `src/Firmware.cpp`, `src/PztController.cpp`, `README.md` | Read-only protocol/wiring references; no firmware modification required |
| `README.md`, `config/README.md`, `gui/README.md`, `docs/user/ARRAY_CONFIGURATION_GUIDE.md` | Updated capabilities, routing/schema, use and compatibility documentation |
| `tests/` | Extend existing focused suites and add a narrow TestBoard GUI/display-state suite if needed |

**Verification**

These checks belong to the later implementation task; they have not been run as
part of writing this plan.

1. **Detection and UI:** Both MCU names activate identical capabilities. TestBoard
   shows exactly the requested controls, default values and limits. Test
   disconnect/reconnect and transitions to Array_PCB1.7/MG24/Teensy/555 so hidden
   controls and board-specific ranges do not leak into other profiles.
2. **Configuration:** Test reference 2.5/5, SPI boundary values and MHz/Hz
   conversion, repeat 1/2/3, boolean Vmid, sequence transitions, bare ACKs, actual
   `key=value` status, `5.0` normalization, reconfiguration after failure, and
   reported mismatches. Verify no generic repeat/buffer/no-op ADC commands are
   emitted. Confirm display switching sends no commands.
3. **Sensor library:** Test two-array JSON normalization/save/clone/editor
   round-trip, version-1 single-array migration, user/bundled merge, malformed
   counts/ADC associations, missing or unsupported PZTs, fixed wiring mismatches,
   reserved channel 15, and B/L/C/R/T assignment on ADC1-4.
4. **Payload mapping:** Parameterize array 1/2/both, scan order adc/array/interleaved,
   sparse PZT selection, user PZT order, manual repeats, and Auto-1. Assert every
   retained sample maps to the correct physical array/PZT/position and count
   stays 5N/10N. Include full 25/50-word frames and malformed count handling.
5. **Runtime displays:** Feed distinct signals to the same PZT numbers on arrays
   1/2, switch repeatedly during capture, and verify every applicable tab follows
   the common selection. Assert unchanged capture/session/counters, both-array
   buffers, array-specific baseline/integration/ghost/force histories, and rejection
   of stale asynchronous render results. For array-2-only capture, display is 2.
6. **Scaling and persistence:** Check ADC counts at zero/full scale under both
   spans, baseline conversion and derived processing units. Export after showing
   either array and verify identical complete signal columns and descriptor.
   Reload archive and CSV into Analysis after disconnecting/changing the sensor
   library, and switch views without changing mapping or timestamps. Preserve
   legacy file behavior and force timestamp alignment.
7. **Focused automated runs:** Start with the relevant existing suites in
   `tests/test_mcu_profile.py`, `test_mcu_detector.py`, `test_mcu_view_state.py`,
   `test_adc_config_state.py`, `test_config_snapshot.py`,
   `test_adc_configuration_service.py`, `test_adc_connection_workflow.py`,
   `test_serial_parser.py`, `test_testboard_7953_board.py`,
   `test_testboard_scan.py`, `test_sensor_config.py`, and `test_sensor_panel.py`.
   For the display/data slice add `test_display_panels.py`, `test_adc_plotting.py`,
   `test_spectrum_processor.py`, `test_spectrum_panel.py`,
   `test_signal_integration_processor.py`, `test_signal_integration_panel.py`,
   `test_pressure_map_array_generator.py`, `test_heatmap_thresholds.py`,
   `test_pzt_decay.py`, `test_force_calibration_panel.py`,
   `test_sample_rate_consistency.py`, `test_data_exporter.py`,
   `test_archive_io.py`, `test_analysis_workbench.py`, and
   `test_analysis_panel.py` as touched. Use the targeted-test selector on actual
   changed Python files, then add missing TestBoard/compatibility cases. Run with
   the repo interpreter, for example:

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests/test_testboard_7953_board.py tests/test_testboard_scan.py tests/test_adc_configuration_service.py tests/test_sensor_config.py -q
   ```

8. **Hardware/manual acceptance:** Connect current TestBoard firmware; verify the
   reported name, status and configuration, acquire individual arrays and both,
   press the same PZT independently on each array, and switch every signal view
   during a continuous scan. Exercise Vmid/manual and Vmid-off/Auto-1, repeats
   1-3 in manual, both spans, single-array lock, stop/reconfigure, disconnect, and
   a capture larger than RAM followed by export/reload. Confirm no returned-channel
   errors or missing/corrupted frames. Requested clocks above 20 MHz are already
   documented in firmware as experimental; retain that context in the clock
   tooltip/docs and record requested Hz. Measure actual SCLK if clock accuracy is
   being validated. Hardware behavior remains unverified until these checks run.

**Decisions**

- The user accepted the suggested defaults: 2.5 V span, 20 MHz SPI clock, Vmid
  false, manual sequence, manual repeat 1, both arrays sampled, scan order `adc`,
  and display array 1 for a new both-array session.
- Both physical arrays use the same sensor arrays and spatial grid as
  Array_PCB1.7, as confirmed by the user. Reuse that grid and its sensor-position
  and polarity settings while applying the TestBoard ADC routing.
- Extend existing TestBoard support; canonical MCU name is `TestBoard_7953`, with
  the historical name retained as an alias.
- One shared live Display Array selector keeps tabs synchronized. Selecting a
  display array is independent of selecting which arrays are acquired.
- Preserve all sampled arrays in processing/capture/export; project one array for
  rendering. Use array-qualified identities throughout state and file metadata.
- Requested manual repeat uses `channelrepeat`; TestBoard payload repeat stays 1.
  Auto-1 displays effective repeat 1 and retains the requested manual value.
- Vmid true forces manual. Vmid false permits either sequence and never disables
  mandatory firmware parking. There is no GUI pin-number input.
- Shared array layout plus per-array ADC pairs describes the two similar arrays.
  Validate TestBoard electrical maps against fixed board wiring. Do not copy the
  different Array_PCB1.7 MUX assignments into the new entry.
- Scan order defaults to `adc` and is editable only in the board configuration
  variables. Firmware engines and binary protocol changes are outside this GUI
  update.
- Use existing configuration/session/processing/persistence boundaries. Introduce
  focused helpers where needed, keeping business rules out of `adc_gui.py`.

**Further Considerations**

1. Different per-array PZT selections and independent spatial layouts are outside
   this request. Keep array identities explicit so later extensions need not
   change capture identity or wire decoding.
2. New captures must be self-describing. Historical TestBoard files may lack the
   routes needed for reliable reload; do not rewrite or guess their contents.
