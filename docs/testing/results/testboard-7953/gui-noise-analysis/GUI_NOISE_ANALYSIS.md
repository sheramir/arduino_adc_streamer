# TestBoard 7953: simultaneous GUI-capture bursts and PZT5_L baseline

**Sensors attached, Vmid control:** Repeating off/on/off with both strips
attached and reported unstressed leaves channel 11 lowest on ADC2/ADC4.
ADC2 changes by -3.05 mV and returns exactly; ADC4's small increase persists
in the off return. ADC2 channel 12 rises reversibly by 13.43 mV. All captures
pass; Vmid-off is restored. See [the attached-sensor results](../TESTBOARD_7953_VMID_SENSORS_ATTACHED_RESULTS.md).

**Vmid-between-channel control:** A new off/on/off benchmark uses the existing
reference-insertion setting. Channel 11 falls by 31.74 mV on ADC2 and 8.24 mV
on ADC4 relative to the mean off controls, and remains lowest on each ADC.
All channel medians return within one count when insertion is disabled.
Sweep period increases from 136 to 346 us. The original stopped Vmid-off
configuration is restored. See [the Vmid baseline report](../TESTBOARD_7953_VMID_BASELINE_RESULTS.md).

**Channel-11 firmware investigation:** The source treats channels 10/11/12
uniformly. Nine new order/continuous-selection controls establish substantial
scan-history dependence, with most of the channel-11 deficit disappearing
when held selected. The user clarifies that each ADC has one Vmid bias resistor
at shared MXO / op-amp input; unplugged individual channel inputs are not
individually biased to Vmid. Dynamic MUX/bias-node behavior is the leading
explanation, while the exact address-specific mechanism remains unresolved.
The user has closed the burst-noise investigation and focuses on this offset.
See [the firmware review and hardware controls](../../../../reports/firmware/TESTBOARD_7953_CHANNEL11_FIRMWARE_REVIEW.md).

