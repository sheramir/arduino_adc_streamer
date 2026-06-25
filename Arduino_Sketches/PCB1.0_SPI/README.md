# PCB1.0_SPI

Firmware pair for PCB hardware revision v1.0 (legacy board revision): a Teensy 4.0/4.1 SPI master (`Teensy_SPI_Master_Array_PZT_PZR1.ino`) paired with an XIAO MG24 SPI slave (`MG24_Dual_MUX_SPI_Slave.ino`). The pair supports the `PZT` (SPI-bridged dual-MUX ADC) and `PZR` (555-astable resistance) modes, but has **no DRDY pin** and **no combined `PZT_RS` mode** — those were added starting with PCB1.5 and PCB1.7 respectively. This is the legacy/oldest variant in the sketch map; prefer `PCB1.5_SPI/` or `PCB1.7_SPI/` for current hardware.

## Files

### MG24_Dual_MUX_SPI_Slave.ino

XIAO MG24 SPI slave that drives two ADG1206 (16:1) MUXes in parallel (shared A0–A3 address lines), reading MUX1 on D1 and MUX2 on D2 via the on-chip IADC. No DRDY signaling — the Teensy master drives all timing via a fixed two-phase SPI exchange (command frame, then ACK or full data block). A `D7` pin is reserved/labeled for DRDY in comments but is not wired or implemented in this revision.

- `spiCallback(handle, status, count)` — SPIDRV transfer-done callback; records status and sets `xferDone`.
- `armCmd()` — arms the next `CMD_FRAME_LEN`-byte command receive transfer and resets state to `WAIT_CMD`.
- `armResp(txBuf, len, isStreaming)` — arms an SPI response transfer (ACK or data block) and sets `RESP_ARMED` state.
- `onCSRising()` — CS rising-edge ISR; sets `csRose` flag for `loop()` to process.
- `allocateAnalogBus(p)` — allocates the correct CDBUSALLOC/BBUSALLOC/ABUSALLOC analog bus bit for a given pin so the IADC can sample it.
- `muxSelect(ch)` — drives the ADG1206 address lines for the requested channel and waits `MUX_SETTLE_US`.
- `initIADC()` — configures and starts the IADC in 2-entry scan mode (MUX1 COM, MUX2 COM) using current reference/OSR/gain settings.
- `iadcReadPair(v1, v2)` — triggers one IADC scan and blocks until both MUX1/MUX2 results arrive, assigning them by scan-table ID.
- `buildEntryList()` — rebuilds the flattened per-sweep channel/ground entry list from `channelSeq`, `repeatCount`, and `useGround`.
- `clampSweepsPerBlock()` — caps `sweepsPerBlock` so a block's sample data always fits in the fixed-size SPI TX buffer.
- `captureBlock(txBuf)` — captures `sweepsPerBlock` sweeps of MUX1/MUX2 pairs into `txBuf`, then writes the block header and trailer.
- `prepareAck(txBuf, ok, b2, b3)` — writes a 4-byte ACK frame (`0xAC`, status, two payload bytes) into `txBuf`.
- `blockResponseLenFromPairs(pairs)` — computes total response byte length for a given pair count.
- `prepareBlockResponse(txBuf)` — calls `captureBlock` and returns the resulting response length.
- `resetStreamingPipeline()` — clears streaming/prefetch state flags (`streamRespArmed`, `nextBlockReady`, `nextBlockLen`).
- `prefetchNextBlockIfNeeded()` — during an armed streaming response, captures the next block into the alternate buffer ahead of time.
- `doWarmup()` — discards `WARMUP_SWEEPS` full sweeps after `run` starts so the IADC reference/analog filters settle.
- `processCommand(frame)` — dispatches a received command frame (`SET_CHANNELS`, `SET_REPEAT`, `SET_BUFFER`, `SET_REF`, `SET_OSR`, `SET_GAIN`, `RUN`, `STOP`, `MCU_ID`, `GROUND_PIN`, `GROUND_EN`, `CMD_CONTINUE`) and returns the response length to arm.
- `setup()` — initializes pins, attaches the CS interrupt, configures SPIDRV (EUSART1, SPI_MODE1, 4 MHz, slave), and pre-arms the first command receive.
- `loop()` — prefetches the next block when possible, waits for SPI transfer completion on CS rising edge, and dispatches to `processCommand` (in `WAIT_CMD`) or advances the streaming pipeline (in `RESP_ARMED`).

