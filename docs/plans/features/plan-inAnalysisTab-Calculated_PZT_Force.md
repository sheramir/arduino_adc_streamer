# Analysis Tab – Calculated PZT Force Feature Specification

**Owner:** Host Application (GUI / Data Processing)

**Version:** 1.0

**Date:** 6/29/2026

---

## 1. Purpose

Extend the Analysis tab with the ability to reconstruct the applied force on each piezoelectric (PZT) sensor from the measured voltage waveform.

The reconstructed force is calculated offline from the captured PZT voltage data and displayed as an additional synchronized graph.

This feature is completely read-only and does not affect firmware, acquisition, or stored raw data.

---

## 2. Background

The Analysis tab may already display a measured force signal acquired from an external force sensor (load cell).

This feature adds a second force source:

- **Measured Force**
  - Acquired directly from the force sensor.

- **Calculated PZT Force**
  - Reconstructed from each PZT voltage signal using the piezoelectric model.

The two force sources are independent and may be displayed simultaneously for comparison and validation.

---

## 3. User Interface

### Analysis Tab

Add a new toggle:

```text
Calculate PZT Force
```

When disabled:

- No calculated force is displayed.
- No force calculation is performed.

When enabled:

- The force reconstruction pipeline is executed.
- Calculated force traces become available.
- The Force graph is updated.

The Analysis tab shall use nested sub-tabs:

- **Display**
  - Source controls
  - display toggles
  - channel visibility
  - force-trace visibility
  - voltage and force graphs
- **Settings**
  - PZT Force Settings
  - Analysis export controls

The Display sub-tab shall be scrollable so control lists and plots can exceed the visible window height without compressing the Force graph.

---

### Force Graph

The existing Force graph shall become a combined graph capable of displaying:

- Measured Force (if available)
- Calculated Force - PZT 1
- Calculated Force - PZT 2
- ...
- Calculated Force - PZT N

Each trace shall have:

- independent visibility toggle
- legend entry
- unique color

The graph shares:

- X-axis
- zoom
- pan
- marker
- cursor

with the voltage graphs.

The Force graph shall be large enough for comparison workflows and may occupy roughly the same vertical priority as the voltage graph.

---

## 4. Analysis Settings

Add a new **PZT Force Settings** section inside the Analysis Settings tab.

The following settings are persistent.

| Setting | Symbol | Units | Description |
|----------|---------|-------|-------------|
| PZT Capacitance | Cpzt | pF / nF / F | Sensor capacitance |
| Effective Leak Resistance | Rleak | Ω | Effective leakage resistance |
| Piezoelectric Constant | d33 | pC/N | Charge generated per Newton |
| Fallback Noise Threshold | NoiseThreshold | V | Threshold used when no per-channel estimate exists |
| Quiet Window | QuietDuration | s | Initial window assumed to contain only noise |
| Noise Multiplier | k | unitless | Display scale used to report a threshold-equivalent sigma |

The application shall internally convert values to SI units.

Settings are stored in the Analysis settings JSON and persist across application restarts.

Default values:

```text
Cpzt = 150 pF
Rleak = 1000000 ohm
d33 = 600 pC/N
NoiseThreshold = 0.01 V
QuietDuration = 2 s
k = 5
```

The settings UI shall provide a **Calculate Vmid + Noise** action. When pressed,
the application estimates and displays per-channel values:

- Vmid [V]
- MAD [V]
- robust sigma [V]
- noise threshold [V]
- quiet-window sample count

These per-channel values shall be used by calculated force when present.

---

### 4.1 Channel Display Rules

When Analysis operates on in-memory data, channel labels and sample columns shall be taken from the same runtime display-channel specifications used by the Time Series graph.

If runtime display specs are available:

- only labeled/displayed PZT channels shall appear in the Analysis channel checklist
- raw unlabeled buffer columns shall not be shown as fallback `ColN` channels
- calculated force traces shall be generated only for visible labeled voltage channels

