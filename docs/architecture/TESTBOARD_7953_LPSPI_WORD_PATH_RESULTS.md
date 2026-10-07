# TestBoard 7953: LPSPI word-path benchmark results

Analyzed 2026-10-06. All 18 new captures passed on their first attempts. Against
the matched diagnostic-build baseline with profiling off, sustained sampling
improved 21.0% for both full arrays, 14.6% for array 1 and 18.2% for sparse routes.
The cycle profiles confirm savings inside the SPI transfer loop. Rare USB write
stalls remain. Firmware and original benchmark files were not changed during
this analysis.

## Inputs and checks

The new sessions are `lpspi_word_path_off_adc20` and
`lpspi_word_path_on_adc20`. Their baselines are `phase_profile_off_adc20_v2` and
`phase_profile_on_adc20_v2`, under
`Arduino_Sketches/TestBoard_7953/benchmarks/results/`.

Settings match: three route sets, manual LPSPI, requested 20 MHz SPI clock,
ADC payload order, repeat 1, optional Vmid off, 1 s warm-up, 5 s measurement,
three repetitions and no drift controls. Route lists and requested/effective
configuration fields match. Both builds expose profiling and both runners are
version 2.4. CPU frequency is 600 MHz in the enabled profiles. Compare off
against off for throughput and on against on for phase attribution.

All 18 repetition rows are PASS, attempt 1, without capture timeout or failed
attempt log entries. Firmware ADC/start/timeout/channel/USB errors and stream
replay/regression/invalid-timing/framing/resynchronization/discard counters are
zero. Independently decoded all new raw captures and reconciled their whole-run
counts, warm-up cuts, measurement counts and acquisition/period/gap medians.
Headers and route counts are valid, complete frame records are unique,
durations/periods are positive, and sweep timestamps do not overlap.

The two new sessions contain 2,756,465 complete sweeps including warm-up and
2,295,235 retained measurement sweeps. All enabled profile summaries decode
consistently, with zero aborted sweeps, frequency changes or ambiguous foreground
intervals. Their 1,336,844 complete writes equal the full-capture received counts.
Whole-run period/gap counts, totals, maxima, threshold counts and histograms
match independent raw timestamp calculations. Each recorded tail's period/gap
occurs in its raw capture.

These checks establish the observed stream's consistency. The protocol has no
sequence number/checksum, so they do not prove detection of every possible
missing frame or payload corruption. Historical and current metadata retain
the same Git revision because the profiling/candidate edits are not committed;
that revision alone is not a firmware binary fingerprint.

## Throughput with profiling off

Values are medians across three measurement windows. Sustained sweeps/s uses
received frames divided by first-start to last-end device elapsed time, rather
than the reciprocal of median period.

| Routes | Acquisition before / after, us | Period before / after, us | Sweeps/s before | Sweeps/s after | Rate gain |
| --- | ---: | ---: | ---: | ---: | ---: |
| Both full arrays (50) | 71 / 58 | 72 / 60 | 13,773 | 16,671 | 21.04% |
| Array 1 (25) | 47 / 41 | 48 / 42 | 20,787 | 23,822 | 14.60% |
| Sparse/unbalanced (15) | 29 / 25 | 31 / 26 | 32,430 | 38,317 | 18.15% |

Candidate and baseline rate ranges do not overlap in any topology. Both full
arrays range from 13,772-13,777 to 16,665-16,678 sweeps/s. Array 1 ranges from
20,787-20,795 to 23,814-23,823, and sparse routes from 32,426-32,501 to
38,310-38,336. The gain is consistent across these repetitions.

Median p99 periods improve from 77 to 64 us for both arrays, 50 to 44 us for
array 1 and 35 to 30 us for sparse routes. Median inter-sweep gap stays at 1 us.
This is a faster ordinary acquisition path, with rare long gaps still present.

## Phase attribution with profiling on

The table uses medians of whole-run cycle-phase means, including warm-up.
Those are a different scope from the measurement-window medians above.

| Routes | Transfer before / after, us | Transfer saved, us | Acquisition before / after, us |
| --- | ---: | ---: | ---: |
| Both full arrays | 69.244 / 56.586 | 12.658 | 71.817 / 58.411 |
| Array 1 | 45.592 / 39.548 | 6.044 | 46.834 / 40.738 |
| Sparse/unbalanced | 27.857 / 23.088 | 4.770 | 29.447 / 24.679 |

