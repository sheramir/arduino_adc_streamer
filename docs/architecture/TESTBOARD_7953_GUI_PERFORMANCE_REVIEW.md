# TestBoard 7953 GUI performance review

Initial GUI review: 2026-10-05. Firmware benchmark addendum: 2026-10-07. GUI changes remain proposed; this update documents requirements from the firmware optimizations and live USB tests. The selected production LPSPI path has now completed full-matrix and forced-stall validation; GUI repair can proceed as a separate task.

## Finding

The current host pipeline cannot sustain the reported 12,000 sweeps/second with two 25-channel arrays. There are identifiable bottlenecks in GUI ingestion and archive scheduling, including an unthrottled hidden plot. Increasing buffer capacity alone will postpone backlog rather than resolve it.

The user confirmed that 12 ksps refers to the per-channel/sweep rate. Every TestBoard frame contains one sample from each active route. With 50 routes, this means:

| Quantity | Required rate |
| --- | ---: |
| Frames and GUI ingestion callbacks | 12,000/s |
| ADC values | 600,000/s |
| Raw uint16 payload | 1.20 MB/s |
| Framed USB stream, including 14 bytes/frame overhead | 1.368 MB/s |
| Average time available per ingestion callback, before other GUI work | 83.3 microseconds |

The firmware emits one sweep per frame (`PztController::captureBlock`). Unlike older firmware, its PZT stream has no `buffer` command to combine sweeps. `channelrepeat` changes settling conversions, not emitted sweep count. The GUI normally displays one physical array at a time: 25 visible channels while recording all 50.

### Updated capacity targets after firmware optimization

The original 12,000 sweeps/s remains a useful regression case, but is no longer a sufficient performance target. The [completed live USB production matrix](TESTBOARD_7953_LIVE_USB_FULL_MATRIX_RESULTS.md) measured approximately 16,887 received sweeps/s for both full arrays, manual LPSPI at 20 MHz, and a highest received rate of approximately 54,397 sweeps/s for single ADC1, Auto-1 LPSPI at 20 MHz. A smaller channel selection can therefore impose more frame-decoding and signal-delivery overhead despite carrying fewer bytes.

| Selection / measured build | Sweeps/s for sizing | Routes/frame | Wire bytes/frame | Approximate wire load | Mean time budget/frame |
| --- | ---: | ---: | ---: | ---: | ---: |
| Both full arrays / live production, manual LPSPI 20 MHz | 16,887 | 50 | 114 | 1.925 MB/s | 59.2 us |
| Full array 1 / same build and mode | 24,042 | 25 | 64 | 1.539 MB/s | 41.6 us |
| Single ADC1 / live production, Auto-1 LPSPI 20 MHz, fastest repetition | 54,397 | 10 | 34 | 1.849 MB/s | 18.4 us |

These are measured workloads, not a maximum-rate guarantee. The first two rows use median repetition rates; the last identifies the fastest repetition. Both-array 20 MHz LPSPI discarded zero sweeps in both sequencing modes using deferred parsing. Size and replay-test approximately 17,000 frames/s at 50 routes and 60,000 frames/s at 10 routes; the latter is a provisional capacity target above the measured 54,397/s, with additional burst testing. At 16,887 sweeps/s, the existing 2,000-row display covers only 0.118 seconds and the 50,000-row history covers 2.96 seconds.

The subsequent [experimental manual LPSPI 30 MHz test](TESTBOARD_7953_LPSPI_30MHZ_RESULTS.md) passes all 21 captures and reaches approximately 19,394 frames/s with both arrays and 65,372/s with single ADC1, around 2.21–2.22 MB/s. It also shows unresolved channel-level and variation differences, so 20 MHz remains the production recommendation. If the GUI is to support this experimental workload, extend replay capacity tests to approximately 20,000/s at 50 routes and 75,000/s at 10 routes, with burst headroom; the 60,000/s target alone is below the measured experimental single-ADC rate. At 75,000/s, a 10–20 ms batch holds 750–1,500 sweeps. Capacity testing is separate from analog acceptance of 30 MHz.

## Evidence in the code

