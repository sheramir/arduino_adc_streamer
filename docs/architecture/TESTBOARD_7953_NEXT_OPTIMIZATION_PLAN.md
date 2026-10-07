# TestBoard 7953 next firmware optimization plan

Planned 2026-10-06 after the repaired firmware completed the focused 12-capture
check and the full 252-capture benchmark. Phase 1 profiling is measured on the
board. Phase 2 LPSPI word-path changes pass the first 18 hardware captures,
the 36-capture manual/Auto-1 comparison and the production 252-capture matrix.
The subsequent live-discard change now passes its full production 252-capture
matrix and forced-stall tests: manual both-array LPSPI retains 16,887 sweeps/s,
and no actual sampling period exceeds 171 us in any engine. GUI repair is the
next integration task; blocking-channel dips, a both-array DMA rate decrease
and stronger analog acceptance remain separate work. Later throughput phases
remain plans. See [current full-matrix results](TESTBOARD_7953_LIVE_USB_FULL_MATRIX_RESULTS.md).

## Earlier starting point and scope

The original baseline for the phases below was the USB-repaired firmware. Both full arrays at
20 MHz, manual LPSPI: 71 us median acquisition, 72 us median sweep period,
13,841 sustained sweeps/s, and 77 us maximum period in three measurement windows.
Auto-1 LPSPI reaches essentially the same rate. All 252 captures have clean
stream checks, zero firmware errors, and no retries. The existing implementation
already caches scan/manual command plans and configures LPSPI once per sweep.
USB transmission already overlaps subsequent sampling at the peripheral level.

The typical 1 us inter-sweep gap leaves approximately 1.4% typical-rate headroom
if eliminated. Acquisition is the main throughput target. Other configurations
show occasional much larger gaps outside acquisition, so latency deserves its
own investigation rather than being hidden by a median-rate improvement.

GUI performance is a separate task. The user will repair GUI support for the
fast TestBoard before testing it. This plan uses the standalone benchmark reader
and does not require GUI testing, GUI changes, or archive/export work.

See [the validated baseline results](TESTBOARD_7953_USB_FIX_BENCHMARK_RESULTS.md)
and [the USB repair](TESTBOARD_7953_USB_STREAM_DIAGNOSIS.md).

## 1. Measure acquisition phases and long gaps

Implement optional, bounded profiling before changing the transfer scheduler:

- Measure sweep reset/preparation, LPSPI session setup/teardown, transfer-loop
  execution, frame encoding, USB write, and the rest of the foreground interval.
- Track count, total, maximum, and fixed-size latency histograms. Summaries should
  distinguish acquisition cost from USB enqueue time and between-sweep work.
- Record full/short write counts and application-observed write capacity, without
  treating that capacity as a measurement of the core's entire transmit queue.
- Attribute periods above 100 us and 1 ms, especially the observed 30 ms tail,
  to measured phases. Inspect foreground command/EventResponder servicing too.
- Keep diagnostics out of the binary stream. Report summaries after stopping;
  use compatible additive status fields if the runner needs to collect them.
- Start with sweep-level cycle measurements. Enable more detailed per-transfer
  probes only for a bounded diagnostic run. Do not allocate or print per word.
- Measure the probes' own cost using profiling-on/off builds. Validate cycle
  counter wrap and CPU-clock conversion. Preserve existing wire timestamps and
  timeout behavior; do not claim instrumented timing as the uninstrumented rate.

Deliverable: a phase-cost table and tail attribution for both full arrays and
sparse/unbalanced routes, with an evidence-based choice for phase 2.

## 2. Reduce measured LPSPI polling and per-word overhead

If phase 1 confirms meaningful software cost in the transfer loop, make one
focused change at a time:

1. Cache CS GPIO set/clear addresses and masks when registering chip selects,
   removing repeated runtime pin lookup from the LPSPI word path.
2. Select an LPSPI-specific execution path once per sweep rather than repeatedly
   dispatching among engines for every word and completion poll.
3. Evaluate a bounded cycle-counter timeout instead of repeated `micros()`
   queries in the short LPSPI poll loop. Keep USB interrupts enabled and preserve
   required foreground servicing on extended waits. Keep DMA EventResponder
   behavior intact; optimize LPSPI independently first.

Retain fresh completion-flag checks, receive readiness, CS framing/high time,
channel-tag validation, mandatory Vmid parking, pipeline tracking, and cleanup
on every error/stop path. Review optimized ARM assembly and use a logic analyzer
to verify actual SCK and CS timing; native stubs cannot establish electrical
timing. Remain at the specified 20 MHz interface limit for the main comparison.