**Charger reconnection update:** A matched short return benchmark restores
the strong 1.32 s burst pattern on both arrays after the user reconnects
the charger. Quiet levels return to 0.48/0.40 mV standard deviation and
burst levels are 1.10/0.80 mV. PZT5_L remains low. This strengthens the
association with laptop power condition without identifying the coupling
path. See [the charger-return control](../TESTBOARD_7953_LAPTOP_BATTERY_NOISE_RESULTS.md#charger-reconnected-return-control).

**Laptop battery update:** With the charger disconnected, a matched short
benchmark no longer shows the strong 1.32 s burst pattern, but noise remains
near the earlier burst levels almost continuously. Channel-11 baselines are
unchanged. See [the battery control report](../TESTBOARD_7953_LAPTOP_BATTERY_NOISE_RESULTS.md).
The user rules out powering the board from an alternative 5 V source;
scope measurements are planned later.

**Analog supply clarification:** The user reports that ADC +VA and OPA365
supplies are powered from USB 5 V through a ferrite bead and bypass capacitors,
while Vref and Vmid are supplied by REF2025. USB-derived supply/ground
coupling remains a candidate; see the power hypothesis section below.

**Engine/topology update:** The completed 21-capture standalone comparison
retains 1.32 s bursts across blocking, DMA and LPSPI, each ADC alone, each
array alone and both arrays. ADC2/ADC4 channel 11 stays low even with a
single active ADC. See [the complete engine/topology report](../TESTBOARD_7953_ENGINE_TOPOLOGY_NOISE_RESULTS.md).

**Standalone benchmark update:** A new 10 MHz/repeat-1 capture with the GUI
disconnected and both sensor strips unplugged reproduces the 1.32 s burst
recurrence and exactly matches the GUI's ADC2/ADC4 channel-11 medians.
See [the benchmark comparison report](../TESTBOARD_7953_BENCHMARK_NOISE_RESULTS.md).
This establishes reproduction outside the GUI, while leaving firmware versus
board-level causation unresolved.

Analyzed 2026-10-08. The visible bursts also occur in the archived, unfiltered
ADC values. Their timing is strongly correlated between the arrays and repeats
at approximately 1.32 seconds. PZT5_L is genuinely lower on both ADCs; this
channel-specific offset also exists in the firmware benchmark recordings that
precede the GUI repair. Neither observation establishes a defective sensor or
an SPI bit-error mechanism. No GUI, firmware, protocol, or source capture was
changed for this analysis.

Subsequent controls below retain the 1.32 s pattern with both sensor strips
removed and all four ADCs biased from the board. The user identifies OPA365
unity buffers and REF2025-generated 1.25 V Vmid / 2.5 V Vref. The final hardware
clarification section compares the observed offsets with their specifications;
normal specified OPA365 input bias/offset is much too small to explain them.

## Capture and checks

Source: `C:/Users/shera/Documents/sensetics/data/adc/cache/adc_data_20261008_113804_946979.jsonl`.
The attached 11:37 log includes two runs; the first run's cache was cleared at
11:38:03 and is no longer available. These raw findings concern the second run,
which matches both screenshots: 130,559 sweeps, 6,527,950 values, 11.441816 s.

Frozen acquisition metadata and final status agree: both arrays, 50 routes,
manual sequence, blocking SPI engine, 20 MHz, repeat 1, optional between-channel
Vmid sampling off, and 2.5 V full scale. Archived ghost removal is disabled.
Channel extraction uses the frozen channel specifications and sample indices.
All timestamps increase, all retained samples fit 12 bits, the archive count
matches submitted frames, no two complete channel columns are identical, and
the footer reports complete capture, zero parser rejections and zero archive
overruns. Final status reports zero ADC/channel/transfer/USB-write errors.
These checks cannot detect every possible in-range payload error.

Firmware sampled 130,598 sweeps, sent 130,559 and intentionally discarded 39
(0.0299%) under its existing discard-if-busy policy. Maximum actual sampling
period was 89 us with zero periods above 1 ms. Median received interval is
88 us; maximum is 347 us. The three received intervals exceeding three normal
periods occur at 6.429633, 8.041705 and 9.241309 s. There are no received gaps
in the screenshot's 10.58–10.82 or 11.04–11.12 s bursts. This capture does not
show the earlier large pauses or capture queue overrun.

## Shared bursts

After excluding the first second, compute each channel's sample standard
deviation in nonoverlapping 20 ms windows, then take the median across the 25
channels in each array. The two resulting envelopes correlate at **0.9927**.
Array 1's envelope autocorrelation has its strongest recurrence between
0.5 and 2 seconds at **1.32 s**, correlation 0.800. This is a burst recurrence
time, not an identified electrical interference frequency.

| Raw measurement | Quiet, 10.45–10.56 s | Burst, 10.60–10.78 s |
| --- | ---: | ---: |
| Array 1 median channel standard deviation, counts | 0.496 | 1.420 |
| Array 2 median channel standard deviation, counts | 0.458 | 0.966 |
| Median correlation between corresponding array channels | 0.144 | 0.810 |
| Array 1 median channel peak-to-peak range, counts | 2 | 6 |
| Array 2 median channel peak-to-peak range, counts | 2 | 5 |

The disturbance is small in absolute ADC voltage: approximately 0.61 mV per
count at the configured full scale. The graph's narrow vertical range makes it
prominent, and peak-preserving rendering exposes its extrema. It remains a
real recorded variation; display smoothing would not resolve its source.
Standard deviation includes sensor motion and interference, not just intrinsic
ADC electronic noise. Not every channel has the same amplitude or polarity.

The repeatable timing and cross-array correlation favor a common disturbance
over unrelated sensor failures. Candidate mechanisms include shared bias,
reference, supply or ground coupling; acquisition-dependent interference or
settling; and shared mechanical motion. Host activity could also couple
electrically into the board without corrupting the software pipeline. The raw
recording cannot isolate these mechanisms, and the short burst spectra do not
justify labeling the source as a particular mains frequency.

## PZT5_L identity and baseline

The saved mapping and firmware ADC-order scan agree:

| Label | Physical route | Archived column, zero-based | Median after 1 s | Median of other channels on that ADC |
| --- | --- | ---: | ---: | ---: |
| A1_PZT5_L | ADC2 channel 11 | 21 | 1940 | 2037 |
| A2_PZT5_L | ADC4 channel 11 | 46 | 1972 | 2037.5 |

The GUI reads two distinct columns. The approximately 97-count and 65.5-count
offsets are present before display processing. Both also show simultaneous
small negative level shifts, including approximately 10.89–10.94 s and
11.05–11.14 s, with different absolute baselines.

Independent comparison with the completed firmware matrix's
`live_usb_production_adc_10_20/benchmark_channel_stats.csv`, both full arrays,
manual sequence, medians of three repetitions:

| Engine and SPI clock | ADC2 channel 11 median | ADC4 channel 11 median |
| --- | ---: | ---: |
| Blocking 10 MHz | 1940 | 1977 |
| Blocking 20 MHz | 1929 | 1972 |
| LPSPI 10 MHz | 1908 | 1949 |
| LPSPI 20 MHz | 1891 | 1932 |

Other channels on these ADCs have group medians around 2034–2040.5 counts in
those cases. The low channel-11 baselines therefore predate this GUI run and
persist across different engines and both clock settings. The
[full-matrix report](../../../benchmarks/testboard-7953/TESTBOARD_7953_LIVE_USB_FULL_MATRIX_RESULTS.md) also identifies
localized blocking-mode negative excursions on exactly ADC2/ADC4 channel 11.
Quieter LPSPI captures still have low DC baselines; noise and baseline offset
should be assessed separately.

These are recordings from different runs without matched environmental/drift
controls. They demonstrate recurrence, not a causal clock comparison for the
current bursts. ADC2 uses 470 kOhm bias; ADC4 uses 249 kOhm. Sensor capacitance,
leakage, connection/PCB layout and mux settling can differ. A shared channel
position warrants checking its repeated circuit/input characteristics before
concluding that two independent sensors have failed.

TI describes the ADS7953's dependence on source impedance, input charge and
settling after a mux change, and compares first/second conversions while
reducing throughput to evaluate settling. That makes slower-clock and extra
settling-conversion tests useful. Board bias resistance alone is not the
effective ADC source impedance; the attached circuitry must be accounted for.
See [TI ADS7953 datasheet, sections 9.1–9.2](https://www.ti.com/lit/ds/symlink/ads7953.pdf)
and the repo's [channel-quality report](../TESTBOARD_7953_CHANNEL_QUALITY_RESULTS.md).

## Next controlled comparison

1. Record 20–30 seconds at **10 MHz**, keeping blocking/manual, both arrays,
   all 50 routes, repeat 1, reference and optional Vmid settings unchanged.
   Leave the strips/table still and preserve the raw archive before Clear Data.
2. Repeat at **20 MHz** with those same conditions. Compare post-warm-up
   noise envelopes, burst recurrence and each PZT5_L baseline. A reduction or
   period change at 10 MHz supports a clock/acquisition-dependent contribution
   but does not alone prove SPI communication errors.
3. If needed, separately compare manual **repeat 1 versus repeat 3**, at the
   same clock. These are settling conversions, retaining only the final result,
   rather than averaging. Clock/repeat changes also alter selection/revisit
   timing, so a change is not uniquely attributable to one analog mechanism.

If the shared bursts remain unchanged, prioritize common bias/reference/ground,
environment and mechanical controls. If channel 11 stays low while the rest of
each ADC stays normal, compare that input against a known stable input or a
controlled channel swap to distinguish sensor/strip characteristics from the
repeated circuit path. No filtering or baseline offset compensation was added.

## Reproduction and artifacts

Run with the repository virtual environment:

```powershell
.venv/Scripts/python.exe scripts/analyze_testboard_noise.py 'C:/Users/shera/Documents/sensetics/data/adc/cache/adc_data_20261008_113804_946979.jsonl' --output docs/testing/results/testboard-7953/gui-noise-analysis --plot
```

For another capture, choose matching `--quiet start end` and `--burst start end`
windows. The script validates archive counts, timestamps and sample range, and
extracts channels from the saved descriptor. It writes a machine-readable
[summary](summary.json) and the visually checked
[raw-data figure](raw_noise.png).

## Follow-up: 5 MHz capture, 12:17

Preserved the completed 19.211024 s run before the user clears the GUI:
`C:/Users/shera/Documents/sensetics/data/adc/speed_tests/20261008/5MHz_121702/adc_data_20261008_121702_422163.jsonl`
and its matching `_block_timing.csv`. Both copies have matching SHA256 hashes
with their cache sources. The archive reports 5 MHz, blocking/manual, repeat 1,
the same 50 ordered routes, complete capture, and 83,709 sweeps / 4,185,450
values. All 83,709 acquired sweeps were transmitted and archived: zero device
discards, parser rejections, archive overruns or transmission gaps. Received
intervals are 229–230 us; maximum actual sampling period is 230 us.

The synchronous burst pattern persists. The 20 ms array noise envelopes
correlate at 0.9476; Array 1's strongest envelope recurrence in the same
0.5–2 s search is still 1.32 s (autocorrelation 0.733). The recurrence remains
approximately fixed despite the sweep interval increasing from 88 to 230 us.
This makes a fixed sweep-count recurrence less likely and supports investigating
a common disturbance with its own time scale. It does not identify that source
or exclude acquisition-dependent sensitivity to it.

| Post-warm-up measurement | 20 MHz, 11:38 run | 5 MHz, 12:17 run |
| --- | ---: | ---: |
| Array 1 median 20 ms noise envelope, counts | 0.551 | 0.528 |
| Array 2 median 20 ms noise envelope, counts | 0.495 | 0.488 |
| Array 1 95th percentile envelope, counts | 1.458 | 0.789 |
| Array 2 95th percentile envelope, counts | 0.998 | 0.595 |
| A1_PZT5_L median, counts | 1940 | 1974 |
| A2_PZT5_L median, counts | 1972 | 2001 |
| Median of other ADC2 channels, counts | 2037 | 2040 |
| Median of other ADC4 channels, counts | 2037.5 | 2042.5 |

Thus the user correctly observes the same class of bursts at 5 MHz, while
the raw data also shows smaller upper-tail variation and higher PZT5_L
baselines in this run. The offsets relative to the other channels narrow from
97 to 66 counts on ADC2 and from 65.5 to 41.5 counts on ADC4. These separate
runs differ in time and duration and lack environmental drift controls; the
changes alone do not prove a clock-only cause. A matching 10 MHz run is the
next useful comparison, with all other settings kept unchanged.

The [5 MHz summary](5MHz/summary.json) uses
representative quiet 15.38–15.40 s and burst 15.56–15.58 s windows selected
from the final five seconds. They are illustrative rather than a matched
comparison with the old 20 MHz windows; the table above instead uses every
complete post-warm-up 20 ms bin. The
[5 MHz raw-data figure](5MHz/raw_noise.png)
shows the whole-run envelopes and the final second of two raw channel pairs.

## Follow-up: 10 MHz capture, 12:24

Preserved and SHA256-verified the raw archive and timing sidecar outside the
GUI cache in `C:/Users/shera/Documents/sensetics/data/adc/speed_tests/20261008/10MHz_122420/`.
Source basename: `adc_data_20261008_122420_937380`. The stopped archive is
complete: 152,107 sweeps, 7,605,350 values, 20.686523 s. The descriptor confirms
10 MHz, blocking/manual, repeat 1, both arrays / the same 50 routes, optional
Vmid sampling off and 2.5 V full scale. The 5 and 10 MHz descriptors differ
only in clock and the board-context fields containing that clock.

Firmware acquired 152,111 sweeps, submitted 152,107 and intentionally discarded
four (0.00263%). Every submitted frame was archived. Parser rejections,
archive overruns and periods above 1 ms are zero. The maximum actual sampling
period is 138 us; the median received interval is 136 us and maximum is
405 us. Three received intervals indicate missing transmissions: 270 us at
3.083876 s, 271 us at 14.562583 s, and 405 us at 14.562854 s. None crosses the
existing three-normal-period gap threshold; the footer consequently reports
zero transmission gaps. This threshold count must not be mistaken for zero
firmware discards.

Using the same post-warm-up, complete 20 ms bins for each capture:

| Measurement | 5 MHz | 10 MHz | 20 MHz |
| --- | ---: | ---: | ---: |
| Array 1 median envelope variation, counts | 0.528 | 0.488 | 0.551 |
| Array 2 median envelope variation, counts | 0.488 | 0.468 | 0.495 |
| Array 1 95th percentile envelope variation, counts | 0.789 | 0.622 | 1.458 |
| Array 2 95th percentile envelope variation, counts | 0.595 | 0.523 | 0.998 |
| Envelope recurrence, seconds | 1.32 | 1.32 | 1.32 |
| Cross-array envelope correlation | 0.948 | 0.902 | 0.993 |
| A1_PZT5_L median, counts | 1974 | 1946 | 1940 |
| A2_PZT5_L median, counts | 2001 | 1978 | 1972 |
| Other ADC2 channels' median, counts | 2040 | 2039 | 2037 |
| Other ADC4 channels' median, counts | 2042.5 | 2040.5 | 2037.5 |

The periodic synchronized bursts persist at all three speeds. In this 10 MHz
run, their variation is lower than in both earlier runs; variation does not
decrease monotonically with clock speed. PZT5_L remains low at 10 MHz, with
approximately 93-count / 62.5-count offsets from the other channels on ADC2 /
ADC4. The larger baseline improvement at 5 MHz and the fixed burst recurrence
are separate observations. Slowing SPI alone has not removed the recurring
disturbance, and these separate runs do not isolate environmental drift from
clock/acquisition effects.

The next useful comparison is **10 MHz, manual repeat 3**, with all other
settings unchanged, for 20–30 seconds. Compare against this 10 MHz repeat-1
run. Firmware retains the final same-channel settling conversion rather than
averaging. A baseline or variation change would demonstrate sensitivity to
selection/conversion timing, while still not uniquely separating mux settling,
sensor charge/leakage and interference coupling.

Artifacts: [10 MHz summary](10MHz/summary.json),
[10 MHz figure](10MHz/raw_noise.png), and
[three-clock comparison](clock_comparison.json).
Illustrative 10 MHz windows are quiet 16.80–16.82 s and burst 17.36–17.38 s;
the comparison table uses the full post-warm-up envelopes instead.
The original 20 MHz JSONL was later removed by GUI cache clearing. Its already
decoded raw arrays and analysis summary have now also been preserved outside
the cache at `speed_tests/20261008/20MHz_reference_113804/`; that reference is
derived data, not a copy of the original JSONL.

## Follow-up: 10 MHz, repeat 3, 12:29

Preserved and SHA256-verified the completed raw archive and timing sidecar in
`C:/Users/shera/Documents/sensetics/data/adc/speed_tests/20261008/10MHz_repeat3_122958/`.
Source basename: `adc_data_20261008_122958_568387`. The descriptor confirms
10 MHz, blocking/manual, effective repeat 3, the same 50 ordered routes,
optional Vmid sampling off, 2.5 V full scale, and ghost removal disabled.
Compared with the repeat-1 run, the frozen descriptor changes only requested /
effective repeat and the board-context fields containing that repeat.

All 60,737 acquired sweeps were submitted and archived, containing 3,036,850
retained values over 22.128149 s. Capture is complete, with zero device
discards, parser rejections, archive overruns or received gaps. Received
intervals are 363–365 us (median 364 us), maximum actual sampling period
365 us, and zero periods above 1 ms. The frame still contains one retained
sample per route: the repeated conversions do not widen the payload.

| Post-warm-up measurement | 10 MHz repeat 1 | 10 MHz repeat 3 |
| --- | ---: | ---: |
| A1_PZT5_L median, counts | 1946 | 1997 |
| A2_PZT5_L median, counts | 1978 | 2016 |
| Other ADC2 channels' median, counts | 2039 | 2036.5 |
| Other ADC4 channels' median, counts | 2040.5 | 2039 |
| Array 1 median envelope variation, counts | 0.488 | 0.459 |
| Array 2 median envelope variation, counts | 0.468 | 0.449 |
| Array 1 95th percentile envelope variation, counts | 0.622 | 0.959 |
| Array 2 95th percentile envelope variation, counts | 0.523 | 0.687 |
| Cross-array envelope correlation | 0.902 | 0.970 |
| Envelope recurrence, seconds | 1.32 | 1.32 |

Repeat 3 raises the PZT5_L baselines by 51 / 38 counts. Their deficits relative
to other channels on the same ADC narrow from 93 / 62.5 to 39.5 / 23 counts.
This demonstrates substantial sensitivity to the acquisition setting. It is
consistent with selection-time, input charging/leakage or mux-settling effects;
the setting also increases the time between revisits, so the result cannot
uniquely diagnose one of those mechanisms or exclude a sensor/circuit defect.

The synchronized burst pattern persists, with Array 1 recurrence correlation
0.852 at 1.32 s. Median variation decreases slightly, but upper-tail variation
increases approximately 54% / 31% versus the repeat-1 run. Extra conversions
therefore improve this channel's baseline without resolving the shared bursts.
These are separate runs without environmental controls, so the increases
should not be attributed exclusively to repeat count. Noise statistics use
the same 20 ms duration; repeat 3 naturally has fewer samples in each bin.

The fixed recurrence across 5/10/20 MHz and repeat 1/3, plus the absence of
sampling pauses in this run, supports investigating a common periodic source.
Mechanical stillness has been asked about and remains unconfirmed for this
run at the time of this report. A controlled stable-input/reference comparison
is the next way to separate sensor/strip response from acquisition-electronics
or shared bias/reference/supply/ground interference. The existing channel-quality
report's stable-input and sensor-connected controls remain applicable. No
new filtering, baseline compensation, GUI, firmware or wire changes were made.

Artifacts: [repeat-3 summary](10MHz_repeat3/summary.json),
[repeat-3 figure](10MHz_repeat3/raw_noise.png), and
[repeat comparison](repeat_comparison.json).
Illustrative windows: quiet 17.64–17.66 s and burst 19.38–19.40 s.
Three paired channels are constant in the short quiet window, so their
correlations are undefined; the analyzer excludes those pairs and records the
22 defined pairs instead of emitting nonstandard JSON NaN values. Full-run
envelope comparisons in the table do not depend on those illustrative windows.

## Follow-up: Array 1 strip disconnected, 10 MHz repeat 1, 12:39

Preserved and SHA256-verified the raw archive and timing file outside the cache:
`C:/Users/shera/Documents/sensetics/data/adc/speed_tests/20261008/10MHz_array1_disconnected_123911/`.
Source basename: `adc_data_20261008_123911_427281`. The capture is complete:
167,552 sweeps, 8,377,600 retained values, 22.786707 s. Its frozen acquisition
descriptor is identical to the earlier 10 MHz repeat-1 run: blocking/manual,
repeat 1, both arrays still selected, 50 routes, optional Vmid off and 2.5 V
full scale. Physical disconnection is user-reported and is not detectable from
the GUI's array-selection metadata.

The user clarifies that Array 1's board-side path remains connected to Vmid
through its bias resistor and unity buffer between the mux and ADC. With the
sensor strip removed, those ADCs are therefore measuring through that Vmid
bias/buffer path. This is **not an assumption of completely floating ADC
inputs**. It removes Array 1's sensor strip while retaining the board circuitry;
it is still different from a low-impedance source applied directly to every
mux input. The repo's mapped ADC1 / ADC2 bias values are 1 MOhm / 470 kOhm.

Firmware acquired 167,554 sweeps, submitted 167,552 and intentionally discarded
two. All submitted frames were archived. Parser rejections, archive overruns
and actual periods above 1 ms are zero. Received intervals have median 136 us,
maximum 405 us; maximum actual sampling period is 137 us. The missing
transmissions remain below the existing three-normal-period gap threshold.

| Post-warm-up measurement | Both strips connected, 10 MHz repeat 1 | Array 1 strip disconnected, same settings |
| --- | ---: | ---: |
| Array 1 median envelope variation, counts | 0.488 | 1.071 |
| Array 1 95th percentile envelope variation, counts | 0.622 | 1.804 |
| Array 2 median envelope variation, counts | 0.468 | 0.473 |
| Array 2 95th percentile envelope variation, counts | 0.523 | 0.504 |
| ADC2 channel 11 median, counts | 1946 | 1956 |
| Other ADC2 channels' median, counts | 2039 | 2022.5 |
| ADC4 channel 11 / A2_PZT5_L median, counts | 1978 | 1978 |
| Other ADC4 channels' median, counts | 2040.5 | 2040.5 |
| Cross-array envelope correlation | 0.902 | 0.827 |

Both envelopes retain their strongest 0.5–2 s recurrence at **1.32 s**;
autocorrelation is 0.920 for Array 1 and 0.680 for Array 2. Array 2's modulation
is much smaller than Array 1's; similar recurrence must not be described as
equal-amplitude bursts. On the disconnected side, per-ADC envelope 95th
percentiles rise from 0.736 to 1.944 counts on ADC1 and 0.569 to 1.712 on ADC2.
The connected ADC3 / ADC4 remain near 0.567 / 0.479 counts.

The recurring disturbance therefore does not require Array 1's sensor strip.
This substantially strengthens the case for a disturbance in, or coupled into,
the shared electronics/acquisition path. The ADC values alone do not separate
Vmid motion, Vref motion, bias/mux/buffer settling or leakage, supply/ground
coupling, external electrical pickup, or acquisition/host-related coupling.
Array 2 is still attached and can still affect shared circuitry, so this run
does not eliminate every sensor-connected coupling mechanism.

The disconnected ADC2 channel 11 remains 66.5 counts below other channels on
that ADC, but several other disconnected channels also shift; for example
ADC1 channel 0 is 1950 counts. These readings retain the software sensor labels
while no Array 1 sensor is physically attached. They must not be interpreted
as sensor voltages or forces. The persistence of low ADC2 channel-11 readings
through the board path reinforces the need for controlled electrical input
and scan-settling checks before assigning the original offset to a failed
PZT5_L sensor. Board-side bias/buffer loading and mux parasitics remain in the
measurement. TI also notes source-impedance and channel-charge limits in the
buffered-mux configuration; the unity buffer does not establish that the entire
preceding mux/bias path has settled. See
[ADS7953 datasheet, sections 9.1 and 9.2.2](https://www.ti.com/lit/ds/symlink/ads7953.pdf).

A useful next sensor-isolation run is **both strips disconnected**, with both
arrays still selected, 10 MHz, manual, repeat 1 and other settings unchanged.
If the pattern persists, neither attached sensor strip is necessary. That
result would still leave the bias/buffer/reference/supply and acquisition paths
to distinguish. A scope comparison of Vmid at its source, each relevant buffer
output and Vref during streaming can then test actual voltage movement; a
matched standalone-reader capture can separately test dependence on GUI/host
activity. Neither has been performed or inferred as a passed control here.

Artifacts: [disconnected-strip summary](10MHz_array1_disconnected/summary.json),
[annotated raw-data figure](10MHz_array1_disconnected/raw_noise.png),
and [connection comparison](disconnect_comparison.json).
Representative quiet / burst windows are 19.82–19.84 / 21.00–21.02 s, selected
using the connected Array 2 envelope. Full post-warm-up bins supply the table.
Existing GUI repairs, firmware and wire protocol remain unchanged.

## Follow-up: both sensor strips disconnected, 10 MHz repeat 1, 12:51

The completed source `adc_data_20261008_125137_577368` and its timing sidecar
were copied and SHA256-verified outside the GUI cache at
`C:/Users/shera/Documents/sensetics/data/adc/speed_tests/20261008/10MHz_both_disconnected_125137/`.
The user confirms that each ADC retains its Vmid bias resistor and unity buffer
between mux and ADC, with neither sensor strip attached. The descriptor is
identical to both earlier 10 MHz repeat-1 sensor-connection controls: both arrays
remain selected, all 50 routes, blocking/manual, optional Vmid off, 2.5 V full
scale. These are board-side Vmid/bias/buffer measurements, with physical
disconnection recorded from the user's description rather than inferred from
GUI metadata. They are not measurements of floating ADC pins or attached sensors.

Capture is complete: 147,191 submitted and archived sweeps, 7,359,550 retained
values over 20.020179 s. Firmware acquired 147,212 and intentionally discarded
21 (0.0143%). All submitted frames were archived; parser rejections and archive
overruns are zero. Median received interval is 136 us. One received interval
is 2,693 us at 12.617782 s; maximum actual sampling period is 137 us with zero
periods above 1 ms. This received gap represents missing transmissions, not a
matching ADC sampling pause. The recurring bursts continue throughout the run,
including illustrative windows away from that one received gap.

Both array envelopes have a strongest recurrence at **1.32 s** within the same
0.5–2 s search, with autocorrelations 0.909 / 0.908. Cross-array envelope
correlation is **0.9956**. Individual ADC envelope correlations are 0.986–0.997;
each ADC separately has the same 1.32 s recurrence. Neither sensor strip is
necessary for the periodic recorded disturbance.

| Per-ADC post-warm-up quantity | ADC1 | ADC2 | ADC3 | ADC4 |
| --- | ---: | ---: | ---: | ---: |
| Mapped bias resistor, kOhm | 1000 | 470 | 470 | 249 |
| Median 20 ms envelope variation, counts | 1.202 | 1.039 | 0.924 | 0.796 |
| 95th percentile envelope variation, counts | 2.028 | 1.796 | 1.555 | 1.284 |
| Median across channel DC baselines, counts | 1998 | 2022 | 2026.5 | 2034 |
| Channel 0 median, counts | 1950 | 1985 | 1994 | 2016 |
| Channel 11 median, counts | not sampled | 1955 | not sampled | 1986 |

The largest bias resistor corresponds to the largest variation and lowest
group baseline; the smallest corresponds to the smallest variation and highest
baseline. This is consistent with resistance-sensitive bias/loading/leakage
or settling effects, but does not prove that resistance alone causes either
the offset or the burst source. The two 470 kOhm ADC paths differ in amplitude
and baseline. Physical ADCs, routes, mux history, input parasitics and buffers
are not otherwise interchangeable controls.

The original PZT5_L-associated routes still read low without either sensor strip:
ADC2 channel 11 is 1955 versus 2022.5 for its other channels; ADC4 channel 11
is 1986 versus 2034. This places the persistent effect in the retained board /
acquisition setup rather than requiring those original physical sensors.
Channel 0 is also low on all four ADCs, strengthening the need to inspect mux
switching/scan history and board-side input conditions. The nominal Vmid voltage
and buffer part number are not yet known; these observations must not be called
absolute ADC offset errors against an unmeasured reference.

Compared with the connection controls, disconnecting each strip increases that
side's variation while the already-disconnected side remains similar:

| Array envelope 95th percentile, counts | Both strips connected | Only Array 1 disconnected | Both disconnected |
| --- | ---: | ---: | ---: |
| Array 1 | 0.622 | 1.804 | 1.900 |
| Array 2 | 0.523 | 0.504 | 1.356 |

Removing the strips changes the electrical loading while leaving the common
burst recurrence. This supports investigating the board's shared reference,
bias/buffer/mux paths, power/ground and acquisition-related electrical coupling.
It does not prove that Vmid itself moves: ADC code also depends on Vref and
conversion conditions. A unity buffer does not eliminate preceding source/mux
settling or offset from current through a high resistance. TI explains how
op-amp input bias current acting through source resistance contributes voltage
offset; this is a candidate mechanism, not a measured cause here. See
[TI Op Amp Offset Voltage and Bias Current Limitations](https://www.ti.com/lit/wp/sboa590/sboa590.pdf)
and the ADS7953 buffered-mux discussion cited above.

The next discrimination is an independent scope observation of Vmid at its
source, the relevant buffer outputs and Vref during streaming, using a sufficiently
long record to capture the approximately 1.32 s envelope. Faster transients
within bursts also matter; 1.32 s is not an identified interference carrier
frequency. If these analog voltages are quiet, inspect acquisition timing,
buffer/ADC input settling and digital coupling. A matched standalone-reader
capture can test dependence on GUI/host activity; raw-data presence alone does
not exclude host-induced electrical coupling. Scope availability, buffer part
number and nominal Vmid voltage have been requested; none is assumed here.
No firmware, wire protocol or GUI production code was changed.

Artifacts: [both-disconnected summary](10MHz_both_disconnected/summary.json),
[raw-data figure](10MHz_both_disconnected/raw_noise.png),
and [three-state sensor-isolation comparison](sensor_isolation_comparison.json).
Representative windows are quiet 17.68–17.70 s and burst 18.68–18.70 s;
full post-warm-up 20 ms bins supply the tables.

## Hardware clarification: OPA365 buffers and REF2025 reference

The user identifies each unity buffer as **OPA365**, and the reference as
**REF2025**, generating nominal 2.5 V Vref and 1.25 V Vmid. This supersedes
the earlier sections' unknown-part/unknown-nominal-voltage statements. It also
narrows the generic op-amp-bias-current hypothesis substantially.

The [OPA365 datasheet](https://www.ti.com/lit/ds/symlink/opa365.pdf), section 7.6,
lists room-temperature input bias current up to +/-10 pA and offset up to
200 uV under its stated test conditions. Across 1 MOhm, 10 pA produces 10 uV;
even adding 200 uV offset gives approximately 0.34 ADC count at 2.5 V full
scale. Its normal specified bias/offset therefore cannot account for the
sensor-free tens-of-count baseline deficits. This comparison does not exclude
external leakage, mux switching, loading/stability effects or an abnormal
operating condition. Datasheet section 8.3.3 also discusses the dependence of
unity-buffer stability on output loading and layout.

For a nominal 12-bit 0–2.5 V range, one quantization interval is
`2.5 / 4096 = 0.6103515625 mV`; ideal half-scale is near code 2048. The
sensor-free medians translate to the following **nominal ADC-equivalent**
differences, not independently measured analog voltages:

| ADC | Median across channel baselines | Deficit from nominal half-scale | OPA365 10 pA drop across mapped bias resistor |
| --- | ---: | ---: | ---: |
| ADC1 | 1998 | 30.52 mV | 10 uV |
| ADC2 | 2022 | 15.87 mV | 4.7 uV |
| ADC3 | 2026.5 | 13.12 mV | 4.7 uV |
| ADC4 | 2034 | 8.54 mV | 2.49 uV |

ADC2 channel 11 at 1955 corresponds to a nominal 56.76 mV deficit; ADC4
channel 11 at 1986 corresponds to 37.84 mV. The across-channel differences
on the same ADC also remain unexplained by a single constant buffer offset.
Mux/bias-node leakage and recharge, switching/scan history, buffer/ADC-drive
transients and board coupling remain candidates. Actual operating voltages,
temperature and circuit details still require measurement.

The [REF2025/REF20xx datasheet](https://www.ti.com/lit/gpn/REF20), sections 4
and 8.1, confirms the nominal outputs and describes a common band-gap source
with two independent output buffers. ADC code depends on the ratio:

```text
code approximately equals 4096 * ADC_input / Vref
at nominal half-scale:
delta_code approximately equals 1638.4 * delta_ADC_input[V] - 819.2 * delta_Vref[V]
```

If Vmid and Vref change in exactly the same proportion and the input path
tracks without extra error, their ratio is unchanged and that common change
cancels. Sharing one reference chip does not establish that real loading,
transients or noise on its separately buffered outputs track perfectly. Both
outputs must therefore be examined, along with each OPA365 output. The ADC
recording alone does not establish REF2025 failure or ordinary reference noise
as the cause of the 1.32 s disturbance.

A useful next check is an independent meter comparison of the REF2025 outputs
and OPA365 outputs while idle versus streaming. This can locate the average
DC shift without relying on the ADC's own voltage interpretation. If a scope
is available, capture the outputs over several seconds and inspect faster
switching/ringing within the burst intervals. Begin with the low-impedance
reference and buffer outputs: an ordinary probe on the high-resistance
mux/buffer-input node can load it and change the measurement. Measuring that
node requires accounting for probe resistance and capacitance. No resistor,
buffer, reference, firmware or protocol changes have been made.

Numerical artifact:
[buffer/reference comparison](buffer_reference_comparison.json).

## USB power hypothesis — 2026-10-08

The user reports that ADC +VA and OPA365 supplies use USB 5 V through a
ferrite bead and bypass capacitors, while REF2025 supplies the nominal
2.5 V reference and 1.25 V bias. No independent supply/ground measurements
or power-source A/B comparison have been performed yet. The stated clean
reference/bias does not establish that the analog supply and local grounds
are quiet at the converter and buffer pins.

The measured approximately 1.32 s burst-envelope recurrence does not match
normal USB bus framing: full-speed frames are 1 ms and high-speed microframes
are 125 us. The native CDC data endpoint is bulk in the installed Teensy
core, and bulk transfers have no reserved periodic bandwidth. See
[Microsoft USB bus timing](https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/transfer-data-to-isochronous-endpoints)
and [bulk scheduling](https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/usb-bulk-and-interrupt-transfer).
The installed `cores/teensy4/usb_serial.c` uses a 75 us transmit-flush timer;
the project's `usb_core_patch.py` retains that timer behavior. These facts
supply no explicit 1.32 s USB streaming cycle. Host/controller activity or
power-supply modulation could nevertheless have a slower envelope; no USB
traffic trace or electrical measurement has established such a connection.
The 20 ms envelope analysis is not a measurement of the interference carrier.

Electrical coupling remains plausible even when every USB frame arrives:
VBUS ripple/load transients, shared-return voltage differences, and data-line
or MCU switching coupling can affect the ADC/buffer path. This is a hypothesis,
not a demonstrated cause. The unchanged recurrence across engine and scan
cadence favors a disturbance with timing independent of those settings, but
does not identify USB rather than another common source.

TI explicitly calls for well-regulated ADS7953 supplies and close local
supply decoupling in [datasheet section 10](https://www.ti.com/lit/ds/symlink/ads7953.pdf).
The OPA365's [power-supply rejection curve, figure 7-2](https://www.ti.com/lit/ds/symlink/opa365.pdf)
is frequency dependent. Strong rejection of slow supply changes should not
be extrapolated to fast switching noise or local ground differences. A clean
reference does not independently eliminate disturbances through these paths.

A ferrite/capacitor filter is frequency dependent and is not a regulator or
ground isolator. Its impedance, loading and damping determine attenuation;
resonant peaking is possible. See [ADI AN-1368](https://www.analog.com/en/resources/app-notes/an-1368.html).
This does not establish inadequate filtering or resonance on this board;
component values, layout and measurements are still needed.

Useful controls without a firmware change:

1. Measure USB VBUS before the bead and the analog rail after it, at ADC +VA
   and buffer supply pins, relative to nearby analog ground. Compare burst
   and quiet intervals, including both the slow envelope and fast ripple.
   Also examine buffer output and local reference/bias at the converter.
   Use short probe ground connections; an ordinary probe on a high-resistance
   mux/input node can change the circuit being measured.
2. Keep USB data and the same benchmark configuration while supplying the
   analog branch from an independent clean regulated source, if that branch
   can be isolated. Disconnect its USB supply feed before applying another
   source; retain the required common ground for the existing nonisolated
   interfaces. Do not parallel an external source with USB VBUS. This tests
   the positive supply path but does not eliminate USB ground/data coupling.
3. A laptop-on-battery versus charger-connected comparison is a simple
   additional control for host power/ground-related coupling. A change would
   not distinguish charger common-mode noise from USB-rail changes by itself.

The channel-11 baseline is a separate observation: its strong channel and
scan-configuration dependence is not explained merely by identifying a shared
USB supply. The burst and baseline mechanisms must be tested independently.
No firmware, protocol or board wiring was changed for this assessment.
