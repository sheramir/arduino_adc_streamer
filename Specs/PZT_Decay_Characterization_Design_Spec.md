# PZT_Decay_Calc
## Detailed Design and Implementation Specification

**Target:** Existing desktop data-acquisition application for `Array_PZT_PZR1.x` / MG24 dual-MUX hardware  
**Feature name:** **PZT_Decay_Calc**  
**Primary purpose:** Measure PZT voltage decay, estimate decay coefficients and time constants, and optionally estimate PZT capacitance from known leakage resistance and the exact acquisition timing model.

---

## 1. Overview

Add a new application tab named **PZT_Decay_Calc**.

The tab guides the user through a controlled voltage-decay experiment for one selected PZT signal:

1. The user selects a logical PZT signal, such as `PZT1_C`.
2. The application resolves and displays the physical hardware location:
   - MUX number.
   - MUX address/channel.
   - Physical MUX pin where the excitation voltage must be applied.
   - ADC input order, `CH1` or `CH2`.
3. The application measures the channel baseline and calculates `Vmid` using a robust median.
4. The application displays the required excitation voltage:

   ```text
   Vtarget = Vmid + 1.000 V
   ```

5. The user applies the displayed voltage to the indicated hardware input.
6. The application continuously plots the selected signal and verifies that the input is within tolerance of `Vtarget` and stable.
7. Once the target voltage is stable, the application arms the measurement and starts retaining a pre-release plateau.
8. The user removes the applied voltage while applying no mechanical force.
9. The application detects the release and records the complete decay toward `Vmid`.
10. The application fits the decay using samples in a configurable normalized range, defaulting to approximately two-thirds through one-third of the original signal amplitude.
11. The application reports:
    - Per-sample decay coefficient.
    - Wall-clock decay constant.
    - Connected-time decay constant under the selected electrical model.
    - Optional estimated capacitance.
    - The calculated decay function overlaid on the measured samples.
    - Regression fit error reported as RMSE and R².
    - Fit quality and validity warnings.
12. The user can save:
    - Sample-level CSV data.
    - A JSON result and metadata file.
    - An optional one-row summary CSV.

While this workflow is active, normal application capture must not run.

---

## 2. Goals

The implementation must:

- Provide a guided and repeatable decay-measurement workflow.
- Stop normal signal capture before starting the characterization.
- Use the existing logical-signal-to-MUX mapping rather than duplicate it.
- Calculate `Vmid` from measured baseline data.
- Tell the user the exact target voltage to apply.
- Detect target acquisition, voltage removal, and final decay automatically.
- Record actual sample timestamps and voltage values.
- use the existing `AdcMuxTiming` calculator for:
  - Total sensor-connected time.
  - Channel-specific pre-sample decay time.
  - Channel-specific post-sample connected time.
- Distinguish measured wall-clock timing from calculated connected leakage timing.
- Fit the exponential decay in a stable region.
- Expose enough information to estimate PZT capacitance when the required resistance assumptions are supplied.
- Persist results in human-readable CSV and JSON files.
- Keep full internal floating-point precision and round only display/export presentation values where appropriate.
- Be cancellable at every stage and leave the acquisition hardware in a safe state.

---

## 3. Non-goals for the Initial Version

The initial implementation does not need to:

- Characterize several PZT channels simultaneously.
- Automatically apply or remove the excitation voltage.
- Independently estimate both connected and disconnected leakage constants from one run.
- Automatically identify every parasitic resistance in the hardware.
- Restart normal acquisition automatically after completion.
- Modify the MCU firmware unless the existing command set cannot support the required dedicated capture mode.
- Estimate capacitance without a user-supplied or configured resistance assumption.
- Treat the applied 1 V as mathematically exact; the application must use measured plateau voltage.

Future extensions may add batch characterization, multiple timing schedules, automated switching, and simultaneous estimation of connected and disconnected leakage.

---

## 4. Important Physical Model

### 4.1 Voltage relative to baseline

All decay analysis must use voltage relative to the measured midpoint:

```text
x[n] = V[n] - Vmid
```

Do not fit the raw ADC voltage directly.

The target excitation is:

```text
Vtarget = Vmid + 1.000 V
```

The actual initial decay amplitude must be measured from the stable plateau:

```text
A0 = Vplateau - Vmid
```

Use the measured `A0`, not exactly `1.000 V`, in the fit.

### 4.2 Effective sample time

The effective ADC sample is the center of the IADC observation window.

For the current dual-MUX calculator, the selected signal maps to one of:

- Physical ADC input 1 / first scan-table entry / `CH1`.
- Physical ADC input 2 / second scan-table entry / `CH2`.

The timing object provides:

```python
timing.sensor_connected_s
timing.t_decay_before_effective_sample_ch1_s
timing.t_decay_before_effective_sample_ch2_s
timing.t_connected_after_effective_sample_ch1_s
timing.t_connected_after_effective_sample_ch2_s
```

The characterization feature must select the correct channel-specific timing from the existing hardware mapping.

