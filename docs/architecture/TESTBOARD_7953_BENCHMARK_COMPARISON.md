# TestBoard 7953 measured firmware comparison

Analyzed 2026-10-06, after the user uploaded candidate v2 and completed the
252-capture comparison. Firmware and the benchmark runner were not changed
during this analysis; no serial-port access was performed.

The subsequent USB repair has completed its focused 12-capture check and full
252-capture comparison with strict runner 2.3 checks. All repaired captures are
clean, with no failed attempts. Manual LPSPI at 20 MHz retains the 31.5% gain.
See [the final repaired-firmware results](TESTBOARD_7953_USB_FIX_BENCHMARK_RESULTS.md).
The figures and anomaly discussion below preserve the earlier, pre-repair run.

## Findings

For both full arrays (50 samples per sweep), manual LPSPI at 20 MHz improved
from **10,524 to 13,837 sustained sweeps/s: 31.5% faster**. Median acquisition
fell from 91 to 71 us, and the median start-to-start period from 95 to 72 us.
Auto-1 LPSPI reaches essentially the same optimized speed. The headline
configuration's timing sequence is clean in all three baseline and after captures.

Acquisition occupies 71 of the typical 72 us period. Removing a hypothetical
1 us foreground/USB gap entirely could improve this typical rate by only 1.4%.
Across whole measured windows the gap share is about 2.1%, including periodic
6 us gaps. Further throughput work should therefore target acquisition overhead.
The gap does not isolate USB from encoding and other foreground-loop work.

The candidate has 252 PASS results and zero reported DMA/LPSPI start,
transfer-timeout, or returned-channel errors. However, offline raw-data checks
found stream anomalies that the current PASS criteria do not reject. Treat the
run as a demonstrated speed improvement, not a clean stream-integrity sign-off.

## Inputs and method

- Baseline: `Arduino_Sketches/TestBoard_7953/benchmarks/results/optimization_baseline_adc_10_20`
- Candidate: `Arduino_Sketches/TestBoard_7953/benchmarks/results/optimization_after_adc_10_20_v2`
- Read `session_metadata.json`, repetition rows in `benchmark_results.csv`,
  `benchmark_channel_stats.csv`, and all 504 matching raw binary captures.
  The much larger per-sample CSVs were not scanned.
- Both sessions are complete. Matched 84 configuration IDs and their route
  lists, reference range, engines, sequence modes, SPI clocks, payload order,
  repeats, and Vmid settings. Runner version, 1 s warm-up, 5 s measurement,
  and three repetitions match. ADC order, repeat 1, optional Vmid off;
  drift controls were disabled as requested.
- Reconciled raw frame totals, discarded bytes, the runner's prefix-based
  warm-up cut, and measured frame counts against each repetition CSV row.
  Acquisition/period/gap medians independently reproduce the CSV values.
- Each table value is the median of the three per-repetition values.
  Sustained rate = retained frame count / (last end - first start), using
  wrap-safe 32-bit timestamps. Speed gain uses sustained rates, rather than
  reciprocal median periods. p99 values are calculated from individual raw
  periods per repetition, then combined by their median.
- A timestamp step greater than 2^31 us is classified as a backward step:
  an actual 32-bit timer rollover produces a small positive modulo delta.
  Such steps cannot be genuine gaps in these six-second captures.

## Both full arrays, 20 MHz

| Engine | Sequence | Acquisition before → after (us) | Period before → after (us) | Sustained before → after (sweeps/s) | Gain |
|---|---|---:|---:|---:|---:|
| blocking | auto1 | 95 → 87 | 99 → 88 | 10,101 → 11,302 | 11.9% |
| dma | auto1 | 154 → 151 | 158 → 153 | 6,328 → 6,553 | 3.6% |
| lpspi | auto1 | 85 → 71 | 89 → 72 | 11,241 → 13,836 | 23.1% |
| blocking | manual | 102 → 88 | 106 → 90 | 9,441 → 11,105 | 17.6% |
| dma | manual | 165 → 157 | 169 → 159 | 5,909 → 6,320 | 7.0% |
| lpspi | manual | 91 → 71 | 95 → 72 | 10,524 → 13,837 | 31.5% |

