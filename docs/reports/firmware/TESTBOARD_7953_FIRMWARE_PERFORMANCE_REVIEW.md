# TestBoard 7953 firmware performance review

Reviewed 2026-10-05 against workspace revision `4a32cc0`. This is a source and saved-benchmark review; no firmware changes, uploads, or new hardware measurements were performed.

## USB and SPI already overlap at the peripheral level

`PztController::captureBlock()` acquires one sweep, encodes its frame, and calls `UsbSerialController::writeBinaryBlock()`. That method calls `Serial.write()` without a binary flush. The next sweep can start while USB transmits previously queued data.

The installed Teensy framework's `cores/teensy4/usb_serial.c` confirms that writes copy into core-owned transmit buffers. There are four 2,048-byte buffers, with a 75-microsecond timer for submitting a partial buffer. Full buffers are submitted immediately. USB transfer descriptors and the peripheral handle transmission independently of foreground sampling. The application wire buffer can therefore be reused after a successful complete write; adding a second application buffer alone does not introduce new USB concurrency.

`Serial.write()` can nevertheless wait when transmit buffers are occupied. Its timeout is approximately 120 ms, and disconnect/timeout can return a short write. The firmware currently ignores the return count. USB transmission is asynchronous; copying and waiting inside the call are foreground work.