### 4.3 Sample-to-sample connected and disconnected intervals

For one retained sample per sweep, the interval from effective sample `n-1` to effective sample `n` contains:

```text
post-sample connected time of sample n-1
+ disconnected time
+ pre-sample connected time of sample n
```

For a steady schedule on the same physical ADC input:

```text
post_sample_connected + pre_sample_connected
= total sensor-connected time per selection
```

Therefore, for each sample interval:

```python
connected_decay_dt_s = timing.sensor_connected_s
wall_dt_s = sample_timestamp_s[n] - sample_timestamp_s[n - 1]
disconnected_decay_dt_s = max(0.0, wall_dt_s - connected_decay_dt_s)
```

The dummy-ground phase and all other channel selections are part of the selected sensor’s disconnected interval.

### 4.4 General two-path decay model

The general sample-to-sample decay coefficient is:

```text
alpha_total
= exp(
    -connected_decay_dt / tau_on
    -disconnected_decay_dt / tau_off
  )
```

where:

```text
tau_on  = connected-state decay time constant
tau_off = disconnected-state decay time constant
```

A single run with an approximately constant duty cycle cannot independently identify both `tau_on` and `tau_off`.

The application must never claim that both were independently measured from one run.

### 4.5 Initial supported estimation model

The initial capacitance-estimation mode may use this explicit assumption:

```text
Disconnected leakage is negligible compared with connected leakage.
```

Under that assumption:

```text
alpha_sample = exp(-connected_decay_dt / tau_on)
```

and:

```text
tau_on = -connected_decay_dt / ln(alpha_sample)
```

If a known connected leakage resistance is provided:

```text
tau_on = Ron_equivalent * Cpzt
```

then:

```text
Cpzt = tau_on / Ron_equivalent
```

The UI and exported result must label this as an estimate based on the configured resistance and negligible-disconnected-leakage assumption.

### 4.6 Wall-clock decay result

Independently of the electrical assumptions, the application must also report the directly measured wall-clock decay:

```text
x(t) = A * exp(-t / tau_wall)
```

`tau_wall` is useful as an empirical system-level result but must not be used directly to calculate capacitance when the sensor is only connected to the leakage path for a fraction of the wall-clock interval.

---

## 5. Suggested Application Architecture

Implement the feature as a dedicated module rather than embedding all logic in the tab widget.

Suggested components:

```text
PztDecayCharacterizationTab
    GUI and user interaction.

PztDecayMeasurementController
    Owns the state machine, acquisition lock, timers, and transitions.

PztDecayAcquisitionSession
    Starts and stops the dedicated capture and receives sample blocks.

PztDecayAnalyzer
    Baseline, target detection, release detection, decay fitting,
    coefficient calculation, capacitance estimation, and quality metrics.

PztDecayTimingContext
    Resolves wall-clock, connected, disconnected, pre-sample, and
    post-sample timing values.

PztDecayResult
    Immutable or clearly structured result object.

PztDecayExporter
    Writes samples CSV, result JSON, and optional summary CSV.
```

Use existing services for:

- MCU communication.
- Acquisition ownership.
- Channel configuration.
- Channel-to-MUX mapping.
- ADC code-to-voltage conversion.
- Archive and path management.
- Plotting conventions.
- User settings persistence.
- Timing calculator access.
- Error dialogs and application logging.

Do not create a second channel map or second serial protocol implementation.

---

## 6. Acquisition Ownership and Mutual Exclusion

### 6.1 Exclusive acquisition lock

The characterization workflow requires exclusive access to the acquisition hardware.

When the user presses **Begin Characterization**:

1. Request the existing application acquisition lock.
2. If normal capture is running:
   - Stop it cleanly.
   - Wait for confirmation that the capture worker and MCU stream have stopped.
   - Flush or discard stale buffered blocks.
3. Snapshot the current acquisition configuration.
4. Disable normal capture controls while characterization owns the hardware.
5. Start the dedicated characterization acquisition.

If another workflow owns the hardware, show a clear error and do not start.

### 6.2 Completion and cancellation

On completion, cancellation, disconnect, or error:

- Stop the dedicated capture.
- Flush its data path.
- Release the acquisition lock.
- Restore the previous acquisition configuration values.
- Leave normal capture stopped.
- Re-enable normal capture controls.
- Do not automatically restart regular acquisition.

This behavior avoids an unexpected restart after the user has removed or is still handling an external voltage source.

---

## 7. Dedicated Measurement Configuration

### 7.1 Selected signal

The initial version characterizes one logical signal per run.

When the user selects a signal, resolve:

```text
logical signal name
sensor identifier
physical MUX number
MUX address
physical MUX pin
physical ADC input order: 1 or 2
companion signal sampled by the other MUX at the same address
```

Display this mapping prominently.

Example:

```text
Selected signal: PZT1_C
MUX: MUX1
MUX address: 4
Apply voltage to MUX pin: S4
ADC input order: CH1
Companion sampled signal: PZT5_C
```

