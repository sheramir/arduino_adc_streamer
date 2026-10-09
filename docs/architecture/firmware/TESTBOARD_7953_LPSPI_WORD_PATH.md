# TestBoard 7953 LPSPI word-path candidate

Implemented 2026-10-06 after [phase profiling](../../testing/benchmarks/testboard-7953/TESTBOARD_7953_PHASE_PROFILING_RESULTS.md)
identified the SPI transfer loop as 94.6-97.3% of acquisition time in the three
tested topologies. The user has completed the first 18 hardware captures:
all passed, with profiling-off throughput gains of 14.6-21.0%. See
[the measured comparison](../../testing/benchmarks/testboard-7953/TESTBOARD_7953_LPSPI_WORD_PATH_RESULTS.md).
The subsequent 36-capture manual/Auto-1, 10/20 MHz comparison also passes; see
[the mode/clock results and production-upload command](../../testing/benchmarks/testboard-7953/TESTBOARD_7953_LPSPI_MODES_RESULTS.md).
The production 252-capture matrix also passes with clean raw streams; see
[the production results](../../testing/benchmarks/testboard-7953/TESTBOARD_7953_LPSPI_PRODUCTION_RESULTS.md).
Long-gap latency and electrical/analog acceptance remain separate work.
No board upload or serial-port access was performed during implementation.

## Changes

- Each ADC caches its CS GPIO set/clear addresses and mask during `begin()`.
  The LPSPI sampling path writes those registers directly. Blocking and DMA
  retain their existing pin handling.
- `executeStreams` selects a compile-time engine implementation once per ADC
  stream pair. Word starts, polling, cancellation and completion no longer
  dispatch on the runtime engine inside that loop.
- LPSPI start/readiness/finish and the small ADC accessors are inline, allowing
  register access without separate calls in the generated word path. The
  session setup and error cleanup remain separate operations.
- LPSPI uses the Teensy startup-enabled DWT cycle counter for the existing 1 ms
  timeout. Unsigned subtraction handles rollover. Conversion using
  `F_CPU_ACTUAL` occurs once per stream pair. Extended waits service `yield()`
  every 10 us; interrupts remain enabled throughout. DMA retains its existing
  `micros()` deadline and per-poll `yield()`/EventResponder servicing.

Fresh TCF clearing, both RX readiness and transfer completion, 16-bit framing,
the existing 40 ns CS-high delay, response channel validation, pipeline state,
Vmid parking and session cleanup remain in place. There is no change to the
binary protocol, route ordering, sweep pairing, USB queueing or GUI.

## Offline validation

- Both `teensy41` and `teensy41_profile` build successfully.
- The native suite passes 1,188 acquisition configurations per build: all three
  engines, manual/Auto-1, all scan orders, repeats, optional Vmid and selected
  topologies. It checks tagged payload destinations, parking and bus ownership.
- Added checks establish that ordinary LPSPI sweeps do not resolve GPIO pins
  again, and production sweeps use `micros()` only for their two wire timestamps.
  Delayed, unequal transfer-completion flags exercise waiting with RX already
  ready. Stalled first/second buses exercise timeout, rollover, CS release,
  parking attempts and restart, with foreground servicing during long waits.
- 44 focused host tests pass for benchmark/profile handling and the USB patch.
- Both final ELFs pass the 38 USB interrupt/exclusion/flush scenarios.
- ARM assembly inspection confirms inline GPIO/register access, DWT-based
  polling without `micros()` or DMA calls, and no added interrupt masking in
  the LPSPI word function. Engine dispatch is outside that function.

Production FLASH code is 35,312 bytes; RAM1 variables are 17,664 bytes.
Diagnostic FLASH code is 40,688 bytes; RAM1 variables are 20,704 bytes.
Both have 12,832 bytes of RAM2 variables. Versus phase 1, the candidate adds
64 bytes of RAM1 variables and about 1.6 KB of FLASH code through specialization.
Native tests and assembly cannot establish electrical timing or real speedup.

## First hardware comparison: the same 18 captures

Upload the diagnostic environment to compare against the completed
`phase_profile_off_adc20_v2` and `phase_profile_on_adc20_v2` sessions. This also
avoids mixing production and diagnostic builds when comparing profiling off.

```powershell
pio run -d Arduino_Sketches/TestBoard_7953 -e teensy41_profile -t upload
```

Then run from the repository root, using fresh output directories:

```powershell
foreach ($profileMode in @('off', 'on')) {
  .\.venv\Scripts\python.exe Arduino_Sketches\TestBoard_7953\benchmarks\testboard_7953_benchmark.py `
    --port COM3 --scan-order adc `
    --route-set full_array1 --route-set all_four_full --route-set all_four_sparse_unbalanced `
    --tests __manual__lpspi__repeat1__vmidoff__ --spi-clock-hz 20000000 `
    --warm-up-ms 1000 --window-ms 5000 --repetitions 3 --seed 7953 `
    --no-drift-controls --profile $profileMode `
    --output "Arduino_Sketches\TestBoard_7953\benchmarks\results\lpspi_word_path_${profileMode}_adc20"
  if ($LASTEXITCODE -ne 0) { throw "LPSPI word-path benchmark failed: $profileMode" }
}
```

Compare off against off for sustained sweeps/s, acquisition and period/gap
median, p99, maxima and long-gap counts. Compare on against on for whole-run
transfer/session/USB phase attribution, accounting for probe disturbance.
Require clean first attempts, no new firmware errors, and clean whole-capture
framing/replay/timing checks. Preserve failed runs rather than overwriting them.

After the first comparison passes, use the same three route sets with
`--tests __lpspi__repeat1__vmidoff__` and both `--spi-clock-hz 10000000` and
`--spi-clock-hz 20000000`, initially `--profile off`, in a new directory. This
is 36 captures covering manual/Auto-1 and both clocks. Expand to the existing
252-capture compatibility matrix after confirming the candidate's benefit.

Verify actual SCK/CS framing and high time on hardware and check representative
analog signals, noise and ghosting before accepting the candidate. Do not
interpret a digitally clean stream alone as an analog settling test.

USB FIFO/batching and independent SPI-bus scheduling remain separate future
steps in the [optimization plan](../../plans/firmware/TESTBOARD_7953_NEXT_OPTIMIZATION_PLAN.md).
