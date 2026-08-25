# PCB1.7_SPI

Firmware pair for PCB hardware revision v1.7: a Teensy 4.0/4.1 SPI master (`Teensy_SPI_Master_Array_PZT_PZR1.7_DRDY.ino`) paired with the current XIAO MG24 SPI slave (`MG24_Dual_MUX_SPI_Slave1.7b.ino`). This is the current/recommended revision for new PZT/RS array hardware. It carries forward PCB1.5's DRDY-synchronized streaming and adds a combined `mode PZT_RS*` that interleaves each selected 5-channel PZT sensor with its two held Rosette/RS resistance values into one binary stream; `mcu*` reports `# Array_PZT_PZR1.7` (note the `.7` suffix, distinct from PCB1.0/1.5's `# Array_PZT_PZR1`). The earlier `MG24_Dual_MUX_SPI_Slave1.7_DRDY.ino` remains in this folder as the previous baseline.

**Architecture note:** the `PZT_RS` combined mode is implemented entirely on the Teensy side. The MG24 slave sketch in this folder is functionally and protocol-identical to PCB1.5's MG24 slave (same command codes, same DRDY behavior, same pure dual-MUX ADC streaming) — it has no awareness of RS/Rosette values, `pztmuxes`, or `rschannels`. The Teensy measures RS/Rosette resistance itself via the same 555-timer circuitry used in PZR mode, then splices the held RS values into the PZT block fetched from MG24 before forwarding it to the host (`pzt_buildCombinedBlock`).

## Files

### MG24_Dual_MUX_SPI_Slave1.7b.ino

Current XIAO MG24 SPI slave driving two ADG1206 (16:1) MUXes in parallel (MUX1 on D1, MUX2 on D2), with active-HIGH DRDY on D7. It performs pure PZT dual-MUX ADC acquisition only; it has no RS/Rosette logic and is unaware of the host's `PZT_RS` mode. Its SPI command framing, ACKs, binary block layout, and DRDY behavior are compatible with the prior PCB1.7 DRDY sketch.

- `drdyWrite(asserted)` — drives the DRDY output pin HIGH/LOW.
- `spiCallback(handle, status, count)` — SPIDRV transfer-done callback; records status and sets `xferDone`.
- `armCmd()` — deasserts DRDY and arms the next command-frame receive transfer.
- `armResp(txBuf, len, isStreaming)` — arms an SPI response transfer and asserts DRDY.
- `onCSRising()` — CS rising-edge ISR; deasserts DRDY and sets `csRose`.
- `allocateAnalogBus(p)` — allocates the IADC analog bus bit for a given pin.
- `makeFastMuxPin(idx, arduinoPin)` — resolves an Arduino pin to a raw GPIO port/pin for fast MUX control.
- `fastMuxWrite(idx, high)` — sets/clears a MUX address line via direct GPIO register access.
- `initFastMuxPins()` — initializes all four fast MUX address pins; falls back to slow `digitalWrite` if needed.
- `muxSelectSlow(ch)` — sets MUX address lines via `digitalWrite` (fallback path).
- `muxSelect(ch)` — selects a MUX channel via fast or slow path, settling for `MUX_SETTLE_US` if changed.
- `initIADC()` — configures and starts the IADC in 2-entry scan mode.
- `iadcFlushFifo()` — drains stale IADC scan FIFO results.
- `iadcReadPairFast(v1, v2)` — fast hot-path scan read assuming fixed FIFO order.
- `iadcReadPairChecked(v1, v2)` — safer scan read verifying scan-table ID order (debug-only).
- `groundStepIfNeeded()` — inserts a ground/Vmid MUX step before a new channel when `useGround` is set.
- `parkMuxOnGround()` — parks both MUXes on the ground/Vmid channel after a block / during SPI TX.
- `buildEntryList()` — rebuilds the flattened per-sweep channel/ground entry list.
- `clampSweepsPerBlock()` — caps `sweepsPerBlock` so block data fits the fixed-size SPI TX buffer.
- `captureBlock(txBuf)` — captures `sweepsPerBlock` sweeps of MUX1/MUX2 pairs, writes header/trailer, then parks the MUX.
- `prepareAck(txBuf, ok, b2, b3)` — writes a 4-byte ACK frame.
- `blockResponseLenFromPairs(pairs)` — computes response byte length for a pair count.
- `prepareBlockResponse(txBuf)` — captures a block and returns its response length.
- `resetStreamingPipeline()` — clears streaming/prefetch state.
- `prefetchNextBlockIfNeeded()` — captures the next block ahead of time while the current one streams.
- `doWarmup()` — discards `WARMUP_SWEEPS` sweeps after `run` starts, then parks the MUX.
- `processCommand(frame)` — dispatches a received command frame to the matching handler and returns the response length.
- `setup()` — initializes MUX/ADC/DRDY pins, attaches the CS interrupt, configures SPIDRV, and pre-arms the first command receive.
- `loop()` — prefetches the next block, services SPI transfer completion, and dispatches to `processCommand` or advances the streaming pipeline.

