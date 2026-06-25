# Teensy Libraries

Sketch-local libraries used by the PCB1.7 modular Teensy master sketch. They implement the Teensy side of the Teensy/MG24 SPI array protocol plus the PCB1.7-only combined `PZT_RS` stream: serial command dispatch and mode switching (`Pcb17Firmware`), host-facing protocol framing (`SharedProtocol`), serial line tokenizing (`SerialLineParser`), the DRDY-aware SPI master transport (`SpiMasterLink`), MG24/PZT configuration and non-blocking streaming (`PztController`), PZT_RS sensor routing/RS refresh/block repacking (`PztRsController`), and PZR/555 resistance acquisition (`PzrController`).

Unlike the PCB1.5 Teensy libraries, `PztController`, `PztRsController`, and `PzrController` here use module-level (file-static) state behind free functions rather than an explicit `Runtime&` struct passed by the caller — there is exactly one instance of each per sketch. `SpiMasterLink` also gained DRDY (data-ready) interrupt support, and `PztController::handleRun` is DRDY-driven with a polling fallback instead of the PCB1.5 version's single blocking SPI exchange per block.

## Files

### Pcb17Firmware.h / Pcb17Firmware.cpp

Namespace `pcb17_firmware`. Thin top-level orchestrator: owns the `MODE_PZT` / `MODE_PZR` / `MODE_PZT_RS` state, serial command dispatch (`mode`, `mcu`, `help`, `status`, `stop`, and mode-specific commands), and `setup()`/`loop()` delegation called directly from the `.ino`.

- `setupFirmware()` — starts serial, initializes the line parser, calls `pzt_controller::begin()` and `pzr_controller::begin()`, and prints MCU/mode banner text.
- `loopFirmware()` — drains serial input into the line parser/dispatcher and, in `MODE_PZR`, drives one acquisition block per loop iteration (`pzr_controller::doOneBlock()`) while running.

Mode switching (`mode PZT|PZR|PZT_RS*`) is handled internally: entering `PZT_RS` enables combined-block repacking in `PztController` and enables the RS 555 MUX; entering `PZR` stops PZT/PZT_RS streaming and enables the PZR/RS MUX as configured.

### SharedProtocol.h / SharedProtocol.cpp

Namespace `shared_proto`. Identical role and API to the PCB1.5 version: host ACK/NOT_OK writer, engineering-suffix value parser, and binary block encoder.

- `writeHostAck(bool ok, const String &args, bool suppress)` — prints `#OK [args]` or `#NOT_OK [args]` (or nothing if suppressed), then flushes.
- `parseValueSuffix(const String &in_raw, double &out_val, bool is_cap_units)` — parses ohms (k/M suffix) or farads (p/n/u/m suffix) values.
- `encodeBinaryBlock(uint8_t *dst, uint32_t dst_cap, const uint16_t *samples, uint16_t sample_count, uint16_t avg_dt_us, uint32_t block_start_us, uint32_t block_end_us)` — encodes the shared `[0xAA 0x55][count][samples...][trailer]` block format.

### SerialLineParser.h / SerialLineParser.cpp

Same role and API as the PCB1.5 version: `*`-terminated serial line tokenizer.

- `SerialLineParser::begin(char term, uint16_t max_line_len)` — sets terminator/length cap.
- `SerialLineParser::feed(char c, String &out_line)` — accumulates characters, returns true with the completed line once the terminator is seen.
- `SerialLineParser::clear()` — discards the in-progress line.
- `splitCommand(const String &line, String &out_cmd, String &out_args)` — splits into lowercase command + trimmed args.

### SpiMasterLink.h / SpiMasterLink.cpp

Low-level SPI master transport, extended from the PCB1.5 version with DRDY (data-ready) GPIO interrupt support so the Teensy can tell when the MG24 has armed a response without polling blindly.

