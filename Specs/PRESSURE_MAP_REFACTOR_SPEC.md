# Pressure Map Refactor Specification

## Third-pass local-participation revision (2026-08)

Thresholded anchors also produce an `active_sensor_mask` (`C/L/R/T/B` bits).
This lightweight metadata prefilters array work: only direct or diagonal grid
neighbours are considered, and a pair is skipped when neither package has an
active centre or an outer anchor facing that overlap.  Final participation is
still determined per pixel by a Boolean `local_present` mask derived from the
already evaluated signed candidate (`abs(candidate) > epsilon`); no second
floating local-confidence field exists.

Pair weights are evaluated only in each pair's raster overlap slice.  A single
locally present candidate passes through unchanged, while two locally present
candidates use the existing direct linear or regularized diagonal geometric
weights.  Candidate fallback is weighted by support × package activity × local
presence.  These rules prevent a package from attenuating another package in a
region where its own field is zero and reduce regular-array pair work from
all-pairs to neighbouring overlaps.

Array results retain `pressure_grid` as the signed field and add
`magnitude_pressure_grid`.  The latter blends candidate magnitudes before
rendering, so equal opposite signed fields can cancel in Signed mode without
vanishing from Magnitude mode.  Single-package Magnitude rendering remains the
absolute signed candidate.

A center-active package with no active outer anchors uses the dedicated
`center-only` mode: `C * smoothstep_fade(hypot(x, y), sensor_spacing_mm)`.
It is rotationally symmetric, reaches zero exactly at every outer sensor, and
does not extend beyond that radius.  Natural reach maps exactly from minimum
at zero strength, through reference reach at one amplitude reference, to the
configured maximum at two references or above.  All signed and magnitude
outputs remain exactly zero on and beyond Outer Boundary support.

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

Outside the sensor square, each physical quadrant intersects a ray from its
own inferred peak or magnitude-weighted local anchor with the core and
Outer-Boundary squares.  The core value at the first intersection receives an
independent natural smoothstep fade, followed only by a final 20%-of-available
terminal boundary guard.  Natural reach is never rescaled to the square.
An explicit strict support mask makes every candidate exactly zero on and
outside an Outer Boundary; a lone outer sensor keeps its centre → sensor →
near-outer peak lobe before that decay.

Array blending has no integer contributor-count branches.  Each package has a
raw-signal activity confidence as well as a Chebyshev support confidence of one
through Mid Boundary and a smoothstep fade to zero at Outer Boundary.  Pair
geometry weights are activity-normalized, and pair aggregation is zero when
either participant is inactive; fallback uses support × activity weighting.
Thus zero packages cannot attenuate an active neighbour.  Diagonal area weights
blend continuously into inverse-distance weights near singular corners.

Magnitude is `abs(signed_grid)` only in the widget.  Fixed magnitude levels
are `0..max_intensity`, signed levels are `-max_intensity..+max_intensity`, and
a separate smooth display-alpha fade never changes numeric data.  Images use
pixel-edge rectangles derived from coordinate centres and result `frame_id`
values invalidate image caches safely.

## Interpretation and geometry

The pressure map is an inferred relative-signal visualization. It is not calibrated pressure per unit area, and integrating pixel values is not expected to reproduce `NormalForceResult.total_force`.

`PressureMapGeometry` is the immutable geometry contract shared by single and array generation. Its defaults are sensor spacing 2.0 mm, package-center spacing 7.5 mm, Outer-Boundary reach 1.75 mm, near-outer offset 1.0 mm, and 10 pixels/mm. It derives a 3.5 mm facing-sensor gap, 3.75 mm Mid Boundary half-width, and 5.5 mm Outer Boundary half-width.

Each local field uses the fixed square support `[-outer_half_width, +outer_half_width]` on both axes.  Raster coordinates use integer multiples of a micrometre-rounded geometry GCD; requested `pixels_per_mm` is a minimum density, and result metadata reports the aligned cell size and actual density.  The default 0.25 mm quantum turns a 3 px/mm request into 4 px/mm, placing centres and boundaries exactly on samples. View padding for dashed overlays is rendering-only and never expands numerical support.

## Field construction

Activity uses `abs(value) > max(signal_activity_threshold, PRESSURE_NUMERIC_EPSILON)` in the calibrated signal domain; exact and sub-threshold inputs are normalized to zero. Package participation uses a separate smooth raw-vector activity confidence. Active sensor anchors are reconstructed exactly. Single-axis lobes interpolate center -> inferred peak -> active outer sensor, then use radial compact-support decay. A lone active outer sensor uses one continuous circular radial lobe centered at the outward inferred peak, multiplied by a smooth axial gate; its radius is selected from natural reach, support, and the peak-gain cap while preserving the measured signed sensor anchor.

Peak-height extrapolation is controlled only by `peak_height_reference_distance_mm` and `peak_height_decay_rate`. Spatial reach is controlled separately by `natural_decay_reference_distance_mm`, `decay_amplitude_reference`, and minimum/maximum decay reach. The default amplitude reference of 1.0 is a named integrated-signal-domain starting point and must be calibrated against representative capture data.

Spatial fading uses one natural radial smoothstep factor from the relevant anchor/peak plus a separate terminal boundary guard. The post-peak portion of an isolated-outer response is a support-limited rounded lobe centered on the inferred peak, so equal world-space distances along and across the active axis receive the same decay. Fields may become zero before the Outer Boundary and are exactly zero at or past it.

## Array and rendering

Arrays reject duplicate IDs, duplicate grid cells, non-finite candidate data, and any package whose complete geometry differs from the shared geometry. World coordinates preserve exact support limits and use `pixels_per_mm`; result metadata records the actual `cell_size_x_mm` and `cell_size_y_mm` from those coordinate vectors. Direct, diagonal, and multi-package overlaps retain their weighted pair blending. `structural_pairs` records stable direct/diagonal grid adjacency and is the only pair set used to choose combined-array versus separate-package display. `active_overlap_pairs` records signal-dependent pairs that actually contributed to the current blend; `overlap_pairs` remains a compatibility alias for that active set and is calculation/diagnostic metadata only.

Magnitude and Signed are display-only modes. Single and separate-package Magnitude rendering uses `abs(grid)`; combined arrays use the separately blended `magnitude_pressure_grid`. Signed uses the signed field with a zero-centred diverging palette. Neither changes interpolation, mode selection, or decay. The fixed Max Intensity range is common across every visible package. Shear-arrow length is capped from Outer-Boundary half-width, not from the near-outer offset.

The widget caches a view-range signature made only from display structure, layout geometry, and mirror state. Live field values and frame IDs do not reset the range. Changing among single, separate-package, and combined-array modes, or changing geometry or mirror state, invalidates the signature and applies the new range once.

The independent visual overlays are the Near-Outer Circle, Outer-Boundary Square, and differently dashed Mid-Boundary Square. The circle diameter is twice `sensor_spacing_mm + near_outer_peak_offset_mm`.

## Settings migration

Old `decay_ref_distance_mm` loads as `natural_decay_reference_distance_mm`. Old `show_negative` loads as Signed or Magnitude display mode. Those legacy values are accepted on read but are no longer shown or written by the settings UI; the separate current shaping and display controls are persisted instead.