The companion signal may be captured internally because the MG24 returns a pair, but it must not be included in the selected signal fit.

### 7.2 Default characterization schedule

Default to a dedicated single-address schedule:

```text
one physical MUX address
repeat count = 1
existing OSR and gain, unless overridden in the tab
existing configured MUX settle time
dummy ground enabled by default
one sweep per block where supported
```

This gives a high sample rate and a clear decay trace.

Log the exact configuration because decay coefficients are timing-schedule dependent.

### 7.3 Advanced schedule option

Optionally expose an advanced setting:

```text
Acquisition schedule:
- Selected address only
- Current production channel schedule
```

The initial implementation may support only **Selected address only**, but structure the controller so the schedule can be extended later.

---

## 8. GUI Specification

## 8.1 Tab title

Use:

```text
PZT_Decay_Calc
```

## 8.2 Layout

Recommended layout:

### Left panel: Setup and controls

#### Channel selection

- Signal dropdown.
- Search/filter field if the signal list is long.
- Read-only mapping details:
  - MUX.
  - MUX address.
  - Physical MUX pin where the user must apply the voltage.
  - ADC input order.
  - Companion signal.

#### Electrical settings

- Excitation above `Vmid`, default `1.000 V`.
- Known connected leakage resistance, in ohms.
- Capacitance estimation enabled checkbox.
- Assumption label:

  ```text
  Assumes disconnected leakage is negligible.
  ```

- Optional maximum expected capacitance for timeout estimation.

#### Acquisition settings

- OSR.
- Gain.
- Repeat count.
- Dummy ground enabled.
- MUX settle time display.
- Timing source display.
- Read-only calculated values:
  - Total connected time.
  - Pre-sample decay time for the selected ADC input.
  - Post-sample connected time.
  - Expected sample interval, once capture begins.

#### Detection and fitting settings

- Target tolerance.
- Stable-target duration.
- Release detection threshold.
- Fit upper normalized amplitude, default `0.67`.
- Fit lower normalized amplitude, default `0.33`.
- Minimum fit points.
- End threshold.
- Maximum recording duration.
- Optional robust-fit checkbox, enabled by default.

#### Action buttons

- `Begin Characterization`
- `Cancel`
- `Reset`
- `Save Result`
- `Open Result Folder`

Disable controls that must not change during an active session.

### Center/right panel: Live chart

Plot:

- Voltage in volts versus relative wall time.
- Horizontal `Vmid` line.
- Horizontal `Vtarget` line.
- Target tolerance band.
- Detected release marker.
- Fit-region start and end markers.
- Samples included in fit using a distinct marker.
- Fitted exponential curve after analysis.

Optional second plot:

- `ln((V - Vmid) / A0)` versus cumulative timing exposure used by the fit.
- Fitted regression line.

### Result panel

Display:

```text
Measurement state
Vmid
Target voltage
Measured plateau voltage
Measured initial amplitude
Release time
Number of recorded samples
Number of fit samples
Measured mean sample interval
Calculated connected interval
Calculated disconnected interval
CH1/CH2 pre-sample decay interval
Per-sample alpha
Wall-clock tau
Connected-time tau estimate
Known resistance
Estimated capacitance
R²
RMSE in voltage
Fit validity
Warnings
```

Use clear units for every value.

---

## 9. Measurement State Machine

Use an explicit state enum.

Suggested states:

```python
class PztDecayState(Enum):
    IDLE = "idle"
    STOPPING_NORMAL_CAPTURE = "stopping_normal_capture"
    CONFIGURING = "configuring"
    BASELINE = "baseline"
    WAITING_FOR_TARGET = "waiting_for_target"
    TARGET_STABILIZING = "target_stabilizing"
    ARMED = "armed"
    WAITING_FOR_RELEASE = "waiting_for_release"
    RECORDING_DECAY = "recording_decay"
    ANALYZING = "analyzing"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    ERROR = "error"
```

### 9.1 IDLE

- No characterization capture.
- Setup controls enabled.
- Save disabled unless a completed unsaved result exists.

### 9.2 STOPPING_NORMAL_CAPTURE

- Stop normal capture if active.
- Show:

  ```text
  Stopping regular acquisition...
  ```

### 9.3 CONFIGURING

- Resolve mapping.
- Validate target voltage against ADC range.
- Configure the dedicated acquisition.
- Clear stale data.
- Calculate the timing context.

### 9.4 BASELINE

Instruction:

```text
Do not apply voltage or force. Measuring Vmid...
```

Collect a configurable baseline interval.

Default requirements:

```text
minimum baseline duration: 1.0 s
minimum baseline samples: 100
```

Complete when both are satisfied.

Calculate:

```python
vmid_v = median(baseline_voltages)
baseline_mad_v = median(abs(v - vmid_v))
baseline_sigma_v = 1.4826 * baseline_mad_v
```

Also calculate baseline slope and reject an unstable baseline.

### 9.5 WAITING_FOR_TARGET

Calculate:

