# TestBoard 7953 phase profiling

Implemented 2026-10-06 as the first step of the
[next optimization plan](../../plans/firmware/TESTBOARD_7953_NEXT_OPTIMIZATION_PLAN.md). This is
instrumentation, not a further sampling optimization. No board upload, COM3
access, or GUI change was performed during implementation.

## Build and upload

The default `teensy41` environment compiles out all profiling probes and storage.
Default `pio run` and upload still select this environment. The diagnostic
environment includes the same USB repair and starts with profiling disabled.

Build both environments without a board:

```powershell
pio run -d Arduino_Sketches/TestBoard_7953 -e teensy41 -e teensy41_profile
```

When ready, upload the diagnostic environment explicitly:

```powershell
pio run -d Arduino_Sketches/TestBoard_7953 -e teensy41_profile -t upload
```

The `profile on*`/`profile off*` commands are accepted only while stopped.
Normal firmware accepts off and rejects on. `status*` has additive
`profile_available` and `profile_enabled` fields. On the diagnostic build,
stopped status includes version 1 summaries when profiling is on. No diagnostic
text is emitted automatically during sampling or stopping. Each new run resets
the summaries after startup ADC parking, before compiling the run plan.

## First hardware comparison: 18 captures

Start with three topologies at 20 MHz, manual LPSPI, three repetitions each,
first profiling off then on. Both use the same diagnostic firmware, ADC order,
repeat 1, optional Vmid off, 1 s warm-up, 5 s measurement, seed 7953, and no drift
controls. No GUI is involved. Startup smoke checks are additional captures.

Run from the repository root after upload, with COM3 available:

```powershell
foreach ($profileMode in @('off', 'on')) {
  .\.venv\Scripts\python.exe Arduino_Sketches\TestBoard_7953\benchmarks\testboard_7953_benchmark.py `
    --port COM3 --scan-order adc `
    --route-set full_array1 --route-set all_four_full --route-set all_four_sparse_unbalanced `
    --tests __manual__lpspi__repeat1__vmidoff__ --spi-clock-hz 20000000 `
    --warm-up-ms 1000 --window-ms 5000 --repetitions 3 --seed 7953 `
    --no-drift-controls --profile $profileMode `
    --output "Arduino_Sketches\TestBoard_7953\benchmarks\results\phase_profile_${profileMode}_adc20"
  if ($LASTEXITCODE -ne 0) { throw "Profiling benchmark failed: $profileMode" }
}
```

Use fresh directories. A resume must keep the same profiling mode. Compare
profiling-off elapsed-time throughput with the validated repaired baseline,
then on versus off to measure instrumentation disturbance. The profiling build
still has branches when off; only the normal build removes the probes completely.
Do not subtract adjacent-read calibration from all phase times and claim a
corrected production rate.

If this passes, expand to manual/Auto-1 and 10/20 MHz using the same three route
sets and `--tests __lpspi__repeat1__vmidoff__`. That is 36 captures per mode.
Further candidates can use the existing 252-capture compatibility matrix.

## Measurements and boundaries

All cycle timings are elapsed time, including interrupts. No interrupts are
masked by profiling and no per-word logging/probing is added. Summaries use fixed
storage: 13 phase histograms and up to eight tail snapshots. Aggregation runs
after frame submission; its cost is reported separately.

| Phase | Measured scope |
| --- | --- |
| run_prepare | Once per run: cached scan/manual command preparation, after startup parking. |
| prepare | Per sweep: written-mask clear, stream reset/build, and state commit, combined across both ADC pairs. Mask clear occurs before the wire start timestamp. |
| session | Explicit LPSPI session setup and normal teardown, combined across buses; empty scope overhead in other engines. |
| transfer | Both `executeStreams` calls, including polling, response validation/mapping, and interrupt time. |
| validate | Final check that every payload destination was written. |
| acquisition | Cycle interval adjacent to the existing wire start/end timestamps. Includes probe overhead and the work between them; overlaps the component phases. |
| encode | Average-time calculation and binary frame encoding. |
| capacity | Immediate `Serial.availableForWrite()` observation and bookkeeping; not the core's entire queue depth. |
| usb_write | The complete binary write call, including any waiting. |
| foreground | Between the end of the previous profiling aggregation and entry to the next sweep. Includes loop/command/yield/interrupt activity; excludes the preceding write and measured bookkeeping. |
| bookkeeping | Post-write aggregation and tail selection, before recording this phase's own histogram. |
| period / gap | The unchanged microsecond wire start-to-start / previous-end-to-current-start intervals. First sweep has no preceding interval. |

