# TestBoard 7953: measured phase profiling

Analyzed 2026-10-06. Both diagnostic-firmware sessions completed nine captures:
profiling off, then profiling on. All 18 passed on their first attempts. The
transfer loop dominates ordinary sweep time; the observed millisecond gaps are
inside USB writes. Profiling has a measurable throughput cost and is diagnostic.
No firmware, runner, GUI, or original result files were changed during analysis.

## Inputs and verification

- `phase_profile_off_adc20_v2` and `phase_profile_on_adc20_v2`, under
  `Arduino_Sketches/TestBoard_7953/benchmarks/results/`.
- Both report `profile_available=true`; mode is off/on as intended, runner 2.4.
  Same three route sets, manual LPSPI, 20 MHz requested SPI clock, ADC payload
  order, repeat 1, optional Vmid off, 1 s warm-up, 5 s measurement, three
  repetitions, and no drift controls. Configuration fields and route lists match.
- All repetition verdicts are PASS, attempt 1. Logs have no failed attempts.
  All replay/timestamp/timing/framing/discarded-byte and firmware error counters
  are zero. Profiling has zero aborted sweeps, counter-wrap ambiguities, or
  frequency changes; complete write counts equal full-capture received counts.
- Independently decoded all 18 raw captures: valid headers/counts, no exact
  repeated frames, positive durations/periods, and non-overlapping timestamps.
  Reconciled warm-up cuts, measured frame counts, and acquisition/period/gap
  medians with CSV. Recomputed the enabled profile's whole-run period/gap
  counts, totals, maxima, threshold counts, and histograms from raw timestamps;
  all match. Each tail snapshot's period/gap appears in its raw capture.
- These paired sessions contain 2,349,151 full-capture sweeps, including
  1,956,551 retained measurement sweeps. The enabled profiles cover 1,142,406
  complete sweeps, including warm-up. Larger per-sample CSVs were not scanned.
- `phase_profile_off_adc20` is a separate, earlier normal-build run. Its nine
  captures also pass independent integrity checks, but `profile_available=false`.
  The accompanying `phase_profile_on_adc20` attempt was rejected before sampling.
  Preserve those as normal-build data and a setup failure; the v2 pair is the
  correct same-build comparison of enabling probes.

## Profiling overhead

Values below are medians across three measurement windows. Sustained rate uses
received frame count divided by first-start to last-end device elapsed time,
not the reciprocal of a median period.

| Routes | Off acquisition / period us | On acquisition / period us | Off sweeps/s | On sweeps/s | On rate change |
| --- | ---: | ---: | ---: | ---: | ---: |
| all_four_full (50) | 71 / 72 | 72 / 76 | 13,773 | 13,202 | -4.14% |
| all_four_sparse_unbalanced (15) | 29 / 31 | 29 / 33 | 32,430 | 30,297 | -6.58% |
| full_array1 (25) | 47 / 48 | 47 / 50 | 20,787 | 19,944 | -4.06% |

Enabling profiling costs approximately 4.1% for one/both full arrays and 6.6%
for sparse routes. Bookkeeping alone costs about 1.38-1.46 us/sweep. Capacity
observation, probes, branches, and code between probes add further cost. Do not
use the enabled rate as production performance or subtract one calibration
constant to derive a supposedly corrected rate. The off diagnostic build also
retains branches; its rate differs by -1.6% to +1.1% from the separate normal
run, with variation and rare stalls confounded by different builds/run times.

## Where the sweep time goes

The following are medians of whole-run phase means from the three enabled
captures, including warm-up. They do not have the same scope as the post-warm-up
CSV medians above. Component phases do not partition acquisition exactly;
prepare includes mask clearing before the wire start, and acquisition overlaps
the component phases. All cycle timings include interrupt time.

| Phase | Both full arrays (50), us | Array 1 (25), us | Sparse/unbalanced (15), us |
| --- | ---: | ---: | ---: |
| acquisition | 71.817 | 46.834 | 29.447 |
| transfer | 69.244 | 45.592 | 27.857 |
| prepare | 0.511 | 0.381 | 0.494 |
| session | 0.916 | 0.446 | 0.778 |
| validate | 0.836 | 0.228 | 0.162 |
| encode | 0.521 | 0.225 | 0.230 |
| capacity | 0.187 | 0.171 | 0.173 |
| usb_write | 0.557 | 0.405 | 0.612 |
| foreground | 0.465 | 0.465 | 0.465 |
| bookkeeping | 1.461 | 1.411 | 1.385 |
| run_prepare | 12.607 | 5.823 | 5.070 |

