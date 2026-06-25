# Teensy555_streamer

Teensy 4.0 sketch that measures unknown resistance/displacement via a 555-astable timing circuit and streams the results to the host using the shared MG24-style serial command protocol and binary block framing. It responds `# Teensy555` to `mcu*` and is used with the desktop GUI's `555` mode (see the top-level `Arduino_Sketches/README.md` sketch map). Status: active variant for 555/displacement-based resistance measurement, paired with an ADG706-style MUX for multi-channel capture.

## Files

### Teensy555_streamer.ino

Captures high/low pulse-width pairs from a 555 astable oscillator via an input-capture interrupt (`isr555`) timed with the Teensy's DWT cycle counter, derives the discharge resistance and then the unknown resistor `Rx` for the currently MUX-selected channel, and streams the resulting `Rx` values (in ohms, rounded and clamped to `uint16`) inside the standard `[0xAA][0x55]` binary block format. The serial command parser reuses the shared MG24/Teensy text-protocol style (`*`-terminated commands, `#OK`/`#NOT_OK` acknowledgments) and adds sketch-specific 555-model parameter commands.

- `dwtInit()` — enables the ARM DWT cycle counter used for high-resolution pulse timing.
- `dwtNow()` — returns the current DWT cycle count.
- `isr555()` — input-capture interrupt handler; records high/low pulse durations from the 555 output and flags when a fresh high/low pair is ready.
- `resetCaptureState()` — clears the shared capture state (`cap0`) under interrupt protection.
- `computePairTimeoutMs()` — computes a safe per-sample wait timeout from the configured 555 component values and `Rx_max`.
- `waitForPair(hCyc, lCyc, timeout_ms)` — blocks (while staying responsive to incoming serial bytes) until a fresh high/low cycle pair is captured or the timeout elapses.
- `updateMA(buf, sum, idx, count, N, newVal)` — generic ring-buffer moving-average update helper.
- `resetAllChannels()` — resets the per-channel moving-average state for all 16 possible channels.
- `muxEnable(en)` — drives the MUX enable pin (if configured), honoring active-low/active-high polarity.
- `muxSelect(ch)` — sets the MUX address pins for the given channel, settles, re-enables the MUX, and resets capture state.
- `measureOneRx(ch, switched, outRx)` — performs one 555-based resistance measurement on the given channel (optionally switching/settling the MUX first), updates the per-channel `Rdis`/`Rx` moving averages, and returns the smoothed `Rx` value.
- `sendCommandAck(ok, args)` — writes the `#OK`/`#NOT_OK` (optionally with echoed args) command acknowledgment.
- `splitCommand(line, cmdOut, argsOut)` — splits a raw input line into command and argument strings.
- `parseValueWithSuffix(inRaw, outVal, isCapUnits)` — parses a numeric value with engineering suffixes (`k`/`M` for ohms, `p`/`n`/`u`/`m` for farads) or scientific notation.
- `handleChannels(args)` — parses a CSV channel list (0-15, duplicates allowed) and resets per-channel state.
- `handleRepeat(args)` — sets the repeat-per-channel count (1-256).
- `handleBuffer(args)` — sets the sweeps-per-block count (1-256).
- `handleRun(args)` — starts continuous or timed streaming.
- `handleStop()` — stops streaming.
- `handleRb(args)` — sets the 555 discharge resistor `Rb` (ohms, with suffix support) and resets channel state.
- `handleRk(args)` — sets the known series resistor `Rk` (ohms, with suffix support) and resets channel state.
- `handleCf(args)` — sets the timing capacitor `Cf` (farads, with suffix support) and resets channel state.
- `handleRxMax(args)` — sets the maximum expected unknown resistance, used to bound the per-sample measurement timeout.
- `printMcu()` — prints the `# Teensy555` device-identification line.
- `printStatus()` — prints the current channel list, repeat/buffer counts, 555 model parameters, and running state.
- `printHelp()` — prints the full command list, including the 555-specific parameter commands.
- `write_u16_le(v)` — writes a little-endian `uint16` to serial.
- `write_u32_le(v)` — writes a little-endian `uint32` to serial.
- `doOneBlock()` — captures one full binary block of `Rx` measurements across the configured channel sequence and sends it in the standard framed binary format.
- `handleLine(lineRaw)` — top-level command dispatcher; parses one `*`-terminated line and routes it to the matching handler.
- `setup()` — configures pins, starts serial, attaches the 555 interrupt, initializes the DWT counter, and announces the device via `printMcu()`.
- `loop()` — reads and dispatches serial commands, handles timed-run expiry, and drives one capture block per iteration while running.

## Sketch-Specific Notes

In addition to the shared command set, this sketch implements 555-model parameter commands (all terminated by `*`):

- `rb <ohms|k|M>*` — set the discharge resistor `Rb` (e.g. `rb 470*`, `rb 1k*`).
- `rk <ohms|k|M>*` — set the known series resistor `Rk` (e.g. `rk 10*`).
- `cf <F|p|n|u|m>*` — set the timing capacitance `Cf` (e.g. `cf 2.2n*`, `cf 0.0022u*`).
- `rxmax <ohms|k|M>*` — set the maximum expected unknown resistance, used to size measurement timeouts (e.g. `rxmax 50k*`).

`channels`, `repeat`, `buffer`, `run`, `stop`, `status`, `mcu`, and `help` follow the shared protocol style, but this sketch's `channels` accepts pin indices `0-15` only (MUX-addressed channels, not direct Teensy analog pins). The shared commands `ref`, `osr`, `gain`, `ground`, and `speed` are accepted and acknowledged with `#OK` but otherwise ignored, since they do not apply to the 555 timing measurement path. Each `uint16` sample in the binary block payload is an `Rx` resistance value in ohms (rounded and clamped to `0..65535`), not a raw ADC reading.