If runtime display specs are unavailable, Analysis may fall back to generated labels such as `CH1` or `Col0`.

---

## 5. Parameters Extracted Automatically

The following values are obtained directly from the loaded capture and are not user configurable.

- timestamps
- sampling interval per PZT channel
- Vmid, preferably from per-channel quiet-window calibration
- per-channel noise threshold, preferably from quiet-window percentile deviation
- channel list
- visible channels
- filter settings
- x-axis mode

For multiplexed captures, the sampling interval shall be computed between consecutive samples of the same PZT channel.

---

## 6. Force Reconstruction

For every PZT channel:

Preferred Vmid and noise threshold estimation:

```python
Vquiet = first QuietDuration seconds of the channel voltage
Vmid = median(Vquiet)
MAD = median(|Vquiet - Vmid|)
sigma_robust = 1.4826 * MAD
NoiseThreshold = percentile(|Vquiet - Vmid|, 95)
sigma_display = NoiseThreshold / k
```

MAD and robust sigma are diagnostic values. The force threshold shall use the
same percentile-deviation method for every channel. This handles ADC-quantized
quiet windows where visually similar traces can otherwise get very different
thresholds because one channel has `MAD = 0` and another has nonzero MAD.

If no per-channel estimate exists, the user-configured fallback threshold is
used and the force calculator may fall back to a full-trace median Vmid.

Measured voltage:

```python
v[n] = Vpzt[n] - Vmid
```

Noise thresholding:

```python
if |v[n]| < NoiseThreshold:
    v[n] = 0
```

Voltage samples below the noise threshold shall not contribute to integrated calculated force.

Leakage time constant:

```text
τ = Rleak × Cpzt
```

Per-sample interval:

```text
dt = t[n] - t[n-1]
```

Leakage factor:

```text
α = exp(-dt / τ)
```

Generated charge:

```text
ΔQ = Cpzt × (v[n] - α × v[n-1])
```

Generated force increment:

```text
ΔF = ΔQ / d33
```

Integrated force:

```text
F[n] = F[n-1] + ΔF
```

Expanded equation:

```text
F[n] = F[n-1]
      + (Cpzt / d33)
      × (v[n] - α × v[n-1])
```

Default:

```text
d33 = 600 pC/N
```

---

### 6.1 Implementation Ownership

PZT force reconstruction shall be reusable outside the Analysis tab:

- numeric defaults and supported units live in `constants/pzt_force.py`
- voltage-to-force calculation helpers live in `data_processing/pzt_force_calculation.py`
- quiet-window Vmid/noise estimation for one voltage trace lives in `data_processing/pzt_force_calculation.py`
- `data_processing/analysis_workbench.py` only adapts Analysis snapshots into calculated-force traces

The calculation module shall not depend on Analysis tab data structures or GUI widgets.

---

## 7. Automatic Force Zeroing

Because piezoelectric sensors cannot accurately measure static force indefinitely, small integration drift is expected.

To prevent long-term drift, the application performs automatic force zeroing.

### Event Detection

Detect a signal event whenever

```text
v > NoiseThreshold
```

or

```text
v < -NoiseThreshold
```

Record the event polarity.

---

### Opposite Polarity Detection

Detect when

Positive → Negative

or

Negative → Positive

occurs.

---

### Zero Condition

When:

- opposite-polarity pair detected
- absolute voltage falls below the noise threshold

```text
|v| < NoiseThreshold
```

then

```text
Force = 0
```

Reset:

- force accumulator
- event polarity state

This zeroing is performed independently for every PZT channel.

---

## 8. Compute Pipeline

The processing order shall be:

1. Load capture
2. Apply optional filtering
3. Calculate PZT force
4. Apply automatic zeroing
5. Calculate derived Analysis signals
    - Shear
    - Normal Pressure
    - Integration
6. Update graphs
7. Update marker values