```python
target_voltage_v = vmid_v + excitation_above_vmid_v
```

Display the required target to at least 3 decimal places.

Instruction example:

```text
Apply 2.651 V directly to MUX1 pin S4.
Do not apply mechanical force.
```

Continue live plotting.

### 9.6 TARGET_STABILIZING

Enter when the measured voltage is within the dynamic target tolerance.

Recommended tolerance:

```python
target_tolerance_v = max(
    user_target_tolerance_v,
    5.0 * baseline_sigma_v,
)
```

Default user tolerance:

```text
0.020 V
```

Require a stable window:

```text
default stable-target duration: 0.50 s
```

Stability checks:

- Median within target tolerance.
- Peak-to-peak below a configurable threshold.
- Absolute fitted slope below a configurable threshold.

If the voltage leaves tolerance, return to `WAITING_FOR_TARGET`.

### 9.7 ARMED / WAITING_FOR_RELEASE

Once stable:

- Start retaining the pre-release plateau samples.
- Record `plateau_voltage_v` as the median of the final stable window.
- Record the measured amplitude:

  ```python
  initial_amplitude_v = plateau_voltage_v - vmid_v
  ```

- Show:

  ```text
  Target detected and stable. Remove the applied voltage now.
  ```

Do not use exactly `1.000 V` as the initial fit amplitude.

### 9.8 RECORDING_DECAY

Detect release using a combination of:

- Drop below the plateau by a noise-aware threshold.
- Negative slope.
- Several consecutive samples confirming the change.

Suggested default release threshold:

```python
release_drop_v = max(
    0.02 * initial_amplitude_v,
    5.0 * baseline_sigma_v,
)
```

The release timestamp is estimated from the first confirmed falling sample or by interpolation between the preceding and following samples.

After release:

- Continue recording all samples.
- Continue live plotting.
- Mark the release.
- Calculate normalized amplitude:

  ```python
  normalized_amplitude = (voltage_v - vmid_v) / initial_amplitude_v
  ```

### 9.9 Stop conditions

Stop recording when all required analysis data exists and the decay is near baseline.

Default completion condition:

```text
normalized amplitude <= end threshold
for N consecutive samples
```

Suggested defaults:

```text
end threshold: max(0.03, 5 * baseline_sigma / initial_amplitude)
consecutive samples: 10
```

Also require that the trace has crossed below the configured lower fit threshold.

Stop on timeout if the decay does not complete.

Suggested default maximum duration:

```text
60 s
```

Make it configurable.

If timeout occurs after enough fit data exists, allow analysis with a warning. If not enough fit data exists, mark the result invalid.

### 9.10 ANALYZING

Freeze the dataset and perform fitting and quality checks.

### 9.11 COMPLETE

Show results and enable export.

---

## 10. Voltage and Safety Validation

Before starting target acquisition:

```python
target_voltage_v = vmid_v + excitation_above_vmid_v
```

Validate:

```text
target voltage < ADC positive full-scale limit - safety margin
target voltage > ADC negative limit + safety margin
```

Default safety margin:

```text
0.050 V
```

If the current voltage reference or gain cannot safely measure the requested target, block the test and explain what must change.

Also detect:

- ADC saturation.
- Clipping.
- Large overvoltage.
- Wrong-polarity excitation.
- Excessive baseline noise.
- Channel value not responding to applied voltage.
- A sudden mechanical event during decay.

Do not attempt a capacitance estimate from a clipped or invalid curve.

---

## 11. Timing Context

Create a result object such as:

```python
@dataclass(frozen=True)
class PztDecayTimingContext:
    timing_source: str
    physical_adc_input: int

    sensor_connected_s: float
    pre_sample_decay_s: float
    post_sample_connected_s: float

    mean_wall_sample_interval_s: float
    median_wall_sample_interval_s: float
    wall_sample_interval_std_s: float

    mean_disconnected_s: float
    median_disconnected_s: float

    calculated_signal_sequence_s: float
    calculated_ground_phase_s: float
    calculated_complete_sequence_s: float

    adc_mux_timing: AdcMuxTiming
```

Resolve the channel-specific values:

```python
if physical_adc_input == 1:
    pre_sample_decay_s = (
        timing.t_decay_before_effective_sample_ch1_s
    )
    post_sample_connected_s = (
        timing.t_connected_after_effective_sample_ch1_s
    )
elif physical_adc_input == 2:
    pre_sample_decay_s = (
        timing.t_decay_before_effective_sample_ch2_s
    )
    post_sample_connected_s = (
        timing.t_connected_after_effective_sample_ch2_s
    )
else:
    raise ValueError("physical_adc_input must be 1 or 2")
```

For every consecutive recorded sample pair:

```python
wall_dt_s = timestamp_s[n] - timestamp_s[n - 1]

connected_dt_s = timing.sensor_connected_s

disconnected_dt_s = max(
    0.0,
    wall_dt_s - connected_dt_s,
)
```

If `wall_dt_s < connected_dt_s`, mark a timing consistency error.