- `begin(SPIClass &spi_ref, uint8_t cs, uint32_t bitrate, uint32_t setup_us)` — configures CS pin and SPI settings (4 MHz default, MSB-first, mode 1).
- `beginDrdy(uint8_t pin)` — configures the DRDY input pin (pulldown) and attaches a rising-edge interrupt that increments an edge counter.
- `transfer(const uint8_t *tx, uint8_t *rx, uint32_t len)` — full-duplex transfer with CS framing.
- `transferLeadByte(uint8_t lead, uint8_t *rx, uint32_t len)` — like `transfer` but sends a single lead/control byte followed by zero-fill.
- `send(const uint8_t *tx, uint32_t len)` / `recv(uint8_t *rx, uint32_t len)` — write-only / read-only convenience wrappers around `transfer`.
- `recvStreamingResponse(uint8_t *buf, uint16_t len, uint8_t control_byte, uint8_t max_attempts, uint8_t ack_magic, uint8_t block_magic1, uint8_t block_magic2)` — sends `control_byte` as the lead byte and retries up to `max_attempts` times (with backoff) until a valid ACK or block-magic header is seen.
- `drdyPending() const` — true if at least one unconsumed DRDY edge has been recorded.
- `drdyConsumeOne()` — decrements the pending DRDY edge count by one.
- `drdyClearAll()` — clears all pending DRDY edges/flag.
- `waitForDrdy(uint32_t timeout_ms)` — blocks (yielding) until DRDY is pending or the timeout elapses.
- `drdyIsrThunk()` — static ISR trampoline that updates the single registered `SpiMasterLink` instance's DRDY state.

### PztController.h / PztController.cpp

Namespace `pzt_controller`. Owns MG24/PZT configuration (channels, repeat, buffer, ref/osr/gain, ground) and the PZT/PZT_RS streaming run loop. Tracks both the "logical" channel list (which, in `PZT_RS` mode, repeats groups of 5 channels per sensor) and the deduplicated "physical" MG24 MUX channel list actually sent to the MG24. The run loop is DRDY-driven: it queues incoming blocks (`kRxQueueDepth`=4 slots), opportunistically falls back to polling if DRDY has been idle too long, repacks blocks into the combined `PZT_RS` payload via `pzt_rs_controller::buildCombinedBlock` when combined mode is enabled, and streams queued blocks out over USB serial in chunks sized to `Serial.availableForWrite()`.

- `begin()` — initializes the SPI link, DRDY pin, and PZT_RS routing.
- `setCombinedMode(bool enabled)` — enables/disables `PZT_RS` repacking; stops any active run and resets RS routing when disabled.
- `combinedMode()` — returns whether combined mode is active.
- `handleChannels(const String &args)` — parses the logical channel list (in `PZT_RS` mode, must be a multiple of 5 channels per sensor), derives the deduplicated physical channel list, configures sensor count for `PztRsController`, and forwards the physical channel list to the MG24.
- `handlePztMuxes(const String &args)` — (combined mode only) forwards to `pzt_rs_controller::handlePztMuxes`, assigning which MG24 MUX side (1 or 2) feeds each selected PZT sensor.
- `handleRsChannels(const String &args)` — (combined mode only) forwards to `pzt_rs_controller::handleRsChannels`, assigning the RS1/RS2 555-MUX channel pair per selected PZT sensor.
- `handleRepeat(const String &args)` — sets samples-per-channel (1-100) and forwards to the MG24.
- `handleBuffer(const String &args)` — sets sweeps-per-block (1-255) and forwards to the MG24.
- `handleRef(const String &args)` — sets ADC reference (`1.2`/`1v2` or `3.3`/`vdd`) and forwards to the MG24.
- `handleOsr(const String &args)` — sets oversampling ratio (2/4/8) and forwards to the MG24.
- `handleGain(const String &args)` — sets analog gain (1-4) and forwards to the MG24.
- `handleGround(const String &args)` — sets ground channel or toggles ground insertion and forwards to the MG24.
- `handleRun(const String &args)` — validates `PZT_RS` routing/sizing if combined mode is active, sends `run`/`run <ms>` to the MG24, waits for the first block (DRDY or fallback poll), ACKs the host, then runs the DRDY-driven streaming loop (servicing RS refresh, SPI RX, and USB TX each iteration) until stop is requested/timed out/faulted; logs a stream summary (DRDY vs. fallback block/ACK counts, RX errors) when the run ends.
- `requestStop()` — requests the run loop to begin stopping on its next iteration.
- `isRunning()` — returns whether a PZT/PZT_RS run is active.
- `printStatus()` — prints logical/physical channel lists, PZT_RS routing details (via `pzt_rs_controller::printStatusDetails`), and PZT config/timing to the host.