Manual LPSPI p99 period improved from 96 to 76 us; Auto-1 from 90 to 76 us.
Both optimized LPSPI modes have a maximum period of 77 us and no period above
100 us across their three measured windows. Acquisition maxima are 72 us.
At 10 MHz, full-array manual LPSPI improves from 118 to 90 us acquisition,
122 to 92 us median period, with a 33.2% sustained-rate gain.

The existing DMA engine remains substantially slower for this workload:
157 us manual / 151 us Auto-1 acquisition at 20 MHz versus 71 us LPSPI.
This measures the present per-word DMA implementation; it does not establish
the performance of a redesigned hardware-paced DMA acquisition engine.

## Stream anomalies and limits of PASS

Two configuration comparisons are excluded from sustained-rate and tail
conclusions. All six repetitions have backward timestamp steps even though
their individual acquisition durations remain plausible:

| Session / configuration (all at 10 MHz, full array 1) | Repetition | Backward steps in whole capture | Backward steps after runner warm-up | Discarded bytes |
|---|---:|---:|---:|---:|
| Baseline Auto-1 blocking | 1 | 2 | 2 | 0 |
| Baseline Auto-1 blocking | 2 | 8 | 8 | 0 |
| Baseline Auto-1 blocking | 3 | 7 | 6 | 64 |
| Candidate manual LPSPI | 1 | 1683 | 1419 | 64 |
| Candidate manual LPSPI | 2 | 1618 | 1364 | 128 |
| Candidate manual LPSPI | 3 | 1597 | 1579 | 128 |

There are 17 backward steps in the baseline configuration and 4,898 in the
candidate configuration, including steps during the measured windows.
The other 498 captures have no backward steps or parser-discarded bytes.

The baseline also contains one 64-byte damaged slot beginning `#OK false`.
The candidate contains 64, 128, and 128 bytes of status-text fragments, including
`vmid_between_channels_requested=false`, `route_count=25`, and `active_adcs=1,2`.
These fragments occur about 0.126, 0.271, and 0.190 seconds from the first
frame's timestamp, near startup. They do not explain away the subsequent
backward steps: those also occur after the retained measurement starts.
Each of these 25-sample binary frames is exactly 64 bytes long.

In the third affected repetition in each session, the runner's retained
first-to-last timestamp span is about 19.2 seconds instead of about 5 seconds.
Warm-up slicing and unsigned period calculations cannot be trusted on a
nonmonotonic stream. Consequently, the affected candidate's apparent sustained
gain and its approximately 2^32 us tail values are omitted from conclusions.
Its medians remain useful provisional indicators, but are not a reliability
validation. No data has been silently repaired or removed from the original files.

The runner rejects invalid frame counts, incomplete trailing frames, timeouts,
sample integrity failures and firmware error counters. Its parser accepts a
matching header/count without checking timestamp continuity. Resynchronization
and discarded-byte counts alone do not fail a repetition. This explains how the
candidate can report 252 PASS despite the observed anomalies. The baseline
reports 251 PASS and one WARN for settling.

The raw bytes establish inconsistent transport data, not its origin. Firmware
packet construction, USB buffering/cache behavior, command/stream boundaries,
host capture, and possible replay need to be distinguished. No sequence number
or checksum is present, so long positive gaps alone cannot prove dropped frames.
Raw capture files also do not retain host arrival timestamps.

Subsequent diagnosis identified 9,134 exact replayed frames in the affected
candidate captures and reproduced a compiler-ordering race in the compiled
Teensy USB write/automatic-flush implementation. See
[the USB stream diagnosis](TESTBOARD_7953_USB_STREAM_DIAGNOSIS.md) for the
machine-code evidence, deterministic reproduction, proposed repair, and
remaining on-board validation. Firmware and the original captures remain unchanged.

