# TestBoard 7953: production LPSPI optimization benchmark

Analyzed 2026-10-07; the run completed on 2026-10-06. All 252 production captures
passed on their first attempts. Independent whole-capture checks find no detected
replay, framing or timestamp fault. Manual LPSPI with both full arrays at 20 MHz
reaches 16,889 sweeps/s: 60.5% above the original and 22.0% above the repaired
first optimization. Long inter-sweep delays remain, so this is throughput and
stream-compatibility validation, not a worst-case latency or analog sign-off.

The [channel-quality follow-up](TESTBOARD_7953_CHANNEL_QUALITY_RESULTS.md)
finds localized noise increases and brief post-pause level dips. Baseline-relative
noise and cross-mode warnings were inactive because these ADC-order sessions
contain none of the runner's required interleaved-order reference tests.

## Inputs and verification

- Latest: `lpspi_word_path_production_adc_10_20`.
- Repaired first optimization: `optimization_after_usb_fix_adc_10_20`.
- Original: `optimization_baseline_adc_10_20`.
- All sessions are under `Arduino_Sketches/TestBoard_7953/benchmarks/results/`.
- Latest metadata reports profiling unavailable and disabled, confirming the
  production environment. Runner versions are 2.4, 2.3 and 2.2 respectively.
- Matched 84 configuration IDs and their routes, array selection, sequencing,
  engine, clock, repeat and Vmid settings, reference range, ADC payload order,
  1 s warm-up, 5 s window and three repetitions. The matrix includes all seven
  route sets, manual/Auto-1, blocking/DMA/LPSPI and both 10/20 MHz clocks.
- Independently decoded all 252 latest raw captures. Reconciled complete frame
  counts, warm-up cuts, retained counts and acquisition/period/gap medians with
  CSV. All frame headers/counts and sample ranges are valid. Complete frame
  records are unique, durations/periods are positive and timestamps do not
  overlap, with uint32 rollover handled explicitly.
- All repetition rows are PASS, attempt 1, without capture timeout or failed
  attempt log entries. Every reported ADC/start/channel/timeout/USB error and
  replay/regression/invalid-timing/framing/resynchronization/discard counter is zero.
- All 252 additive profile records decode and reconcile received counts. They
  confirm profiling unavailable/off; no cycle-phase attribution exists in this run.
- Latest contains 35,703,046 complete sweeps including warm-up and 29,766,941
  retained measurement sweeps. The large per-sample CSV was not scanned.
- Earlier metrics were reused from independently validated raw comparisons.
  Original full-array-1 Auto-1 blocking at 10 MHz has corrupt timestamps and is
  excluded from original rate conclusions. Repaired and latest captures for
  that configuration are clean. There are 83 valid original comparisons and
  84 valid repaired comparisons.
- Source results and firmware were not changed during analysis; no serial
  port or board upload was used. Metadata Git revision alone does not fingerprint
  the uncommitted profiling/optimization code or uploaded binary.
- The protocol has no sequence number/checksum. Clean checks establish absence
  of the detected faults, not detection of every possible lost/corrupt sample.

## Both full arrays at 20 MHz

Values are medians across three retained measurement windows. Sustained rate
is frames divided by first-start to last-end device elapsed time, not the
reciprocal of median period. It excludes waiting after the final acquisition.

| Mode | Original sweeps/s | First optimized + USB repair | Latest production sweeps/s | Gain vs original | Gain vs repaired | Latest acquisition / period, us |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| auto1 blocking | 10,101 | 11,105 | 11,529 | 14.14% | 3.82% | 85 / 87 |
| auto1 dma | 6,328 | 6,540 | 7,040 | 11.25% | 7.65% | 141 / 142 |
| auto1 lpspi | 11,241 | 13,860 | 16,279 | 44.82% | 17.46% | 60 / 61 |
| manual blocking | 9,441 | 11,190 | 11,377 | 20.50% | 1.67% | 86 / 88 |
| manual dma | 5,909 | 6,320 | 6,802 | 15.12% | 7.63% | 145 / 147 |
| manual lpspi | 10,524 | 13,841 | 16,889 | 60.48% | 22.03% | 58 / 59 |

Manual LPSPI acquisition is 91 -> 71 -> 58 us across the three stages; typical
period is 95 -> 72 -> 59 us. Its p99 period improves from 96 to 76 to 63 us.
Auto-1 LPSPI p99 improves from 90 to 76 to 65 us. Manual is about 3.8% faster
in this latest both-array comparison, while sparse routes still favor Auto-1.
Each full sweep contains 50 values: latest manual delivers about 844,469 channel
values/s and 1.925 MB/s of unchanged 114-byte wire frames.

## LPSPI at 20 MHz by topology

