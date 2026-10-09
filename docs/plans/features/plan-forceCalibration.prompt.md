## Plan: Force Calibration Tab

Add a dedicated Force Calibration tab that fits the existing mixin-based GUI architecture. The tab will let the user select a sensor family and sensor number, start/stop a measurement window while force sensors are connected, capture the peak force and sensor response values during that window, append a row to a calibration table, and save/load calibration files per sensor family. Loaded calibration data will feed both the display legends and the processing path that maps sensor readings to force.

For this first slice, keep the scope to the new tab and the calibration table creation/loading/saving workflow. The pressure-map, shear, and heatmap legend/value mapping will be a later use of this feature and should be treated as a future follow-up.

**Steps**
1. Define the calibration data model and ownership boundaries. Create a focused calibration state/helper that tracks the active measurement window, selected sensor family, selected sensor number, integration sample count, captured peak values, and persisted rows. Reuse the existing force runtime state for force-sensor connectivity and raw force sample access, but keep calibration history separate from zero-offset load-cell calibration. *Depends on the existing force connection/session lifecycle.*
2. Add a new GUI mixin for the Force Calibration tab. Implement widget construction in a new calibration panel mixin under gui/ that follows the same pattern as the Heatmap and Pressure Map panels: a top-level tab, a control group, a table widget/model, and file actions for save/load. The tab should include start/stop, sensor family, sensor number, integration samples, and save/load controls. Add the tab to the visualization tab strip in gui/display_panels.py and register the mixin in adc_gui.py and gui/__init__.py. *Depends on step 1.*
3. Gate measurement creation on force connection state. When the force sensors are disconnected, the tab must disable or reject starting a new calibration run and only allow loading an existing file. When connected, start/stop should toggle measurement capture, and the UI should clearly reflect whether a capture is active. Use the existing force connection state and button enable/disable patterns as the source of truth. *Parallel with step 4 once the tab exists.*
4. Hook the live capture path into the existing processing pipeline. While a calibration run is active, collect the current force X/Z peaks plus the selected sensor’s live response using the appropriate existing pipeline source: integrated PZT voltage for PZT, resistance extrema for PZR and Rosette. On stop, commit a single table row using the max force values observed during the window and the corresponding sensor extrema, then reset the active-measurement buffer. If the force sensors disconnect mid-run, cancel the capture and warn the user. *Depends on step 1 and the existing force/pressure-map/heatmap processing hooks.*
5. Add save/load persistence for calibration files. Store one file per sensor family, using the shared settings persistence helpers but a calibration-specific payload key and versioned metadata. The file should preserve the table rows plus metadata needed to reload safely, including sensor family, selected sensor number, integration samples, and timestamps. Loading should repopulate the table and update any in-memory calibration lookup used by the plots. *Depends on step 2.*
6. Add focused tests for the new slice. Cover tab creation and connection gating, capture start/stop behavior, row construction from sampled maxima, and save/load round-tripping for the calibration table. Mirror the repo’s existing GUI-test style and avoid broad end-to-end tests unless necessary. *Depends on steps 1-5.*

**Relevant files**
- `adc_gui.py` — wire the new mixin into the main window and initialize any shared calibration state.
- `gui/__init__.py` — export the new calibration panel mixin.
- `gui/display_panels.py` — add the Force Calibration tab to the visualization tab widget.
- `gui/control_panels.py` — reuse the existing force-connection controls and state conventions as the source of truth for when calibration is allowed.
- `gui/heatmap_panel.py` — reuse the persistence and per-sensor calibration UI patterns.
- `gui/signal_integration_panel.py` — reuse the pressure-map/shear settings, live-processing, and save/load patterns.
- `data_processing/force_state.py` — separate force connection/runtime state from the new calibration history state.
- `data_processing/force_processor.py` — integrate or expose the force sample capture needed for the measurement window.
- `data_processing/force_overlay.py` and `data_processing/pressure_map_generator.py` — future candidates for calibration-backed legend/value mapping.
- `file_operations/settings_persistence.py` — shared JSON save/load helper for calibration files.
- `constants/force.py` and `constants/ui.py` — add calibration defaults and the tab name if needed.
- `tests/` — add narrow tests for the new tab, persistence, and calibration capture behavior.

**Verification**
1. Run focused tests for the new tab and persistence slice with `PYTHONPATH=.` and pytest, starting from the closest existing GUI and force tests plus any new force-calibration tests.
2. Run the smallest affected test set for force connection and processing behavior to confirm that calibration gating does not break connect/disconnect or baseline reset.
3. If the feature touches shared state or serialization, run the targeted test file(s) for settings persistence and the new calibration-table helpers.
4. Manually verify the UI flow in the app: connected state allows start/stop capture, disconnected state blocks new calibration creation, save/load round-trips, and the table reflects one row per completed measurement.

**Decisions**
- Use separate calibration files per sensor family rather than one mixed file.
- Include metadata in the file payload so the table can be reloaded safely and future migrations are possible.
- Keep the first implementation limited to the tab UI and calibration table persistence; apply loaded calibration to display legends and runtime mapping later.
- Keep calibration capture disabled when no force sensors are connected; loading an existing file remains allowed.
- Keep the new logic in a dedicated mixin/helper instead of expanding adc_gui.py with business rules.

**Further Considerations**
1. Decide whether the calibration table should always show every column with N/A placeholders, or dynamically show the relevant response columns for the selected sensor family.
2. Decide whether switching sensor family while a capture is active should be blocked, or whether it should cancel the active measurement automatically.
3. Decide whether calibration files should be user-scoped defaults in addition to explicit save/load dialogs, similar to the existing heatmap and shear settings flows.
4. Define how the saved calibration table will later be consumed by pressure-map, shear, and heatmap legend/value mapping.