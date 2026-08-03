# Pressure Map Refactor Specification

## Continuity revision (2026-08)

`PressureFieldModel` is the authoritative signed backend.  It stores
thresholded C/L/R/T/B anchors, package mode, complete core triangles, inferred
peaks, decay settings, and shared `PressureMapGeometry`; both the local raster
and world-space array candidates call `model.evaluate(...)`.

Package classification is `all-inactive`, `isolated-outer`,
`center-plus-one-outer`, or `general-multi-sensor`.  General cores use a
complete two-triangle C/H/K and C/K/V split, or a complete four-triangle peak
fan.  Mixed signs are a signed-transition core, never a deleted quadrant or
sign-clamped field.  Axes are evaluated separately from their one-dimensional
sensor anchors, so their result is independent of quadrant order.

Outside the sensor square, the evaluator intersects a ray from the selected
field origin with the core and Outer-Boundary squares, copies the core value at
the first intersection, and applies exactly one compact smoothstep fade over
`min(natural_reach, available_boundary_distance)`.  A lone outer sensor keeps
its centre → sensor → near-outer peak lobe before that single fade.  The field
is zero on and outside Outer Boundary and can naturally reach zero earlier.

Array blending has no integer contributor-count branches.  Each package has a
Chebyshev support confidence of one through Mid Boundary and a smoothstep fade
to zero at Outer Boundary.  Direct/diagonal pair values are accumulated by the
product of their confidences; where no pair remains, the continuous
confidence-weighted candidate average is used.  Diagonal area weights blend
continuously into inverse-distance weights near singular corners.

Magnitude is `abs(signed_grid)` only in the widget.  Fixed magnitude levels
are `0..max_intensity`, signed levels are `-max_intensity..+max_intensity`, and
a separate smooth display-alpha fade never changes numeric data.  Images use
pixel-edge rectangles derived from coordinate centres and result `frame_id`
values invalidate image caches safely.

## Interpretation and geometry

The pressure map is an inferred relative-signal visualization. It is not calibrated pressure per unit area, and integrating pixel values is not expected to reproduce `NormalForceResult.total_force`.

`PressureMapGeometry` is the immutable geometry contract shared by single and array generation. Its defaults are sensor spacing 2.0 mm, package-center spacing 7.5 mm, Outer-Boundary reach 1.75 mm, near-outer offset 1.0 mm, and 10 pixels/mm. It derives a 3.5 mm facing-sensor gap, 3.75 mm Mid Boundary half-width, and 5.5 mm Outer Boundary half-width.

Each local field uses the fixed square support `[-outer_half_width, +outer_half_width]` on both axes. Its grid has `2 * ceil(outer_half_width * pixels_per_mm) + 1` pixels per side, so the centre and both Outer Boundary edges are exact grid coordinates. View padding for dashed overlays is rendering-only and never expands numerical support.

## Field construction

Activity uses `abs(value) >= signal_activity_threshold` in the calibrated signal domain. Active sensor anchors are reconstructed exactly. Single-axis lobes interpolate center -> inferred peak -> active outer sensor, then use radial compact-support decay. A lone active outer sensor interpolates from the measured sensor value to an outward inferred peak, whose signed height is bounded by `maximum_peak_gain`.

Peak-height extrapolation is controlled only by `peak_height_reference_distance_mm` and `peak_height_decay_rate`. Spatial reach is controlled separately by `natural_decay_reference_distance_mm`, `decay_amplitude_reference`, and minimum/maximum decay reach. The default amplitude reference of 1.0 is a named integrated-signal-domain starting point and must be calibrated against representative capture data.

Spatial fading uses one radial smoothstep compact-support factor from the relevant anchor/peak. Fields may become zero before the Outer Boundary and are always zero at or past it. There is no additional per-axis terminal fade.

## Array and rendering

Arrays reject duplicate IDs, duplicate grid cells, non-finite candidate data, and any package whose complete geometry differs from the shared geometry. World coordinates preserve exact support limits and use `pixels_per_mm`; result metadata records the actual `cell_size_x_mm` and `cell_size_y_mm` from those coordinate vectors. Direct, diagonal, and multi-package overlaps retain their weighted pair blending; `overlap_pairs` is the authoritative metadata name.

Magnitude and Signed are display-only modes. Magnitude renders `abs(grid)`; Signed uses a zero-centred diverging palette. Neither changes interpolation, mode selection, or decay. The fixed Max Intensity range is common across every visible package. Shear-arrow length is capped from Outer-Boundary half-width, not from the near-outer offset.

The independent visual overlays are the Near-Outer Circle, Outer-Boundary Square, and differently dashed Mid-Boundary Square. The circle diameter is twice `sensor_spacing_mm + near_outer_peak_offset_mm`.

## Settings migration

Old `decay_ref_distance_mm` loads as `natural_decay_reference_distance_mm`. Old `show_negative` loads as Signed or Magnitude display mode. Those legacy values are accepted on read but are no longer shown or written by the settings UI; the separate current shaping and display controls are persisted instead.