Force calculation shall use the filtered voltage signal whenever filtering is enabled.

---

## 9. Plot Behaviour

The Analysis tab shall contain synchronized stacked plots:

### Voltage Graph

Displays:

- PZT voltages
- only labeled runtime-display channels when available

### Integrated Graph

Displays:

- one independently integrated trace for each visible voltage channel
- the same color for each integrated trace as its source raw voltage trace
- continuous line traces

### Force Graph

Displays:

- Measured Force (optional)
- Calculated PZT Force(s)

Both graphs shall share:

- X-axis
- zoom
- pan
- marker
- cursor

### Shear / Normal Graph

Displays:

- Shear Left/Right [V]
- Shear Top/Bottom [V]
- Normal Pressure [V]

Shear and normal pressure require position-aware R/L/C/T/B channels. Integration does not require positional channel mapping and is calculated per visible channel independently.

All Analysis plots shall share:

- X-axis
- zoom
- pan
- marker
- cursor

Hiding a PZT voltage channel shall also hide its integrated trace and calculated force trace.

---

## 10. Export

### Image Export

The Display sub-tab shall provide Analysis image export controls. The user can choose any combination of:

- Raw signals
- Integrated signals
- Shear / Normal
- Force

Selected plots are saved as PNG images. When more than one plot is selected, the exported filenames shall include plot-specific suffixes.

### Data Export

When exporting Analysis results to CSV, the exported file shall include both the original captured data and any enabled derived calculations.

The export shall contain, where available:

#### Original Signals

- Timestamp
- Sample Index
- PZT Voltages
- Measured Force
- Other acquired channels

#### Derived Signals

- Calculated PZT Force [N]
- Shear Left/Right [V]
- Shear Top/Bottom [V]
- Normal Pressure [V]
- Integration [V]

Derived columns shall be appended after the original captured data.

Column names shall clearly identify:

- signal type
- channel
- units

Example:

```text
Timestamp_ms

PZT1_V
PZT2_V
...

MeasuredForce_N

PZT1_ForceCalc_N
PZT2_ForceCalc_N
...

ShearLR_V
ShearTB_V

NormalPressure_V

Integration_V
```

The exported CSV shall contain the exact data currently displayed in the Analysis tab after all enabled calculations have been applied.

---

## 11. Caching

Calculated force traces shall be cached using:

- capture fingerprint
- Cpzt
- Rleak
- d33
- NoiseThreshold
- per-channel Vmid/noise calibration
- filter settings
- timestamps

Changing any parameter invalidates the cached force traces.

---

## 12. Error Handling

Force calculation shall not execute when:

- Cpzt ≤ 0
- Rleak ≤ 0
- d33 ≤ 0
- timestamps are invalid
- voltage data is missing
- requested quiet window has no usable voltage samples

The application shall display an informative warning while leaving the remainder of the Analysis tab operational.

---

## 13. Acceptance Criteria

- User can enable or disable calculated PZT force.
- PZT force settings live in the Analysis Settings sub-tab.
- The Analysis Display sub-tab is scrollable.
- In-memory Analysis hides unlabeled raw buffer columns when runtime display specs are available.
- Force graph supports measured force and calculated force simultaneously.
- One calculated force trace is produced for every PZT channel.
- Force graph is synchronized with the voltage graphs.
- Integration graph is separate from raw voltage data and uses source-channel colors.
- Shear and normal pressure share a separate derived graph.
- User can save selected Analysis plots as PNG images.
- Force settings persist across application restarts.
- User can calculate and view per-channel Vmid/noise estimates from the initial quiet window.
- Calculated force uses per-channel Vmid/noise estimates when available.
- Automatic zeroing removes integration drift after complete bipolar events.
- Voltage below the configured noise threshold does not contribute to calculated-force integration.
- CSV export contains all enabled derived calculations.
- Original acquired data remains unchanged.
- Analysis remains offline and read-only.
