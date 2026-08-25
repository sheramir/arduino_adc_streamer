Implement a display-only pressure-map masking feature for the multi-package array view.

Locked requirements

1. Masking applies only to:
   PressureMapWidget.update_array_display(...)
   PressureMapWidget._update_array_image(...)

   Do not apply masking to the single-package update_display(...) path.

2. Masking is display-only.

   It must not modify:
   - PressureMapArrayResult.pressure_grid
   - normal-force calculations
   - shear calculations
   - package readouts
   - exported or saved pressure data

   Apply the crop through the rendered RGBA alpha channel, following the same principle as the existing display-floor alpha fade.

3. Outside the selected polygon, the pressure image must be fully transparent. The existing black pressure-map scene background will therefore appear black.

4. Display a solid, single-color polygon outline around the mask.

5. Support bundled masks and user-imported masks. Follow the architecture and persistence conventions used by:
   config/sensor_config.py:SensorConfigStore
   sensors_library/
   ~/.adc_streamer/sensors/

Files to add

A. data_processing/pressure_map_mask.py

Add a frozen PressureMapMaskGeometry dataclass with:

- name: str
- points_mm: tuple[tuple[float, float], ...]

The polygon is implicitly closed from the last point back to the first.

Validation must:

- Require a non-empty name.
- Require at least three unique points.
- Require finite numeric x/y coordinates.
- Reject consecutive duplicate points.
- Accept an optional duplicate closing point equal to the first point and normalize it away.
- Reject zero or near-zero polygon area.
- Store normalized immutable tuples.

Add:

mask_inside_grid(
    points_mm,
    x_grid_mm,
    y_grid_mm
) -> np.ndarray[bool]

Requirements:

- Pure NumPy; add no new dependency.
- Use vectorized even/odd ray casting.
- Loop over polygon edges while vectorizing over the grid.
- Avoid allocating a pixels-by-edges three-dimensional array.
- Validate that x_grid_mm and y_grid_mm have matching shapes.
- Treat points on polygon edges as inside.
- Return a boolean array matching the grid shape.

Add a small cache helper, or implement an equivalent widget-local cache. Do not allow an unbounded global cache. The cache key must distinguish:

- polygon points
- grid shape
- x/y bounds
- grid spacing or equivalent resolution information

Changing pressure-map pixels-per-mm must invalidate the cached mask.

B. config/pressure_map_mask_config.py

Mirror the relevant SensorConfigStore behavior.

Provide MaskConfigStore with:

- Bundled library:
  sensors_library/masks/mask_name.json

- User library:
  Path.home() / ".adc_streamer" / "masks" / "mask_library.json"

- load()
- save(...)
- import_file(path) -> str

The standalone import schema is:

{
  "name": "Mask name",
  "points_mm": [[x_mm, y_mm], ...]
}

The bundled library may use a configurations/list structure matching the sensor-library convention, but standalone files must use the simple schema above.

Import requirements:

- Validate using PressureMapMaskGeometry.
- Persist imported masks in the user library.
- Return the final imported mask name.
- Follow SensorConfigStore’s duplicate-name convention where applicable.
- Never silently replace a bundled mask.
- Use atomic or otherwise safe persistence consistent with the existing config code.
- Preserve deterministic ordering.
- Handle malformed or missing user-library files safely without losing bundled masks.

C. sensors_library/masks/Plus5_mask.json

a JSON file was created in the masks library.

The current file uses these polygon points, in order:

(-3.75, 11.25)
( 3.75, 11.25)
( 3.75,  5.50)
( 5.50,  3.75)
(11.25,  3.75)
(11.25, -3.75)
( 5.50, -3.75)
( 3.75, -5.50)
( 3.75,-11.25)
(-3.75,-11.25)
(-3.75, -5.50)
(-5.50, -3.75)
(-11.25,-3.75)
(-11.25, 3.75)
(-5.50,  3.75)
(-3.75,  5.50)

Do not repeat the first point at the end in the bundled normalized representation.

Plus5_mask was derived from the following sensor array geometry:

- Sensor spacing = 2.0 mm
- Package-center spacing = 7.5 mm
- Outer-boundary reach = 1.75 mm
- Mid-boundary half-width:
  2.0 + 1.75 = 3.75 mm
- Diagonal junction coordinate:
  7.5 - 2.0 = 5.5 mm
- Outward arm extent:
  7.5 + 3.75 = 11.25 mm

The provided near-outer peak offset of 1.0 mm belongs to the pressure-profile geometry but does not alter this polygon because the requested mask follows the displayed mid-boundary and its intersections with the outer boundary.

D. constants/pressure_map.py

Add constants equivalent to:

- DEFAULT_PRESSURE_MASK_ENABLED = False
- DEFAULT_PRESSURE_MASK_NAME = "None"
- DEFAULT_PRESSURE_MASK_COLOR = "#FFD600"
- PRESSURE_MASK_OUTLINE_WIDTH_PX
- A mask-outline z value, if the current z-value structure requires one

Choose an outline width visually consistent with the screenshot and existing overlay pens.

The mask pen must be cosmetic so its width remains constant in screen pixels.

E. gui/pressure_map_widget.py

Add widget state for:

- mask_enabled
- mask_points_mm
- mask_color
- mask_outline_item
- cached mask-grid data

Add:

configure_mask(
    *,
    mask_enabled=None,
    mask_points_mm=None,
    mask_color=None
) -> None

Follow the exact pattern of existing configure_* methods:

