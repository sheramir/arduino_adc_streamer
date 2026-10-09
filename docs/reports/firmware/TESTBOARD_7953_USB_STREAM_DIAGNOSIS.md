# TestBoard 7953: 64-byte stream replay diagnosis

Diagnosed 2026-10-06. Firmware, the installed Teensy package, the benchmark
runner, and captured results were not changed. No serial port was opened and
no firmware was uploaded. A standalone offline reproduction was added.

## Conclusion

The built Teensy USB serial implementation has a compiler-ordering race between
`usb_serial_write()` and its automatic-flush interrupt. The compiled writer
reads `tx_head` and `tx_available` before setting `tx_noautoflush`, even though
the C source places that flag first. The flag is volatile; the buffer-state
variables are not, and there is no compiler memory barrier after the guard.

A flush interrupt between those loads and the guard switches the active USB
buffer. The resumed writer uses its old buffer/capacity snapshot, while the next
flush uses the new global state. This can transmit stale buffer contents and
omit current data. Executing the actual built ARM code in an emulator reproduces
both stale binary frames and stale ASCII status text. Guard-first ordering
prevents the tested interleaving.

This is a demonstrated defect in the compiled core and a strong causal match
to the captures. The captures do not contain interrupt/register traces or an
on-board binary checksum, so a focused on-board retest after repair is still
needed to establish that this defect accounts for every observed anomaly.

## Raw capture evidence

Both configurations emit 25 samples per sweep: 4-byte header + 50-byte payload
+ 10-byte trailer = exactly 64 bytes.

| Session / configuration, full array 1 at 10 MHz | Repetition | Whole-frame exact replays | Backward timestamp steps | Parser-discarded bytes |
|---|---:|---:|---:|---:|
| Baseline, Auto-1 blocking | 1 | 37 | 2 | 0 |
| Baseline, Auto-1 blocking | 2 | 88 | 8 | 0 |
| Baseline, Auto-1 blocking | 3 | 84 | 7 | 64 |
| Candidate v2, manual LPSPI | 1 | 3,150 | 1,683 | 64 |
| Candidate v2, manual LPSPI | 2 | 3,029 | 1,618 | 128 |
| Candidate v2, manual LPSPI | 3 | 2,955 | 1,597 | 128 |

These are comparisons of all 64 bytes, not just equal ADC values. Candidate
captures contain 9,134 exact within-capture replays, approximately 3.7% of their
combined slots. Baseline captures contain 209. This is a lower bound on stale
data: frames replayed from a previous capture do not have an earlier match
within the current file.

For example, in candidate repetition 1, zero-based slot 60 is identical to slot
53, slot 61 to slot 48, and slot 62 to slot 32. Their start/end timestamps are:

| Slot | Start (us) | End (us) | Earlier matching slot |
|---:|---:|---:|---:|
| 59 | 4,287,084,783 | 4,287,084,855 | — |
| 60 | 4,287,084,335 | 4,287,084,409 | 53 |
| 61 | 4,287,083,964 | 4,287,084,036 | 48 |
| 62 | 4,287,082,773 | 4,287,082,845 | 32 |
| 63 | 4,287,084,932 | 4,287,085,004 | — |

Most candidate replay distances are 11–13 frame slots; baseline replay distances
are often around 100–123 slots. The USB core uses four 2,048-byte transmit buffers.
Small partial flushes recycle them more quickly than large buffered transfers,
consistent with the shorter candidate replay distances. The captures do not
record actual USB transfer boundaries, so the exact buffer assignment is inferred.

The malformed slots contain old command output: baseline `#OK false`; candidate
status fragments including `vmid_between_channels_requested=false` and
`route_count=25`. These fragments are compatible with stale contents remaining
in a reused USB buffer. The host log has no status request during the six-second
capture; the benchmark requests status before and after it.

## Why the fault depends on sampling mode

