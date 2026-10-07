# TestBoard 7953: completed live USB production matrix

Analyzed 2026-10-07. The production live-discard firmware completes all 252
ADC-order captures. Independent checks reconcile every saved raw capture with
its final result and device counters. No actual sampling interval exceeds
171 us in any engine, or 86 us in LPSPI. Both full arrays at 20 MHz, manual
LPSPI, retain approximately 16,887 sweeps/s with zero discarded sweeps in all
three repetitions. The selected LPSPI path has passed normal and forced-stall
validation; further firmware changes are not required to begin the planned GUI
repair. Localized blocking-mode dips and a both-array DMA rate decrease remain
separate findings.

The subsequent [manual LPSPI 30 MHz experiment](TESTBOARD_7953_LPSPI_30MHZ_RESULTS.md)
passes 21 captures and adds 14–23% throughput over matching 20 MHz settings.
Its channel-level and variation differences remain unresolved; 20 MHz stays
the production recommendation.

## Inputs and verification

Session: `Arduino_Sketches/TestBoard_7953/benchmarks/results/live_usb_production_adc_10_20`.
Completed 2026-10-07 at 19:46 UTC after resuming PC-standby and disk-full
interruptions. Runner 2.5; profiling unavailable/off; deferred parsing; no
deliberate reader pause; ADC payload order; repeat 1; optional between-channel
Vmid off; 1 s warm-up; 5 s measurement; seed 7953; no drift controls. Seven
route sets, manual/Auto-1, blocking/DMA/LPSPI and 10/20 MHz produce 84
configurations times three repetitions. Configuration fields and route lists
match the previous [production matrix](TESTBOARD_7953_LPSPI_PRODUCTION_RESULTS.md).

All 252 final repetition rows are PASS, with attempt field 1 and distinct
test/repetition keys. This does not mean the session had no interruptions:
the interrupted repetitions were rerun through `--resume`. The recorded Git
revision alone does not fingerprint the uncommitted firmware or uploaded binary.

Independently decoded all 252 raw captures. Checked complete frame boundaries,
headers, route counts, 12-bit sample ranges, exact whole-frame uniqueness,
positive durations, monotonically increasing nonoverlapping timestamps and
uint32 rollover. Reconciled warm-up cuts, measurement counts and timing medians.
Recomputed every measurement channel's median, minimum, maximum and sample
standard deviation from raw data and checked the channel-statistic CSV.
Stopped status counters agree with result columns, submitted frames and raw
counts. No source capture, firmware, serial connection or board upload was
changed for this analysis.

| Whole-matrix quantity | Result |
| --- | ---: |
| Acquired sweeps, including warm-up and discarded sweeps | 35,913,864 |
| Submitted and received complete frames | 35,909,837 |
| Intentionally discarded sweeps | 4,027 (0.01121%) |
| Captures with intentional discards | 54 of 252 |
| Received measurement values independently checked | 524,730,250 |
| Largest actual sensor sampling period, all engines | 171 us |
| Actual sensor periods above 1 ms | 0 |
| Largest gap between received frames | 3,454 us |

Acquired = submitted + discarded in every capture. All reported firmware/ADC
errors, framing/timestamp faults, resynchronizations, discarded bytes, trailing
bytes and capture timeouts are zero. Every channel passes the coarse startup
settling check, maximum 9.931 ms, within warm-up. This is not a measurement of
accuracy after each mux switch.

