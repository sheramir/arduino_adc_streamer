# Teensy Libraries

Sketch-local libraries used by the PCB1.5 modular Teensy master sketch. They implement the Teensy side of the Teensy/MG24 SPI array protocol: host-facing serial command framing, the SPI master link to the MG24 ADC slave, blocking PZT acquisition orchestration, and PZR/555 resistance-timing acquisition. PZT_RS combined mode does not exist in this PCB1.5 library set (see `PCB1.7_with_libraries/Teensy/libraries/` for that).

## Files

### SharedProtocol.h / SharedProtocol.cpp

Namespace `shared_proto`. Host-facing protocol constants (baud rate, command terminator, binary block magic bytes) plus helpers for writing ACK/NOT_OK responses, parsing numeric values with engineering-unit suffixes, and assembling the shared binary block format.

- `writeHostAck(bool ok, const String &args, bool suppress)` — prints `#OK [args]` or `#NOT_OK [args]` to the host (or nothing if `suppress` is true), then flushes.
- `parseValueSuffix(const String &in_raw, double &out_val, bool is_cap_units)` — parses values like `470`, `10k`, `220n`, `1uF`; `is_cap_units=true` enables farad-style p/n/u/m suffixes, otherwise k/M ohm-style suffixes are used.
- `encodeBinaryBlock(uint8_t *dst, uint32_t dst_cap, const uint16_t *samples, uint16_t sample_count, uint16_t avg_dt_us, uint32_t block_start_us, uint32_t block_end_us)` — encodes `[0xAA 0x55][count][samples...][avg_dt_us][block_start_us][block_end_us]`; returns 0 if `dst_cap` is insufficient.

### SerialLineParser.h / SerialLineParser.cpp

Streaming serial command tokenizer with a configurable terminator character, plus a free function for splitting a line into command/argument tokens.

- `SerialLineParser::begin(char term, uint16_t max_line_len)` — sets the terminator and per-line length cap, clears any pending line.
- `SerialLineParser::feed(char c, String &out_line)` — feeds one character; ignores `\r`/`\n`; returns true (with `out_line` set) only once a full terminator-delimited line has accumulated; resets the buffer if `max_line_len` is exceeded.
- `SerialLineParser::clear()` — discards any partially accumulated line.
- `splitCommand(const String &line, String &out_cmd, String &out_args)` — splits on the first space; lowercases and trims the command token.

### SpiMasterLink.h / SpiMasterLink.cpp

Low-level SPI master transport for Teensy-to-MG24 transactions; wraps `SPIClass` with fixed settings (4 MHz default, MSB-first, mode 1) and CS handling.

- `begin(SPIClass &spi_ref, uint8_t cs, uint32_t bitrate, uint32_t setup_us)` — configures the CS pin and SPI settings.
- `transfer(const uint8_t *tx, uint8_t *rx, uint32_t len)` — full-duplex byte-by-byte transfer with CS asserted for the whole transaction.
- `transferLeadByte(uint8_t lead, uint8_t *rx, uint32_t len)` — like `transfer`, but sends `lead` as the first byte and zero-fills the rest (used to send a streaming control byte while clocking out a response).
- `send(const uint8_t *tx, uint32_t len)` — write-only transfer (discards RX).
- `recv(uint8_t *rx, uint32_t len)` — read-only transfer (sends zero bytes).

### PztController.h / PztController.cpp

Namespace `pzt_controller`. Owns PZT-mode command handling and a single blocking SPI streaming loop that runs the whole acquisition (`run`/`run <ms>`) until stopped, polling for a host `stop*` command and writing each received binary block straight to the USB serial port.

- `begin(Runtime &rt, SpiMasterLink &link)` — binds the controller to a SPI link.
- `handleChannels(Runtime &rt, const String &args)` — parses a comma/space-separated channel list (0-15, max 16) and forwards it to the MG24 over SPI.
- `handleRepeat(Runtime &rt, const String &args)` — sets samples-per-channel (1-100) and forwards to the MG24.
- `handleBuffer(Runtime &rt, const String &args)` — sets sweeps-per-block (1-255) and forwards to the MG24.
- `handleRef(Runtime &rt, const String &args)` — sets ADC reference (`1.2`/`1v2` or `3.3`/`vdd`) and forwards to the MG24.
- `handleOsr(Runtime &rt, const String &args)` — sets oversampling ratio (2/4/8) and forwards to the MG24.
- `handleGain(Runtime &rt, const String &args)` — sets analog gain (1-4) and forwards to the MG24.
- `handleGround(Runtime &rt, const String &args)` — sets ground channel (0-15) or toggles ground insertion (`true`/`false`) and forwards to the MG24.
- `printStatus(const Runtime &rt)` — prints current PZT config and estimated timing to the host.
- `runBlocking(Runtime &rt, const String &args, char cmd_term)` — sends `run`/`run <ms>` to the MG24, waits for warmup+first block, ACKs the host, then loops writing each subsequent block to Serial while polling for a host stop request or a timed-run deadline, finally exchanging a STOP/ACK handshake with the MG24; returns false on any protocol fault.
- `requestStop(Runtime &rt)` — clears the `running` flag so `runBlocking`'s loop exits on its next check.

### PzrController.h / PzrController.cpp

Namespace `pzr_controller`. PZR/555-timer resistance acquisition: an ISR captures 555 astable high/low half-period lengths via DWT cycle counting on the configured ICP pin, channel state tracks a moving average and last computed Ra, and the controller exposes channel/repeat/buffer config plus binary or ASCII block output. Supports two physical 555 sources (`SOURCE_PZR`, `SOURCE_RS`) distinguished by `Pins::source_index`.

- `begin(Runtime &rt, const Pins &pins)` — validates pins, configures MUX/ICP GPIOs, attaches the 555 edge ISR, resets channel state, and parks the MUX.
- `parkMux(Runtime &rt, uint8_t ch = 15)` — selects an idle MUX channel.
- `handleChannels(Runtime &rt, const String &args)` — parses a comma-separated channel sequence (0-15, max 64 entries) and resets channel averages.
- `handleRepeat(Runtime &rt, const String &args)` — sets samples-per-channel (1-256).
- `handleBuffer(Runtime &rt, const String &args)` — sets sweeps-per-block (1-256).
- `handleRun(Runtime &rt, const String &args)` — starts continuous or timed (`run <ms>`) acquisition.
- `handleStop(Runtime &rt)` — stops acquisition.
- `handleRb(Runtime &rt, const String &args)` — sets the Rb resistor value (ohms, supports k/M suffixes) and resets channel averages.
- `handleRk(Runtime &rt, const String &args)` — sets the known series resistor Rk (kept for timeout calculation only).
- `handleCf(Runtime &rt, const String &args)` — sets the timing capacitor value (farads, supports p/n/u/m suffixes) and resets channel averages.
- `handleRxMax(Runtime &rt, const String &args)` — sets the maximum expected Rx, used only to size capture timeouts.
- `handleAscii(Runtime &rt, const String &args)` — toggles ASCII vs. binary block output; switching modes stops any active run.
- `printStatus(const Runtime &rt)` — prints PZR config, timing diagnostics, and sample/block sizing to the host.
- `doOneBlock(Runtime &rt)` — captures one full block (sweeps x channels x repeats) of Ra measurements and emits it as ASCII CSV lines or a binary block, depending on `ascii_output`.