Other clean configurations can still have rare long foreground gaps. For example,
one-ADC LPSPI at 20 MHz has an observed maximum period near 28 ms. These are
separate from the clean full-array LPSPI 20 MHz results and should be investigated
if latency matters; a faster median does not eliminate backpressure everywhere.

## Analog comparison

The largest median code difference across matched channels is -27 counts
(ADC 2, channel 11, full array 1 manual LPSPI 10 MHz), which is in an affected
capture configuration. Among the configurations with clean timing streams,
the largest absolute difference is 19 counts on the same ADC/channel in full
array Auto-1 LPSPI 20 MHz. Several other shifts are 15–18 counts.
This is not evidence of identical analog behavior. Separate before/after runs
without a controlled reference cannot distinguish input/temperature drift,
settling changes, and transport effects. Mandatory parking and conversion
timing constraints should remain intact through further optimization.

## Recommended next work

1. Diagnose the 64-byte stream anomaly first. Use a focused full-array-1 test
   in the two affected modes, validate monotonic timestamps and preserve raw
   captures. Add explicit timestamp/resynchronization verdicts to a new runner
   revision once the cause is understood; preserve these existing results and
   their runner version. Distinguish replay, corruption and missed frames before
   choosing a USB or firmware fix. Revalidate the same matrix after the fix.
2. Profile LPSPI acquisition phases with a logic analyzer or temporary timing
   instrumentation: bus/session setup, GPIO/CS, register polling, inter-word work,
   and payload stores. Sampling consumes almost all the full-array period.
   Optimize the dominant phase while retaining CS and ADC pipeline constraints.
   Independent bus progress may help unbalanced routes, but requires measurement.
3. Check production GUI throughput and stop behavior separately. The benchmark
   measures a capture reader; plotting and processing have different workloads.
   Investigate rare enqueue/foreground stalls and write completion before adding
   an application queue. An extra queue alone has little typical full-array
   throughput headroom in the current measurements.

No additional optimization or protocol change was implemented during this analysis.

## All 84 matching configurations

Values marked `exclude` retain provisional acquisition/period medians but omit
sustained gains because one side has stream anomalies. For every other row,
the sustained rate improved in this session pair. Results describe these captures,
not guaranteed gains under arbitrary host load.

