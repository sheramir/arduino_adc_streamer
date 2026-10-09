# TestBoard 7953 GUI repair and host replay validation

Implemented and replay-tested 2026-10-07 against the requirements in
[the GUI review](../../../reports/gui/TESTBOARD_7953_GUI_PERFORMANCE_REVIEW.md),
[the completed live production matrix](../../benchmarks/testboard-7953/TESTBOARD_7953_LIVE_USB_FULL_MATRIX_RESULTS.md)
and [the experimental 30 MHz report](../../benchmarks/testboard-7953/TESTBOARD_7953_LPSPI_30MHZ_RESULTS.md).
No firmware source, upload, clock recommendation or ADC wire format was changed.
20 MHz remains the production recommendation.

## Host pipeline

On Windows, TestBoard capture now reads the existing COM handle in an isolated
Python process, protecting raw reads from plotting/archive GIL contention.
Owned chunks of at most 64 KiB pass through bounded 16 MiB child and bridge
queues, then the serial QThread feeds the bounded 16 MiB decoder queue.
Other boards/platforms retain the threaded raw reader. A separate continuous
decoder owns partial-frame/text state.
TestBoard's fixed-width frames are vector-validated in consecutive runs, with
the existing scalar resynchronization path for corrupt headers, timing fields
and mixed ASCII replies. The same header, sample-count and timing sanity limits
apply to both paths. Legacy boards keep their existing per-block signal interface.

For ordinary TestBoard capture, validated frames form host batches at roughly
20 ms, bounded additionally by 1,500 sweeps and 256 KiB of framed data. An owned
NumPy matrix and the individual start/end/average timestamp vectors go directly
to a widget-free acquisition worker, through a 32 MiB bounded queue. There are
no per-frame GUI callbacks. The capture descriptor, route groups and column
indices are frozen for that worker. Its ring metadata and arrays share the GUI's
buffer lock; snapshots copy coherent ranges while holding that lock.

The worker extends successive device timestamps into an int64 microsecond
timeline; elapsed time does not return to zero after 71.6 minutes. Ordinary
rollovers are retained, while backwards/duplicate timestamps, overlapping frames
and ambiguous intervals above 60 seconds interrupt this high-rate capture.
Without a device boot identifier, a restart close to a legitimate rollover can
remain indistinguishable on the existing wire. Host queue ages use the same
monotonic high-resolution clock; they are not absolute sensor-to-display latency.

Median-of-three and optional IIR state continue across host batch boundaries.
The first 101 delivered starts provide a fixed initial period estimate independent
of batch division; a shorter stopped capture uses its available starts. Received
intervals above `max(10 us, 3 normal sweep periods)` split contiguous segments.
Median/IIR and active physical force state reset at these boundaries. This policy
detects substantial missing intervals; the wire has no sequence number to identify
every omitted individual sweep. FFT/PSD and calculated offline force reject
affected windows. Pressure Map HPF/moving sums restart per contiguous segment;
Heatmap processing uses the latest contiguous segment. Existing decay fitting
already excludes separated cadence runs with explicit rejection reasons/warnings.
No archive timestamps or measurements are interpolated across gaps.

Once physical Force Display is activated, its acquisition consumer continues
while its dock/tab is hidden. Its ordered samples are consumed in the acquisition
worker, with no latest-only physics queue eviction. Only render results are
replaceable. Active decay characterization on supported older boards retains
its existing all-sample path; TestBoard offers the voltage preview because its
firmware does not supply physical connection timing for decay characterization.

## Persistence and GUI behavior

JSONL sweep compatibility is retained. The archive queue is bounded to 64 MiB
and 2,048 items, counts pending sweeps/bytes, and measures oldest-item age.
It owns arrays and writes whole host batches without the previous fixed 2 ms
sleep. Per-frame timing-sidecar rows are written by the same persistence worker,
including original uint32 start/end timestamps, average intervals and device gaps.
Optional ghost startup calibration has a separate 64 MiB pending-data budget;
Zero Signals changes are ordered through the acquisition worker and recorded.