PJRC documents native USB transport and the fact that the nominal serial baud setting is ignored: [Teensy USB Serial](https://www.pjrc.com/teensy/td_serial.html). Raising `460800` does not accelerate this link. Actual sustained throughput depends on the connection and host reader.

## Saved measurements bound the likely USB benefit

The following aggregate rows are from `Arduino_Sketches/TestBoard_7953/benchmarks/results/20261001T154835Z/benchmark_results.csv`, captured on October 1. All use both arrays, 50 routes, manual sequencing, LPSPI, `scanorder adc`, repeat 1, and optional Vmid sampling off.

| Requested SPI clock | Acquisition median | Start-to-start median | Inter-block gap median | Typical per-channel sweep rate |
| --- | ---: | ---: | ---: | ---: |
| 20 MHz | 91 us | 95 us | 4 us | 10,526 Hz |
| 24 MHz | 91 us | 95 us | 4 us | 10,526 Hz |
| 30 MHz | 84 us | 88 us | 4 us | 11,364 Hz |

These are historical measurements at revision `a39307d`, not newly measured results for HEAD. The relevant manual stream and SPI/USB implementation remain materially the same; subsequent acquisition changes chiefly optimized persistent Auto-1. Rebenchmark the final implementation.

The 4-us gap includes frame encoding, the USB write, foreground loop/command servicing, and preparation before the next acquisition timestamp. It is not a direct USB transfer measurement. Eliminating the whole gap with acquisition unchanged would improve the typical rate by only `95/91 - 1 = 4.4%` at 20 MHz, or `88/84 - 1 = 4.8%` at 30 MHz. Those are optimistic bounds for this measured configuration, not bounds under sustained USB backpressure.

All three rows have zero malformed frames, transfer timeouts, and returned-channel errors, but nonzero `suspected_missing_frames` (153, 180, and 24 respectively). That metric estimates missing frames from long timestamp periods; it cannot distinguish acquisition stalls from dropped frames. The frame has no sequence number. PASS does not establish zero frame loss.

An earlier matched 10-MHz manual/LPSPI comparison (`20260930T200133Z`) measured an approximately 20-us gap for interleaved/array payload order versus 4 us for ADC order. `buildScanPlan()` executes before the start timestamp and repeatedly searches the routes for interleaved/array ordering. This supports caching the canonical plan, while not attributing the entire gap difference to one function without instrumentation.

At 50 routes each frame is 114 bytes. A 12,000-Hz sweep rate produces 1.368 MB/s on the wire and 600,000 emitted ADC values/s. USB packet boundaries need not match frame boundaries.

## Recommended changes, in implementation order

1. **Instrument acquisition and enqueue cost separately.** Record cycles for route preparation, stream preparation, transfer execution, encoding, and `Serial.write()`. Track maximum/p95 write delay, accepted byte counts, queue high-water marks, and sustained frames per elapsed second. Keep diagnostics out of the binary stream until stopped. The existing gap metric combines several costs and its median hides rare stalls.

2. **Configure LPSPI once per acquisition session or sweep.** `SpiController::startLpspi16()` currently constructs `SPISettings`, calls `beginTransaction()`, drains RX, clears status, saves TCR, and selects a 16-bit frame for every word. `finishLpspi16()` restores TCR and ends the transaction for every word. The installed SPI library's `beginTransaction()` disables and reconfigures the peripheral even when the clock is unchanged. Establish a bounded session with fixed 16-bit format, then perform only CS assertion, TDR/RDR access, completion checks, and CS release in the ordinary transfer path. Separate bus/session ownership from an individual in-flight word; restore normal SPI state at stop, engine change, and recovery. Leave USB interrupts enabled and audit SPI interrupt masking before extending transaction lifetime.

3. **Compile the acquisition plan when configuration changes.** Cache payload destinations, per-ADC commands, expected pipeline responses, active buses, and parking decisions. `captureBlock()` currently rebuilds the route plan and every per-ADC operation stream on every sweep. `resetStream()` clears the whole `FrameStream`, including a large operation array. Retain immutable templates and reset only cursors, pending results, and per-sweep validity. Auto-1 needs separate initialization and persistent-resume templates; preserve its existing mask/parking state rather than rebuilding or reprogramming it unnecessarily. Invalidate on routes, array, order, repeat, Vmid, sequence, range, and relevant engine/clock changes.

4. **Use a specialized LPSPI polling path.** Cache register pointers and CS GPIO set/clear registers plus masks. CS pin arguments are runtime values, so the current `digitalWriteFast()` calls use the runtime pin-lookup path. Replace repeated engine dispatch and `micros()` calls in the short poll loop with a bounded cycle-counter deadline where appropriate. Service foreground events between sweeps or periodically on a long wait; retain EventResponder servicing for the existing DMA engine. Keep interrupts enabled. `yield()` may be almost empty in this build, so its benefit must be measured rather than assumed.

5. **Add a bounded queue of complete frames if write stalls matter.** Sampling produces frames; foreground USB service submits queued bytes when the core reports adequate capacity. Preserve an offset on short writes, never overwrite a pending frame, and keep FIFO ordering. Start with a small queue, for example 64 frames (7,296 wire bytes, about 5.3 ms at 12 kHz), and measure its required size. It absorbs brief host stalls, not a persistent rate mismatch. A full queue needs an explicit pause-with-gap policy or acquisition failure; do not silently drop data. On stop/timed stop, finish or explicitly account for pending frames before text ACKs, and prevent partially transmitted binary frames from mixing with command output.

   Batch several unchanged complete frames into a USB write if measurements show small-transfer overhead. Bound batching latency, initially around 0.5-1 ms, and drain at stop. Preserve every frame's own timestamps and 50-word payload; this does not require changing the wire format or concatenating multiple sweeps into one logical frame. The core already coalesces traffic, so measure additional benefit before adding batching complexity.

6. **Consider independent bus scheduling for unequal route counts.** `executeFrame()` waits for both buses at each word, and `captureBlock()` waits for the ADC1/ADC3 pair before starting ADC2/ADC4. Separate per-bus progress would let a bus move to its next ADC while the other bus is still working. This chiefly benefits sparse/unbalanced selections. Preserve same-bus CS exclusion, mandatory parking, canonical output order, and the documented timing meaning of a sweep.

7. **Investigate full-sequence DMA only after these changes.** The current DMA engine starts a two-byte asynchronous transfer for every ADC frame and immediately polls it. Its setup/completion overhead can exceed direct LPSPI polling; its benchmark result does not establish that all DMA approaches are slower. A timer/PCS/GPIO-coordinated engine could offload a complete sequence, but ADS7953 requires distinct CS-delimited conversions. A long transfer with CS held low is not a valid replacement. Hardware PCS feasibility must be checked against the existing CS pin wiring; do not assume it can be enabled without routing changes. DMA-accessible aligned buffers and cache maintenance are also required. This is a larger hardware-validated phase, not the first optimization.

## Preserve analog and host correctness

TI specifies a 20-MHz SPI interface, up to 1-MSPS conversion throughput, and a 325-ns acquisition interval. Faster software must preserve acquisition/settling time, CS timing, channel tags, two-frame command tracking, and mandatory Vmid parking. The 40-ns board delay is not a substitute for validating the complete ADC timing diagram. Review [ADS7953 datasheet, sections 7.6 and 7.9](https://www.ti.com/lit/ds/symlink/ads7953.pdf). The saved 30-MHz result is experimental and outside the specified interface clock; prioritize reducing overhead at 20 MHz.

Do not lower repeat or remove optional Vmid merely for a higher number without comparing ghosting, settling, noise, and pressed-sensor waveforms. The current Auto-1 implementation already retains masks across sweeps and parks through channel 15. Older Auto-1 benchmark rows predate that optimization and cannot establish its current ranking.

The host rejects `avg_dt_us < 1`. Firmware computes this integer by rounding acquisition duration divided by emitted sample count; if 50-route acquisition drops below 25 us, it rounds to zero. Any optimization approaching that range must coordinate timing semantics with the host instead of silently clamping or changing units. Start/end timestamps are the more useful sweep timing measurements; the per-word average is not the physical conversion interval for parallel buses.

The separate `TESTBOARD_7953_GUI_PERFORMANCE_REVIEW.md` identifies host ingestion/archive bottlenecks at high sweep rates. A firmware speed increase requires validation with a continuously draining benchmark reader and with the actual GUI, including full capture/export. Increasing acquisition speed does not resolve host callback or persistence backlog.

## Hardware acceptance

Compare baseline and optimized builds at 20 MHz with identical routes, sequence, repeat, Vmid, reference, and order. Cover each array, both arrays, all four full ADCs, and sparse/unbalanced selections. Check manual and current persistent Auto-1 separately. Use a logic analyzer to confirm clocks, frame lengths, CS setup/hold/high intervals, analog acquisition timing, bus overlap, and outgoing-ADC Vmid parking.

Measure sustained elapsed-time sweep rate as well as median/p95/p99/max start-to-start periods and write stalls. Compare returned channel identity, per-channel values/noise, startup settling, and ghosting against baseline. Stress slow readers, normal/timed stop, unplug/reconnect, and restart; verify pending-frame ownership, parser recovery, ACK ordering, zero transfer/channel errors, and complete two-array archive reload/export. No new speedup or lossless-delivery claim is established by this review.
