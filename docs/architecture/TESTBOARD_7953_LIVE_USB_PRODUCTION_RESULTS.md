# TestBoard 7953: live USB production validation

Analyzed 2026-10-07. All 18 unpaused production captures and six subsequent
forced-pause LPSPI captures pass on their first attempts.
Both manual and Auto-1 LPSPI retain their previous throughput and discard no
sweeps with the deferred-parser reader. Actual sampling periods remain below
1 ms in every engine. DMA throughput is approximately 3% lower than the previous
production run, and blocking modes still have localized post-gap voltage dips.
Production LPSPI also keeps sampling through 500 ms reader pauses without
large resumption dips. The subsequent full 252-capture matrix is now complete;
see [full-matrix results](TESTBOARD_7953_LIVE_USB_FULL_MATRIX_RESULTS.md).

## Inputs and independent verification

Session: `Arduino_Sketches/TestBoard_7953/benchmarks/results/live_usb_production_all_four_adc20`.
Runner 2.5, completed 2026-10-07 at 17:04 UTC. Both arrays, 50 routes, ADC payload
order, manual/Auto-1, blocking/DMA/LPSPI, 20 MHz, repeat 1, optional
between-channel Vmid off, 1 s warm-up, 5 s measurement, three repetitions,
profiling off, deferred parsing and no deliberate reader pause. Initial and
stopped status report profiling unavailable, confirming the production build
class. The recorded Git revision does not fingerprint the uncommitted firmware
or uploaded binary.

Independently decoded every complete raw frame. Headers, route counts, 12-bit
sample ranges, positive acquisition times, monotonic nonoverlapping timestamps
and whole-frame uniqueness are valid, with uint32 rollover handled. Reconciled
warm-up cuts, measurement counts, duration/period medians and all submitted
frames against CSV, stopped status and profile records. Recomputed each
channel's measurement median, extrema and sample standard deviation from raw
values and checked the channel CSV. The approximately 9.2 GB per-sample CSV
was not needed. Source results and firmware were not modified, and the serial
port was not opened during analysis.

- Acquired sweeps: **1,253,924**.
- Submitted and received complete frames: **1,253,233**.
- Intentionally discarded sweeps: **691**, or **0.0551%** across the whole session.
- Acquired = submitted + discarded in all 18 runs, including warm-up.
- No reported firmware/ADC errors, invalid or duplicate frames, timestamp
  faults, resynchronizations, discarded bytes, trailing bytes or capture timeouts.
- No actual sensor sampling period above 1 ms. The largest is **175 us** across
  all engines, including warm-up and discarded sweeps.
- Checked **52,219,450 received measurement values** across all 50 routes.
  All channels pass the coarse startup-settling check, maximum **9.539 ms**.

## Throughput and sampling continuity

Compare matched configurations from
[`lpspi_word_path_production_adc_10_20`](TESTBOARD_7953_LPSPI_PRODUCTION_RESULTS.md).
Rates are medians of three measurement-window rates, computed from frame count
over first-start to last-end MCU elapsed time. They are not reciprocal median
periods. Discard counts and maximum actual sampling periods cover the whole run.

| Mode | Previous production sweeps/s | Live production received sweeps/s | Change | Median acquisition / received period, us | Largest actual sampling period, us | Discards in r1 / r2 / r3 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Auto-1 blocking | 11,529 | 11,578 | +0.42% | 85 / 86 | 91 | 6 / 26 / 277 |
| Auto-1 DMA | 7,040 | 6,854 | -2.64% | 144 / 146 | 175 | 7 / 6 / 4 |
| Auto-1 LPSPI | 16,279 | 16,317 | +0.24% | 60 / 61 | 66 | 0 / 0 / 0 |
| Manual blocking | 11,377 | 11,409 | +0.29% | 86 / 88 | 89 | 106 / 125 / 81 |
| Manual DMA | 6,802 | 6,602 | -2.95% | 150 / 151 | 152 | 8 / 16 / 29 |
| Manual LPSPI | 16,889 | 16,887 | -0.01% | 58 / 59 | 64 | 0 / 0 / 0 |

The LPSPI change is chiefly continuity under backpressure, not another typical
sweep-speed improvement. Manual delivers approximately 844,362 channel values/s
and 1.925 MB/s of 114-byte frames. Both LPSPI modes have zero discards in all
three repetitions. Their largest received periods also match the actual sensor
maxima: 64 us manual and 66 us Auto-1. Received-period p99 is 63 us manual and
65 us Auto-1.

Blocking and DMA have received gaps up to 2.416 ms and 1.803 ms respectively.
Those gaps reflect omitted transmissions, not equivalent sensor pauses:
whole-run sensor maxima remain 89-91 us for blocking and 152-175 us for DMA.
Always-on counters establish these maxima with profiling disabled; phase-level
USB write durations are unavailable in this build.