A 5 Hz GUI timer renders the newest coherent ring snapshot. Intermediate display
requests are coalesced; received acquisition/archive batches are not evicted.
The ordinary decay preview runs only on a visible tab and copies at most 5,000
rows of its selected column. It never copies the entire history matrix per frame.
Time Series has a TestBoard-only seconds control (default 1 s, zero selects the
existing sweep-count control). Its time window is bounded by the 50,000-row ring:
about 2.94 s at 17,000/s and 0.67 s at 75,000/s. Full archives remain independent
of that memory limit. Pixel/total-point min/max envelopes keep narrow extrema
and NaN discontinuity markers; these display arrays never feed analysis/export.
Time Series uses 1-pixel pens, clipping and cached unchanged pen/axis settings.

The status bar and its tooltip expose queue depths, bytes, oldest ages, worker
and render duration, source freshness, decode-to-render age and received gaps.
Missing arrivals or old pipeline data show **Stale data** after 500 ms. Queue
budget exhaustion or writer failure stops capture and reports it as incomplete;
data are never silently discarded to make the display current.

Stop acknowledgment precedes an ordered decoder flush and acquisition drain.
No arbitrary serial-byte clear is used for TestBoard stop. Capture generations
exclude old batches and old timed-run callbacks. JSONL ends with a
`capture_summary` record containing completion/interruption, received counts,
parser rejections, pipeline statistics and archive written/overrun counts.
Stopped TestBoard status supplies `sampling_sweeps`, `usb_frames_sent`,
`usb_frames_discarded`, `sampling_period_max_us` and `sampling_period_over_1ms`
when available. These are run-scoped and are never polled while streaming.
Device submitted/host accepted/processed counts are reconciled when supported.
Pre-run counters are excluded from the frozen configuration snapshot so a
previous run's diagnostics cannot be mistaken for the new capture's counters.
Reload and CSV metadata retain the summary; sample readers skip its footer.

Windows capture requests temporary system wakefulness, released on stop/error/
exit. USB read failures finalize an incomplete archive and preserve it during
disconnect; a reconnect/new capture creates fresh parser/filter/timestamp state.
Failed archive files are retained by cache cleanup. Deliberate sleep/removal can
still interrupt USB; keep-awake does not guarantee delivery.

## Replays

`scripts/benchmark_testboard_gui.py` uses the real offscreen GUI, shown for layout
and painting, an isolated temporary settings/archive directory and a finite mock
serial source. It opens no hardware port. The source paces 10 ms bursts, splits
frames across reads and crosses uint32 rollover. Recording, median-of-three and
the default 60/120 Hz IIR notches were active. Counts below include the entire
source, without warm-up exclusions.

| Routes | Target frames/s | Seconds | Received = archived | Heartbeat p95 |
| --- | ---: | ---: | ---: | ---: |
| 50 | 12,000 | 5 | 60,000 | 33.1 ms |
| 50 | 17,000 | 5 | 85,000 | 45.2 ms |
| 10 | 60,000 | 5 | 300,000 | 26.0 ms |
| 50 | 20,000 | 5 | 100,000 | 42.1 ms |
| 10 | 75,000 | 5 | 375,000 | 34.2 ms |
| 10 | 75,000 | 30 | 2,250,000 | 33.3 ms |

All completed with zero parser rejections and zero trailing capture bytes.
The 30-second run's maximum observed pending raw data was 102,000 bytes,
decoded backlog 4,500 sweeps and archive backlog 1,500 sweeps, with empty queues
after drain. Heartbeat maximum was 417 ms; p95 is not a promise that every event
arrives within 100 ms. Finite-source idle time before stop contributes to final
read/age measurements. See the machine-readable
[capacity matrix](../../datasets/testboard-7953/TESTBOARD_7953_GUI_REPLAY_RESULTS.json) and
[sustained run](../../datasets/testboard-7953/TESTBOARD_7953_GUI_SUSTAINED_REPLAY_RESULTS.json).

The [10-second stall replay](../../datasets/testboard-7953/TESTBOARD_7953_GUI_STALL_REPLAY_RESULTS.json) received
and archived all 750,000 sweeps with separate 500 ms reader and GUI pauses.
Heartbeat p95 was 26.6 ms, maximum 511 ms including the intentional GUI sleep.
Pending raw data peaked at 678,022 bytes, decoded backlog at 36,000 sweeps and
archive backlog at 3,000 sweeps. A fresh render returned about 11 ms after the
GUI pause; it was already current at the first observed pipeline-catch-up check.
This mock retains a finite source during the read pause. It tests host backlog
recovery, not the board's live-discard behavior; explicit 500 ms timestamp gaps
are tested separately against the real parser/worker/archive path.

