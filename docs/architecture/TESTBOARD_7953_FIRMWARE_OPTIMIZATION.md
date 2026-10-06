# TestBoard 7953 firmware optimization candidate

Implemented 2026-10-05 after the user started the existing-firmware baseline.
No upload or serial-port access was performed. The benchmark runner and its
configuration matrix are unchanged.

## Changes

- Prepare canonical route order, per-ADC payload destinations, channel masks,
  active buses, and manual command streams once at every `run*`.
- Keep a separate stream for each ADC. Manual sweeps rewind cursors and pending
  pipeline results; Auto-1 uses the cached routes while preserving persistent
  mask programming, resume behavior, and Vmid parking.
- Stop clearing unused command storage and the sample buffer every sweep.
  Every emitted sample must still have been written during that sweep.
- Configure each active LPSPI peripheral once per sweep, rather than once per
  conversion. Each ADC conversion still has its own CS frame and the existing
  minimum CS-high delay. Wait for RX data and a fresh transfer-complete flag before
  releasing CS. Restore normal SPI configuration on success and failure.

SPI clocks, repeats, reference range, optional Vmid settings, mandatory parking,
payload order, binary framing, and trailer units retain their existing behavior.
The additional per-ADC command storage costs approximately 4 KiB of RAM.

## USB and scope

The installed Teensy core already queues `Serial.write()` data in core-owned
buffers and transmits it while the foreground acquires the next sweep. This
candidate targets sampling/setup overhead. It does not add an application USB
queue, change write/stop semantics, or redesign the two-byte DMA engine. USB
backpressure and short-write handling remain separate follow-up work if the
measured gaps and sustained rates establish that need.

## Offline validation

`pio run -d Arduino_Sketches/TestBoard_7953` builds the Teensy 4.1 firmware.

The native runtime test compiles the actual acquisition, SPI, ADC, encoding,
and USB controller sources against tagged digital ADC/register stubs. It
covers 1,188 configurations with four sweeps each: blocking/DMA/LPSPI,
manual/Auto-1, all payload orders, repeats 1–3, Vmid on/off, full 25-channel
arrays, combined 50-channel arrays, and sparse/unbalanced routes. Checks cover
sample identity/order, same-bus CS exclusion, modeled outgoing-ADC parking,
one LPSPI transaction per active bus per sweep, completion-flag gating, restoration,
timeout recovery, engine/clock/configuration changes, and timed stop.

Run with a native C++ compiler, or use the ephemeral compiler environment:

```powershell
uv run --no-project --with pytest --with ziglang python -m pytest tests/test_testboard_7953_firmware_runtime.py -q
```

Digital models cannot validate SCLK/CS edge timing, conversion settling,
electrical noise, crosstalk, or on-board speed. Follow the hardware validation
steps in the firmware README after upload.

## LPSPI startup repair, 2026-10-06

The first on-board optimized session timed out during LPSPI startup parking
after nine successful DMA/blocking captures. `run 6000*` returned `#NOT_OK`;
subsequent blocking recovery reported a channel error. The session remains in
`optimization_after_adc_10_20` as evidence of this unsuccessful candidate.