### PztRsController.h / PztRsController.cpp

Namespace `pzt_rs_controller`. Implements the PCB1.7-only combined `PZT_RS` mode: sensor-to-MUX/RS-channel routing, a round-robin RS refresh state machine that shares the 555 timer/ISR infrastructure with `PzrController` to measure each configured RS channel's resistance, per-channel held values (median-filtered) for "hold last value" output, and the routine that repacks a raw PZT block plus held RS values into the combined 7-values-per-sensor wire format.

- `resetRouting()` / `setSensorCount(uint8_t count)` — clear or (re)size the sensor-to-mux/RS routing tables (max `kMaxSensorSlots`=6 sensors).
- `sensorCount()`, `sensorMuxCount()`, `rsChannelCount()`, `rsRefreshChannelCount()`, `rsRefreshChannel(uint8_t index)` — routing/config accessors.
- `routingReady()` — true once sensor count, MUX assignments, RS channel assignments, and refresh channel list are all consistent.
- `handlePztMuxes(const String &args)` — parses one MUX side (1 or 2) per sensor (`pztmuxes mux1,mux2...*`).
- `handleRsChannels(const String &args)` — parses one RS1,RS2 channel pair per sensor (`rschannels rs1,rs2...*`) and builds the deduplicated RS refresh channel list.
- `outputSamplesPerBlock(uint8_t repeat_count, uint8_t sweeps_per_block)` — computes combined-mode sample count per block (`sensors * repeat * sweeps * 7`).
- `resetState()` — reseeds per-channel held values from `PzrController`'s last plot Ra, resets refresh diagnostics, and restarts the refresh state machine.
- `stopRefresh()` — idles the refresh state machine (used when a run stops).
- `serviceRefresh(bool allow_channel_switch = true)` — advances the refresh state machine by consuming one ready 555 high/low pulse pair if available (discard cycles after a MUX switch, then median-filtered measurement update).
- `snapshotHeldValues(uint16_t *dst, uint8_t count = 16)` — copies the current quantized (scaled-ohms) held value per channel under interrupt protection.
- `buildCombinedBlock(...)` — given a raw PZT block, a snapshot of held RS values, and the logical/physical channel mappings, repacks the block into `[PZT_CH1..PZT_CH5,RS1_hold,RS2_hold]` groups per sensor per repeat per sweep; returns false if inputs are inconsistent or the result would exceed `kMaxBlockBytes`.
- `printStatusDetails()` — prints sensor count, MUX/RS routing tables, and refresh diagnostics (updates, mux switches, timeouts, broken channels).
- `printRefreshDiagnostics(uint8_t ch, const __FlashStringHelper *prefix = nullptr)` / `printStreamDiagnostics()` — print per-channel or full-stream RS refresh timing/health diagnostics.
- `noteIsrFire()`, `activeChannel()`, `noteRise(uint8_t ch)`, `noteFall(uint8_t ch)`, `notePairReady(uint8_t ch, uint32_t high_cycles, uint32_t low_cycles)` — hooks called from `PzrController`'s 555 edge ISR to attribute edges/pairs to the RS channel currently selected by the refresh state machine.

### PzrController.h / PzrController.cpp