1. **The hidden decay preview runs at the acquisition frame rate.** `data_processing/binary_processor.py:257` calls `process_pzt_decay_block` for every ingestion block. In `gui/pzt_decay_panel.py:507`, an ordinary TestBoard capture enters the inactive-decay preview branch. It rebuilds display specs, requests five seconds of history, copies the entire channel matrix, sets curve data and updates the plot title. There is no visibility or refresh-rate check. Slicing to the last 5,000 rows occurs after copying all channels. At the reported rate, the requested history exceeds the 50,000-row ring, so each callback can copy approximately 10 MB of ADC data. Sustaining that design would require approximately 120 GB/s of data copying, before other work.

2. **Reading in a thread does not move ingestion off the GUI thread.** `serial_communication/serial_threads.py:238` emits a signal for each frame; `serial_communication/adc_session.py:72` connects it to the GUI ingestion handler. `process_binary_sweep` runs timing bookkeeping, copies/conversions, channel routing and filtering, ring writes, preview work, archive enqueueing and timing-sidecar writes on the GUI thread. The main plot's 0.2-second gate does not bound this ingestion workload. Queued callbacks can age while competing with paint and input events.

3. **The archive writer imposes a per-block throughput ceiling.** `data_processing/archive_writer.py:47,145` sleeps for 2 ms after every queued block during capture. At one sweep per item, the sleep alone limits throughput to less than 500 sweeps/s, versus the required 12,000/s. Its `queue.Queue()` is unbounded. The backlog retains arrays and Python objects and can grow RAM use and stop/save delays. JSON conversion also requires Python execution time; moving it to a thread does not eliminate GIL contention.

4. **Configuration work repeats inside ingestion.** `prepare_pzt_blip_filter_blocks` resolves lane groups on every frame. `_get_pzt_ghost_groups` calls `get_testboard_adc_routes` before replacing those routes with the frozen descriptor's routes. That unnecessary rebuild remains even when ghost removal is disabled, because the median-of-three filter also uses the grouping helper. `descriptor_specs` deep-copies all captured specs when the decay preview obtains display specs. These values can be prepared once per capture/configuration generation.

5. **Rendering has secondary costs and fidelity limits.** Time Series copies at most 2,000 sweeps and redraws at approximately 5 Hz. Curves are reused, which is already helpful. However, wide pens, repeated style/axis changes, and stride-based decimation add cost. The advertised 12,000-point budget is approximate because the per-curve minimum is 500 and decimation uses floor division. Stride selection can miss narrow PZT peaks. The 2,000-sweep live limit spans only 0.167 seconds at 12 ksps/channel; the 50,000-sweep memory ring spans 4.17 seconds.

The two float32 acquisition rings and float64 timestamps occupy approximately 20.4 MB at this width. The fixed ring capacity itself is modest; repeated copies and growing pending queues are the stronger problems.

## Synthetic measurements

Used the repository `.venv`: Python 3.12.11, PyQt 6.10.2, Qt 6.10.0, pyqtgraph 0.14.0 and NumPy 2.4.2. Constructed the real GUI offscreen with isolated temporary settings and auto-connect disabled, configured both arrays and all five sensor packages (`6,7,1,3,5`), froze the 50-route descriptor, and filled the 50,000-row ring. The visible tab was Time Series, with the decay tab hidden and inactive.

Called the real ingestion handler 1,000 times with synthetic uint16 sweeps and a nominal 83-microsecond sweep period. Main Time Series refreshes were suppressed; archive and timing-sidecar writing were disabled. Ghost removal and baseline subtraction were disabled; the application's median-of-three ingest filter remained active. The comparison replaced only `process_pzt_decay_block` with a no-op in the probe process. No source files were patched for the measurements.

| Ingestion condition | Elapsed for 1,000 frames | Mean per frame | Approximate handler capacity |
| --- | ---: | ---: | ---: |
| Current hidden decay preview | 3.436 s | 3.436 ms | 291 frames/s |
| Hidden decay callback bypassed | 0.1484 s | 0.1484 ms | 6,738 frames/s |

Removing the hidden preview improved this isolated workload by approximately 23 times. Even that case did not meet 12,000 frames/s, and it excluded normal painting, signal delivery and persistence overhead. A separate profiler pass identified history copying and spec deep-copying as the dominant preview costs; route/group reconstruction dominated much of the remaining filtering overhead.

For the archive writer, pre-enqueued 12,000 synthetic 50-channel sweeps and inspected live-writer status after two seconds:

| Sweeps per queue item | Written sweeps after two seconds | Pending queue items |
| --- | ---: | ---: |
| 1 | 797 | 11,203 |
| 100 | 12,000 | 0 |