| Routes | Mode | Latest acquisition, us | Latest sweeps/s | Gain vs original | Gain vs repaired |
| --- | --- | ---: | ---: | ---: | ---: |
| all_four_full | manual | 58 | 16,889 | 60.48% | 22.03% |
| all_four_full | auto1 | 60 | 16,279 | 44.82% | 17.46% |
| full_array1 | manual | 40 | 24,001 | 47.48% | 16.51% |
| full_array1 | auto1 | 41 | 23,636 | 35.75% | 12.99% |
| all_four_sparse_unbalanced | manual | 24 | 38,952 | 64.79% | 18.83% |
| all_four_sparse_unbalanced | auto1 | 23 | 40,473 | 50.39% | 14.84% |

## Whole-matrix throughput

The following are unweighted medians of percentage changes across the 28
configurations per engine. They are not an aggregate sampling rate.

| Engine | Median gain vs repaired | Range vs repaired | Faster configurations |
| --- | ---: | ---: | ---: |
| blocking | 2.22% | 1.09% to 3.82% | 28 / 28 |
| dma | 3.69% | -1.13% to 7.65% | 26 / 28 |
| lpspi | 12.17% | 7.94% to 22.03% | 28 / 28 |

All 28 LPSPI configurations improve against both the original and repaired
production firmware. Their cumulative original gains range from 24.2% to 64.8%.
Every LPSPI/blocking median p99 period improves or stays equal to the repaired
baseline. Two DMA configurations have slightly worse rate and p99:
full-array-1 Auto-1 at 20 MHz (-1.13%, p99 93 -> 95 us), and full-array-1 manual
at 10 MHz (-0.71%, p99 121 -> 124 us). Functional checks pass. Three short
repetitions do not isolate compiler/timing changes from run variation; do not
claim universal DMA improvement. DMA mechanisms remain per-word and are still
substantially slower than LPSPI for both full arrays.

## Long inter-sweep delays remain

The retained measurement windows contain 239 periods above 1 ms, in 91 of
252 captures and 35 of 84 configurations. The repaired baseline had 247 in
98 captures and 39 configurations. These counts do not establish a reduction
in sporadic stall frequency, particularly because the latest build produces
more frames in the same window. All latest acquisition maxima are <=169 us;
long periods come from gaps between sweeps.

The longest retained period is 34,499 us in one-ADC bus 2 Auto-1 LPSPI at 20 MHz,
with a 34,482 us gap. The repaired matrix maximum was 30,120 us. Including
warm-up, there are 259 long periods and a 95,365 us maximum: one-ADC bus 2
manual blocking at 20 MHz, repetition 2, approximately 456 ms after the first
sweep. Its preceding acquisition is 18 us and gap is 95,347 us. Warm-up also
contains 95,154 us full-array-2 manual LPSPI and 94,704 us paired-ADC manual
LPSPI periods. These are valid positive gaps, not replay or timestamp regression.
Do not omit warm-up tails from latency conclusions just because headline rate
uses the retained measurement windows.

The prior enabled profiles attributed their long periods to USB writes.
That makes USB/backpressure and host-reader behavior the next latency target.
This production run has no phase profiling, so the individual new long gaps
cannot be assigned to USB, host scheduling or another foreground activity from
wire timestamps alone. In particular, the approximately 95 ms warm-up stalls
need controlled reader comparison rather than an assumed queue-size fix.

## Acceptance scope and next work

The benchmark supports accepting this stage for throughput and digital stream
compatibility in the tested matrix. Worst-case latency remains unresolved.
Channel-statistics medians shift up to 22 ADC codes versus the repaired
baseline; all benchmark signal thresholds pass. These sequential runs do not
isolate input/temperature changes from analog settling. Hardware CS/SCK framing,
CS-high time and representative analog/ghosting checks remain separate sign-off.
GUI support/testing remains deferred as requested.

Freeze this production result as the baseline for the next change. The next
firmware candidate should address USB submission/backpressure independently
of the SPI scheduler, with a bounded FIFO and submission that cannot block
sampling while capacity is unavailable. A FIFO alone cannot help if draining
it still calls a blocking write or if the reader is persistently too slow.
Define frame ownership, full-queue policy, partial writes, stop/drain/text ACK
ordering, disconnect and restart before implementation. Never silently drop
or replay samples. Compare a continuously draining reader and a controlled
slow-reader case, including warm-up, before selecting queue size and margins.
The measured 95 ms tail is evidence to investigate, not proof that a particular
queue size will suffice. See the [optimization plan](TESTBOARD_7953_NEXT_OPTIMIZATION_PLAN.md).

The full software matrix need not be repeated again before a new candidate
changes behavior. Preserve original directories and use a fresh result path
for future comparisons.