Use actual timestamps for wall time. Do not construct wall time only from nominal sample rate.

---

## 12. Sample Data Model

Suggested per-sample record:

```python
@dataclass
class PztDecaySample:
    sample_index: int
    timestamp_absolute: datetime | None
    relative_time_s: float

    voltage_v: float
    delta_from_vmid_v: float
    normalized_amplitude: float | None

    wall_dt_s: float | None
    connected_decay_dt_s: float | None
    disconnected_decay_dt_s: float | None

    cumulative_wall_time_s: float
    cumulative_connected_time_s: float
    cumulative_disconnected_time_s: float

    calculated_voltage_v: float | None

    measurement_state: str
    fit_included: bool
    rejection_reason: str | None
```

Retain full precision internally.

---

## 13. Fit-Region Selection

Use normalized positive amplitude:

```python
y_i = (V_i - Vmid) / A0
```

Default fit window:

```text
upper normalized limit: 2/3 ≈ 0.6667
lower normalized limit: 1/3 ≈ 0.3333
```

A sample is eligible when:

```python
lower_fit_limit <= y_i <= upper_fit_limit
```

Also require:

- Sample is after release detection.
- `V_i - Vmid > 0`.
- No clipping.
- No missing timestamp.
- No invalid timing.
- No manually excluded artifact.
- Sample is not an extreme outlier.

Minimum fit samples:

```text
default: 20
```

If the sample rate or decay rate makes 20 points impossible between two-thirds and one-third, allow a lower minimum only through explicit user configuration and show reduced-confidence status.

---

## 14. Exponential Fitting

## 14.1 Wall-clock fit

For accepted fit samples:

```python
z_i = log(V_i - Vmid)
x_i = relative_time_s_i
```

Fit:

```text
z_i = intercept_wall - k_wall * x_i
```

Then:

```python
tau_wall_s = 1.0 / k_wall
```

Reject a nonpositive `k_wall`.

Calculate:

```text
R²
RMSE in voltage domain
number of fit samples
fit duration
```

For every valid post-release sample, calculate the fitted voltage so the
calculated decay function can be plotted over the measured samples:

```python
calculated_voltage_v = (
    vmid_v
    + fitted_amplitude_v
    * math.exp(-fitted_decay_rate_per_s * fit_time_s)
)
```

Display and export only these regression fit-error metrics:

```text
R²
RMSE in voltage [V]
```

Calculate RMSE over the samples included in the regression fit:

```python
rmse_voltage_v = math.sqrt(
    mean(
        (measured_voltage_v - calculated_voltage_v) ** 2
        for each fit-included sample
    )
)
```

Do not add a separate residual graph or additional error metrics such as MAE,
maximum error, median error, normalized RMSE, or point-by-point exported error.

## 14.2 Connected-time fit

Under the negligible-disconnected-leakage assumption, use cumulative connected exposure:

```python
x_connected_i = cumulative_connected_time_s_i
z_i = log(V_i - Vmid)
```

Fit:

```text
z_i = intercept_on - k_on * x_connected_i
```

Then:

```python
tau_on_estimated_s = 1.0 / k_on
```

Equivalent per-sample coefficient at the reference connected interval:

```python
alpha_connected_reference = exp(
    -sensor_connected_s / tau_on_estimated_s
)
```

## 14.3 Direct sample-ratio coefficient

Also calculate a robust pairwise coefficient as a diagnostic:

```python
alpha_i = (
    (V_i - Vmid)
    / (V_{i-1} - Vmid)
)
```

Use only valid consecutive samples in the fit region.

Report:

```text
median alpha
MAD of alpha
mean alpha
standard deviation of alpha
```

The regression result is the primary result; the pairwise median is a cross-check.

## 14.4 Robust fitting

Default to robust fitting.

Suggested process:

1. Perform an initial least-squares fit.
2. Calculate residuals in log space.
3. Calculate residual MAD.
4. Remove samples exceeding a configurable robust threshold, default `3.5 MAD`.
5. Refit.
6. Record excluded sample indices and reasons.

Use an existing robust-regression dependency if already available. Otherwise implement a deterministic NumPy least-squares plus MAD rejection.

---

## 15. Capacitance Estimation

Only calculate capacitance when:

- Capacitance estimation is enabled.
- Known connected equivalent resistance is valid and greater than zero.
- The fit is valid.
- `tau_on_estimated_s` is positive.
- The selected model is explicitly accepted.

Calculate:

```python
capacitance_estimated_f = (
    tau_on_estimated_s
    / connected_equivalent_resistance_ohm
)
```

Display convenient units:

```text
pF
nF
µF
```

Also retain the value in farads.

Required warning:

```text
Capacitance estimate assumes that the configured connected resistance
dominates decay and that disconnected leakage is negligible. MUX leakage,
sensor insulation resistance, op-amp input current, PCB leakage, and other
paths may affect the result.
```

If the user has a known disconnected time constant or leakage resistance, store it for future use, but the initial single-run implementation must not claim to solve both `tau_on` and `tau_off`.