This is a finite backlog experiment, not proof of sustained hardware capture. It demonstrates the large effect of per-item scheduling overhead. End-to-end hardware rate, USB bursts, filtering, painting and export integrity still need validation.

## Firmware findings that affect the host design

### Read promptly, process separately

In the live USB diagnostic tests, normal both-array benchmark reading discarded 80, 124 and 89 sweeps. Reading raw bytes during capture and parsing afterward discarded zero in all three matching runs. This supports host parsing/scheduling as a contributor to backpressure; it does not isolate every Windows, USB-controller or Python scheduling cause. Those were benchmark runs, not measurements of the GUI.

The GUI reader also reads, parses and emits per-frame signals in the same thread (`SerialReaderThread.run` and `process_binary_data`). Moving the existing GUI handler to another thread, or batching its signals alone, does not address all work between serial reads. Keep the read loop small, pass owned raw chunks to a bounded decoder queue, and timestamp chunk arrival with a host monotonic clock. Decode, validate and batch continuously in a separate stage; preserve the parser's existing handling of partial frames and mixed ASCII replies. Measure read intervals, decoder throughput and queue age independently. Python threads can still compete for execution time, so demonstrate sustained throughput rather than assuming thread separation resolves it.

The benchmark's deferred parsing stores a finite capture and processes it afterward. It is a diagnostic control, not the proposed GUI architecture: an indefinite GUI capture must read and process concurrently with bounded memory.

### A transmission gap is no longer necessarily a sampling pause

The live firmware uses `usb_stream_policy=discard_if_busy`: it keeps sampling while USB is busy and discards complete unsent sweeps instead of storing acquisition history for replay. In the forced 500 ms host-read pause, approximately 8,000 sweeps were discarded per run and received timestamps had approximately 490 ms gaps. Actual sensor sampling intervals remained at or below 66 us. All 18 diagnostic, 18 production mixed-engine, six production forced-pause and 252 full-matrix captures passed. The full matrix's largest actual sampling interval is 171 us across all engines and 86 us in LPSPI, including discarded sweeps. Its 228,105,470 received LPSPI measurement values stay within seven counts of their own channel medians. Production LPSPI's first 10 ms of received data after each forced gap stays within two counts. Production blocking modes retain some localized voltage dips after transmission gaps despite continuous sampling, so a gap is neither proof of a sensor pause nor proof that analog effects are absent. See the [full-matrix analysis](TESTBOARD_7953_LIVE_USB_FULL_MATRIX_RESULTS.md), [production comparison](TESTBOARD_7953_LIVE_USB_PRODUCTION_RESULTS.md) and [stream policy](TESTBOARD_7953_LIVE_USB_STREAM.md).

The GUI must retain each delivered frame's MCU timestamps and expose missing transmission intervals. Do not compress the time axis, fill gaps with invented samples, or infer that a sensor stopped being selected from a received-frame gap alone. FFT/PSD, integration, decay analysis and stateful filters need an explicit gap policy: reject affected windows, reset state where appropriate, or use an analysis method that supports the actual timestamps. Merely preserving filter state across host batch boundaries does not establish correctness across missing measurements. Plot discontinuities visibly instead of connecting across a long gap as though it contained measured data.

Long-capture timing also needs attention. `data_processing/binary_processor.py` computes elapsed time as `(timestamp - first_timestamp) & 0xFFFFFFFF`. This handles an MCU rollover during a short capture, but elapsed time returns to zero after a full 32-bit microsecond cycle, approximately 71.6 minutes. Extend successive device timestamps into a monotonic capture timeline, resetting the extension only at capture-generation boundaries; distinguish a device restart from rollover. Preserve the original timestamps in timing metadata.

This distinction matters physically: the sensors charge toward Vmid when selected and leak toward ground while unselected. Continuous sampling prevents the extra discharge previously caused by a blocking USB write. The latest received data show no recurrence of the earlier large resumption dips, including after the forced pause; discarded sample voltages were not recorded. ADC-specific bias resistors and settling still matter. GUI smoothing should not conceal these effects or substitute for the [channel-quality checks](TESTBOARD_7953_CHANNEL_QUALITY_RESULTS.md).

### Separate display freshness from recording completeness

