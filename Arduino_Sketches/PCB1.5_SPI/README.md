# PCB1.5_SPI

Firmware pair for PCB hardware revision v1.5: a Teensy 4.0/4.1 SPI master (`Teensy_SPI_Master_Array_PZT_PZR1.5_DRDY.ino`) paired with an XIAO MG24 SPI slave (`MG24_Dual_MUX_SPI_Slave1.5_DRDY.ino`). This revision adds a real, wired **DRDY** signal (MG24 D7 → Teensy pin 0, active-HIGH) as the primary stream synchronization mechanism, replacing the fixed-delay polling used on PCB1.0. It supports `PZT` and `PZR` modes (with switchable PZR/RS 555 timer sources) but **does not** support the combined `PZT_RS` mode — that was added in PCB1.7. This is the current board revision for dual-board array hardware without combined PZT+RS streaming; `mcu*` reports `# Array_PZT_PZR1`.

## Files

### MG24_Dual_MUX_SPI_Slave1.5_DRDY.ino

XIAO MG24 SPI slave that drives two ADG1206 (16:1) MUXes in parallel, reading MUX1 on D1 and MUX2 on D2 via the IADC. Adds an active-HIGH DRDY output on D7: asserted when a response is armed, deasserted on CS rising edge and when re-arming the command receive. Also adds fast-GPIO MUX switching, ground-channel "park" behavior between blocks/while transmitting, and a configurable ground-dwell vs ground-read-ADC strategy, compared to PCB1.0's MG24 slave.

- `drdyWrite(asserted)` — drives the DRDY output pin HIGH/LOW.
- `spiCallback(handle, status, count)` — SPIDRV transfer-done callback; records status and sets `xferDone`.
- `armCmd()` — deasserts DRDY and arms the next command-frame receive transfer.
- `armResp(txBuf, len, isStreaming)` — arms an SPI response transfer and asserts DRDY.
- `onCSRising()` — CS rising-edge ISR; deasserts DRDY and sets `csRose`.
- `allocateAnalogBus(p)` — allocates the IADC analog bus bit for a given pin.
- `makeFastMuxPin(idx, arduinoPin)` — resolves an Arduino pin to a raw GPIO port/pin for fast (non-`digitalWrite`) MUX control.
- `fastMuxWrite(idx, high)` — sets/clears a MUX address line via direct GPIO register access.
- `initFastMuxPins()` — initializes all four fast MUX address pins; falls back to slow `digitalWrite` if any pin can't be resolved.
- `muxSelectSlow(ch)` — sets MUX address lines via `digitalWrite` (fallback path).
- `muxSelect(ch)` — selects a MUX channel via fast or slow path, settling for `MUX_SETTLE_US` if the channel changed.
- `initIADC()` — configures and starts the IADC in 2-entry scan mode using current reference/OSR/gain settings.
- `iadcFlushFifo()` — drains any stale IADC scan FIFO results.
- `iadcReadPairFast(v1, v2)` — fast hot-path scan read assuming fixed FIFO entry order (no ID check).
- `iadcReadPairChecked(v1, v2)` — safer scan read that verifies scan-table ID order (debug-only, not in hot path).
- `groundStepIfNeeded()` — inserts a ground/Vmid MUX step (with optional discarded ADC read) before a new channel when `useGround` is set.
- `parkMuxOnGround()` — parks both MUXes on the ground/Vmid channel after a block and while SPI is transmitting.
- `buildEntryList()` — rebuilds the flattened per-sweep channel/ground entry list.
- `clampSweepsPerBlock()` — caps `sweepsPerBlock` so block data fits the fixed-size SPI TX buffer.
- `captureBlock(txBuf)` — captures `sweepsPerBlock` sweeps of MUX1/MUX2 pairs, writes header/trailer, then parks the MUX.
- `prepareAck(txBuf, ok, b2, b3)` — writes a 4-byte ACK frame.
- `blockResponseLenFromPairs(pairs)` — computes response byte length for a pair count.
- `prepareBlockResponse(txBuf)` — captures a block and returns its response length.
- `resetStreamingPipeline()` — clears streaming/prefetch state.
- `prefetchNextBlockIfNeeded()` — captures the next block ahead of time while the current one streams, skipping prefetch if a stop or timed-run expiry was just observed.
- `doWarmup()` — discards `WARMUP_SWEEPS` sweeps after `run` starts, then parks the MUX.
- `processCommand(frame)` — dispatches a received command frame to the matching handler and returns the response length.
- `setup()` — initializes MUX/ADC/DRDY pins, attaches the CS interrupt, configures SPIDRV, and pre-arms the first command receive.
- `loop()` — prefetches the next block, services SPI transfer completion, and dispatches to `processCommand` or advances the streaming pipeline.

### Teensy_SPI_Master_Array_PZT_PZR1.5_DRDY.ino