### Teensy_SPI_Master_Array_PZT_PZR1.ino

Teensy 4.0/4.1 sketch combining two acquisition paths behind one serial API: `mode PZT*` (default) bridges the host to the MG24 dual-MUX SPI slave above, and `mode PZR*` performs 555-astable resistance measurement through an ADG706 MUX, reporting `mcu*` as `# Array_PZT_PZR1`. PZT `run*` is blocking; PZR `run*` is non-blocking and executes per-block inside `loop()`. There is no DRDY pin wired in this revision — the Teensy paces all PZT SPI transfers itself with fixed delays and polling/retry loops (no fallback-vs-DRDY distinction exists here, unlike PCB1.5/1.7).

- `pzt_spiTransfer(tx, rx, len)` — performs a raw byte-by-byte SPI transfer to/from the MG24 slave with CS framing.
- `pzt_spiSend(buf, len)` / `pzt_spiRecv(buf, len)` — thin send-only/receive-only wrappers around `pzt_spiTransfer`.
- `pzt_spiRecvStreamingResponse(buf, len, controlByte, maxAttempts)` — polls for a valid ACK or block-magic response, retrying with short delays.
- `pzt_waitStreamingResponse(buf, len, controlByte, timeoutMs)` — repeatedly calls the above until success or timeout.
- `pzt_spiRecvAck(buf, maxAttempts)` — retries reading a 4-byte ACK frame until the ACK magic byte is seen.
- `pzt_writeBlockBuffered(buf, len)` — writes a binary block to the host serial port respecting `availableForWrite()` flow control.
- `pzt_emitBlock(buf, len)` — emits a captured block either as raw binary or (if `PZT_DEBUG_TEXT_STREAM`) as human-readable debug text.
- `pzt_discardPendingTerminators(settleMs)` — drains stray bytes/terminators left on the serial line after a command.
- `pzt_sendCmd(cmd, args, nargs)` — builds and sends a fixed 20-byte PZT command frame to MG24.
- `pzt_sendCmdAck(cmd, args, nargs)` — sends a command and waits for/validates its ACK response.
- `pzt_usPerPair()` — estimates per-(MUX1,MUX2)-pair acquisition time from the current OSR setting.
- `pzt_entriesPerSweep()` — computes MG24 entries per sweep, including ground entries if enabled.
- `pzt_blockDelayMs()` / `pzt_warmupDelayMs()` — estimate timing windows for one streaming block and for the warmup phase.
- `pzt_blockResponseBytes()` — computes the expected SPI response size (ACK header + MUX1/MUX2 samples + trailer) for the current config.
- `pzt_firstBlockWaitMs()` / `pzt_streamBlockWaitMs()` — compute timeout windows for the first block and for each subsequent streamed block.
- `pzt_isValidAckFrame(buf)` — checks whether a 4-byte buffer is a legal MG24 ACK frame.
- `pzr_isr555()` — 555 output edge ISR; computes high/low cycle counts from the DWT cycle counter and flags `pairReady`.
- `pzr_resetCaptureState()` — clears the shared 555 capture state (interrupt-safe).
- `pzr_computePairTimeoutMs()` — derives a conservative wait timeout for one 555 high/low pair from `Rb`/`Cf`/`RxMax`.
- `pzr_waitForPair(hCyc, lCyc, timeout_ms)` — blocks until one complete 555 pulse pair is captured or the timeout elapses.
- `pzr_updateMA(buf, sum, idx, count, N, val)` — generic fixed-size moving-average update helper.
- `pzr_resetAllChannels()` — resets per-channel Rx/Rdis moving-average state for all 16 PZR channels.
- `pzr_muxEnable(en)` — drives the PZR MUX enable line if wired (no-op if `PZR_MUX_EN_PIN < 0`).
- `pzr_muxSelect(ch)` — selects a PZR/RS MUX channel, applies settle delay, and resets capture state.
- `pzr_measureOneRx(ch, switched, outRx)` — measures one Rx value on a channel from 555 high/low timing, applying moving averages for Rdis and Rx.
- `hostAck(ok, args)` — emits the `#OK`/`#NOT_OK` protocol acknowledgment line (suppressed during PZR ASCII streaming).
- `parseValueSuffix(inRaw, outVal, isCapUnits)` — parses a numeric value with engineering suffixes (k/M for ohms, p/n/u/m for farads).
- `pzt_handleChannels(args)` — parses a PZT channel list and sends `SET_CHANNELS` to MG24.
- `pzt_handleRepeat(args)` — applies and pushes the PZT repeat count.
- `pzt_handleBuffer(args)` — applies and pushes the PZT sweeps-per-block setting.
- `pzt_handleRef(args)` — applies and pushes the ADC reference selection (1.2V / VDD-3.3V).
- `pzt_handleOsr(args)` — validates and pushes the oversampling-rate setting (2/4/8).
- `pzt_handleGain(args)` — validates and pushes the analog gain setting (1–4).
- `pzt_handleGround(args)` — configures dummy-ground channel/enable behavior.
- `pzt_handleRun(args)` — blocking PZT streaming run: sends `CMD_RUN`, waits for the first block, then loops reading/forwarding streamed blocks until `stop*`, timeout, or fault.
- `pzt_printStatus()` — prints current PZT configuration/status to the serial port.
- `pzr_handleChannels(args)` — parses and validates the PZR channel sequence list.
- `pzr_handleRepeat(args)` / `pzr_handleBuffer(args)` — apply PZR repeat/buffer settings.
- `pzr_handleRun(args)` — arms continuous or time-limited PZR streaming (`pzr_isRunning`/`pzr_timedRun`).
- `pzr_handleStop()` — stops active PZR streaming.
- `pzr_handleRb(args)` / `pzr_handleRk(args)` / `pzr_handleCf(args)` / `pzr_handleRxMax(args)` — parse and apply the 555 discharge resistor, known series resistor, timing capacitor, and max-Rx settings.
- `pzr_handleAscii(args)` — toggles PZR ASCII/binary output mode (stops streaming on change).
- `pzr_printStatus()` — prints current PZR configuration/status to the serial port.
- `pzr_doOneBlock()` — captures one PZR block of Rx measurements and emits it as ASCII or as a binary block.
- `handleMode(args)` — switches between `MODE_PZT` and `MODE_PZR`, stopping any active run in the outgoing mode.
- `printMcu()` — prints the device ID line (`# Array_PZT_PZR1`).
- `printHelp()` — prints the command reference for both modes.
- `handleLine(rawLine)` — parses one `*`-terminated command line and dispatches it to the shared, PZT, or PZR handler.
- `setup()` — initializes serial, SPI, PZT/PZR/RS pins, attaches the 555 ISR, and announces the device.
- `loop()` — parses incoming serial commands and (in PZR mode) drives non-blocking PZR block capture.