The firmware cannot recall bytes already accepted by USB or Windows. A nonblocking board therefore does not guarantee a current display. Track read-to-decode queue age and decode-to-render age, coalesce obsolete display snapshots, and show stale-data status when no new samples arrive. Do not subtract MCU microseconds directly from a host clock: absolute acquisition-to-display age requires clock alignment and an allowance for transport uncertainty. Host queue ages can be measured directly with one monotonic clock.

Recording every **received** sweep is different from recording every **acquired** sweep under the live discard policy. Archives should preserve all received measurements and explicit gaps, plus run-level discard diagnostics. Replacing display snapshots must not silently discard archive data. A requirement for lossless sensor acquisition would need a separately designed capture mode; it is not provided by the current real-time stream.

After stopping and draining the capture, retain `sampling_sweeps`, `usb_frames_sent`, `usb_frames_discarded`, `sampling_period_max_us` and `sampling_period_over_1ms` in capture metadata when supported. Distinguish device discards, parser rejections and host archive overruns. Read diagnostics at stopped capture boundaries; do not introduce periodic `status` polling during streaming. Current status output shares the serial stream, and acknowledgments call `Serial.flush()`, so polling can perturb the timing being measured. Counters reset per run and must be associated with the correct capture generation. Aggregate counters do not identify exactly which frames were lost, and the wire protocol still has no sequence number or checksum.

### Handle PC sleep and USB reconnection explicitly

