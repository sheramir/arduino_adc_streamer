# TestBoard 7953 next firmware optimization plan

Planned 2026-10-06 after the repaired firmware completed the focused 12-capture
check and the full 252-capture benchmark. This document proposes follow-up work;
none of these additional firmware optimizations has been implemented.

## Starting point and scope

Use the current repaired firmware as the next baseline. Both full arrays at
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

## 4. Add a frame queue or batching only if writes cause stalls

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
- A candidate should improve measured elapsed-time throughput without a
  meaningful p99/tail or analog regression. Extend repetitions only when the
  observed gain is too small or variable to distinguish from run-to-run variation.
- The current format has no sequence number/checksum. If stronger missing-frame
  or payload-corruption detection becomes necessary, plan a versioned compatible
  protocol extension as a separate firmware/host task; do not silently change
  frame layout as part of a speed optimization.

The next implementation task is phase 1 profiling. GUI integration stays deferred
until the separate GUI repair is ready.