The [upstream USB serial core](https://github.com/PaulStoffregen/cores/blob/master/teensy4/usb_serial.c)
has a retriggerable 75 us flush timer. The two affected configurations have
typical sweep/write intervals around 73–74 us. Timer expiry and the next write
therefore can occur close together. Optimization moved manual LPSPI at 10 MHz
into this timing region. The baseline Auto-1 blocking configuration already
occupied it, which explains why this is not exclusive to the new LPSPI changes.
Other timings can still encounter the race under different interrupt/host load.

ADC/SPI operations cannot produce a previously transmitted frame with identical
start/end timestamps. The application encodes every frame before one USB write.
The core copies the application's bytes into its own transmit buffers, so the
application's ordinary output-buffer reuse is supported by the intended API.
The benchmark appends serial-read bytes to its raw capture before parsing, and
the stale frames are present in those raw bytes. Parser timestamp arithmetic
does not create them, though it inflates backward steps to nearly 2^32 us.
There is no evidence here that changing the ADC engine is the appropriate repair.

## Compiled instruction evidence

Installed package: `framework-arduinoteensy` 1.162.0, with the project's
`teensy@6.0.0` platform. The existing build's `usb_serial_write.part.0` begins
at 0x5978. Its critical entry sequence is:

```text
0x599e / +0x26: load tx_head into r5
0x59a0 / +0x28: load tx_available into r3
0x59a2 / +0x2a: calculate transfer descriptor using the loaded head
0x59a6 / +0x2e: store 1 to tx_noautoflush
```

The partial-buffer path keeps both loaded values. An interrupt at +0x2a or
+0x2e has a complete old snapshot while the guard is still zero. This is the
reproduced failure window. The compiled writer also loads `tx_available` before
reacquiring the flag after `yield()`; ordering must be enforced there too.

The end-of-write data synchronization barrier does not prevent entry loads
from moving ahead of the entry guard. Adding an empty GNU assembly statement
with a `memory` clobber immediately after each guard acquisition in a temporary
source copy makes the guard store precede these loads with the installed ARM
GCC at `-O2`. The installed package was not edited. This identifies a narrow
repair direction; it is not an integrated or uploaded fix.

## Deterministic reproduction

[reproduce_usb_tx_race.py](../../../Arduino_Sketches/TestBoard_7953/benchmarks/reproduce_usb_tx_race.py)
loads the existing ELF and executes the actual writer, timer-flush callback,
and transfer-preparation code using Unicorn. Only hardware submission is stubbed:
submitted bytes are captured immediately and the transfer is marked completed.
No USB device is used. It checks the relevant instruction bytes before running.

The test interrupts the writer at each of six entry instruction boundaries,
preserves/restores its CPU context, and runs the actual flush callback. It tests
both a buffer holding old complete binary frames and a buffer holding old status
text, then repeats six instruction boundaries with guard-first instruction order
in emulator memory. There are 26 scenarios including uninterrupted controls.

Representative result:

| Scenario | USB submissions | Stream bytes | Fresh frame present | Stale bytes present |
|---|---|---:|---|---|
| Uninterrupted original | 128 bytes | 128 | yes | no |
| Original, interrupt in race window | 64 then 128 bytes | 192 | no | yes |
| Guard first, same interrupt timing | 128 bytes | 128 | yes | no |

The unsafe case first flushes one pending frame. The resumed writer writes the
fresh frame using the old buffer index/offset, leaves a nonzero pending length
for the new buffer, and the subsequent flush submits two old frames or status
chunks from that new buffer. It creates both replay and missing fresh data.

Run from the repository root:

```powershell
uv run --no-project --with unicorn --with pyelftools python Arduino_Sketches/TestBoard_7953/benchmarks/reproduce_usb_tx_race.py
```

All 26 scenarios pass their expected assertions: the original reproduces the
failure, the ordered control does not. This helper is specific to the current
core instruction layout; it intentionally rejects a changed layout, including
a future repaired build, until its instrumentation is adapted.
The emulator does not model USB bus timing, physical DMA/cache coherency or
interrupt frequency, so it does not predict on-board error rates.

Artifacts examined (SHA-256):

- Existing `firmware.elf`: `0b08c1206e6cdfa528179abbe567e1c52a9040c7b00214ae80f179cd41bd7986`
- Installed core `teensy4/usb_serial.c`: `a675e0479e27cbad3a8e0fa6b918020af5b0f8894be43ebc495832995f5d842c`

## Recommended repair and validation

1. Enforce compiler ordering after transmit exclusion is acquired, including
   after waiting/yielding, and inspect the rebuilt machine code. Audit explicit
   flush acquisition too: its pending-byte check currently precedes exclusion,
   leaving a separate check/flush window. Keep the repair project-controlled and
   reproducible rather than manually changing a user's globally installed core.
2. Check USB write return counts, so a short write is visible. This is a separate
   protection: the emulator returns the full count even when the race corrupts
   output, so return-count checking alone cannot fix or detect this race.
3. Strengthen benchmark verdicts to reject backwards/duplicate timestamps and
   flag discarded bytes/resynchronizations. The present runner accepts matching
   headers/counts and plausible samples without stream continuity checks.
   Preserve the original results and version metadata when revising the runner.
4. After upload, first retest full array 1 at 10 MHz in manual LPSPI and Auto-1
   blocking, with three repetitions and raw captures. Add full array 2 and both
   full arrays as controls. Require no replays, backward steps, or discarded
   bytes. Then repeat the matching performance matrix to check the repair's
   throughput and timing tails. Sequence numbers/checksums remain a possible
   later protocol enhancement if stronger end-to-end detection is needed.

Per-sweep flushing or slowing sampling would change timing and might hide the
fault without repairing its underlying race.

## Implemented repair

Implemented 2026-10-06 after the user requested the fix. The project now uses
`scripts/pre_usb_core_patch.py` and `scripts/usb_core_patch.py` to substitute a
build-local repaired core through PlatformIO middleware. The source hash is
checked against the audited framework before patching; a changed core fails the
build. No installed framework file is changed. All four guard acquisitions have
compiler memory barriers, including reacquisition after `yield()`. The explicit
flush pending-length check is moved under exclusion, with guard release on its
empty early-return path. The 75 us timer and asynchronous USB transfers remain.

Application binary writes check the returned count. A short write increments
`usb_write_errors` and stops sampling instead of continuing a broken frame stream.
This adds a status counter while keeping commands and the binary frame layout.
PZR binary writes use the same return behavior.

Runner 2.3 adds whole-capture replay, timestamp regression, and invalid-timing
counts, propagates them through warm-up slicing, rejects discarded bytes and
resynchronizations, and checks `usb_write_errors`. Smoke and recovery captures
use the same stream checks. The original results have not been rewritten.
CSV schema changes require a new output directory. The Excel Results worksheet
includes the new numeric fields. A failed first attempt remains a failure row
and raw file even when an automatic retry passes; require no failed attempts
for stream-integrity sign-off.

Offline validation completed:

- PlatformIO build succeeds and compiles `patched_core/usb_serial.c` into the
  framework archive. Its machine code sets the guard before TX-state reads,
  at entry and after `yield()`, and before the explicit-flush pending check.
- The actual repaired ELF passes 38 emulated scenarios: binary/status stale
  buffers, entry interrupt positions, and explicit flush with pending/empty data.
  Every submitted stream contains the expected fresh bytes; the guard is released.
- The retained pre-fix ELF still reproduces corruption in the diagnostic's
  original 26 scenarios, guarding against weakening the reproducer.
- 123 focused Python tests pass, including benchmark verdicts, rollover,
  warm-up-only corruption, source patch validation, shared ADC124 benchmark
  helpers, ghosting behavior, reports, and firmware source contracts.
- Native execution passes the 1,188 digital acquisition configurations and
  short-write stop/release/restart checks with assertions enabled.

To rerun the repaired-core verification:

```powershell
uv run --no-project --with unicorn --with pyelftools python Arduino_Sketches/TestBoard_7953/benchmarks/reproduce_usb_tx_race.py --expect-fixed
```

Build/upload with the PlatformIO project so its middleware is included:

```powershell
pio run -d Arduino_Sketches/TestBoard_7953 -t upload
```

Then run this focused check on COM3. It schedules two sequence/engine choices
at two clocks, three repetitions each: 12 measured captures, plus startup smoke
checks. Both known failing configurations are included at 10 MHz; 20 MHz acts
as a timing control. ADC payload order, repeat 1, optional Vmid off, 1 s warm-up,
5 s measurement, seed 7953, and no drift controls match the earlier comparison.

```powershell
.\.venv\Scripts\python.exe Arduino_Sketches\TestBoard_7953\benchmarks\testboard_7953_benchmark.py `
  --port COM3 --route-set full_array1 --scan-order adc `
  --tests __manual__lpspi__repeat1__vmidoff__ --tests __auto1__blocking__ `
  --spi-clock-hz 10000000 --spi-clock-hz 20000000 `
  --warm-up-ms 1000 --window-ms 5000 --repetitions 3 --seed 7953 `
  --no-drift-controls `
  --output Arduino_Sketches\TestBoard_7953\benchmarks\results\usb_fix_check_adc_10_20
```

Require zero replay/regression/invalid-timing/discarded-byte counts, zero new
firmware errors, and no failed attempts. After that, use the original full matrix
with runner 2.3 and a fresh after directory to compare throughput. On-board
confirmation and performance measurements were pending at implementation time;
no upload or serial access was performed during implementation.

## Completed hardware validation, 2026-10-06

The user uploaded the repaired firmware. The focused check passed all 12 captures,
followed by the complete matching matrix in `optimization_after_usb_fix_adc_10_20`.
All 252 captures passed on their first attempt with runner 2.3. Every stream and
firmware error counter is zero, and the log contains no failed attempts.
Independent checks of all raw captures agree, including warm-up. Both formerly
affected configurations are now clean. The measurement windows contain
27,807,255 sweeps.

Full-array manual LPSPI at 20 MHz retains 71 us acquisition, 72 us median period,
and 13,841 sustained sweeps/s: 31.5% above the original firmware and +0.03% from
the pre-repair optimized run. Its maximum period is 77 us across three windows.
Other configurations retain occasional positive foreground gaps; their source
is not isolated by this test. No sequence number/checksum exists, so this is
validation of the tested integrity conditions, not proof of zero missing frames.

See [the repaired firmware results](../../testing/benchmarks/testboard-7953/TESTBOARD_7953_USB_FIX_BENCHMARK_RESULTS.md)
for all 84 comparisons, timing tails, limits, and the recommended GUI check.