The transfer loop is 18.3%, 13.3% and 17.1% shorter respectively, and remains
93.6-97.1% of measured acquisition. The observations support the targeted word
path improvement, but do not separately measure how much was saved by cached
GPIO, engine specialization, inlining or cycle polling. Some smaller phase
changes accompany compiler/code-layout changes too.

Enabled-profile sustained throughput also improves by 22.0%, 13.7% and 17.2%
respectively. Enabling profiling on the candidate reduces sustained rate by
3.4%, 4.8% and 7.4% against its own off run. Enabled rate is diagnostic, not
production throughput. A separate normal-build comparison is still needed for
the final compatibility benchmark.

## USB stalls remain

Off-run post-warm-up tails:

| Routes | Maximum period before / after, us | Periods above 1 ms before / after |
| --- | ---: | ---: |
| Both full arrays | 2,264 / 8,421 | 2 / 4 |
| Array 1 | 8,196 / 7,289 | 3 / 4 |
| Sparse/unbalanced | 21,420 / 20,523 | 7 / 9 |

Short sequential windows do not establish whether the candidate worsens rare
stall frequency. They do establish that it has not eliminated those stalls.

Across the nine enabled captures, 15 periods exceed 1 ms and 16 USB writes
exceed 1 ms. No acquisition, transfer, foreground or bookkeeping phase exceeds
1 ms. All 15 recorded long periods attribute at least 99.9% of their gap to
the preceding USB write. The largest observed USB writes are 11.609 ms for
both arrays, 9.951 ms for array 1 and 31.195 ms for sparse routes.

Sparse repetition 3 has four long writes but three long periods. Its 31.195 ms
write exceeds every observed period in that capture. Given complete frame/write
reconciliation and exact period/gap reconciliation, the unmatched write is
attributed to the final frame submission: there is no subsequent sweep start
to produce a period/gap. This inference explains why the maximum profile write
can exceed the maximum raw period. First-start to last-end rate does not include
waiting after the final acquisition; write-phase measurements do include it.

The largest recorded sparse period is 18.528 ms, with 18.503 ms gap and
18.500 ms preceding USB write. The largest both-array period is 11.670 ms with
11.612 ms gap and 11.609 ms write. These are USB submission delays, not direct
measurements of peripheral transmission time. The present data cannot isolate
host scheduling, the serial driver, core descriptor/buffer availability or
interrupt activity as their cause. A bounded queue remains a separate latency
candidate, and needs a controlled reader test before choosing its size/policy.

## Signal checks and next validation

Comparing channel-statistics medians across three off repetitions shows offsets
up to 12 ADC codes for both arrays, 8 for array 1 and 13 for sparse routes
(13 codes is about 0.32% of the 12-bit span). The larger shifts are small in
full-scale terms but exceed within-window noise. The sessions were sequential
without a controlled constant input, so these changes cannot be attributed to
sampling/settling rather than source changes. No benchmark signal threshold
fails, but this is not an analog ghosting/settling acceptance test.

The next step is the same three topologies in manual and Auto-1, at both 10
and 20 MHz, with profiling off: 36 captures. Use the currently uploaded
diagnostic firmware; no further upload or optimization is needed for this step.

```powershell
.\.venv\Scripts\python.exe Arduino_Sketches\TestBoard_7953\benchmarks\testboard_7953_benchmark.py `
  --port COM3 --scan-order adc `
  --route-set full_array1 --route-set all_four_full --route-set all_four_sparse_unbalanced `
  --tests __lpspi__repeat1__vmidoff__ `
  --spi-clock-hz 10000000 --spi-clock-hz 20000000 `
  --warm-up-ms 1000 --window-ms 5000 --repetitions 3 --seed 7953 `
  --no-drift-controls --profile off `
  --output Arduino_Sketches\TestBoard_7953\benchmarks\results\lpspi_word_path_modes_adc_10_20
```

If this passes, upload the normal `teensy41` build and run the same full
252-capture compatibility matrix against the repaired normal baseline, including
blocking/DMA controls. Retain fresh result directories. Hardware CS/SCK timing
and representative analog settling/noise checks remain necessary before final
acceptance. Keep USB buffering or independent-bus scheduling in a later change
so their effects can be measured separately. GUI testing remains deferred.