Deliverable: a separate candidate with a repeatable sustained-rate improvement
without worse integrity or timing tails. If probes show these costs are already
small, skip the change rather than add complexity for an assumed gain.

The candidate now caches each ADC's GPIO set/clear pointers and mask at startup,
dispatches to a fixed-engine word loop once per stream pair, inlines the LPSPI
register operations and ADC accessors, and uses a rollover-safe 1 ms DWT deadline.
CPU-clock conversion occurs once per stream pair. Extended LPSPI waits call
`yield()` every 10 us; interrupts remain enabled. DMA retains microsecond
timeouts and per-poll EventResponder servicing. See
[the implementation and comparison commands](TESTBOARD_7953_LPSPI_WORD_PATH.md).
The first matched manual 20 MHz comparison passes with consistent throughput
gains and lower p99 periods. Rare USB write stalls remain. Next run the focused
36 captures covering manual/Auto-1 and 10/20 MHz before the full compatibility
matrix. That comparison is now complete: all 36 pass with 7.9-20.6% gains over
the repaired first optimization. The production 252-capture matrix now also
passes cleanly: both-array manual LPSPI reaches 16,889 sweeps/s, 60.5% above
the original and 22.0% above the repaired first optimization. Use that session
as the next baseline. Long inter-sweep stalls remain, including warm-up tails
near 95 ms. Next investigate USB submission/backpressure and controlled reader
behavior as a separate latency change. See
[the production validation](TESTBOARD_7953_LPSPI_PRODUCTION_RESULTS.md),
[the measured mode/clock results](TESTBOARD_7953_LPSPI_MODES_RESULTS.md) and
[the first word-path results](TESTBOARD_7953_LPSPI_WORD_PATH_RESULTS.md).

## 3. Schedule the two SPI buses independently

Evaluate this only after profiling and the simpler word-path work. The current
loop pairs transfers and finishes one ADC pair before advancing to the next.
Let a bus advance to its next operation/ADC when ready, while the other bus
continues its own stream. This chiefly targets sparse/unbalanced routes; do not
promise the same gain for balanced full arrays.

Preserve one active CS per bus, per-ADC response pipelines and parking, canonical
payload destinations, and start/end sweep timing. State the changed sampling
order and assess inter-channel/bus skew before adopting it. Expand native
coverage for unequal streams, one bus finishing early, timeouts, cancel, restart,
and manual/Auto-1 transitions. Compare full-array controls as well as the target
unbalanced configurations.

## 4. Keep sampling and discard sweeps when USB is busy

The user's 2026-10-07 requirement supersedes the large-FIFO proposal: sensors
must keep being sampled through USB stalls, while untransmitted sweeps are
discarded to favor fresh live data. The implementation uses an audited core
helper that reserves complete frames without a host-completion wait. It keeps
the binary protocol, adds acquired/sent/discarded counters and actual sampling
period diagnostics, and stores no acquisition history. See
[live USB implementation and the reduced hardware test](TESTBOARD_7953_LIVE_USB_STREAM.md).
Local builds, controller tests and ARM emulator checks pass. All 18 diagnostic
hardware captures now pass, including real backpressure during a 500 ms reader
pause: actual sampling periods remain at or below 66 us and the large sensor
dips are absent from received samples. Deferred parsing eliminates both-array
discards in the three unpaused control captures. The 18 production mixed-engine
captures now pass too: both LPSPI modes discard zero sweeps, with manual
throughput unchanged near 16,887 sweeps/s. DMA is approximately 3% slower and
blocking modes retain localized post-gap dips despite continuous sampling.
The six production LPSPI forced-pause captures now also pass, with maximum
actual sensor interval 66 us and no large resumption dips. Full-matrix coverage
is now complete: all 252 final captures pass, with actual sensor periods at
or below 171 us overall and 86 us in LPSPI. No further upload is needed for
the validated LPSPI path. See [full-matrix results](TESTBOARD_7953_LIVE_USB_FULL_MATRIX_RESULTS.md).
See [diagnostic hardware results](TESTBOARD_7953_LIVE_USB_RESULTS.md) and
[production results](TESTBOARD_7953_LIVE_USB_PRODUCTION_RESULTS.md).
Already accepted USB/Windows bytes can still arrive late.

The paragraphs below preserve the earlier lossless-buffering proposal for
context. That policy is not implemented in this live-data candidate.

This condition is met by the enabled phase profiles. The completed production
matrix confirms faster sampling and clean streams, but still has inter-sweep
delays (up to 34.5 ms after warm-up and 95.4 ms including warm-up). No new phase
attribution exists in that production run. Include controlled reader comparison
when investigating those tails, and avoid blocking the acquisition loop while
draining any future queue. A queue alone does not remove a blocking submission.

