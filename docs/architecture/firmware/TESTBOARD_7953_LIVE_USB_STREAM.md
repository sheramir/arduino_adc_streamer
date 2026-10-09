# TestBoard 7953: keep sampling and discard sweeps when USB is busy

Implemented 2026-10-07, following the user's requirement for fresh live data.
PZT sampling must continue while USB is stalled. Sweeps that cannot be submitted
immediately are discarded, rather than stored for transmission after the stall.
This supersedes the earlier proposal to absorb stalls in a large frame FIFO.
No acquisition FIFO, new frame format, GUI change or automatic upload is added.

## Firmware behavior

- The project-local patch adds `usb_serial_try_write_frame` to the pinned
  Teensy 1.162.0 core. It reserves space for a complete wire frame under the
  existing ordered autoflush guard. It checks the actual current/next ring
  descriptors, rather than trusting `Serial.availableForWrite()`'s sum of other
  free descriptors. It has no host-completion wait or `yield` loop.
- A frame fits entirely or contributes zero bytes. Frames can span USB buffer
  boundaries, but a busy next descriptor is checked before any prefix is copied.
  Previously accepted partial buffers are submitted when rejecting a new frame,
  avoiding indefinite timer deferral from repeated failed attempts.
- PZT still executes and commits every complete SPI sweep, including channel
  pipeline state, validation and mandatory Vmid parking. A busy or disconnected
  USB path increments a discard counter and sampling continues. Recovery sends
  the newly completed sweep; there is no application history to drain.
- Invalid writer results remain errors and stop acquisition. PZR retains its
  existing write path. Explicit stop and timed-run completion still stop/park
  sampling. ASCII ACKs and status may block after stopping, as before.
- Frames, payload ordering and start/end timestamps remain unchanged. Received
  timestamps can have gaps because whole sampled sweeps were intentionally
  omitted. The unchanged binary format has no per-frame discard/sequence field.
- Existing USB buffers and Windows buffers still contain bytes already accepted
  before congestion was detected. They cannot be recalled by this change. The
  pinned core retains four 2 KB TX buffers; their total 8 KB storage corresponds
  to roughly 4.3 ms of full-array data at the previous production rate, not an
  additional 30-100 ms acquisition queue. Individual accepted bytes can still
  arrive much later if the host itself stalls. This change does not guarantee
  end-to-end delivery latency or that every frame generated after the physical
  start of a host stall is rejected; it discards when immediate capacity is gone.

USB submission still uses the core's short descriptor/cache operations. The
underlying transfer scheduler has a bounded hardware tripwire retry; sampling
can also still be interrupted by MCU interrupts or explicit command handling.
Hardware profiling is required to establish actual timing tails.

## Observability and benchmark interpretation

`status*` adds `usb_stream_policy=discard_if_busy` and per-run counters:

| Field | Meaning |
| --- | --- |
| `sampling_sweeps` | Completed sensor sweeps, including discarded sweeps |
| `usb_frames_sent` | Complete frames accepted by USB, not proof of host receipt |
| `usb_frames_discarded` | Complete sweeps omitted because USB was busy/disconnected |
| `sampling_period_max_us` | Largest actual sensor-sweep start interval, including warm-up |
| `sampling_period_over_1ms` | Actual sensor-sweep periods greater than 1 ms |

Counts reset on each successful PZT run. `usb_write_errors` stays cumulative and
does not count expected discards. On clean stopped runs,
`sampling_sweeps = usb_frames_sent + usb_frames_discarded`.

Runner 2.5 saves these fields as numeric result columns and preserves each
stopped status as JSON. It reconciles sent frames against all decoded frames,
including warm-up, and acquired/sent/discarded counts even with profiling off.
Discards are expected live omissions, not parser corruption. A PASS can include
discards; assess discard counts separately. A gap between received frames no
longer establishes a sensor sampling pause. Use the sampling-period diagnostics
or enabled acquisition profile to determine whether sensors stopped sampling.

Profile version 2 separates written, discarded and aborted attempts and includes
discarded sweeps in acquisition-period histograms. The decoder still accepts
version 1. Accepted writes must still match all received frames.

Reader controls are `--defer-parsing` (collect raw chunks and arrival times,
parse afterward) and `--reader-pause-ms N --reader-pause-at-ms 2000` (pause reads
once during each measured capture). Windows may absorb the pause in its own
buffers, so a reader pause does not necessarily stall USB. Check the discard
counter before claiming the test exercised backpressure. Use a fresh results
directory; resume cannot change these controls or profiling mode.

## Local validation

- Production `teensy41` and diagnostic `teensy41_profile` builds pass.
- Actual controller tests run 1,188 digital route/engine/sequence configurations
  per build mode. Additional tests run 400 consecutive discarded sweeps in each
  of six engine/sequence combinations, including disconnected USB, then check
  fresh recovery, parking, counters, timed stop and restart. Both profiling
  modes pass. These stubs do not establish electrical settling.