DMA's median acquisition itself increases from 141 to 144 us in Auto-1 and
145 to 150 us in manual. Its lower rate cannot be explained solely by omitted
frames. The cause is not isolated by these runs. Reader controls also differ:
the earlier production matrix parsed during capture, whereas this session
parsed afterward. Small gains and noise changes should not be attributed to
the firmware alone. DMA remains substantially slower than the selected LPSPI
engine; record this regression rather than hiding it behind an overall PASS.

## Channel statistics and remaining dips

Standard deviation below is the median across channels after taking each
channel's median across three repetitions. It measures observed signal
variation, not isolated electronic noise. Inputs were not controlled enough
to attribute every difference to USB or firmware.

| Mode | Previous standard deviation, counts | Live production, counts | Largest measurement departure from each channel's median, counts |
| --- | ---: | ---: | ---: |
| Auto-1 blocking | 0.714 | 0.533 | 12 |
| Auto-1 DMA | 0.506 | 0.526 | 3 |
| Auto-1 LPSPI | 0.592 | 0.493 | 3 |
| Manual blocking | 0.492 | 0.516 | 18 |
| Manual DMA | 0.528 | 0.534 | 5 |
| Manual LPSPI | 0.524 | 0.510 | 5 |

Both LPSPI modes show no received measurement values more than eight counts
from their own channel median, across **24,899,950 values**. Manual's largest
departure is five counts and Auto-1's is three. These are the unpaused captures;
the completed production forced-pause check below also finds no large
resumption dips.

The blocking modes contain 92 values beyond eight counts, across 69 frames,
exclusively ADC2 channel 11 and ADC4 channel 11. Of these, 86 are negative dips
and six are positive excursions. Eighty-three negative values occur at or
within 1 ms after a received gap greater than 500 us. Auto-1 dips appear on
ADC4 channel 11 in repetition 3, up to 12 counts; manual dips appear on both
channels across all three repetitions, up to 18 counts. These remain a
localized analog/timing concern despite valid framing and continuous sampling.
The counters do not support explaining them as millisecond-long sensor
sampling pauses. Their mechanism has not been identified, and the missing
sample voltages are unavailable.

Interpret these channels with the board bias map: ADC1 1 MOhm, ADC2/ADC3
470 kOhm and ADC4 249 kOhm. Sensor charging toward Vmid, leakage while
unselected, mux settling and engine-dependent timing remain relevant.
Coarse startup settling does not establish accuracy after each mux switch.
Baseline-relative noise/cross-mode warnings remain inactive in this ADC-order
session because it has no eligible interleaved-order reference. Absence of
those warnings is not analog sign-off. See the
[channel-quality review](TESTBOARD_7953_CHANNEL_QUALITY_RESULTS.md).

## Production forced-pause validation

Session `live_usb_production_pause500ms_adc20` completed 2026-10-07 at 17:19 UTC.
It uses the same production build and both-array settings, manual and Auto-1
LPSPI at 20 MHz, three repetitions, deferred parsing and one deliberate 500 ms
host-read pause at elapsed 2 s. All six pass on attempt 1. This confirms the
earlier diagnostic [forced-pause results](TESTBOARD_7953_LIVE_USB_RESULTS.md)
with probes disabled and adds Auto-1 stress coverage.

The independent raw-frame, timestamp, uniqueness, warm-up, status-counter and
per-channel-statistic checks used above all pass for these six captures.
Acquired **598,025** sweeps = **548,838** submitted/received + **49,187** discarded.
Every capture has real firmware discards, so the test exercised board-side
backpressure rather than only Windows buffering. There are no firmware errors,
framing/timestamp faults, resynchronizations or partial frames. No actual
sampling interval exceeds 1 ms, including warm-up and discarded sweeps.

| LPSPI mode | Discards in r1 / r2 / r3 | Largest actual sensor period, us | Received gap, ms | Delivered measurement sweeps/s | Median acquisition / received period, us |
| --- | --- | ---: | --- | ---: | ---: |
| Auto-1 | 8,057 / 8,057 / 8,057 | 66 | 489.970-489.971 | 14,718 | 60 / 61 |
| Manual | 8,341 / 8,333 / 8,342 | 64 | 489.491-490.020 | 15,233 | 58 / 59 |

Discard fractions are 8.219-8.228% of whole captures including the 1 s warm-up.
Delivered measurement rate is lower because the 5 s window contains the
intentional omissions; typical acquisition/period medians are unchanged.
A received gap of approximately 490 ms is not a sensor sampling pause.

Independently checked **22,461,000 received measurement values**. No value is
more than eight counts from its own channel's measurement median; the largest
departure is three counts in Auto-1 and six in manual. In the first 10 ms of
received data after each largest gap, every channel stays within **two counts**
of its median. Comparing each channel's 10 ms pre-gap and post-gap medians
shows a maximum shift of one count in Auto-1 and two in manual. There is no
large post-stall voltage dip in these recordings. Untransmitted sample voltages
remain unobservable; the firmware counters establish their sampling continuity.