---

## 16. Future Two-Schedule Extension

Design the result model to permit several runs at different schedules.

For schedule `j`:

```text
-ln(alpha_j)
= Ton_j / tau_on
+ Toff_j / tau_off
```

With two sufficiently different timing schedules:

```text
k1 = Ton1 * a + Toff1 * b
k2 = Ton2 * a + Toff2 * b

a = 1 / tau_on
b = 1 / tau_off
```

This future mode can estimate both time constants if the matrix is well-conditioned.

Do not implement it unless requested, but do not design the stored result format in a way that prevents it.

---

## 17. Result Data Model

Suggested result:

```python
@dataclass(frozen=True)
class PztDecayResult:
    schema_version: str
    result_id: str
    created_at: datetime

    mcu_type: str
    logical_signal: str
    mux_number: int
    mux_address: int
    physical_adc_input: int
    mux_pin_label: str

    vmid_v: float
    baseline_sigma_v: float
    target_voltage_v: float
    plateau_voltage_v: float
    initial_amplitude_v: float

    release_time_s: float
    recording_duration_s: float
    total_samples: int
    fit_samples: int

    fit_lower_normalized: float
    fit_upper_normalized: float

    alpha_sample_regression: float
    alpha_sample_pairwise_median: float
    alpha_sample_pairwise_mad: float

    tau_wall_s: float
    tau_on_estimated_s: float | None
    connected_equivalent_resistance_ohm: float | None
    capacitance_estimated_f: float | None

    r_squared: float
    rmse_voltage_v: float

    timing: PztDecayTimingContext
    acquisition_configuration: dict
    quality_status: str
    warnings: tuple[str, ...]
```

Store the sample list separately or by reference to avoid copying large arrays through immutable result objects.

---

## 18. Quality Status

Use explicit result statuses:

```text
valid
valid_with_warnings
invalid
cancelled
```

Warnings may include:

```text
baseline unstable
target not exactly reached
plateau unstable
ADC clipping
too few fit samples
fit range not fully traversed
low R²
large fit residual
mechanical disturbance suspected
sample timing jitter high
disconnected leakage assumption may be invalid
known resistance not supplied
capacitance not calculated
timeout before full decay
```

Suggested default validity thresholds:

```text
R² >= 0.98
minimum 20 fit samples
no clipping
positive fitted decay rate
fit covers both configured normalized boundaries
```

Make thresholds configurable but persist them.

---

## 19. Plot Behavior

### 19.1 Live and completed voltage plot

During capture, update efficiently without redrawing all historical samples on every sample.

Plot:

- Measured voltage samples.
- `Vmid`.
- `Vtarget`.
- Target tolerance.
- Plateau.
- Release marker.
- Fit-range thresholds converted to volts.
- Included fit samples.

After analysis completes, overlay the calculated decay function on the same graph as the measured samples:

```python
calculated_voltage_v(t) = (
    vmid_v
    + fitted_amplitude_v
    * exp(-fitted_decay_rate_per_s * fit_time_s)
)
```

Use the same time basis as the selected fit:

- Wall-clock time for the wall-time fit.
- Cumulative connected exposure for the connected-time fit.

The default completed plot must show:

```text
Measured samples
Calculated decay function
Fit-region samples
```

Display the regression quality next to or above the plot:

```text
RMSE: <value> V
R²: <value>
```

Extend the calculated decay curve across the complete recorded post-release
interval, not only across the samples used for fitting. Do not add a separate
error or residual graph.

### 19.2 Normalized plot

Optional normalized plot:

```text
normalized amplitude = (V - Vmid) / A0
```

Horizontal lines:

```text
0.667
0.333
end threshold
```

### 19.3 Log-fit plot

After analysis:

```text
ln(V - Vmid)
```

against:

- Wall time.
- Connected exposure time.

Allow switching the x-axis basis.

---

## 20. Export Requirements

Use a unique run ID and timestamp including seconds or microseconds.

Suggested names:

```text
pzt_decay_PZT1_C_20260724_113035_<run-id>_samples.csv
pzt_decay_PZT1_C_20260724_113035_<run-id>_result.json
pzt_decay_PZT1_C_20260724_113035_<run-id>_summary.csv
```

Do not use minute-only filenames.

## 20.1 Samples CSV

Required columns:

```text
SampleIndex
Timestamp
RelativeTime_s
Voltage_V
Vmid_V
DeltaFromVmid_V
NormalizedAmplitude
WallDeltaT_s
ConnectedDecayDeltaT_s
DisconnectedDecayDeltaT_s
CumulativeWallTime_s
CumulativeConnectedTime_s
CumulativeDisconnectedTime_s
CalculatedVoltage_V
State
FitIncluded
RejectionReason
```

Include voltage in volts.

The first sample may have empty delta-time values.

## 20.2 Result JSON

Suggested structure:

