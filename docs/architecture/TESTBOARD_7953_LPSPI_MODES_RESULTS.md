# TestBoard 7953: manual/Auto-1 and 10/20 MHz validation

Analyzed 2026-10-06. All 36 captures pass on the first attempt. All 12 matched
LPSPI configurations improve sustained rate over both the original firmware
and the repaired first-optimization baseline. This run uses the diagnostic
build with profiling off. The subsequent production 252-capture comparison
also passes; see [the final production results](TESTBOARD_7953_LPSPI_PRODUCTION_RESULTS.md).

## Inputs and verification

- Latest: `lpspi_word_path_modes_adc_10_20`.
- Original: matching configurations in `optimization_baseline_adc_10_20`.
- Repaired first optimization: matching configurations in `optimization_after_usb_fix_adc_10_20`.
- All are under `Arduino_Sketches/TestBoard_7953/benchmarks/results/`.
- Matched routes/array, ADC payload order, manual/Auto-1, 10/20 MHz requested
  clock, repeat 1, optional Vmid off, reference range, 1 s warm-up, 5 s window
  and three repetitions. Runner versions differ (2.2 / 2.3 / 2.4), so all rates
  and timing quantiles were recomputed from unchanged wire timestamps.
- Independently decoded and reconciled all 108 selected raw captures across
  the three sessions. These selected baseline captures have no replay, invalid
  timing, backward/overlapping timestamps or malformed headers/counts.
- All 36 latest captures are PASS, attempt 1, without timeout or failed-attempt
  log entries. All firmware ADC/start/channel/timeout/USB error counters and
  framing/replay/regression/resynchronization/discard counters are zero.
- Latest raw frame counts, warm-up cuts and acquisition/period/gap medians
  match CSV. All 36 profile records decode, reconcile whole-capture received
  counts and confirm profiling available but disabled.
- Latest contains 4,932,923 complete sweeps including warm-up and 4,110,565
  retained measurement sweeps. Counts do not prove detection of every possible
  lost frame or corrupt payload because the protocol has no sequence/checksum.

## Sustained performance

Each value is the median across three measurement windows. Rate uses frame
count divided by first-start to last-end device elapsed time. Gains compare
sustained rates, not reciprocal median periods. The repaired baseline is a
production build; the candidate retains disabled profiling branches. Final
production-to-production validation is still pending.

| Routes | Mode | MHz | Original acquisition, us | Repaired acquisition, us | Latest acquisition, us | Latest sweeps/s | Gain vs original | Gain vs repaired | Latest p99 period, us |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Both full arrays | auto1 | 10 | 109 | 88 | 81 | 12,095 | 36.92% | 8.26% | 83 |
| Both full arrays | auto1 | 20 | 85 | 71 | 60 | 16,241 | 44.48% | 17.18% | 66 |
| Both full arrays | manual | 10 | 118 | 90 | 81 | 12,158 | 48.54% | 11.51% | 83 |
| Both full arrays | manual | 20 | 91 | 71 | 58 | 16,697 | 58.65% | 20.64% | 64 |
| Array 1 | auto1 | 10 | 78 | 68 | 63 | 15,631 | 26.59% | 8.49% | 66 |
| Array 1 | auto1 | 20 | 55 | 47 | 41 | 23,599 | 35.53% | 12.81% | 44 |
| Array 1 | manual | 10 | 83 | 71 | 64 | 15,357 | 32.76% | 10.18% | 67 |
| Array 1 | manual | 20 | 59 | 47 | 41 | 23,857 | 46.59% | 15.81% | 44 |
| Sparse/unbalanced | auto1 | 10 | 44 | 34 | 31 | 30,914 | 43.31% | 7.92% | 37 |
| Sparse/unbalanced | auto1 | 20 | 35 | 27 | 23 | 40,263 | 49.61% | 14.25% | 29 |
| Sparse/unbalanced | manual | 10 | 51 | 37 | 34 | 28,646 | 52.99% | 9.51% | 39 |
| Sparse/unbalanced | manual | 20 | 40 | 29 | 25 | 38,621 | 63.38% | 17.82% | 30 |

All candidate rate ranges exceed their matching repaired baseline ranges.
Total gains over the original range from 26.6% to 63.4%; this word-path stage
adds 7.9-20.6% over the repaired first optimization. All median p99 periods
improve against both baselines.

For both full arrays at 20 MHz, manual reaches 16,697 sweeps/s (58 us acquisition)
and Auto-1 reaches 16,241 (60 us). Manual is about 2.8% faster here. Auto-1
remains faster for sparse routes at both clocks (40,263 versus 38,621 sweeps/s
at 20 MHz). Neither sequence is universally fastest.

## Tails and signal limits

Latest post-warm-up periods above 1 ms total 39: both arrays at 10 MHz have
18 Auto-1 and 17 manual; sparse 20 MHz has three Auto-1 and one manual.
Other tested configurations have none. The maximum is 3,630 us. Acquisition
maxima stay at or below 83 us across the matrix, so these are inter-sweep delays.
Profiling is off, so this run does not identify their individual phases.
They are consistent with the USB submission stalls attributed by the previous
enabled-profile run, but that is an inference rather than new direct attribution.
The absence of a tail in one short configuration does not establish its removal.

Channel-statistics medians differ by up to 12 ADC codes against the repaired
baseline, and 34 against the earlier original run. All benchmark thresholds
pass. Sequential sessions do not isolate source/temperature changes from analog
settling effects. CS/SCK timing and controlled analog/ghosting checks remain
separate acceptance work. GUI testing remains deferred.

## Next: production compatibility check

The production `teensy41` environment includes the same sampling and USB repairs
and compiles out profiling. Upload explicitly from the repository root:

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\pio.exe" run -d Arduino_Sketches/TestBoard_7953 -e teensy41 -t upload
```

Then run all 84 configurations with three repetitions: 252 captures. This
includes blocking/DMA controls, manual/Auto-1, seven route sets and both clocks.
The dry run confirms 84 configurations; no serial port was opened during analysis.

```powershell
.\.venv\Scripts\python.exe Arduino_Sketches\TestBoard_7953\benchmarks\testboard_7953_benchmark.py `
  --port COM3 --scan-order adc `
  --tests __repeat1__vmidoff__ `
  --spi-clock-hz 10000000 --spi-clock-hz 20000000 `
  --warm-up-ms 1000 --window-ms 5000 --repetitions 3 --seed 7953 `
  --no-drift-controls --profile off `
  --output Arduino_Sketches\TestBoard_7953\benchmarks\results\lpspi_word_path_production_adc_10_20
```

Require clean first attempts, zero new errors and clean whole-capture integrity.
Compare the production result with the repaired production baseline and original
firmware. Retain fresh result directories. Proceed to a separate USB buffering
change after compatibility validation, with an explicit queue/full/stop policy
and controlled reader tests.

See [the first 18-capture results](TESTBOARD_7953_LPSPI_WORD_PATH_RESULTS.md)
and [the optimization plan](TESTBOARD_7953_NEXT_OPTIMIZATION_PLAN.md).