Teensy 4.0/4.1 sketch combining `mode PZT*` (SPI bridge to the MG24 slave above) and `mode PZR*` (555-astable resistance via two independently addressable 555 MUXes — `TIMER555_PZR` and `TIMER555_RS`, selectable in firmware via `DEFAULT_555_MODE`) behind one serial API; `mcu*` reports `# Array_PZT_PZR1`. PZT `run*` is blocking but, unlike PCB1.0, now uses real DRDY interrupt notification (MG24 D7 → Teensy pin 0, `RISING`) plus a small RAM receive queue so SPI reads happen promptly and USB writes drain in parallel. A genuine **DRDY-stall fallback poll path** (`pzt_serviceSpiRxFallbackPoll`) is included: if no DRDY edge arrives within an expected window, the Teensy falls back to a direct SPI poll to keep the stream alive, and per-run diagnostics (`pzt_logStreamSummary`) report the drdy-vs-fallback block/ACK counts.

- `pzt_drdyISR()` — DRDY rising-edge ISR; sets the pending-edge flag/counter.
- `pzt_drdyIsAsserted()` — reads the current DRDY pin level.
- `pzt_drdyPending()` — reports whether an unread DRDY edge is queued.
- `pzt_drdyConsumeOne()` — consumes one queued DRDY edge.
- `pzt_drdyClearAll()` — clears all queued DRDY edges.
- `pzt_waitForDrdy(timeoutMs)` — blocks until a DRDY edge arrives or times out.
- `pzt_spiTransfer(tx, rx, len)` — raw byte-by-byte SPI transfer with CS framing.
- `pzt_spiSend(buf, len)` / `pzt_spiRecv(buf, len)` — send-only/receive-only wrappers.
- `pzt_spiRecvStreamingResponse(buf, len, controlByte, maxAttempts)` — attempts to read a valid ACK or block-magic response.
- `pzt_recvAckWhenReady(buf, timeoutMs)` — waits for DRDY, then reads/validates a 4-byte ACK.
- `pzt_queueIsEmpty()` / `pzt_queueIsFull()` — receive-queue state checks.
- `pzt_queueFront()` / `pzt_queueWriteSlot()` — accessors into the ring-buffer receive queue.
- `pzt_queueCommitWrite(len)` / `pzt_queuePopFront()` — commit a filled slot / drop a fully-sent slot.
- `pzt_streamResetState()` — resets all per-run streaming/queue/diagnostic counters.
- `pzt_logStreamSummary()` — prints aggregated DRDY-vs-fallback block/ACK/error diagnostics for the just-finished run.
- `pzt_recordRxError(reason)` — tracks consecutive RX error streaks; returns true once the abort threshold is hit.
- `pzt_clearRxErrors()` — resets the consecutive RX error counter.
- `pzt_serviceSpiRxFallbackPoll()` — fallback path: when DRDY signaling stalls, polls one SPI response directly to keep the stream alive.
- `pzt_writeBlockBuffered(buf, len)` — writes a binary block to host serial respecting flow control.
- `pzt_emitBlock(buf, len)` — emits a block as raw binary or debug text.
- `pzt_serviceUsbTx()` — drains one queued block to USB serial without blocking SPI servicing.
- `pzt_pollStreamStopRequest()` — detects an inline `stop*` while the blocking PZT run loop is active.
- `pzt_serviceSpiRx()` — services pending DRDY edges, reading ACK/block responses and queuing valid blocks (the DRDY-driven primary path).
- `pzt_discardPendingTerminators(settleMs)` — drains stray trailing bytes/terminators.
- `pzt_sendCmd(cmd, args, nargs)` — builds and sends a fixed 20-byte command frame, clearing DRDY state first.
- `pzt_sendCmdAck(cmd, args, nargs)` — sends a command and waits for/validates its DRDY-signaled ACK.
- `pzt_usPerPair()` — estimates per-pair acquisition time from OSR.
- `pzt_entriesPerSweep()` — computes MG24 entries per sweep including ground entries.
- `pzt_blockDelayMs()` / `pzt_warmupDelayMs()` — estimate block/warmup timing windows.
- `pzt_blockResponseBytes()` — computes expected SPI response size for the current config.
- `pzt_isValidAckFrame(buf)` — checks whether a 4-byte buffer is a legal ACK frame.
- `pzr_isr555()` — active-555 ICP edge ISR; computes high/low cycle counts via DWT and flags `pairReady`.
- `pzr_resetCaptureState()` — clears shared 555 capture state.
- `pzr_computePairTimeoutMs()` — derives a conservative pair-wait timeout from Rb/Cf/RxMax.
- `pzr_waitForPair(hCyc, lCyc, timeout_ms)` — blocks until one 555 pulse pair is captured or timeout.
- `pzr_updateMA(buf, sum, idx, count, N, val)` — generic moving-average update helper.
- `pzr_resetAll555Averages()` — resets the per-physical-555 (PZR/RS) low-cycle moving averages.
- `pzr_resetAllChannels()` — resets per-channel Ra state and the per-555 averages.
- `pzr_muxEnable(en)` — drives the active 555's MUX enable line, if wired.
- `pzr_muxSelect(ch)` — selects an active-555 MUX channel and resets capture state.
- `pzr_measureOneRa(ch, switched, outRa)` — measures Ra=(Rx+Rk) on a channel from 555 timing, with discharge-time (`lCyc`) moving-average smoothing per physical 555 source.
- `hostAck(ok, args)` — emits `#OK`/`#NOT_OK` (suppressed during PZR ASCII streaming).
- `parseValueSuffix(inRaw, outVal, isCapUnits)` — parses numeric values with engineering suffixes.
- `pzt_handleChannels(args)` — parses a PZT channel list and sends `SET_CHANNELS`, waiting for the DRDY-signaled ACK.
- `pzt_handleRepeat(args)` / `pzt_handleBuffer(args)` / `pzt_handleRef(args)` / `pzt_handleOsr(args)` / `pzt_handleGain(args)` / `pzt_handleGround(args)` — apply and push the corresponding PZT settings.
- `pzt_handleRun(args)` — blocking PZT run: sends `CMD_RUN`, waits (DRDY-driven) for the first block, then services DRDY/fallback/USB-TX in a loop until stop/timeout/fault, logging a stream summary at the end.
- `pzt_printStatus()` — prints current PZT configuration/status.
- `pzr_handleChannels(args)` / `pzr_handleRepeat(args)` / `pzr_handleBuffer(args)` — parse/apply PZR channel sequence, repeat, and buffer settings.
- `pzr_handleRun(args)` — arms continuous or time-limited PZR streaming.
- `pzr_handleStop()` — stops active PZR streaming.
- `pzr_handleRb(args)` / `pzr_handleRk(args)` / `pzr_handleCf(args)` / `pzr_handleRxMax(args)` — parse/apply 555 component and timeout settings.
- `pzr_handleAscii(args)` — toggles PZR ASCII/binary output mode.
- `pzr_printStatus()` — prints current PZR configuration/status, including active 555 source name and timing diagnostics.
- `pzr_doOneBlock()` — captures one PZR block of Ra measurements and emits it as ASCII or binary.
- `handleMode(args)` — switches between `MODE_PZT` and `MODE_PZR`.
- `printMcu()` — prints `# Array_PZT_PZR1`.
- `printHelp()` — prints the command reference for both modes.
- `handleLine(rawLine)` — parses one command line and dispatches it.
- `setup()` — initializes serial/SPI/DRDY/PZR/RS pins, attaches the DRDY and 555 ISRs, and announces the device and active 555 source.
- `loop()` — parses incoming commands and (in PZR mode) drives non-blocking PZR block capture.