```json
{
  "schema_version": "1.0",
  "result_id": "...",
  "timestamp": "...",
  "measurement_type": "pzt_decay_characterization",

  "device": {
    "mcu_type": "Array_PZT_PZR1.7",
    "adc_timing_profile": "mg24_dual_mux_v3"
  },

  "signal": {
    "logical_name": "PZT1_C",
    "mux_number": 1,
    "mux_address": 4,
    "mux_pin": "S4",
    "physical_adc_input": 1
  },

  "excitation": {
    "requested_above_vmid_v": 1.0,
    "vmid_v": 1.651,
    "target_voltage_v": 2.651,
    "plateau_voltage_v": 2.647,
    "measured_initial_amplitude_v": 0.996
  },

  "acquisition": {
    "osr": 4,
    "gain": 1,
    "repeat_count": 1,
    "dummy_ground_enabled": true,
    "mux_settle_us": 20.0,
    "sample_count": 1234,
    "recording_duration_s": 4.21
  },

  "timing": {
    "timing_source": "calculated_adc_mux_plus_measured_timestamps",
    "sensor_connected_s": 0.0000404,
    "pre_sample_decay_s": 0.0000208,
    "post_sample_connected_s": 0.0000196,
    "mean_wall_sample_interval_s": 0.00123,
    "median_wall_sample_interval_s": 0.00122,
    "mean_disconnected_s": 0.0011896,
    "adc_mux_timing": {}
  },

  "fit": {
    "normalized_upper": 0.6667,
    "normalized_lower": 0.3333,
    "sample_count": 83,
    "alpha_sample_regression": 0.9971,
    "alpha_sample_pairwise_median": 0.9970,
    "tau_wall_s": 0.42,
    "tau_on_estimated_s": 0.0138,
    "fitted_amplitude_v": 0.996,
    "fitted_decay_rate_per_s": 2.381,
    "r_squared": 0.995,
    "rmse_voltage_v": 0.004
  },

  "capacitance_estimate": {
    "enabled": true,
    "connected_equivalent_resistance_ohm": 1000000.0,
    "capacitance_f": 1.38e-8,
    "assumption": "disconnected leakage negligible"
  },

  "quality": {
    "status": "valid_with_warnings",
    "warnings": []
  },

  "files": {
    "samples_csv": "...",
    "summary_csv": "..."
  }
}
```

Embed the existing `adc_mux_timing` JSON object without reconstructing it manually.

## 20.3 Summary CSV

Create an optional one-row CSV with:

```text
ResultID
Timestamp
Signal
MUX
MUXAddress
MUXPin
ADCInput
Vmid_V
TargetVoltage_V
PlateauVoltage_V
InitialAmplitude_V
Samples
FitSamples
MeanWallDeltaT_s
ConnectedDeltaT_s
PreSampleDecay_s
PostSampleConnected_s
AlphaSample
TauWall_s
TauOnEstimated_s
Resistance_Ohm
Capacitance_F
R2
RMSE_V
QualityStatus
Warnings
SamplesCSV
ResultJSON
```

---

## 21. Persistence

Persist user-editable settings:

```text
last selected signal
excitation above Vmid
target tolerance
stable target duration
release threshold
fit upper and lower normalized bounds
minimum fit samples
end threshold
maximum recording duration
known resistance
capacitance estimation enabled
robust fitting enabled
```

Do not persist transient values such as measured `Vmid` or plateau voltage as settings.

Use the application’s existing settings mechanism.

---

## 22. Threading and Performance

- Acquisition and serial I/O must remain outside the GUI thread.
- Analysis may run in a worker if the dataset is large.
- GUI updates must be marshaled through the framework’s normal signal/slot mechanism.
- Throttle live plot refresh to a reasonable rate, such as 10–20 frames per second.
- Do not drop acquisition samples merely to reduce plot load.
- Cancellation must be thread-safe.
- Ignore stale callbacks from previous run IDs.

Every session must have a unique `session_id` or `run_id`.

---

## 23. Error Handling

Handle at least:

- MCU disconnected before start.
- MCU disconnected during measurement.
- Failure to stop normal capture.
- Failed timing calculation.
- Selected channel not mapped.
- Target voltage outside ADC range.
- Target never reached.
- Voltage unstable.
- Release never detected.
- Decay never reaches fit region.
- Too few fit samples.
- Nonpositive values in log fit.
- ADC clipping.
- Timing timestamps missing or nonmonotonic.
- Save failure.
- User cancellation.

On error:

- Stop dedicated capture.
- Release acquisition ownership.
- Preserve any collected data where useful.
- Allow saving partial raw data with an invalid-result status.
- Show a concise user-facing message.
- Log the full technical exception.

---

## 24. Tests

## 24.1 Unit tests: baseline

Test:

- Median `Vmid`.
- MAD-based noise.
- Rejection of unstable baseline.
- Correct target voltage.
- ADC-range validation.

## 24.2 Unit tests: state machine

Test valid path:

```text
IDLE
→ BASELINE
→ WAITING_FOR_TARGET
→ TARGET_STABILIZING
→ ARMED
→ WAITING_FOR_RELEASE
→ RECORDING_DECAY
→ ANALYZING
→ COMPLETE
```

