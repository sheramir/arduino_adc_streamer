# TestBoard 7953: experimental manual LPSPI at 30 MHz

Analyzed 2026-10-07. All 21 measured captures pass independent raw-data and
counter checks. Compared with the matching live production 20 MHz captures,
the requested 30 MHz clock increases delivered throughput by approximately
14–23%, depending on route selection. Both full arrays reach 19,394 sweeps/s,
14.8% above 20 MHz. No detected digital errors or large signal excursions occur.
Some channel variation and level shifts warrant analog follow-up before using
30 MHz routinely; retain 20 MHz as the production recommendation.

## Inputs and verification

Sessions under `Arduino_Sketches/TestBoard_7953/benchmarks/results/`:

- Experimental: `live_usb_production_manual_lpspi_adc30`, completed
  2026-10-07 at 20:29 UTC.
- Reference: matching manual LPSPI 20 MHz repetitions in
  `live_usb_production_adc_10_20`, independently validated in the
  [full-matrix report](TESTBOARD_7953_LIVE_USB_FULL_MATRIX_RESULTS.md).

Both use the production live-discard stream, runner 2.5, profiling off/unavailable,
deferred parsing, ADC payload order, repeat 1, optional between-channel Vmid
off, 1 s warm-up, 5 s measurement, three repetitions and no drift controls.
Route lists and the remaining acquisition settings match. Seven route selections
produce 21 measured captures, all PASS on attempt 1. Both automatic blocking
startup smoke checks at 30 MHz also pass; these are separate from the measured
LPSPI results. No recovery failures appear in the command log.

Independently decoded all 21 saved raw captures and checked frame boundaries,
headers, route counts, 12-bit ranges, positive durations, timestamp progression,
uint32 rollover, nonoverlapping sweeps and exact frame uniqueness. Reconciled
raw counts with stopped device counters, final result rows and all 21 profiling
records. Recomputed every measurement channel's sample count, median, extrema
and sample standard deviation, matching the channel-statistic CSV. No board
upload, serial-port access or source-capture changes were made for this analysis.

| Whole-session quantity | Result |
| --- | ---: |
| Acquired sweeps, including warm-up and omitted transmissions | 5,353,505 |
| Submitted and received complete frames | 5,353,249 |
| Intentionally discarded sweeps | 256 (0.00478%) |
| Received measurement values checked | 79,449,845 |
| Largest actual sampling period | 56 us |
| Actual sampling periods above 1 ms | 0 |
| Largest received gap | 3,870 us |
| Largest departure from a channel's own measurement median | 5 counts |

Acquired = submitted + discarded in every capture. All firmware/ADC errors,
LPSPI start errors, transfer timeouts, returned-channel errors, USB write errors,
framing faults, timestamp faults, resynchronizations, discarded bytes, trailing
bytes and capture timeouts are zero. Thus the observed rate of the detected
digital fault categories is zero over 5,353,249 received frames. This does not
establish an analog error rate: plausible incorrect codes can retain valid
channel IDs, and the wire format has no checksum or frame sequence number.
Discarded sample voltages are unavailable for inspection.

All channels pass the coarse startup check, maximum 4.535 ms, within warm-up.
This check does not establish accuracy immediately after every mux switch.

## Speed compared with 20 MHz

Rates use received measurement count over first-start to last-end device
elapsed time, with the median rate across three repetitions. They do not use
reciprocal median period or file-export wall time. Settings differ in clock;
the experiments were separate sessions, without alternating clock controls.

| Selection | 20 MHz sweeps/s | 30 MHz sweeps/s | Gain | Median acquisition, 20 / 30 MHz, us |
| --- | ---: | ---: | ---: | ---: |
| Both full arrays | 16,887 | 19,394 | +14.8% | 58 / 50 |
| Full array 1 | 24,042 | 29,532 | +22.8% | 40 / 33 |
| Full array 2 | 23,874 | 29,280 | +22.6% | 41 / 33 |
| Single ADC1 | 54,062 | 65,372 | +20.9% | 17 / 14 |
| Single ADC3 | 53,731 | 64,887 | +20.8% | 17 / 14 |
| ADC1 and ADC3, one on each bus | 38,625 | 44,020 | +14.0% | 25 / 21 |
| All four, sparse/unbalanced | 39,363 | 44,954 | +14.2% | 24 / 21 |

Both-array median received period falls from 59 to 51 us, with p99 of 55 us
and actual maximum of 56 us. Its 114-byte frame stream carries approximately
2.211 MB/s and 969,683 channel values/s. Single ADC1 reaches approximately
2.223 MB/s with 34-byte frames. The increase in requested SPI clock does not
produce a proportional sweep-rate gain; other per-word and sweep overheads
remain. This run is not phase-profiled and does not isolate those costs.