| Routes | MHz | Sequence | Engine | Acquisition before → after (us) | Period before → after (us) | Sustained gain |
|---|---:|---|---|---:|---:|---:|
| all_four_full | 10 | auto1 | blocking | 140 → 131 | 144 → 133 | 8.2% |
| all_four_full | 20 | auto1 | blocking | 95 → 87 | 99 → 88 | 11.9% |
| all_four_full | 10 | auto1 | dma | 171 → 163 | 174 → 164 | 6.3% |
| all_four_full | 20 | auto1 | dma | 154 → 151 | 158 → 153 | 3.6% |
| all_four_full | 10 | auto1 | lpspi | 109 → 88 | 113 → 90 | 26.3% |
| all_four_full | 20 | auto1 | lpspi | 85 → 71 | 89 → 72 | 23.1% |
| all_four_full | 10 | manual | blocking | 150 → 136 | 153 → 137 | 11.7% |
| all_four_full | 20 | manual | blocking | 102 → 88 | 106 → 90 | 17.6% |
| all_four_full | 10 | manual | dma | 183 → 169 | 187 → 170 | 9.6% |
| all_four_full | 20 | manual | dma | 165 → 157 | 169 → 159 | 7.0% |
| all_four_full | 10 | manual | lpspi | 118 → 90 | 122 → 92 | 33.2% |
| all_four_full | 20 | manual | lpspi | 91 → 71 | 95 → 72 | 31.5% |
| all_four_sparse_unbalanced | 10 | auto1 | blocking | 54 → 48 | 56 → 49 | 14.8% |
| all_four_sparse_unbalanced | 20 | auto1 | blocking | 38 → 32 | 40 → 33 | 21.8% |
| all_four_sparse_unbalanced | 10 | auto1 | dma | 66 → 59 | 68 → 61 | 11.9% |
| all_four_sparse_unbalanced | 20 | auto1 | dma | 59 → 55 | 62 → 56 | 9.9% |
| all_four_sparse_unbalanced | 10 | auto1 | lpspi | 44 → 34 | 46 → 35 | 32.6% |
| all_four_sparse_unbalanced | 20 | auto1 | lpspi | 35 → 27 | 37 → 28 | 31.2% |
| all_four_sparse_unbalanced | 10 | manual | blocking | 63 → 54 | 65 → 56 | 17.9% |
| all_four_sparse_unbalanced | 20 | manual | blocking | 44 → 35 | 46 → 36 | 27.3% |
| all_four_sparse_unbalanced | 10 | manual | dma | 78 → 68 | 80 → 70 | 15.7% |
| all_four_sparse_unbalanced | 20 | manual | dma | 70 → 63 | 72 → 64 | 12.3% |
| all_four_sparse_unbalanced | 10 | manual | lpspi | 51 → 37 | 53 → 38 | 39.3% |
| all_four_sparse_unbalanced | 20 | manual | lpspi | 40 → 29 | 42 → 30 | 39.1% |
| full_array1 | 10 | auto1 | blocking | 70 → 67 | 73 → 68 | exclude |
| full_array1 | 20 | auto1 | blocking | 48 → 44 | 51 → 45 | 11.7% |
| full_array1 | 10 | auto1 | dma | 119 → 115 | 122 → 116 | 4.5% |
| full_array1 | 20 | auto1 | dma | 98 → 94 | 100 → 95 | 4.5% |
| full_array1 | 10 | auto1 | lpspi | 78 → 70 | 81 → 71 | 14.0% |
| full_array1 | 20 | auto1 | lpspi | 55 → 47 | 57 → 48 | 19.2% |
| full_array1 | 10 | manual | blocking | 76 → 68 | 78 → 69 | 12.9% |
| full_array1 | 20 | manual | blocking | 50 → 44 | 53 → 45 | 17.5% |
| full_array1 | 10 | manual | dma | 127 → 119 | 130 → 121 | 7.3% |
| full_array1 | 20 | manual | dma | 104 → 97 | 107 → 98 | 8.6% |
| full_array1 | 10 | manual | lpspi | 83 → 72 | 86 → 74 | exclude |
| full_array1 | 20 | manual | lpspi | 59 → 48 | 61 → 49 | 25.0% |
| full_array2 | 10 | auto1 | blocking | 70 → 67 | 73 → 68 | 8.1% |
| full_array2 | 20 | auto1 | blocking | 48 → 44 | 51 → 45 | 11.9% |
| full_array2 | 10 | auto1 | dma | 119 → 116 | 122 → 117 | 4.6% |
| full_array2 | 20 | auto1 | dma | 98 → 94 | 101 → 96 | 5.5% |
| full_array2 | 10 | auto1 | lpspi | 81 → 70 | 84 → 72 | 17.2% |
| full_array2 | 20 | auto1 | lpspi | 58 → 49 | 60 → 50 | 20.3% |
| full_array2 | 10 | manual | blocking | 76 → 68 | 78 → 69 | 13.0% |
| full_array2 | 20 | manual | blocking | 50 → 44 | 53 → 45 | 17.8% |
| full_array2 | 10 | manual | dma | 127 → 121 | 130 → 122 | 6.7% |
| full_array2 | 20 | manual | dma | 105 → 99 | 107 → 100 | 7.4% |
| full_array2 | 10 | manual | lpspi | 87 → 74 | 90 → 75 | 18.6% |
| full_array2 | 20 | manual | lpspi | 62 → 50 | 64 → 51 | 25.8% |
| one_adc_bus1 | 10 | auto1 | blocking | 29 → 28 | 31 → 29 | 8.9% |
| one_adc_bus1 | 20 | auto1 | blocking | 20 → 18 | 22 → 19 | 12.7% |
| one_adc_bus1 | 10 | auto1 | dma | 49 → 47 | 50 → 48 | 5.4% |
| one_adc_bus1 | 20 | auto1 | dma | 40 → 38 | 42 → 39 | 6.6% |
| one_adc_bus1 | 10 | auto1 | lpspi | 32 → 29 | 34 → 30 | 12.6% |
| one_adc_bus1 | 20 | auto1 | lpspi | 23 → 20 | 25 → 21 | 18.4% |
| one_adc_bus1 | 10 | manual | blocking | 31 → 28 | 33 → 30 | 12.1% |
| one_adc_bus1 | 20 | manual | blocking | 21 → 18 | 23 → 20 | 17.4% |
| one_adc_bus1 | 10 | manual | dma | 53 → 49 | 55 → 50 | 8.0% |
| one_adc_bus1 | 20 | manual | dma | 43 → 40 | 45 → 41 | 10.0% |
| one_adc_bus1 | 10 | manual | lpspi | 35 → 30 | 37 → 32 | 15.8% |
| one_adc_bus1 | 20 | manual | lpspi | 25 → 20 | 27 → 22 | 23.5% |
| one_adc_bus2 | 10 | auto1 | blocking | 29 → 27 | 31 → 29 | 9.2% |
| one_adc_bus2 | 20 | auto1 | blocking | 20 → 18 | 22 → 19 | 12.9% |
| one_adc_bus2 | 10 | auto1 | dma | 49 → 47 | 51 → 48 | 5.9% |
| one_adc_bus2 | 20 | auto1 | dma | 40 → 38 | 42 → 39 | 6.8% |
| one_adc_bus2 | 10 | auto1 | lpspi | 33 → 29 | 35 → 30 | 16.2% |
| one_adc_bus2 | 20 | auto1 | lpspi | 24 → 20 | 26 → 22 | 18.7% |
| one_adc_bus2 | 10 | manual | blocking | 31 → 28 | 33 → 30 | 12.4% |
| one_adc_bus2 | 20 | manual | blocking | 21 → 18 | 23 → 20 | 18.3% |
| one_adc_bus2 | 10 | manual | dma | 53 → 50 | 55 → 51 | 7.3% |
| one_adc_bus2 | 20 | manual | dma | 44 → 41 | 45 → 42 | 8.6% |
| one_adc_bus2 | 10 | manual | lpspi | 36 → 31 | 38 → 32 | 19.7% |
| one_adc_bus2 | 20 | manual | lpspi | 26 → 21 | 28 → 22 | 24.8% |
| one_adc_each_bus | 10 | auto1 | blocking | 57 → 54 | 60 → 55 | 8.7% |
| one_adc_each_bus | 20 | auto1 | blocking | 39 → 35 | 41 → 37 | 13.1% |
| one_adc_each_bus | 10 | auto1 | dma | 70 → 66 | 72 → 67 | 7.0% |
| one_adc_each_bus | 20 | auto1 | dma | 63 → 62 | 65 → 63 | 4.3% |
| one_adc_each_bus | 10 | auto1 | lpspi | 45 → 37 | 48 → 38 | 25.8% |
| one_adc_each_bus | 20 | auto1 | lpspi | 35 → 30 | 37 → 31 | 21.3% |
| one_adc_each_bus | 10 | manual | blocking | 62 → 56 | 65 → 58 | 12.3% |
| one_adc_each_bus | 20 | manual | blocking | 42 → 36 | 45 → 38 | 18.9% |
| one_adc_each_bus | 10 | manual | dma | 77 → 70 | 79 → 71 | 10.8% |
| one_adc_each_bus | 20 | manual | dma | 68 → 65 | 71 → 66 | 7.2% |
| one_adc_each_bus | 10 | manual | lpspi | 49 → 38 | 51 → 39 | 32.5% |
| one_adc_each_bus | 20 | manual | lpspi | 38 → 30 | 40 → 31 | 29.0% |