#### MG24 1.7b changes

`MG24_Dual_MUX_SPI_Slave1.7b.ino` is the recommended MG24 sketch for this folder. Compared with `MG24_Dual_MUX_SPI_Slave1.7_DRDY.ino`, it:

- Raises the IADC source-clock target from 10 MHz to 20 MHz and the ADC-clock target from 5 MHz to 10 MHz for faster acquisition.
- Uses `iadcWarmupKeepWarm` for repeated low-latency conversions.
- Configures the scan FIFO data-valid level as `iadcFifoCfgDvl2` and uses the raw FIFO-data pull API when flushing stale results. These are initialization/hot-path refinements; the active acquisition path still polls and reads the same D1/D2 scan pair.
- Reinitializes the IADC on `run` when either configuration changed or the peripheral is not ready (`g_configDirty || !g_iadcReady`).

No host serial command, ACK layout, DRDY signaling, or binary sample/trailer format changed in 1.7b.

### Teensy_SPI_Master_Array_PZT_PZR1.7_DRDY.ino

Teensy 4.0/4.1 sketch with three modes behind one serial API: `mode PZT*` (SPI bridge to MG24, default), `mode PZR*` (555-astable resistance via PZR or RS MUX), and `mode PZT_RS*` (combined PZT+RS stream). `mcu*` reports `# Array_PZT_PZR1.7`. PZT/PZT_RS `run*` is blocking, using DRDY interrupt notification (MG24 D7 → Teensy pin 0) plus a RAM receive queue, with the same DRDY-stall fallback poll path as PCB1.5 (`pzt_serviceSpiRxFallbackPoll`, diagnostics in `pzt_logStreamSummary`). In `PZT_RS` mode the Teensy concurrently runs a non-blocking RS/Rosette refresh state machine (`pzt_rsServiceRefresh` / `pzt_rsConsumeReadyPair` / `pzt_rsStartNextRefreshChannel`) that continuously cycles the RS MUX across all channels referenced by `rschannels`, holding the latest measured value per channel; these held values are spliced into each PZT block via `pzt_buildCombinedBlock` before it is queued for the host. The refresh state machine has no IDLE wait state — `pzt_rsStartNextRefreshChannel` is called immediately after each successful measurement, so the 555 is always actively measuring the next channel (per the project's `pzt-rs-idle-elimination` design note).

- `pzt_drdyISR()` — DRDY rising-edge ISR; sets the pending-edge flag/counter.
- `pzt_drdyPending()` / `pzt_drdyConsumeOne()` / `pzt_drdyClearAll()` — DRDY edge-queue state management.
- `pzt_waitForDrdy(timeoutMs)` — blocks until a DRDY edge arrives or times out.
- `pzt_spiTransfer(tx, rx, len)` — raw byte-by-byte SPI transfer with CS framing.
- `pzt_spiSend(buf, len)` / `pzt_spiRecv(buf, len)` — send-only/receive-only wrappers.
- `pzt_spiRecvStreamingResponse(buf, len, controlByte, maxAttempts)` — attempts to read a valid ACK or block-magic response.
- `pzt_recvAckWhenReady(buf, timeoutMs)` — waits for DRDY, then reads/validates a 4-byte ACK.
- `pzt_queueIsEmpty()` / `pzt_queueIsFull()` — receive-queue state checks.
- `pzt_physicalChannelCount()` — returns the MG24-side physical channel count (deduplicated logical channels in `PZT_RS` mode, else `channelCount`).
- `pzt_physicalIndexForChannel(ch)` — maps a logical PZT channel to its index in the deduplicated physical-channel list.
- `pzt_addUniqueRsRefreshChannel(ch)` — adds an RS_MUX channel to the unique refresh list if not already present.
- `pzt_queueFront()` / `pzt_queueWriteSlot()` — accessors into the ring-buffer receive queue.
- `pzt_queueCommitWrite(len)` / `pzt_queuePopFront()` — commit a filled slot / drop a fully-sent slot.
- `pzt_streamResetState()` — resets per-run streaming/queue/diagnostic counters, including RS refresh state.
- `pzt_logStreamSummary()` — prints aggregated DRDY-vs-fallback and (in `PZT_RS` mode) per-RS-channel timing/refresh diagnostics for the just-finished run.
- `pzt_recordRxError(reason)` / `pzt_clearRxErrors()` — track/clear consecutive RX error streaks.
- `pzt_rsSnapshotHeldValues(dst, count)` — atomically copies the current held RS quantized-ohms values for all 16 channels.
- `pzt_handleStreamingFrame(slot, fromDrdy)` — processes one received ACK/block frame; in `PZT_RS` mode, services RS refresh, snapshots held values, and repacks the block via `pzt_buildCombinedBlock` before queuing it.
- `pzt_serviceSpiRxFallbackPoll()` — fallback path: polls one SPI response directly when DRDY signaling stalls.
- `pzt_writeBlockBuffered(buf, len)` — writes a binary block to host serial respecting flow control.
- `pzt_emitBlock(buf, len)` — emits a block as raw binary or debug text.
- `pzt_serviceUsbTx()` — drains one queued block to USB serial without blocking SPI servicing.
- `pzt_pollStreamStopRequest()` — detects an inline `stop*` during the blocking PZT run loop.
- `pzt_serviceSpiRx()` — services pending DRDY edges, reading and queuing ACK/block responses (the DRDY-driven primary path).
- `pzt_discardPendingTerminators(settleMs)` — drains stray trailing bytes/terminators.
- `pzt_sendCmd(cmd, args, nargs)` — builds and sends a fixed 20-byte command frame.
- `pzt_sendCmdAck(cmd, args, nargs)` — sends a command and waits for/validates its DRDY-signaled ACK.
- `pzt_usPerPair()` — estimates per-pair acquisition time from OSR.
- `pzt_entriesPerSweep()` — computes MG24 entries per sweep (using the physical channel count) including ground entries.
- `pzt_blockDelayMs()` / `pzt_warmupDelayMs()` — estimate block/warmup timing windows.
- `pzt_firstBlockTimeoutMs()` — first-block timeout, raised to a minimum of `PZT_RS_FIRST_BLOCK_MIN_TIMEOUT_MS` in `PZT_RS` mode.
- `pzt_blockResponseBytes()` — computes the raw MG24 block size in bytes for the current physical-channel configuration.
- `pzt_rsOutputSamplesPerBlock()` — computes the host-facing sample count after PZT_RS sensor repacking (`sensorCount * repeat * sweepsPerBlock * 7`).
- `pzt_isValidAckFrame(buf)` — checks whether a 4-byte buffer is a legal ACK frame.
- `pzr_isr555()` — active-555 ICP edge ISR; computes high/low cycle counts via DWT, tracks per-RS-channel edge/pair counters when in `PZT_RS` mode, and flags `pairReady`; also detects edge-sequence errors.
- `pzr_resetCaptureState()` / `pzr_resetCaptureDiagnostics()` — clear shared 555 capture state / sequence-error counter.
- `pzr_computePairTimeoutMs()` — derives a conservative pair-wait timeout from Rb/Cf/RxMax.
- `pzr_waitForPair(hCyc, lCyc, timeout_ms)` — blocks until one 555 pulse pair is captured or timeout (used by PZR mode).
- `pzr_takeReadyPair(hCyc, lCyc)` — non-blocking pair fetch used by `PZT_RS` so RS refresh never paces PZT blocks.
- `pzr_updateMA(buf, sum, idx, count, N, val)` — generic moving-average update helper.
- `pzr_median3(a, b, c)` / `pzr_updateMedian3(buf, idx, count, val)` — median-of-3 filtering to reject isolated single-pair spikes.
- `pzt_rsMedianN(buf, count)` / `pzt_rsUpdateHeldMedian(ch, ra)` — median-of-N filtering applied to held RS values per channel before quantization.
- `pzr_cyclesToUs(cycles)` / `pzr_cyclesFloatToUs(cycles)` — convert DWT cycle counts to microseconds.
- `pzr_computeModeledLowCycles()` / `pzr_refreshModeledLowCycles()` — compute/cache the theoretical 555 discharge interval from `Rb`/`Cf` (used instead of measured low-cycle time when `PZR_RA_LCYC_SOURCE == PZR_LCYC_SOURCE_MODELED`).
- `pzr_raLowCycleSourceLabel()` — returns a diagnostic label for the active low-cycle source (measured vs modeled).
- `pzr_printChannelTimingDiagnostics(ch, prefix)` — prints detailed per-channel 555 timing diagnostics.
- `pzt_printRsRefreshDiagnostics(ch, prefix)` — prints per-RS-channel refresh diagnostics (edges, pairs, timeouts, broken state).
- `pzr_resetAll555Averages()` / `pzr_resetAllChannels()` — reset per-555 and per-channel smoothing state.
- `pzr_muxDisableAll()` — drives both PZR and RS MUX enable lines low.
- `pzr_muxEnable(en)` — toggles the active-mode MUX enable line.
- `pzr_muxSelect(ch)` — selects a MUX channel, settles, and resets capture state.
- `pzr_updateChannelRaFromPair(ch, hCyc, lCyc, outRa)` — converts one 555 pulse pair into an Ra estimate using the selected low-cycle source, moving average, and median filter.
- `pzr_measureOneRa(ch, switched, outRa)` — measures Ra on a channel (blocking; used by PZR mode), with per-call timeout budget.
- `pzt_rsQuantizeOhms(ra)` — quantizes a float ohm value to uint16 scaled-ohms using `PZT_RS_WIRE_UNITS_PER_OHM`.
- `pzt_rsRecordChannelTimeout(ch)` / `pzt_rsRecordSuccessfulUpdate(ch)` — track per-channel RS timeout streaks and mark/clear "broken" channel state.
- `pzt_rsResetState()` — seeds held RS values from prior estimates and resets all RS refresh diagnostics before a `PZT_RS` run starts.
- `pzt_rsConsumeReadyPair()` — advances the RS refresh state machine (`IDLE`→discard→measure) by one step whenever a 555 pair becomes ready; on a successful measurement it updates the held value and immediately starts the next channel.
- `pzt_rsStartNextRefreshChannel()` — selects the next non-broken RS_MUX channel to refresh, switching the MUX only if it differs from the last-measured channel.
- `pzt_rsServiceRefresh(allowChannelSwitch)` — thin wrapper that advances RS refresh without blocking the PZT/MG24 stream.
- `pzt_buildCombinedBlock(src, srcLen, dst, dstLen, heldRaQSnapshot)` — repacks one raw PZT block into the `PZT_RS` payload layout: for each sensor, copies its 5 selected `PZT_CH*` samples (using the MG24 MUX side from `pztmuxes`) then appends `RS1_hold`/`RS2_hold` from the held-value snapshot (using the channel pair from `rschannels`).
- `hostAck(ok, args)` — emits `#OK`/`#NOT_OK` (suppressed during PZR ASCII streaming).
- `parseValueSuffix(inRaw, outVal, isCapUnits)` — parses numeric values with engineering suffixes.
- `pzt_handleChannels(args)` — parses the channel list; in `PZT_RS` mode requires the count to be a multiple of 5, deduplicates physical MG24 channels, and computes `sensorCount`.
- `pzt_handlePztMuxes(args)` — parses `pztmuxes` (one MG24 MUX side, 1 or 2, per selected PZT sensor).
- `pzt_handleRsChannels(args)` — parses `rschannels` (RS1,RS2 pair per selected PZT sensor) and builds the unique RS refresh channel list.
- `pzt_handleRepeat(args)` / `pzt_handleBuffer(args)` / `pzt_handleRef(args)` / `pzt_handleOsr(args)` / `pzt_handleGain(args)` / `pzt_handleGround(args)` — apply and push the corresponding PZT settings.
- `pzt_handleRun(args)` — blocking PZT/PZT_RS run: validates `pztmuxes`/`rschannels` config in `PZT_RS` mode, sends `CMD_RUN`, waits for the first (possibly RS-combined) block, then services DRDY/fallback/RS-refresh/USB-TX in a loop until stop/timeout/fault.
- `pzt_printStatus()` — prints PZT/PZT_RS configuration, including `pztmuxes`, `rschannels`, RS refresh channel list, and per-channel RS timing/broken-channel diagnostics.
- `pzr_handleChannels(args)` / `pzr_handleRepeat(args)` / `pzr_handleBuffer(args)` — parse/apply PZR channel sequence, repeat, and buffer settings.
- `pzr_handleRun(args)` — arms continuous or time-limited PZR streaming.
- `pzr_handleStop()` — stops active PZR streaming.
- `pzr_handleRb(args)` / `pzr_handleCf(args)` — parse/apply Rb/Cf and refresh the modeled low-cycle time.
- `pzr_handleRk(args)` / `pzr_handleRxMax(args)` — parse/apply Rk and max-Rx settings.
- `pzr_handleAscii(args)` — toggles PZR ASCII/binary output mode.
- `pzr_printStatus()` — prints PZR configuration/status including modeled vs measured low-cycle diagnostics.
- `pzr_doOneBlock()` — captures one PZR block of Ra measurements and emits it as ASCII or binary.
- `handleMode(args)` — switches between `MODE_PZT`, `MODE_PZR`, and `MODE_PZT_RS`, enabling/disabling the PZR/RS MUX lines as appropriate.
- `printMcu()` — prints `# Array_PZT_PZR1.7`.
- `printHelp()` — prints the command reference for all three modes, including `pztmuxes`/`rschannels` and the PZT_RS payload layout/scale note.
- `handleLine(rawLine)` — parses one command line and dispatches it to the shared, PZT/PZT_RS, or PZR handler.
- `setup()` — initializes serial/SPI/DRDY/PZR/RS pins, attaches the DRDY and 555 ISRs, computes the modeled low-cycle time, and announces the device.
- `loop()` — parses incoming commands and (in PZR mode) drives non-blocking PZR block capture.

## Serial Commands

Shared commands (`mcu*`, `status*`, `help*`, `channels*`, `repeat*`, `buffer*`, `run*`/`run <ms>*`, `stop*`) follow the top-level README's shared serial protocol.

- `mode PZT|PZR|PZT_RS*` — switch operating mode (default `PZT`). Confirmed present and functional in this sketch (`handleMode`).
- PZT / PZT_RS: `ref 1.2|3.3|vdd*`, `osr 2|4|8*`, `gain 1|2|3|4*`, `ground <ch>|true|false*`.
- **`pztmuxes mux1,mux2...*`** — PZT_RS-only; confirmed present (`pzt_handlePztMuxes`, dispatched at `cmd == "pztmuxes" && currentMode == MODE_PZT_RS`). Requires exactly one MUX side (`1` or `2`) per selected PZT sensor; rejected outside `PZT_RS` mode.
- **`rschannels rs1,rs2...*`** — PZT_RS-only; confirmed present (`pzt_handleRsChannels`). Requires exactly two RS_MUX channel values per selected PZT sensor; rejected outside `PZT_RS` mode.
- PZR / PZT_RS: `rb <ohms|k|M>*`, `rk <ohms|k|M>*`, `cf <F|p|n|u|m>*`, `rxmax <ohms|k|M>*` (in `PZT_RS` mode these tune the RS measurement, not a separate PZR stream).
- PZR-only: `ascii [1|0|on|off]*`.

## PZT_RS Payload — Verified Against Firmware

Cross-checked directly against `pzt_buildCombinedBlock()` and `PZT_RS_*` constants in the Teensy sketch:

- Each selected PZT sensor's payload is **7 `uint16` values**: `[PZT_CH1, PZT_CH2, PZT_CH3, PZT_CH4, PZT_CH5, RS1_hold, RS2_hold]` — matches the top-level README exactly. `PZT_CHANNELS_PER_SENSOR = 5`, `PZT_RS_VALUES_PER_SENSOR = 2`, `PZT_RS_OUTPUTS_PER_SENSOR = 7`.
- `PZT_RS_WIRE_UNITS_PER_OHM = 100` — confirmed (line ~155); `pzt_rsQuantizeOhms()` multiplies by this constant and clamps to `[0, 65535]`. Host-side code should divide `RS1_hold`/`RS2_hold` by 100.0 to recover ohms, as documented.
- `RS1_hold`/`RS2_hold` are genuinely **held/last-known values**, not synchronized per-sample measurements: they come from a free-running, non-blocking refresh state machine (`pzt_rsConsumeReadyPair`/`pzt_rsStartNextRefreshChannel`) that cycles across all unique `rschannels` channels and only updates a channel's held value when a fresh 555 pair-ready event lands. RS refresh genuinely never blocks/paces PZT block delivery — `pzr_takeReadyPair` is non-blocking and `pzt_rsServiceRefresh` is called interleaved with SPI/DRDY servicing in the run loop.
- `pztmuxes`/`rschannels` really exist and are validated together in `pzt_handleRun`: a `PZT_RS` `run*` is rejected with `#NOT_OK` if `sensorMuxCount != sensorCount` or `rsChannelCount != sensorCount`.
- `mode PZT|PZR|PZT_RS*` really works as described — `handleMode` validates all three tokens and rejects anything else with `# ERROR: mode must be PZT, PZR, or PZT_RS`.
- For the current five-sensor PCB1.7 layout (5 sensors × 7 values), the top-level README's "35 samples per sweep at repeat/buffer=1" figure is consistent with `pzt_rsOutputSamplesPerBlock() = sensorCount * repeatCount * sweepsPerBlock * 7`.

## DRDY Behavior — Verified Against Firmware

Identical DRDY wiring and behavior to PCB1.5: MG24 asserts DRDY (D7, active-HIGH) whenever a response is armed and deasserts it on CS rising edge. The Teensy's primary read path (`pzt_serviceSpiRx`) is DRDY-interrupt-driven. **The guarded fallback polling path genuinely exists in this sketch** (`pzt_serviceSpiRxFallbackPoll`, armed only after `(now - lastActivity) > blockDelay + DRDY_MARGIN`), confirming the top-level README's claim that "the Teensy firmware still includes a guarded fallback polling path for safety if DRDY stalls" — this applies equally to plain `PZT` and combined `PZT_RS` streaming, since both share the same `pzt_serviceSpiRx`/fallback machinery; only the post-receive block repacking (`pzt_handleStreamingFrame` → `pzt_buildCombinedBlock`) differs in `PZT_RS` mode.

## Teensy/MG24 Pairing

Flash both boards with the matching current PCB1.7 pair: `Teensy_SPI_Master_Array_PZT_PZR1.7_DRDY.ino` on the Teensy and `MG24_Dual_MUX_SPI_Slave1.7b.ino` on the MG24. Do not mix a Teensy sketch from this folder with an MG24 sketch from `PCB1.0_SPI/` or `PCB1.5_SPI/` (or vice versa). The 1.7b MG24 sketch remains protocol-compatible with PCB1.5 and the earlier PCB1.7 DRDY slave (same command codes, DRDY behavior, and binary payload), but pairing should still stay within-folder per the top-level README's pairing notes, since the `PZT_RS` repacking logic on the Teensy depends on the exact physical-channel/`pztmuxes` bookkeeping introduced alongside this MG24 sketch version.