The previous production matrix had 259 actual inter-sweep periods above 1 ms
and a whole-run maximum of 95,365 us. The new sampling-period diagnostics
cover even discarded sweeps, whereas received gaps can now represent missing
transmissions. The new 3.454 ms received gap is therefore not a sensor pause.
The earlier [production forced-pause test](TESTBOARD_7953_LIVE_USB_PRODUCTION_RESULTS.md#production-forced-pause-validation)
also demonstrates continuous sampling through 500 ms reader pauses with no
large resumption dips.

## Throughput

Rates are medians of three measurement rates, each computed from received
frame count over first-start to last-end device elapsed time, not reciprocal
median period or wall time spent exporting files.

| Both full arrays, 20 MHz | Previous production sweeps/s | Live production sweeps/s | Change | Median acquisition / received period, us | Largest actual sampling period, us | Discards in r1 / r2 / r3 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Auto-1 blocking | 11,529 | 11,574 | +0.39% | 85 / 86 | 92 | 7 / 50 / 81 |
| Auto-1 DMA | 7,040 | 6,855 | -2.64% | 144 / 146 | 171 | 1 / 4 / 3 |
| Auto-1 LPSPI | 16,279 | 16,317 | +0.24% | 60 / 61 | 71 | 0 / 0 / 0 |
| Manual blocking | 11,377 | 11,419 | +0.38% | 86 / 88 | 89 | 33 / 69 / 20 |
| Manual DMA | 6,802 | 6,603 | -2.93% | 150 / 151 | 152 | 14 / 9 / 54 |
| Manual LPSPI | 16,889 | 16,887 | -0.01% | 58 / 59 | 64 | 0 / 0 / 0 |

Manual LPSPI still delivers approximately 844,361 channel values/s and
1.925 MB/s of unchanged 114-byte frames. It retains the approximately 60.5%
gain over the original firmware. Received-period p99 is 63 us in manual and
65 us in Auto-1. The live change addresses timing tails and continuity, not
another improvement to typical acquisition speed.

| Engine, across its 28 configurations | Median rate change | Range | Discarded sweeps | Largest actual sampling period, us |
| --- | ---: | --- | ---: | ---: |
| Blocking | +0.22% | -0.12% to +2.29% | 375 | 140 |
| DMA | -0.17% | -2.93% to +2.59% | 2,307 | 171 |
| LPSPI | +0.33% | -0.62% to +2.97% | 1,345 | 86 |

These percentage summaries weight configurations equally, not by sample count.
DMA's approximately 3% slowdown is concentrated in the both-array 20 MHz case;
it is not a 3% regression across all DMA configurations. Its acquisition medians
also increase, so omitted frames alone do not explain it. The cause is not
isolated. The previous matrix parsed during capture and the current one parses
afterward; host-dependent differences are not attributable solely to firmware.

Seven LPSPI captures discard sweeps: six both-array 10 MHz captures and one
manual sparse/unbalanced 20 MHz capture. Sensors stay continuous in all seven.
Both-array 20 MHz LPSPI, both full single arrays, and all single-ADC/one-ADC-per-bus
LPSPI captures discard none. The highest received rate is approximately
54,397 sweeps/s for single ADC1 Auto-1 LPSPI at 20 MHz; a GUI must handle more
frames/s for small channel selections than for both full arrays.

## Channel behavior

All **228,105,470** received LPSPI measurement values stay within seven counts
of their own channel's measurement median. None exceed eight counts. The earlier
large resumption dips are absent across all LPSPI route/clock/sequence selections
in this matrix. DMA likewise has no departures beyond eight counts.

Blocking has 24 negative excursions beyond eight counts, across 17 frames,
only on ADC2 channel 11 and ADC4 channel 11 in the both-array 20 MHz case.
Every excursion is at or within 1 ms after a received gap greater than 500 us.
The largest depth is 14 counts. Actual sampling remains continuous; the
mechanism is unresolved and must not be described as a millisecond sensor
sampling pause. The earlier [18-capture production test](TESTBOARD_7953_LIVE_USB_PRODUCTION_RESULTS.md#channel-statistics-and-remaining-dips)
showed the same affected channels, with depths up to 18 counts.

Median per-channel standard deviation for both-array manual LPSPI is
0.457 counts versus 0.524 previously; Auto-1 is 0.623 versus 0.592. Single ADC3
manual LPSPI is 0.583 versus 0.830 at 10 MHz and 0.475 versus 0.632 at 20 MHz.
These describe observed variation, not isolated electronic noise. Some
configurations have more variation and some less, without controlled inputs
or drift references to establish cause. Apply the board bias map separately:
ADC1 1 MOhm, ADC2/ADC3 470 kOhm, ADC4 249 kOhm. Charging toward Vmid,
leakage while unselected and mux settling remain relevant.

The ADC-order matrix has no eligible interleaved-order reference, so baseline
noise/cross-mode warnings remain inactive. The absence of warnings is not
analog sign-off. Discarded sample voltages are not available for inspection.
The wire format has no sequence number/checksum, so clean checks do not detect
every possible payload corruption. See the
[channel-quality review](TESTBOARD_7953_CHANNEL_QUALITY_RESULTS.md).

## Resume/export artifacts and retained evidence

The disk-full interruption occurred after capture diagnostics had been saved
but before that repetition's result row was committed. On resume the same
test/repetition/attempt key was measured again. Consequently:

- `firmware_profile.jsonl` contains 253 records for 252 final captures. Reconcile
  by test/repetition/attempt using the last matching record, checked against
  final raw counts and stopped status; do not blindly zip profile lines and rows.
- The approximately 87.5 GiB `benchmark_samples.csv` retains part of the aborted
  export followed by the rerun under the same key. At byte offset 56,083,756,740,
  its frame index restarts from 77,676 to 0 for both-array manual LPSPI 20 MHz r3.
  Do not use this CSV to count unique measurements or recompute statistics
  without removing that partial export. This analysis uses final raw captures,
  `benchmark_results.csv`, `benchmark_channel_stats.csv` and stopped status.

All 252 final raw captures and result keys reconcile, so no hardware rerun is
needed for this export artifact. Future benchmark improvements should make
per-repetition exports atomic or identify resumed attempts uniquely and make
expanded per-sample CSV export optional. The raw data and compact statistics
are sufficient for the checks here.

Older duplicate CSV exports were removed with user authorization; raw evidence
and summaries were retained. The five obsolete setup/smoke folders were then
removed manually by the user. No further deletion was performed during this
analysis. Avoid PC sleep during future captures; its confirmed interruption
is distinct from ordinary USB backpressure.

## Next step

Keep the currently uploaded production firmware and use manual LPSPI at 20 MHz
for the validated both-array workload. No further upload or repetition of this
matrix is required for the live USB fix. GUI work can proceed separately using
the [performance review](TESTBOARD_7953_GUI_PERFORMANCE_REVIEW.md): drain USB
promptly, batch processing, bound queues, render the newest snapshot, preserve
timestamp gaps and handle sleep/reconnection explicitly. These firmware tests
do not establish acquisition-to-display latency in the current GUI.

Retain the blocking-channel dip and both-array DMA slowdown as separate follow-up
issues. Controlled switching/sensor-input tests are still needed for stronger
analog settling and waveform claims. Independent SPI-bus scheduling and
sequence-wide DMA remain optional future throughput investigations, not
prerequisites for using the validated LPSPI stream.