Do this if phase 1 attributes material tail latency to USB write/backpressure.
A queue cannot fix a reader that is persistently slower than production, and
additional application buffers do not create new peripheral concurrency.

Use a bounded FIFO of complete existing-format frames with explicit ownership,
ordering, and a full-queue policy: pause with an observable gap or stop with an
error. Preserve offsets for any partial submission; never replay, overwrite, or
silently drop frames. Define drain/abort behavior before implementing stop,
timed stop, command ACKs, disconnect, and restart. Do not mix a partial binary
frame with text responses.

Consider batching unchanged wire frames only if measurements show per-write
overhead. Bound latency and memory use. Use a continuously draining benchmark
reader plus a controlled slow-reader stress test, not the unfinished GUI.

## 5. Treat sequence-wide DMA as a separate feasibility study

The current DMA engine submits individual words and remains substantially
slower than LPSPI. That does not predict the performance of a complete-sequence
DMA engine. First inspect the board's CS wiring and determine whether valid
separate conversion frames can be generated with hardware PCS, timer/GPIO
coordination, and DMA. A single long transfer with CS held low is not equivalent.

Estimate achievable gains against the remaining measured CPU cost before
implementation. Account for DMA-accessible buffers, alignment/cache maintenance,
channel response tracking, parking, cancellation, and USB interrupt coexistence.
Proceed only if feasibility and expected benefit justify a larger design change.

## Benchmark and acceptance strategy

- Keep `optimization_after_usb_fix_adc_10_20` unchanged as the repaired baseline.
  Use a fresh, named results directory for each candidate and preserve failures.
- For early LPSPI comparisons, use full array 1, both full arrays, and sparse
  unbalanced routes; manual/Auto-1; 10/20 MHz; three repetitions. This is 36
  captures with the same 1 s warm-up, 5 s window, ADC order, repeat 1, Vmid off,
  seed 7953, and no drift controls. Broaden only when the changed behavior needs
  coverage, such as non-ADC payload ordering or different repeat/Vmid settings.
- After a candidate earns a clear improvement, rerun the same full 252-capture
  matrix for blocking/DMA/LPSPI compatibility. Compare sustained rate,
  acquisition, period/gap median, p95/p99/max, long-gap counts, channel/transfer
  errors, and whole-capture integrity. Require zero failed attempts, replays,
  backward/invalid timing, resynchronizations, and discarded bytes.
- For code validation, select focused Python tests and the actual-controller
  native suite. Keep the USB repaired-ELF reproducer and build checks when
  touching timing, core configuration, or toolchain. No upload is automatic.
- Check analog settling, noise, ghosting, returned channel identity, and
  representative sensor waveforms before accepting a faster acquisition path.
  Repeat/Vmid settings are comparison controls, not shortcuts to a higher rate.
- Account for sensor charging toward Vmid while selected and leakage toward
  ground while unselected, as described by the user. Analyze each channel and
  ADC separately with the existing bias map: ADC1 1 MOhm, ADC2/ADC3 470 kOhm,
  ADC4 249 kOhm. Separate ordinary sample variation from post-pause dip depth
  and recovery time, and compare similar pause lengths and channel revisit
  intervals. A stable low-impedance source test complements a sensor test but
  cannot replace it. See the [channel-quality analysis](TESTBOARD_7953_CHANNEL_QUALITY_RESULTS.md).
- A candidate should improve measured elapsed-time throughput without a
  meaningful p99/tail or analog regression. Extend repetitions only when the
  observed gain is too small or variable to distinguish from run-to-run variation.
- The current format has no sequence number/checksum. If stronger missing-frame
  or payload-corruption detection becomes necessary, plan a versioned compatible
  protocol extension as a separate firmware/host task; do not silently change
  frame layout as part of a speed optimization.

Phase 1 profiling is implemented; see the [profiling guide](TESTBOARD_7953_PHASE_PROFILING.md)
for builds, scope/limits, offline validation, and the reduced COM3 comparison.
The user uploaded the profiling build and completed nine off plus nine on
captures, all clean on first attempts. Profiling costs about 4-7% sustained
throughput. The transfer loop occupies 96.4% of both-array acquisition, so a
dedicated LPSPI word path is the next throughput candidate. All 11 enabled
periods above 1 ms coincide with long USB writes; the condition for investigating
a bounded USB FIFO is met, as a separate latency change. See
[the measured profiling results](TESTBOARD_7953_PHASE_PROFILING_RESULTS.md) for
phase costs, tail attribution, sizing limits and measurement caveats. GUI
integration stays deferred until the separate GUI repair is ready.