`run_prepare` occurs once per run, not every sweep. Its cached-plan cost is
already amortized. For both arrays, `executeStreams` occupies approximately
69.24 of 71.82 us (96.4% of measured acquisition). The corresponding shares are
97.3% for array 1 and 94.6% for sparse routes. This identifies the transfer loop
as the next throughput target; it does not isolate wire time, required CS/ADC
timing, dispatch, GPIO access, polling, or response processing inside that loop.

The existing path still dispatches among engines for each word/poll, performs
runtime CS GPIO lookup, and queries `micros()` for each transfer and wait.
Those are candidates for a dedicated LPSPI path. Profile-guided simplification
is justified, but no numerical speedup is established until its matched run.

Cycle and wire acquisition probes have slightly different boundaries and
microsecond quantization. One long-tail snapshot measures 72.175 us in cycles
against a 71 us wire duration. Their approximate agreement is useful; they
should not be asserted equal at sub-microsecond precision.

## Long gaps are in USB enqueueing

Across the nine enabled captures there are 11 periods above 1 ms, all matched
by 11 USB writes above 1 ms. No measured acquisition, transfer, foreground,
encoding, or bookkeeping interval exceeds 1 ms. Every >1 ms tail snapshot
attributes at least 99.7% of its inter-sweep gap to the preceding USB write.

| Topology | Whole-run periods >1 ms | Longest period us | Longest USB write us | Capacity observations below one frame |
| --- | ---: | ---: | ---: | ---: |
| all_four_full | 2 | 6,531 | 6,456.45 | 148 / 237,789 (0.062%) |
| all_four_sparse_unbalanced | 9 | 22,258 | 22,225.38 | 462 / 545,656 (0.085%) |
| full_array1 | 0 | 52 | 1.91 | 0 / 358,961 (0.000%) |

The largest sparse-route gap is 22,229 us, of which the USB write occupies
22,225.375 us; acquisition remains approximately 29.45 us. The largest
both-array gap is 6,460 us, with a 6,456.452 us write and approximately 71 us
acquisition. These are foreground enqueue delays, not measurements of USB
peripheral transmission time. Low observed write capacity supports transmit
backpressure as a possible explanation; this does not isolate host scheduling,
the driver, core buffer/descriptor availability, or interrupt activity within
the write call. No replay/framing fault recurred.

Array 1 has no >1 ms enabled periods, but three in the off run. The normal and
off sessions also contain rare long gaps. Short sequential runs cannot show
that enabling probes fixes, worsens, or eliminates those sporadic events.

## Next implementation

1. **Optimize the LPSPI word path for throughput.** Cache CS set/clear register
   addresses and masks; select LPSPI dispatch once per sweep; evaluate a bounded
   cycle-counter deadline in its polling path. Preserve fresh completion/RX
   checks, GPIO CS timing, channel validation, mandatory parking, USB interrupts,
   and all cancel/restart cleanup. Keep blocking/DMA behavior intact. Use the
   uninstrumented build for speed comparisons and profiling for attribution.
2. **Treat USB buffering as a separate latency improvement.** The profiling
   condition for investigating a bounded FIFO is now met. A FIFO can absorb
   finite stalls but cannot correct a persistently slow reader. Specify full
   queue, short-write offsets, stop/drain/ACK ordering and restart behavior first;
   never silently drop or replay samples. Use a controlled reader test, since
   GUI repair remains a separate task.
3. Do not assume a 64-frame queue covers the observed extremes: at off rates it
   spans about 4.6 ms for 50 routes and 2.0 ms for sparse routes. The observed
   enabled write extremes would require roughly 89 full-array frames (~10 KB
   wire bytes) or 721 sparse frames (~32 KB), before margins, at those rates.
   These are sizing illustrations, not proof of sufficient buffering. Higher
   sampling rates shorten a queue's time coverage.

Independent-bus scheduling remains a later option for unbalanced selections.
Sequence-wide DMA remains a separate feasibility study. No GUI test is needed
to implement or benchmark the next firmware candidate. Do not repeat the full
252-capture matrix solely for this profiling sign-off; run it after a meaningful
candidate change. Future candidates still need hardware CS/SCK timing and analog
settling/noise checks before adopting the faster path.

The next code change is the dedicated LPSPI path. No additional optimization was
implemented during this analysis. See the [profiling guide](TESTBOARD_7953_PHASE_PROFILING.md)
and [next-stage plan](TESTBOARD_7953_NEXT_OPTIMIZATION_PLAN.md).