Session setup had read TCR immediately after FIFO reset and used the readback
to construct the 16-bit command. The [NXP RT1060 reference manual, section
48.4.1.15](https://www.pjrc.com/teensy/IMXRT1060RM_rev2.pdf) documents incorrect
TCR reads during command loading. This is a plausible cause of the observed
timeout; the log has no register snapshot to establish the exact hardware state.
The repaired candidate constructs the same command bits as the pinned
SPISettings implementation, resets FIFOs while disabled, and loads the known
16-bit command before enabling. Each word clears the sticky TCF bit and requires
RX data plus fresh transfer completion before CS release. Cancellation also
reloads a known command after the disabled FIFO reset.

The original native test invocation used Zig optimization that defined NDEBUG,
silently disabling its assertions. Its earlier pass did not validate acquisition
correctness. The test now explicitly undefines NDEBUG and has a compile-time
guard against disabled assertions. With checks enabled, the previous firmware
fails the unstable-TCR regression; the repaired code passes. The model now checks
write-one-to-clear completion flags, stale completion, the exact failing routes,
actual 10+15-channel array topology, and both buses with unreliable TCR reads.

Build and offline checks do not establish the on-board repair. After uploading,
run this small hardware check before repeating the full comparison:

```powershell
.\.venv\Scripts\python.exe Arduino_Sketches\TestBoard_7953\benchmarks\testboard_7953_benchmark.py `
  --port COM3 --scan-order adc --route-set all_four_sparse_unbalanced `
  --tests __manual__lpspi__repeat1__vmidoff__ --tests __auto1__lpspi__ `
  --spi-clock-hz 10000000 --spi-clock-hz 20000000 `
  --warm-up-ms 1000 --window-ms 1000 --repetitions 1 --seed 7953 `
  --no-drift-controls `
  --output Arduino_Sketches\TestBoard_7953\benchmarks\results\lpspi_startup_check_v2
```

If this passes, run the full matching comparison below in its new directory.

## Matching hardware comparison

After the baseline finishes and the candidate is uploaded, run the same command
with a different output directory to retain the baseline:

The reduced comparison uses ADC payload order, repeat 1, and optional Vmid off
for every topology, both sequence modes, all three engines, and both clocks.
This schedules 84 configurations with three repetitions (252 captures).
Use `optimization_baseline_adc_10_20` for the current-firmware baseline and the
after directory below for the optimized firmware. Earlier captures remain in
`optimization_baseline_10_20` as a separate, broader partial session.

```powershell
.\.venv\Scripts\python.exe Arduino_Sketches\TestBoard_7953\benchmarks\testboard_7953_benchmark.py `
  --port COM3 `
  --scan-order adc `
  --tests __repeat1__vmidoff__ `
  --spi-clock-hz 10000000 `
  --spi-clock-hz 20000000 `
  --warm-up-ms 1000 `
  --window-ms 5000 `
  --repetitions 3 `
  --seed 7953 `
  --no-drift-controls `
  --output Arduino_Sketches\TestBoard_7953\benchmarks\results\optimization_after_adc_10_20_v2
```

Compare each matching configuration's acquisition duration, start-to-start
period, inter-block gap, and sustained frames per elapsed second, together with
channel/transfer errors and malformed-frame counts. Inspect p95/p99/max periods
from raw captures as well as medians; timestamp-based suspected missing frames
are indicators of long gaps and do not prove drops without sequence numbers.

Cached route preparation now happens before streaming starts. The acquisition
timestamps include per-sweep stream reset, LPSPI session setup/teardown, and
sampling; USB enqueue and foreground-loop work remain outside that interval.
Use start-to-start and sustained rate to compare total throughput, so moving
preparation out of the measured acquisition cannot be mistaken for its whole
benefit. No measured speedup is claimed before the board comparison.

## Completed hardware comparison, 2026-10-06

Candidate v2 completed all 252 captures with PASS verdicts. For both full arrays
at 20 MHz, manual LPSPI sustained throughput improved by 31.5%, from 10,524 to
13,837 sweeps/s; acquisition fell from 91 to 71 us. Offline raw checks also found
backward timestamps and status fragments in full-array-1 manual LPSPI at 10 MHz,
which the existing PASS criteria do not reject. Diagnose that stream anomaly
before treating the candidate as fully validated or adding further optimizations.

See [the measured comparison](TESTBOARD_7953_BENCHMARK_COMPARISON.md) for all 84
configurations, timing tails, baseline anomalies, excluded comparisons, and the
recommended next steps.

The USB exclusion repair has now been implemented and built after the user's
request. See [repair and validation](TESTBOARD_7953_USB_STREAM_DIAGNOSIS.md#implemented-repair).
It retains the sampling optimizations and adds strict runner 2.3 stream checks.
The user subsequently uploaded the repaired firmware. The focused 12 captures
and the complete matching 252-capture matrix passed with runner 2.3, zero
integrity/firmware error counters, and no retries. Independent raw checks confirm
the formerly affected configurations are clean. Full-array manual LPSPI at
20 MHz retains 13,841 sweeps/s, 31.5% above the original firmware.
See [the final repaired-firmware comparison](TESTBOARD_7953_USB_FIX_BENCHMARK_RESULTS.md)
for all configuration results and remaining timing limits.