Namespace `pzr_controller`. PZR/555-timer resistance acquisition, shared between standalone `PZR` mode and the RS refresh loop used by `PZT_RS` mode (both 555 sources read through the same ISR and MUX-select helpers; `board_config::kDefault555Mode` picks which physical 555/MUX pair is "active" for direct PZR sampling). Captures high/low half-period cycle counts via DWT cycle counting, supports a "modeled" low-cycle source (computed from `Rb`/`Cf`) as an alternative to the measured low-cycle moving average, and applies a 3-sample median filter to Ra before reporting.

- `begin()` — configures PZR/RS MUX and ICP GPIOs, attaches the 555 edge ISR, computes the modeled low-cycle estimate, resets channel state, and parks/disables the MUX.
- `isr555()` — edge-triggered ISR: tracks rise/fall cycle timestamps, detects out-of-sequence edges (`captureSequenceErrors`), computes high/low cycle counts on each pair, and forwards edge/pair-ready notifications to `pzt_rs_controller` for the currently active RS channel.
- `handleChannels(const String &args)` — parses a channel sequence (0-15, max 64) for standalone PZR streaming and resets channel averages.
- `handleRepeat(const String &args)` / `handleBuffer(const String &args)` — set samples-per-channel (1-256) / sweeps-per-block (1-256).
- `handleRun(const String &args)` — starts continuous or timed PZR acquisition (sets `g_running`).
- `handleStop()` — stops PZR acquisition.
- `handleRb(const String &args)` / `handleRk(const String &args)` / `handleCf(const String &args)` / `handleRxMax(const String &args)` — set Rb, Rk, Cf, and Rx-max respectively (value-suffix parsed); Rb/Cf changes also refresh the modeled low-cycle estimate and reset channel averages.
- `handleAscii(const String &args)` — toggles ASCII vs. binary PZR block output; mode changes stop any active run.
- `doOneBlock()` — captures one full PZR block (sweeps x channels x repeats) and emits it as ASCII CSV or a binary block.
- `printStatus()` — prints PZR config, modeled/measured low-cycle diagnostics, per-channel timing, and sizing info.
- `isRunning()` / `timedRunExpired()` — run-state queries; the latter also stops a timed run once its deadline passes.
- `asciiOutput()` — returns whether ASCII output mode is active (used by `Pcb17Firmware` to decide whether to suppress host ACKs).
- `captureSequenceErrors()` — returns the ISR-detected out-of-sequence edge count.
- `resetCaptureDiagnostics()` — clears the sequence-error counter.
- `resetAllChannels()` — resets all per-channel Ra state and the low-cycle moving-average smoothers.
- `muxDisableAll()` — disables both the PZR and RS 555 MUX enable lines.
- `muxEnable(bool en)` — enables/disables the currently active 555 MUX (per `board_config::kDefault555Mode`).
- `muxSelect(uint8_t ch)` — selects a MUX channel (0-15) on the active 555 MUX, with settle delay, and resets capture state.
- `parkMux(uint8_t ch = 15)` — convenience wrapper around `muxSelect` for idling the MUX.
- `computePairTimeoutMs()` — computes a capture timeout from `Rb`, `Rk`, `Cf`, and `RxMax` (clamped 50-5000 ms).
- `takeReadyPair(uint32_t &h_cycles, uint32_t &l_cycles)` — atomically consumes the latest ready high/low cycle pair, if any (used by `PztRsController`'s refresh state machine).
- `updateChannelRaFromPair(uint8_t ch, uint32_t h_cycles, uint32_t l_cycles, float &out_ra)` — converts a high/low cycle pair into an Ra estimate for the given channel (moving average + median-3 filter), updating that channel's held state.
- `lastPlotRa(uint8_t ch)` — returns the last filtered Ra value for a channel (NAN if none yet).
- `cyclesToUs(uint32_t cycles)` / `cyclesFloatToUs(double cycles)` — convert DWT cycle counts to microseconds using `F_CPU_ACTUAL`.
- `printChannelTimingDiagnostics(uint8_t ch, const __FlashStringHelper *prefix = nullptr)` — prints detailed per-channel timing/Ra diagnostics (raw cycles, modeled vs. measured low-cycle estimates, computed Ra).