- Normalize incoming values.
- Return immediately when nothing changed.
- Clear the boolean-mask cache when polygon geometry changes.
- Restyle the outline when color changes.
- Call _refresh_cached_display() after a meaningful change.

Modify _rgba_image(...) so it can receive an optional boolean visibility mask.

Requirements:

- Preserve all existing color mapping and display-floor behavior.
- Combine the polygon mask with the existing alpha, rather than replacing the existing alpha behavior.
- Outside-mask alpha must be zero.
- Inside-mask alpha must remain whatever the current display-floor logic calculates.
- Validate mask/image shape compatibility.
- Do not mutate the supplied pressure grid.

Modify _update_array_image(...):

- Build the pressure grid exactly as before.
- Compute or retrieve the mask over array_result.x_grid_mm and array_result.y_grid_mm.
- When self.mirror is true, flip the boolean mask with np.fliplr, matching the pressure-grid flip.
- Pass the visibility mask to _rgba_image(...).
- Do not alter array_result or pressure_grid in place.

Add _update_mask_outline(array_result), or an equivalent focused helper.

Outline requirements:

- Reuse one QGraphicsPolygonItem rather than creating one every frame.
- Construct a QPolygonF from mask_points_mm.
- When mirrored, transform each point with x = -x.
- Use no brush/fill.
- Use a solid cosmetic QPen.
- Use DEFAULT_PRESSURE_MASK_COLOR unless configured otherwise.
- Place it above the image and ordinary boundary rectangles/ellipses, but below sensor markers, labels, arrows, and readouts.
- Show it only when:
  mask_enabled is true,
  valid mask points exist,
  and the multi-package array display is active.

Call outline updating from the array-display path after the array geometry is available.

Update all relevant cleanup or mode-switching paths so the outline is hidden when:

- the display is cleared
- packages are empty
- masking is disabled
- no mask is selected
- the widget switches to single-package display

Do not crop package markers, sensor circles, labels, arrows, boundary items, or readout text.

F. gui/signal_integration_panel.py

Create MaskConfigStore once during panel initialization and retain:

- the store
- loaded mask objects
- a name-to-mask lookup

Add a QGroupBox titled "Pressure Map Mask" to the Settings tab.

Controls:

- QCheckBox: Enable mask
- QComboBox: mask selector
- QPushButton: Import Mask...

Populate the selector with:

1. "None"
2. Bundled masks
3. User masks

Use the store’s deterministic order and avoid duplicate displayed names.

Add on_pressure_mask_settings_changed(), or equivalent.

It must:

- Read the checkbox and selected name.
- Resolve the selected geometry.
- Pass enabled state and points to pressure_map_widget.configure_mask(...).
- Preserve the selected name while masking is disabled.
- Treat "None" or a missing name as no geometry.
- Refresh through the same mechanism used by other pressure-map settings.

Import-button behavior:

- Open a JSON file dialog.
- Call MaskConfigStore.import_file(...).
- Show an existing-style error dialog for validation or I/O failure.
- Reload the mask library.
- Refresh the combo box without duplicate signal handling.
- Select the imported mask.
- Apply it immediately.
- Do not automatically enable masking unless that is consistent with existing import workflows; preserve the current checkbox state.

Extend save_shear_settings_to_path / load_shear_settings_from_path:

settings["pressure_map"]["mask_enabled"]
settings["pressure_map"]["mask_name"]

Loading requirements:

- Missing legacy keys use the new defaults.
- Populate the mask library before resolving mask_name.
- If the stored mask no longer exists, select "None" and disable the effective crop safely.
- Avoid multiple unnecessary redraws while restoring controls.
- Apply the final state once after loading.

Do not add a mask-color control in this implementation. Keep color as a constant/configurable widget property.

G. Tests

Add focused tests, including new test files where appropriate:

tests/test_pressure_map_mask.py
- valid polygon normalization
- repeated closing point normalization
- invalid number of points
- non-finite coordinates
- zero-area polygon
- known inside/outside points
- points on horizontal, vertical, and diagonal edges count as inside
- output shape and dtype

tests/test_pressure_map_mask_config.py
- bundled library load
- user and bundled merge
- standalone import
- malformed import rejection
- duplicate-name behavior
- bundled mask cannot be silently overwritten
- Plus5 coordinates load exactly

tests/test_pressure_map_widget.py
- alpha is zero outside the mask
- alpha remains unchanged inside except for existing display-floor behavior
- pressure_grid input is unchanged
- mask cache is reused for identical geometry/grid
- cache invalidates after grid resolution changes
- mirror flips the mask consistently with the image
- outline x coordinates mirror correctly
- outline uses no fill
- outline is hidden in single-package mode and cleanup paths
- mask disabled produces the original image

tests/test_signal_integration_panel.py
- mask controls populate correctly
- imported mask becomes selectable
- enable/name settings round trip
- legacy payload defaults to disabled/None
- missing saved mask falls back safely
- settings restoration applies only the final intended configuration

Acceptance criteria

1. With Plus5 selected and masking enabled, the rendered pressure signal is visible only inside the cross-shaped polygon and the rest of the pressure image is black.

2. A solid yellow outline matches the polygon shown in the supplied reference image.

3. Disabling masking immediately restores the full pressure heatmap.

4. The feature has no effect on any force, shear, pressure-grid, or readout values.

5. Single-package pressure-map rendering remains unchanged.

6. Mirroring keeps the crop and outline aligned with the mirrored pressure image.

7. Changing pressure-map resolution recalculates the boolean mask once, not once per frame.

8. Existing pressure-map settings and legacy settings files continue to work.

9. Run the complete test suite and report any unrelated pre-existing failures separately.