The subphases do not partition the wire intervals exactly: timer/probe overhead,
branches, the bookkeeping histogram's own update, and code between probes leave
a residual. An aborted acquisition may lack its final acquisition interval;
its completed/partial component scopes remain counted. Error cleanup and final
ADC parking are not attributed to normal session teardown. Counts make these
differences visible; do not add all phase means including acquisition together.

Every phase reports count, total ticks, maximum ticks, counts over 100 us/1 ms,
and a histogram. Bounds in us are 1, 2, 4, 8, 16, 32, 64, 100, 128, 256, 512,
1000, 2000, 4000, 16000, 64000, then an unbounded bucket. Quantiles are upper
bounds, not exact p95/p99 values. Period/gap ticks are us; other ticks are cycles
converted using the reported `F_CPU_ACTUAL`. Adjacent counter-read minimum and
maximum are calibration observations only.

The eight longest periods above 100 us retain period/gap, preceding acquisition,
encoding, capacity query, USB write and bookkeeping times, plus current
foreground time. Snapshots tie a long gap to measured phases; sums may leave
the residual described above. Snapshots cover warm-up too and are sorted in the
decoded JSON. A period alone does not prove a missing frame.

Complete/aborted sweep counts, write-call count, minimum/maximum observed write
capacity and observations below frame size are also saved. Complete accepted
writes must equal the number of received frames over the whole timed capture
when profiling is enabled. A mismatch fails the attempt and preserves original
profile fields. Any aborted sweep also fails the profiling attempt, even when
all complete writes arrived; this does not checksum payloads or change the wire format.

## Counter and comparison limits

Per-phase subtraction accepts a uint32 cycle-counter rollover, assuming each
short measured phase lasts less than one full cycle (about 7.16 s at 600 MHz).
Current transfer/write timeouts are well below that. The enclosing microsecond
gap detects foreground intervals that could span a whole cycle; those cycle
measurements are rejected, rather than aliased to a small latency. A CPU clock
change during a run invalidates conversion. Host decoding rejects either
condition. Micros rollover is handled with unsigned differences.

The firmware summaries cover the whole run, including warm-up. Existing CSV
measurement metrics cover the retained post-warm-up window. Compare like scopes.
Profiling adds probes and aggregation to the diagnostic build; determine its
rate/tail disturbance with the off/on comparison before drawing conclusions.
The completed off/on hardware comparison is documented in
[the measured profiling results](../../testing/benchmarks/testboard-7953/TESTBOARD_7953_PHASE_PROFILING_RESULTS.md).
It confirms a measurable profiling cost, transfer-loop dominance, and rare
millisecond delays inside USB writes. No further optimization's speedup has
been established by this diagnostic step.

## Offline validation

Both PlatformIO environments build. Focused Python tests cover status decoding,
units, histogram overflow, malformed summaries, profile-mode normalization,
evidence preservation and received-frame reconciliation, alongside the existing
benchmark, board, ghosting and ADC124 shared-helper checks.

The native controller suite runs normal and profiling variants, each retaining
the 1,188 acquisition configurations. Profiling checks exercise on/off settings,
binary payload preservation, counter rollover, injected slow/low-capacity USB
writes, tail attribution, stopped-only summaries, long-gap rejection, short-write
abort and reset on restart. Native tests cannot validate electrical timing or
measure actual on-board probe overhead. The repaired profiling ELF also passes
the existing 38 USB exclusion/flush scenarios.