The status field records the requested clock, not an oscilloscope measurement.
The local Teensy SPI library normally selects a 240 MHz peripheral root and
integer divider, which implies 30 MHz for this request and 20 MHz for the
reference. This is an inference from local code, not a measured SCLK waveform
or an uploaded-binary fingerprint.

## USB continuity

Twenty captures discard no sweeps. Single ADC1 repetition 2 discards 256 sweeps,
0.0653% of that whole capture, with a 3.870 ms received gap approximately
2.952 s into the measurement window. The actual sensor sampling maximum is
20 us in that capture. This is an omitted transmission interval, not a sensor
sampling pause. The capture's rate is 65,321 sweeps/s versus approximately
65,372/s in the other two repetitions.

The first 10 ms received after the gap stay within three counts of each
channel's own whole-measurement median. The largest shift between pre-gap
and post-gap 10 ms channel medians is one count. No large resumption dip is
observed. All three both-array repetitions discard zero sweeps.

## Channel variation and level shifts

For each configuration/channel, take the median statistic across three
repetitions, then the median across channels. Values below are ADC counts.
Whole-window standard deviation includes signal variation and drift; it is not
an isolated electronic-noise measurement.

| Selection | Whole-window standard deviation, 20 MHz | 30 MHz |
| --- | ---: | ---: |
| Both full arrays | 0.457 | 0.562 |
| Full array 1 | 0.492 | 0.469 |
| Full array 2 | 0.486 | 0.453 |
| Single ADC1 | 0.463 | 0.533 |
| Single ADC3 | 0.475 | 0.513 |
| ADC1 and ADC3 | 0.573 | 0.546 |
| Sparse/unbalanced | 0.492 | 0.446 |

Both-array variation rises approximately 22.9%. Per-ADC medians rise as follows:

| ADC / board bias | 20 MHz | 30 MHz | Change |
| --- | ---: | ---: | ---: |
| ADC1 / 1 MOhm | 0.498 | 0.637 | +28.1% |
| ADC2 / 470 kOhm | 0.421 | 0.568 | +34.8% |
| ADC3 / 470 kOhm | 0.474 | 0.574 | +21.1% |
| ADC4 / 249 kOhm | 0.395 | 0.502 | +27.3% |

As a supplemental check, recomputed sample standard deviations inside 10 ms
device-time windows, then took medians across windows, repetitions and channels.
Both-array values are 0.447 counts at 20 MHz and 0.477 at 30 MHz, approximately
6.6% higher. The smaller short-window difference indicates that the whole-window
increase also includes variation at longer timescales; it cannot all be assigned
to random high-frequency noise. Neither statistic isolates clock causality.

Channel levels also differ between the sessions. Comparing each channel's
median across three repetitions, the largest shifts are -10 counts on ADC4
channels 11 and 12 in full array 2; ADC2 channels 11–13 in full array 1 shift
-9 counts. Both-array ADC4 channel 11 shifts -9 and ADC2 channel 11 shifts -8.
These stable level differences would not be detected by checking only departures
from each run's own median. They do not prove corrupted ADC words, but warrant
settling/accuracy follow-up. Faster conversion timing, sensor charging/leakage,
source impedance and input drift are possible contributors; the data do not
separate them. Apply each ADC's bias resistor and mux sequence separately.

No received measurement value in the 30 MHz session departs more than five
counts from its own channel median. The earlier large post-stall dips are absent.
Baseline-dependent noise/cross-mode warnings are inactive in this ADC-order
subset, so PASS does not establish equivalence to 20 MHz signal quality.

## Decision and next work

The [ADS7953 datasheet](https://www.ti.com/lit/ds/symlink/ads7953.pdf), sections
7.3 and 7.9, specifies a maximum 20 MHz SCLK. Treat this 30 MHz result as
experimental: useful speed gain and no detected digital faults on this board
under these inputs, with unresolved analog level/variation differences. Keep
20 MHz as the production recommendation; no firmware change was made here.

If choosing 30 MHz for regular use, first run a controlled 20–30–20 MHz
comparison with repeatable inputs on the affected ADC2/ADC4 channels, including
input steps/mux settling and longer captures. Existing quiet-input captures
cannot establish waveform accuracy, temperature margin or behavior on other
boards. A repeat of all engines is not needed for that question.

GUI repair can proceed separately with the
[performance review](../../../reports/gui/TESTBOARD_7953_GUI_PERFORMANCE_REVIEW.md). If experimental
30 MHz operation is to be supported, add capacity tests around 20,000 frames/s
for 50 routes and 75,000 frames/s for 10 routes, with burst testing. These are
provisional host capacity targets above the measured rates, not firmware rate
guarantees. Preserve MCU timestamp gaps and distinguish intentional USB omissions
from detected transfer faults and archive overruns.