- The actual production ARM writer passes 649 emulator scenarios covering ring
  wrap, busy current/next slots, 18/64/114-byte frames, invalid requests,
  disconnects and autoflush interrupts at tested instruction boundaries.
  Conditional instructions inside Thumb IT blocks are excluded from interrupt
  injection because Unicorn cannot resume injected handlers there. Profile ELF
  receives the same test matrix. USB completion itself is modeled, not measured.
- The previous repaired-core race reproducer still passes on both final ELFs.
- All 118 selected pytest cases pass, covering live count reconciliation, historical profiles,
  discarded/aborted distinction, reader stress controls, deferred parsing and
  existing benchmark integrity checks. The 18 diagnostic hardware captures now
  pass: no acquired period exceeds 66 us, including during forced reader pauses.
  The subsequent 18 production mixed-engine captures also pass; LPSPI retains
  its rate with zero discards in both modes. DMA is approximately 3% slower
  and localized blocking-mode dips remain. Six production LPSPI forced-pause
  captures also pass: sensors continue at intervals no longer than 66 us,
  complete unsent sweeps are discarded and large resumption dips are absent.
  The original 252-capture matrix is now complete, with no actual sampling
  period above 171 us in any engine or 86 us in LPSPI. See
  [diagnostic hardware results](../../testing/benchmarks/testboard-7953/TESTBOARD_7953_LIVE_USB_RESULTS.md) and
  [production reduced/stall results](../../testing/benchmarks/testboard-7953/TESTBOARD_7953_LIVE_USB_PRODUCTION_RESULTS.md)
  and [completed full-matrix results](../../testing/benchmarks/testboard-7953/TESTBOARD_7953_LIVE_USB_FULL_MATRIX_RESULTS.md).

Validation command (no board access):

```powershell
uv run --no-project --with pytest --with ziglang --with numpy --with pyserial --with openpyxl --with unicorn --with pyelftools python -m pytest tests/test_testboard_7953_firmware_runtime.py tests/test_testboard_7953_firmware_profile.py tests/test_testboard_7953_benchmark.py tests/test_testboard_7953_usb_patch.py tests/test_testboard_7953_live_stream.py tests/test_testboard_7953_ghosting.py -q
```

## Upload and reduced hardware test

From `C:\Code\arduino_adc_streamer`, upload the diagnostic build yourself:

```powershell
pio run -d Arduino_Sketches/TestBoard_7953 -e teensy41_profile -t upload
```

Then run the supplied 18-capture validation (no drift controls):

```powershell
& Arduino_Sketches/TestBoard_7953/benchmarks/run_live_usb_validation.ps1 -Port COM3
```

It runs nine normal manual/LPSPI/20 MHz captures for array 1, both arrays and
single ADC3; three ADC3 manual/10 MHz captures for the earlier variation
exception; three deferred-parser both-array captures; and three with a 500 ms
reader pause. Each uses 1 s warm-up, 5 s measurement and three repetitions.
Review the planned matrix without opening the port with `-DryRun`. Use
`-Repetitions 1` for a six-capture first check, or `-PauseMs 1000` if 500 ms
does not produce firmware discards. Do not modify original comparison sessions.

Acceptance: no malformed/partial/replayed frames or firmware errors; sent versus
received counts match; sensor-period tails and USB-write durations do not exhibit
the former millisecond host waits when frames are discarded. Received-frame
gaps during deliberate reader pauses are expected. Compare normal/deferred
discard rates and steady acquisition timing. Compare channel variation and
post-gap dips within each ADC, using ADC1 1 MOhm, ADC2/ADC3 470 kOhm, ADC4
249 kOhm. Sensor continuity is verified by firmware timing, not received gaps.
After this focused test, run the production build and the original matrix for
compatibility/performance comparison. Profiling throughput is diagnostic.

## PC-side controls

Start with a direct PC USB port and compare another port, avoiding simultaneous
heavy traffic on a shared hub. PJRC notes that USB serial bandwidth depends on
the host controller, port and competing traffic:
[USB serial](https://www.pjrc.com/teensy/td_serial.html),
[host benchmark observations](https://www.pjrc.com/teensy/benchmark_usb_serial_receive.html).
Use the deferred-parser test to assess reader work before changing OS settings.

The full production matrix subsequently encountered a confirmed PC standby
interruption: Windows entered Modern Standby during repetition 129 and
re-enumerated the Teensy on wake, invalidating the open serial connection.
See the [incident timeline and resume instructions](../../testing/benchmarks/testboard-7953/TESTBOARD_7953_LIVE_USB_PRODUCTION_RESULTS.md#full-matrix-interrupted-by-pc-standby).
Keep the PC awake during benchmarks, including long post-capture CSV exports.
This explains that interruption, not all earlier short USB stalls, and does
not justify a firmware change or globally disabling USB selective suspend.

For the earlier short stalls while the PC was awake, there is no evidence
identifying USB selective suspend as the cause.
Keep selective suspend at its default for the first comparison; Microsoft
explicitly recommends against disabling it globally:
[USB selective suspend](https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/usb-selective-suspend).
Any later power-setting experiment should be a reversible, controlled comparison,
not a claimed fix. Changing COM baud does not change native Teensy USB speed.
USB bulk scheduling remains host-controlled; neither a firmware buffer nor a
Windows power setting can guarantee immediate delivery.