[Visible-tab replays](../../datasets/testboard-7953/TESTBOARD_7953_GUI_TAB_REPLAY_RESULTS.json) preserved all
85,000 sweeps at 17,000/s on Spectrum, Heatmap and Pressure Map, and all 375,000
at 75,000/s on the decay preview. Heartbeat p95 values were 20.3, 17.7, 59.1 and
17.5 ms respectively. Pressure Map used its normal preview; these rates do not
certify sustained physical force integration for every nonlinear force setting.
Ordered force delivery and reset are regression-tested separately. If an active
analysis exceeds its processing budget, capture reports an incomplete overrun
instead of dropping that analysis's received samples silently.

Tests also cover corrupt/partial frames, mixed ASCII replies, source ordering,
exact archived timestamps and raw sample values, multiple device rollovers without
waiting in real time, restarts, different median/IIR batch divisions, gap resets,
narrow peak/marker preservation, real GUI stop/restart with an old timed callback,
archive reload, USB removal and a forced bounded-queue overrun.

The full host regression suite passed after the reader follow-up: **1,026 passed, 5 skipped, 34 subtests
passed**. Firmware source-contract tests were included; firmware files were not
modified.

To reproduce:

```powershell
.venv/Scripts/python.exe scripts/benchmark_testboard_gui.py --seconds 5 --filters
.venv/Scripts/python.exe scripts/benchmark_testboard_gui.py --seconds 30 --width 10 --rate 75000 --filters
.venv/Scripts/python.exe scripts/benchmark_testboard_gui.py --seconds 10 --width 10 --rate 75000 --filters --stall
.venv/Scripts/python.exe -m pytest -q
```

## Follow-up: blank live traces and Force Display failure

A user capture exposed gaps in the initial display validation. Freezing a new
capture reset the visible array to Array 1 without rebinding the existing Array 2
channel selectors; the plot then had no selected matching traces. A stopped plot's
manual viewport could also persist into live capture. With clipping enabled, data
outside that viewport reduced to one point and produced no visible line.

Capture now retains a valid selected array, rebuilds selectors against the frozen
capture identities while retaining checkbox choices, and restores live X/Y range
behavior at start. Real GUI regressions check populated, visible traces on each
array both with and without a previous manual zoom.