## Serial Commands

Shared commands (`mcu*`, `status*`, `help*`, `channels*`, `repeat*`, `buffer*`, `run*`/`run <ms>*`, `stop*`) follow the top-level README's shared serial protocol. Mode-specific commands:

- `mode PZT*` / `mode PZR*` — switch operating mode (default `PZT`). There is **no `PZT_RS` mode** on this PCB revision (PZT and RS/555 values are never combined into one payload here).
- PZT-only: `ref 1.2|3.3|vdd*`, `osr 2|4|8*`, `gain 1|2|3|4*`, `ground <ch>|true|false*`.
- PZR-only: `rb <ohms|k|M>*`, `rk <ohms|k|M>*`, `cf <F|p|n|u|m>*`, `rxmax <ohms|k|M>*`, `ascii [1|0|on|off]*`.
- No `pztmuxes*` or `rschannels*` commands exist on this revision (those are PCB1.7-only).
- DRDY-related: there is no host-facing DRDY command — DRDY is a hardware signal (MG24 D7 → Teensy pin 0) used internally for stream pacing; it is not configurable over the serial protocol.

## DRDY Behavior

This revision wires DRDY end-to-end: the MG24 asserts it whenever a response (ACK or data block) is armed and deasserts it on CS rising edge / re-arming. The Teensy's primary read path (`pzt_serviceSpiRx`) is driven by the DRDY interrupt. If DRDY signaling stalls beyond the expected per-block timing window, the Teensy falls back to direct polling (`pzt_serviceSpiRxFallbackPoll`) to keep the stream alive — this fallback path is real and present in this sketch, confirming the top-level README's note that "the Teensy firmware still includes a guarded fallback polling path for safety if DRDY stalls."

## Teensy/MG24 Pairing

Flash both boards with the matching PCB1.5 pair: `Teensy_SPI_Master_Array_PZT_PZR1.5_DRDY.ino` on the Teensy and `MG24_Dual_MUX_SPI_Slave1.5_DRDY.ino` on the MG24. Do not mix a Teensy sketch from this folder with an MG24 sketch from `PCB1.0_SPI/` or `PCB1.7_SPI/` (or vice versa) — DRDY wiring, pin assignments, and protocol details differ across revisions.