The full firmware regression run was interrupted when Windows entered Modern Standby and re-enumerated the Teensy on wake. This invalidated the existing COM connection and raised `ClearCommError`; the [incident timeline](TESTBOARD_7953_LIVE_USB_PRODUCTION_RESULTS.md#full-matrix-interrupted-by-pc-standby) distinguishes it from ordinary USB backpressure. The GUI should report interrupted capture, finalize the received archive as incomplete and reset parser/filter/timestamp state at a new capture generation after reconnecting. Do not silently splice pre-sleep and post-reconnect measurements into a continuous recording. Consider a temporary Windows keep-awake request while capture is active, released on stop/error/exit, plus explicit handling of manual sleep or device removal. A keep-awake request cannot promise uninterrupted USB delivery or prevent every deliberate suspend action.

## Recommended implementation order

### 1. Remove unnecessary acquisition-rate GUI work

Keep active decay analysis consuming every required sample. Move the ordinary TestBoard decay preview to a visible-tab refresh timer, initially 5–10 Hz. Copy only its selected column and the required trailing rows. Hidden tabs should receive no preview updates. Precompute immutable acquisition specs, route groups and column indices from the frozen capture descriptor; invalidate them only when the capture/configuration generation changes.

### 2. Batch host ingestion while preserving frame timing

Leave firmware framing unchanged initially. Separate raw reading from continuous decoding, then aggregate decoded frames into batches of approximately 10–20 ms, with an additional byte/count bound. This is 120–240 sweeps at the original rate, approximately 169–338 with both optimized arrays, and approximately 544–1,088 at the measured single-ADC maximum. The provisional 60,000/s capacity target requires 600–1,200 sweeps per such batch. Deliver roughly 50–100 batches/s to processing consumers instead of one GUI callback per frame. Preserve each frame's start/end timestamps and average interval in the batch; GUI notifications should announce available snapshots rather than queue every acquisition batch for widget processing.

Do not merely concatenate payloads and pass the first/last timestamps into the existing generic block handler: it reconstructs sweep times using `avg_sample_time_us * samples_per_sweep`. That omits inter-frame USB/loop gaps and would alter the captured time axis. Batched processing must use the original per-frame start timestamps, continuously extended across rollover, and retain packet validation.

Move NumPy conversion, stateful filtering, ring writes and persistence dispatch into a dedicated acquisition worker with an immutable capture configuration. Keep widget access, curve updates and labels on the GUI thread. Batch stateful filters without changing sample order or their state across boundaries. Coordinate stop/drain and capture generations so old batches cannot enter a new capture.

### 3. Batch persistence and make backlog explicit

Enqueue arrays containing many sweeps, retaining their individual timestamps. At 100 sweeps/item, the current 2 ms yield would be paid approximately 169 times/s instead of 16,887 times/s for both optimized arrays. Batch timing-sidecar rows in the persistence worker too. Replace a fixed yield per wire frame with a measured scheduling policy; the higher frame-rate selections still need a sustained writer-throughput check. At 60,000 sweeps/s, even 100 sweeps/item would incur 600 such yields/s, so that batching example cannot meet the small-selection capacity target with the current fixed sleep.

Expose queue depth in sweeps/bytes and oldest-item age for raw reading, decoded batches and persistence. Set explicit queue budgets and an overrun policy for each stage. If recording all received frames cannot keep up, stop capture with a clear incomplete-capture error rather than silently discarding recorded samples or allowing memory to grow indefinitely. GUI snapshots can be replaced by newer snapshots; acquisition and archive data require separate handling. Do not clear arbitrary serial bytes to catch up: that can split frames and lose command replies. Any future host-side dropping must preserve parser synchronization, count omitted complete frames and respect the recording policy.

Retain JSONL compatibility for the first change. If sustained serialization still limits throughput, consider a versioned binary chunk archive containing timestamp vectors plus uint16 or canonical float32 matrices and captured interpretation metadata. That requires coordinated loader/export changes, but no ADC wire-protocol change.

### 4. Render the newest bounded snapshot

A GUI timer should render the newest available snapshot, coalescing obsolete display requests. Begin with the current 5 Hz cadence and increase only after measurement. After a stall, it should return to the newest available data rather than replaying queued display jobs. Use explicit time-window controls appropriate for the measured rates and pixel-aware min/max or peak decimation so narrow events remain visible. Preserve gap markers through decimation. Keep full-resolution received data for recording, FFT/PSD and analysis; display decimation must not feed those paths.

Cache curve styles, use 1-pixel opaque solid lines where practical, and configure clipping/downsampling once per curve. Guard axis/legend updates so unchanged settings are not reapplied for every redraw. These are secondary optimizations after ingestion and archive scheduling are corrected.

## Validation before calling the issue resolved

- Replay valid 50-route frames at 12,000/s and approximately 17,000/s, and 10-route frames at approximately 60,000/s, including bursty reads, partial frames and MCU timestamp wrap; verify sweep counts, ordering and timestamps. The 60,000/s case provides headroom above the measured single-ADC rate.
- Replay timestamps spanning more than 71.6 minutes and multiple rollovers without waiting in real time; verify monotonically increasing plot/archive times and reset behavior after a device restart.
- Compare streamed filter output across different batch sizes and ensure active decay/force processing retains every required received sample. Add timestamp gaps and verify the selected analysis/filter gap policy; no path should invent measurements or silently assume a uniform time axis.
- Stress capture long enough to expose backlog, with representative filters and each visible tab. Observe reader throughput, worker time, pending sweeps/bytes, oldest-item age, render duration and a GUI heartbeat. Target no steadily growing queues and usable controls; a provisional heartbeat p95 target is below 100 ms.
- Deliberately pause host reading for 500 ms and separately stall rendering/processing. Verify prompt reader recovery, bounded queues and newest-data display recovery; provisionally target recovery within two render periods after the pipeline catches up. Record queue ages and stale-display duration rather than treating throughput alone as a latency measure.
- Stop and restart during bursts; verify drain semantics and absence of old-generation samples. Reload/export both arrays and compare sample counts and timestamps against the replay source.
- Repeat on the real TestBoard with both arrays, single ADC1 Auto-1 and single ADC3, using the same firmware/clock/route settings as the benchmark controls. Archive counts must reconcile with frames accepted by the host; compare complete raw frame counts with device submitted/discarded counters over matching whole-run boundaries. Keep warm-up exclusions separate. USB and firmware behavior cannot be proven by synthetic GUI measurements. The wire format has no frame sequence number, so MCU timestamps can indicate gaps but cannot independently prove zero frame loss or distinguish every loss source.

## External guidance

[Qt: Threads and QObjects](https://doc.qt.io/qt-6/threads-qobject.html) explains queued signal delivery in the receiver's thread and the need to keep widgets on the main thread. This supports separating acquisition computations from GUI updates rather than changing the current widget handler to a direct cross-thread connection.

[pyqtgraph: PlotDataItem performance guidance](https://pyqtgraph.readthedocs.io/en/latest/api_reference/graphicsItems/plotdataitem.html) recommends narrow pens and describes clipping, downsampling and peak reduction. These support the secondary rendering changes; package behavior should be checked against the installed 0.14.0 version.

[PJRC: Teensy USB Serial](https://www.pjrc.com/teensy/td_serial.html) states that USB Serial uses native USB speed and ignores the baud setting. Raising the nominal 460800 baud setting is therefore not the proposed fix for this Teensy USB connection. Actual transport throughput still requires measurement.