The incomplete capture's archived worker error was `force array packages require
unique ids and grid positions`. Force results had attempted to compose both
physical arrays on one grid. They now compose separately per array, with one shared
publication path for both force workers. An acquisition failure forwards its
original error to the decoder instead of replacing it with a generic closed-worker
message. The user's original archives were only read during diagnosis.

The [follow-up display replay](../../datasets/testboard-7953/TESTBOARD_7953_GUI_DISPLAY_REPLAY_RESULTS.json)
repeated the five filtered capacity targets with an additional assertion that live
traces contain finite data inside the actual plot viewport: all 25 selected traces
were visible for 50-route captures and all 10 for single-array captures. Counts
matched at every rate, including 375,000 received/archived sweeps at 75,000/s.
This supplements the earlier count/throughput results; those alone had not verified
trace visibility.

## Follow-up: real transmission gaps and Windows reader wait

The user's 2026-10-08, 185.34-second capture (50 routes, both arrays, manual
LPSPI at 20 MHz) recorded 2,322,413 accepted sweeps and archived all of them,
with zero archive overruns. Stopped firmware diagnostics reported 3,136,562
sampling sweeps, 2,322,433 submitted frames and 814,129 device discards (25.96%).
The maximum reported actual sampling interval was 64 us. There were also two
parser rejections and a 20-frame submitted/accepted discrepancy; the capture
was correctly marked incomplete. No source files were changed during diagnosis.

The timing sidecar confirms 11,903 received intervals above three nominal
59 us sweep periods. Their median was 2.941 ms, p99 16.801 ms and maximum
37.359 ms. These are missing transmissions, not fabricated plotting gaps or
equivalent sensor sampling pauses. The plot continues to show discontinuities.

The ADC reader still used `QThread.msleep(2)` when no bytes were waiting. A
200-call measurement on this Windows machine found a 10.476 ms median and
18.893 ms p95, versus 2.520 ms and 2.683 ms for Python `time.sleep(0.002)` in
the installed Python 3.12 runtime. The idle reader now uses the latter, retaining
the same requested interval and bounded queues. This removes an observed coarse
wait without busy polling, changing timer resolution globally, or changing the
wire protocol. It is a plausible contributor to backpressure, not proof that
every device discard has been explained or eliminated.

After this change, 98 focused serial/pipeline/GUI tests passed. A filtered
17,000/s replay retained all 85,000 sweeps and showed all 25 live traces, with
heartbeat p95 29.4 ms. The finite mock cannot establish device-discard rates.
Repeat the board capture after relaunch and compare whole-run stopped counters,
parser rejections and received gap statistics to verify the hardware effect.

## Follow-up: recurring gaps after the finer idle wait

The next user capture (2026-10-08, 42.84 seconds, same 50-route production
configuration) reported 723,634 sampling sweeps, 693,868 submitted frames and
29,766 device discards: 4.11%, down from 25.96% in the preceding capture.
All 693,679 accepted sweeps were archived, with zero archive overruns. There
were 18 parser rejections and a 189-frame submitted/accepted discrepancy;
the capture remained correctly marked incomplete. Earlier counters alone do
not reveal the rejection causes, so the first ten rejection reasons and timing/
width fields now persist in generation-scoped reader diagnostics. Validation
limits are unchanged.

The sidecar contains 425 received intervals above three nominal 59 us periods,
with median duration 3.763 ms and maximum 18.447 ms. Inter-gap spacings cluster
around 15–20 ms and 180–210 ms. The latter is consistent with the 200 ms plot
refresh cadence, but this correlation does not establish the cause of every gap.

The reader now issues a bounded blocking one-byte read when a real port is
empty, then immediately drains its available burst. This follows the firmware
benchmark reader's arrival-driven strategy instead of waking to poll every
2 ms. Read timeout is capped at 20 ms and restored when the reader exits;
explicitly nonblocking ports and test sources retain a fine sleep fallback.
Regression tests cover arrivals after an empty read, split headers, ordered
1,000-frame bursts, stop/drain and timeout restoration for finite/infinite
original timeouts.

Installed pySerial's Windows backend requests a 4 KiB driver receive buffer
on open, about 2 ms at the production stream load. Where `set_buffer_size` is
available, the reader requests 64 KiB of receive headroom, retaining the 4 KiB
transmit request. This is bounded and advisory; driver acceptance/effective
capacity is not guaranteed. A rejected optional request is recorded and does
not abort acquisition. Reader diagnostics distinguish a request from verified
capacity. No OS-wide timer or firmware setting is changed.

Peak reduction now finds each bin's original min/max indices in vectorized
NumPy operations, retaining the same uneven bin boundaries, extrema, endpoint
timestamps and explicit gap markers. A 30-iteration local probe of 25 traces,
17,000 points each and a 480-point budget measured median reduction time
12.645 ms before and 3.378 ms after this change. This reduces periodic Python
work that can compete with the reader; it is not an end-to-end latency figure.

The [arrival/peak-reduction replay](../../datasets/testboard-7953/TESTBOARD_7953_GUI_ARRIVAL_REPLAY_RESULTS.json)
records the repeated filtered capacity cases with visible-trace assertions.
Its finite nonblocking mock still cannot certify device-discard behavior or
Windows driver queue capacity. A new live capture is required to establish
the remaining discard rate and inspect any recorded rejection examples.

## Follow-up: remaining large gaps and isolated Windows USB reads

The user's next capture (`adc_data_20261008_100953_032303`, 14.80 seconds,
50 routes, manual LPSPI/20 MHz) reported 250,005 sampling sweeps, 242,192
submitted frames and 7,813 device discards (3.125%). All 242,152 accepted
sweeps were archived, with zero archive overruns. There were four timing
rejections and a 40-frame submitted/accepted discrepancy. The maximum actual
sampling interval remained 64 us, with no sampling intervals above 1 ms.
The sidecar contains 140 received intervals above three nominal 59 us periods;
median duration is 2.735 ms and maximum is 16.978 ms. The maximum host read
interval is 28.644 ms. These remain real missing transmissions. The original
capture files and firmware were only read during diagnosis.

The rejection examples have average-time fields containing ADC-sized values
(2030–2031 us) and timestamp words consistent with a two-byte footer shift.
The existing examples cannot establish whether or where bytes were altered.
Diagnostics now retain at most 256 surrounding raw bytes for each of the first
ten rejections per generation, together with the candidate offset. This permits
examining the actual next header/footer boundaries without weakening validation
or fabricating replacement measurements.

A Python reader thread can still wait for GUI and JSON execution in the same
process. TestBoard's Windows native reader now starts a hidden Python process
before `run*`, duplicates the already open COM handle with `DuplicateHandle`,
and gives the child its own overlapped-read event. There is one active serial
reader; the parent hands over at a completed read boundary. The child performs
only raw serial reads, bounded chunk coalescing/FIFO enqueueing, and pipe delivery. Commands keep
using the original parent port. No second port open, reset, firmware upload,
command change or ADC wire-format change is introduced. Private IPC framing is
removed before the unchanged decoder sees the original bytes.

The child's raw FIFO and parent bridge FIFO each have 16 MiB / 2,048-item
limits, in addition to the existing decoder/worker/archive budgets. Pipe writes
run in a separate child thread so a stalled parent cannot immediately block USB
reads. Budget exhaustion interrupts capture explicitly; queued owned bytes
drain before the bridge reports its fault. Startup failure prevents `run*`.
The child persists across capture generations and exits before COM close on
disconnect. Shutdown allows bounded graceful exit, then terminates a child
that fails to exit. Child cleanup closes its duplicated handle and event;
it does not restore shared COM timeouts. The parent restores its original
timeout after child shutdown.

Reader diagnostics identify `transport.kind=isolated_process`, bridge depth/
age, both queue budgets, child peak queued bytes and delivery age. The child
records actual read completion using the same Windows monotonic clock; decoder
age includes pipe delay. Transport high-water marks and byte totals are
connection-scoped (`connection_received_bytes` includes ASCII replies), while
accepted frames/rejections remain capture-scoped. Child pending bytes are the
last reported snapshot, not a claim of its instantaneous backlog. The status
bar exposes bridge backlog/age and includes it in stale-data detection.

Process tests deliberately hold the parent's Python GIL for 200 ms at both
17,000 x 50 and 75,000 x 10 values/s. Child arrival timestamps demonstrate
continued reads during the stall; all raw samples, headers and MCU timestamps
remain ordered and exact. Tests also cover startup failure, bounded overrun,
owned-prefix draining, stop/child exit, generation reuse, malformed-frame
context and real GUI display/archive reload across MCU rollover.

The [isolated-reader replay](../../datasets/testboard-7953/TESTBOARD_7953_GUI_ISOLATED_REPLAY_RESULTS.json)
uses the production process/pipe and startup handoff with a finite synthetic
source inside the child. All filtered five-second cases displayed signals and
matched expected/received/archived counts with zero parser rejections:

| Routes | Sweeps/s | Archived sweeps | Live heartbeat p95 |
| ---: | ---: | ---: | ---: |
| 50 | 12,000 | 60,000 | 18.75 ms |
| 50 | 17,000 | 85,000 | 19.58 ms |
| 10 | 60,000 | 300,000 | 15.35 ms |
| 50 | 20,000 | 100,000 | 24.72 ms |
| 10 | 75,000 | 375,000 | 16.02 ms |

Heartbeat timing starts after reader startup, before live GUI event processing.
Finite-source read-interval maxima include the approximately 300 ms wait between
the source's last frame and its stop reply; they are not streaming stalls.
The [isolated stall replay](../../datasets/testboard-7953/TESTBOARD_7953_GUI_ISOLATED_STALL_REPLAY_RESULTS.json)
also preserved all 375,000 sweeps during a synthetic 500 ms source-read pause
and separate 500 ms GUI pause, with fresh rendering 13.45 ms after GUI resume.
Unlike the live discard policy, this finite source retains its paused history;
that replay establishes host drain/recovery behavior, not lossless acquisition.

These tests do not exercise physical Windows COM-handle duplication or prove
that the remaining hardware discards are gone. Repeat the user's production
capture after relaunching the GUI, confirm the isolated transport in its archive
footer, and compare stopped discard counters, received gap durations and any
raw rejection contexts. Keep the current validated firmware and 20 MHz settings.

To reproduce the isolated runs:

```powershell
.venv/Scripts/python.exe scripts/benchmark_testboard_gui.py --seconds 5 --filters --isolated-reader
.venv/Scripts/python.exe scripts/benchmark_testboard_gui.py --seconds 5 --filters --isolated-reader --stall --width 10 --rate 75000
```

## Follow-up: Windows venv launcher caused immediate disconnection

The user's 2026-10-08 10:59/11:00 logs show successful connection and
configuration, followed immediately after start by the isolated reader's
`ClearCommError` failure (incorrect function or invalid handle). Both captures
archived zero sweeps. This was a host handoff bug introduced by the isolated
reader, not evidence that the original gap repair had passed hardware startup.

On this machine, launching `.venv/Scripts/python.exe` starts a redirector whose
PID differs from the actual interpreter. A local reproduction reported launcher
PID 81,760 and interpreter PID 118,104. The old code duplicated the COM handle
into `Popen._handle`, belonging to the redirector. The numeric handle then sent
to the actual interpreter could name an unrelated handle or no valid handle.
The synthetic backend never used that COM handle and therefore missed this bug.

The child now reports its own `os.getpid()` before receiving settings. The
parent opens and pins that actual process, duplicates the COM handle into it,
and retains the process handle until shutdown to avoid PID reuse. Diagnostics
include both `launcher_pid` and `reader_pid`. A local corrected startup reported
launcher 101,508, reader 124,556 and handle target 124,556. Handle access and
duplication follow [Microsoft's DuplicateHandle API](https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-duplicatehandle).

After attaching the handle and read event, the child now probes COM status before
sending ready; a failed probe prevents `run*`. Forced shutdown also terminates
and waits for the actual interpreter, then reaps the redirector, instead of
terminating only the launcher and potentially orphaning a reader holding COM.
Original parent port ownership, wire commands, firmware and timeout restoration
are preserved.

New native Windows regressions duplicate a real signaled event into an actual
interpreter launched through the same virtual-environment Python, verifying
that the child can use it and that the parent's original handle stays valid.
Other tests reject a transferred non-COM handle before ready and force an
unresponsive reader to exit without leaving its interpreter behind. These are
real Windows process/handle tests; they do not require or open a hardware port.
The [PID-corrected replay](../../datasets/testboard-7953/TESTBOARD_7953_GUI_ISOLATED_PID_REPLAY_RESULTS.json)
repeats the five filtered capacity cases through the corrected process bootstrap:
all 920,000 expected sweeps were received and archived, all selected traces were
visible, and all five cases completed with zero parser rejections. The full
regression suite passed with 1,021 tests, including the three native Windows
regressions above (five existing tests skipped; 34 subtests passed).
Physical COM reads and the remaining discard rate still need a fresh board run
after restarting the GUI and reconnecting.

## Follow-up: tiny-read item overflow and an independent raw sensor dip

The user's `adc_data_20261008_111935_504343` capture started successfully
through the corrected native COM handoff, then stopped on a child raw-FIFO
overrun. It accepted and archived 4,552 sweeps (227,600 values), covering
approximately 398 ms of MCU time, with zero parser rejections and zero archive
overruns. The child reported only 120,841 peak queued raw bytes against its
16 MiB byte budget. The other bound, 2,048 items, exhausted because each tiny
read became a separate IPC record. Stopped firmware diagnostics were unavailable
after the raw reader exited. The archive correctly retained an incomplete footer.

The raw reader now accumulates successive reads into an owned chunk, flushing
at 64 KiB or after approximately 2 ms of active reading. Reads continue during
accumulation; this is a delivery interval, not an idle sleep or a wire-frame
change. The accumulator has its own 64 KiB limit. Quiet ports flush a final
partial chunk on the next bounded read timeout (at most the requested 20 ms,
subject to host scheduling), and shutdown/removal also attempts to retain that
owned tail. The FIFO byte/item limits remain 16 MiB / 2,048 at both stages.
Chunk arrival is its first actual read time, so ages include accumulation delay.
Parser handling of partial frames, mixed ASCII replies, sample ordering and MCU
timestamps is unchanged.

New diagnostics include connection-scoped native read and pipe-chunk counts,
the chunk interval, and capture-scoped `native_read_interval_max_s` separately
from forwarded chunk intervals. Native read spacing within and across chunks
is retained in private IPC metadata. Queue errors now state current item/byte
usage, the failed size, and whether the isolated child or parent FIFO overflowed.
A fatal raw reader error disconnects cleanly after retaining the incomplete
capture, rather than leaving Start available against an exited reader. Known
failed captures log `Capture incomplete` instead of `Capture complete`.

The new replay alternates one-byte and remainder-of-frame reads, reproducing
the high item rate absent from the earlier large-burst fixtures. All five
filtered five-second [fragmented-read capacity cases](../../datasets/testboard-7953/TESTBOARD_7953_GUI_FRAGMENTED_REPLAY_RESULTS.json)
retained all 920,000 sweeps, displayed signals and reported zero parser
rejections. At 17,000/s x 50 routes, 170,002 reads became 520 pipe chunks,
preserving all 85,000 frames. At 75,000/s x 10 routes, 750,002 reads became
1,527 chunks, preserving all 375,000 frames. Counts include ASCII stop/status
replies and are connection-scoped. The
[fragmented stall replay](../../datasets/testboard-7953/TESTBOARD_7953_GUI_FRAGMENTED_STALL_REPLAY_RESULTS.json)
also retained all 375,000 sweeps through the synthetic 500 ms source pause and
separate GUI pause; pipeline catch-up took 174.37 ms after GUI resume and fresh
rendering followed 26.84 ms later. The finite fixture retains paused history;
these results establish host buffering/drain behavior, not device discard rates.

Tests cover thousands of single-byte reads below both queue limits, exact byte
preservation, bounded-size and aged partial-reply flushes, actual process/GIL
stalls with fragmented reads, and retained archives/disconnection after a fatal
raw-source error. The full suite passed: 1,026 tests, five skips, 34 subtests.

The separate dip around 332.6–333.1 ms is already in unmodified archived raw
samples (ghost removal was disabled). It affects Array 2 PZT7 / ADC3 inputs
5–9: channel C reaches 707 counts versus its approximately 2,039-count median;
B and R reach 1,190 and 1,118. All received start-to-start intervals in this
capture are at most 88 us, with no transmission gaps. This run used the
blocking engine. The latest firmware reports qualify production LPSPI and
record some blocking-engine dips, but those observations do not establish
the cause of this event. The user did not touch the sensors but could not rule
out table movement, and intends to repeat with the table still. Raw values
and the current engine selection are preserved; no smoothing or replacement
samples were added to conceal the dip. Firmware and ADC wire format remain
unchanged. A physical repeat after GUI relaunch is still required.

To reproduce the new stress cases:

```powershell
.venv/Scripts/python.exe scripts/benchmark_testboard_gui.py --seconds 5 --filters --isolated-reader --fragmented-reads
.venv/Scripts/python.exe scripts/benchmark_testboard_gui.py --seconds 5 --filters --isolated-reader --fragmented-reads --stall --width 10 --rate 75000
```

## Hardware acceptance still required

These finite synthetic runs establish host behavior for these workloads, not
indefinite capture, acquisition-to-display clock alignment or analog accuracy.
Repeat on the existing production TestBoard firmware with both arrays/manual
LPSPI/20 MHz, single ADC1/Auto-1/20 MHz and single ADC3. Switch arrays and tabs,
exercise representative force settings, stop/restart during bursts and export
a capture exceeding RAM history. Compare exported counts/timestamps with JSONL
and per-frame timing; reconcile stopped counters over matching whole-run
boundaries. Perform a controlled 500 ms read pause and USB removal/reconnection.
Confirm an interrupted capture is retained separately and the next starts at
time zero. Check status/queue ages, controls and newest-display recovery.
Do not infer sensor sampling pauses from transmitted gaps or use this repair as
analog acceptance for experimental 30 MHz operation.