Median per-channel standard deviation is 0.493 counts for paused Auto-1 versus
0.493 unpaused, and 0.524 for paused manual versus 0.510 unpaused. Manual's
third repetition has more variation, but not a large gap-resumption excursion.
These sequential sensor measurements do not isolate electronic noise or
establish settling accuracy after every mux switch. All channels pass the coarse
startup-settling check, maximum 5.148 ms.

Reproduction command for the completed six-capture session:

```powershell
.\.venv\Scripts\python.exe Arduino_Sketches\TestBoard_7953\benchmarks\testboard_7953_benchmark.py `
  --port COM3 --scan-order adc --route-set all_four_full `
  --tests __lpspi__repeat1__vmidoff__ --spi-clock-hz 20000000 `
  --warm-up-ms 1000 --window-ms 5000 --repetitions 3 --seed 7953 `
  --no-drift-controls --profile off --defer-parsing `
  --reader-pause-ms 500 --reader-pause-at-ms 2000 `
  --output Arduino_Sketches\TestBoard_7953\benchmarks\results\live_usb_production_pause500ms_adc20
```

## Completed full-matrix validation

The original 252-capture ADC-order compatibility matrix completed after resuming
the PC-standby and disk-full interruptions. Every final capture passes independent
raw checks, with actual sampling periods no longer than 171 us across all engines
and 86 us in LPSPI. Manual both-array LPSPI retains 16,887 sweeps/s and discards
zero sweeps at 20 MHz. See the [full-matrix analysis](TESTBOARD_7953_LIVE_USB_FULL_MATRIX_RESULTS.md)
for throughput, channel statistics and resume/export artifacts. Reproduction command:

```powershell
.\.venv\Scripts\python.exe Arduino_Sketches\TestBoard_7953\benchmarks\testboard_7953_benchmark.py `
  --port COM3 --scan-order adc --tests __repeat1__vmidoff__ `
  --spi-clock-hz 10000000 --spi-clock-hz 20000000 `
  --warm-up-ms 1000 --window-ms 5000 --repetitions 3 --seed 7953 `
  --no-drift-controls --profile off --defer-parsing `
  --output Arduino_Sketches\TestBoard_7953\benchmarks\results\live_usb_production_adc_10_20
```

This command was dry-run checked: 84 configurations times three repetitions,
with no serial-port access. Compare elapsed-time rate, duration, received-period
tails, actual sensor-period maxima, intentional discard counts, errors and
channel statistics. The previous matrix used parsing during capture, so
reader-dependent differences should not be attributed solely to firmware.
The full matrix now covers all seven route sets and both clocks in this configuration.
Investigation of the blocking dips and DMA rate change remains separate
from the demonstrated LPSPI stall behavior. GUI hardware testing stays deferred
until the [GUI repair](TESTBOARD_7953_GUI_PERFORMANCE_REVIEW.md).

### Full matrix interrupted by PC standby

The first full-matrix attempt saved 128 PASS repetitions, all on attempt 1,
and 128 raw captures. Repetition 129 (both full arrays, manual LPSPI, 10 MHz,
r3) was interrupted by a Windows serial-device error. It has no completed
result or saved raw capture at that point and required repeating. The user
subsequently resumed this repetition and completed the matrix.

Windows System events explain the interruption, in local Eastern time on
2026-10-07:

- 14:12:51: benchmark starts repetition 129.
- 14:12:55: Kernel-Power event 506 records entry to Modern Standby, reason
  `SC_MONITORPOWER`; nearby event 566 records `SleepButton`.
- 14:27:02: USBHUB3 event 205 records re-enumeration and a port cycle for
  VID `16C0`, PID `0483`, matching the Teensy serial device.
- 14:27:04: Kernel-Power event 507 records exit from Modern Standby on mouse input.
- 14:27:05: benchmark reports `ClearCommError` failure, Windows error 22.

This identifies a PC suspend/resume and USB reconnection interruption, not
evidence of a new SPI framing failure. It does not explain every earlier
millisecond USB stall. Microsoft's [Modern Standby description](https://learn.microsoft.com/en-us/windows-hardware/design/device-experiences/modern-standby)
describes the screen-off/sleep transition, and
[Windows error codes](https://learn.microsoft.com/en-us/windows/win32/debug/system-error-codes--0-499-)
identify error 22 as `ERROR_BAD_COMMAND`; the Python `PermissionError` label
does not establish that administrative permissions are needed.

COM3 enumerated again after wake. The recovery was to keep the PC awake,
temporarily avoid automatic display-off/sleep and manual sleep/lid-close actions,
and rerun the command above with `--resume` and the same output directory.
At that interruption the resume logic recognized 128 saved repetitions and left
124 to run, starting with the interrupted r3 after its startup smoke checks.
Disk space later ran out after 152 saved repetitions; cleanup and another
resume completed the remaining 100. The final session is complete.
No firmware or benchmark code was changed for this incident. Do not silently
splice samples across a USB reconnection into one capture.

The wire format has no sequence number/checksum; the checks detect the listed
faults, not every possible payload corruption. These captures also do not
measure acquisition-to-GUI display age. Accepted USB/Windows bytes may arrive
late even though the board keeps sampling and stores no acquisition history.