Test:

- Target lost during stabilization.
- Cancel from every active state.
- Timeout.
- MCU disconnect.
- Stale callback ignored by run ID.

## 24.3 Unit tests: release detection

Use synthetic plateau and exponential decay with noise.

Verify release timing and false-trigger resistance.

## 24.4 Unit tests: timing selection

For physical ADC input 1:

```python
pre_sample_decay_s == timing.t_decay_before_effective_sample_ch1_s
post_sample_connected_s == timing.t_connected_after_effective_sample_ch1_s
```

For physical ADC input 2:

```python
pre_sample_decay_s == timing.t_decay_before_effective_sample_ch2_s
post_sample_connected_s == timing.t_connected_after_effective_sample_ch2_s
```

Verify:

```python
pre_sample_decay_s + post_sample_connected_s
== pytest.approx(timing.sensor_connected_s)
```

## 24.5 Unit tests: fit

Generate:

```text
V(t) = Vmid + A * exp(-t / tau)
```

Add controlled noise.

Verify:

- Fit region selection.
- Recovery of `tau_wall`.
- Recovery of alpha.
- Robust outlier rejection.
- Rejection of nondecaying or increasing data.
- Minimum sample enforcement.
- Calculated voltage values across the complete post-release interval.
- Correct RMSE in volts over the fit-included samples.
- Correct R² over the fit-included samples.
- Completed plot model contains both measured and calculated voltage series.
- Completed plot annotation contains RMSE and R².
- No separate residual/error plot is created.

## 24.6 Unit tests: connected-time capacitance model

Generate synthetic samples with:

```text
alpha = exp(-Ton / tau_on)
tau_on = R * C
```

Verify recovery of:

```text
tau_on
C
```

Use the exact connected time from a mock `AdcMuxTiming`.

## 24.7 Integration tests

Test that starting characterization:

- Stops regular capture.
- Acquires the hardware lock.
- Applies dedicated channel configuration.
- Receives samples.
- Restores prior configuration.
- Does not restart normal capture.
- Produces valid CSV and JSON files.
- Uses a unique filename.

## 24.8 Export tests

Verify:

- CSV row count equals collected sample count.
- Required timing columns are present.
- JSON contains full configuration and timing provenance.
- JSON contains coefficients, fitted decay-function parameters, RMSE, R², and fit quality.
- Files use unique run IDs.
- Full internal values are not accidentally replaced with rounded display values.

---

## 25. Acceptance Criteria

The feature is complete when:

1. A user can select one PZT signal and see its physical MUX/pin mapping.
2. Normal capture stops automatically before characterization begins.
3. `Vmid` is measured from a stable baseline using a median.
4. The exact target voltage `Vmid + 1.000 V` is displayed.
5. The application detects and validates the applied voltage.
6. The application records a stable plateau and detects voltage removal.
7. The complete decay is displayed live.
8. Samples between the configured two-thirds and one-third range are selected automatically.
9. The application calculates:
   - Per-sample alpha.
   - Wall-clock tau.
   - Connected-time tau estimate.
   - Calculated voltage at every valid post-release sample.
   - Regression RMSE in volts.
   - Regression R².
   - Fit quality.
10. The completed display overlays the calculated decay function on the measured samples and shows RMSE and R².
11. The application uses the correct channel-specific pre-sample decay timing.
12. Optional capacitance is calculated only when a valid resistance and explicit model assumption are present.
13. CSV and JSON exports contain measured voltage, calculated voltage, actual delta times, connected/disconnected timing, coefficients, timing provenance, RMSE, R², and quality information.
14. The workflow is safely cancellable.
15. Existing normal acquisition behavior is unchanged outside this tab.
16. Automated tests cover state transitions, fitting, RMSE and R² calculations, timing selection, force-related timing values, plotting, and exports.

---

## 26. Implementation Notes for the Coding Agent

- Inspect the existing application architecture before creating new classes.
- Reuse existing channel mappings, acquisition workers, configuration models, plotting utilities, and archive writers.
- Do not infer physical ADC input from exported-column order when a mapping exists.
- Display the physical MUX pin directly; do not display or require a connector-pin mapping.
- Do not use the displayed or rounded timing JSON for calculations.
- Use the full-precision `AdcMuxTiming` object.
- Use actual per-sample timestamps for wall-clock intervals.
- Treat the dummy-ground phase as disconnected time for the selected PZT.
- Keep measured wall-clock decay separate from connected-time decay estimates.
- Label every capacitance result as model-dependent.
- Do not silently claim that one run separates connected and disconnected leakage.
- Preserve backward compatibility with existing acquisition and force-analysis features.
- Add logging at state transitions and when timing/model assumptions are selected.
- Add concise comments explaining the difference between:
  - Wall sample interval.
  - Total connected time.
  - Pre-sample decay time.
  - Post-sample connected time.
  - Disconnected time.