## Serial Commands

Shared commands (`mcu*`, `status*`, `help*`, `channels*`, `repeat*`, `buffer*`, `run*`/`run <ms>*`, `stop*`) follow the top-level README's shared serial protocol. Mode-specific commands:

- `mode PZT*` / `mode PZR*` — switch operating mode (default `PZT`). There is **no `PZT_RS` mode** on this PCB revision.
- PZT-only: `ref 1.2|3.3|vdd*`, `osr 2|4|8*`, `gain 1|2|3|4*`, `ground <ch>|true|false*`.
- PZR-only: `rb <ohms|k|M>*`, `rk <ohms|k|M>*`, `cf <F|p|n|u|m>*`, `rxmax <ohms|k|M>*`, `ascii [1|0|on|off]*`.
- No `pztmuxes*` or `rschannels*` commands exist on this revision (those are PCB1.7-only).

## Teensy/MG24 Pairing

Flash both boards with the matching PCB1.0 pair: `Teensy_SPI_Master_Array_PZT_PZR1.ino` on the Teensy and `MG24_Dual_MUX_SPI_Slave.ino` on the MG24. Do not mix a Teensy sketch from this folder with an MG24 sketch from `PCB1.5_SPI/` or `PCB1.7_SPI/` (or vice versa) — protocol/pin details differ across revisions.
