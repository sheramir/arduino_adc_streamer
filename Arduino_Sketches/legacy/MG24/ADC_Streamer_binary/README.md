# ADC_Streamer_binary

Legacy/archived MG24 ADC sweeper that introduces the `*`-terminated command framing and `#OK`/`#NOT_OK` acknowledgments used by the modern shared protocol, but still sends one binary packet per sweep rather than accumulating multiple sweeps into a multi-sweep block. This sketch is **not** part of the current default GUI workflow — it is kept for reference only. The top-level `Arduino_Sketches/README.md` describes this folder as representing an "older single-sweep binary/CSV-era host flow," which matches: it is the transitional step between the pure-CSV `ADC_Streamer XIAO MG24` sketch and the blocked-output `ADC_Streamer_binary_buffer` sketch.

## Divergence From The Modern Shared Protocol

- **No `buffer` command and no multi-sweep blocks.** Every sweep is sent immediately as its own binary packet (`[0xAA][0x55][countL][countH]` + `count` x `uint16` samples); there is no concept of accumulating `buffer N` sweeps into one block, and no `avg_dt_us` or `block_start_us`/`block_end_us` trailer fields.
- **No `mcu*`, `gain`, or `osr` commands.** The command set is `channels`, `ground`, `repeat`, `ref`, `res`, `run`, `stop`, `status`, `help` — there is no MCU identification command and no gain/oversampling control.
- **`res` instead of (or alongside) `osr`/`gain`.** ADC resolution is set directly in bits via `res <bits>`, not through an oversampling or gain abstraction.
- **`ref` values are sketch-specific** (`1.2`, `3.3`/`vdd`, `0.8vdd`, `ext`) rather than a generic reference voltage.
- It does match the modern protocol on: `*`-terminated commands, `#OK`/`#NOT_OK` acknowledgments (with optional echoed args), and the `0xAA 0x55` binary magic header with little-endian `uint16` sample count + payload.

## Files

### ADC_Streamer_binary.ino

Interactive `*`-terminated ADC sweeper for the XIAO MG24 that sends each completed sweep as a single binary packet (no CSV) at 460800 baud. Commands configure the channel sequence, repeat count, optional ground dummy reads, and ADC reference/resolution; `run`/`run <ms>` start sweeping and each sweep is sent as `[0xAA][0x55][countL][countH]` followed by raw `uint16` sample bytes.

- `toLowerTrim(s)` — returns a trimmed, lowercased copy of a string.
- `splitCommand(line, cmd, args)` — splits an input line into a command keyword and its argument string.
- `chooseDummyPin()` — picks a pin (ground pin, first channel, or fallback 0) to use for ADC settling reads.
- `doDummyRead()` — performs one throwaway `analogRead()` on the chosen dummy pin after a ref/resolution change.
- `sendCommandAck(ok, args)` — sends `#OK`/`#NOT_OK` (optionally with echoed args), flushes Serial, and adds a small settling delay.
- `recomputeDerivedConfig()` — recalculates `samplesPerSweep` and the effective ground pin whenever configuration changes.
- `sendSweepHeader(totalSamples)` — writes the 4-byte `[0xAA][0x55][countL][countH]` binary header.
- `handleChannels(args)` — parses the channel list into `channelSequence` and recomputes derived config; returns success/failure.
- `handleGround(args)` — sets the ground pin or enables/disables ground dummy reads; returns success/failure.
- `handleRepeat(args)` — sets `repeatCount` (capped at `MAX_REPEAT_COUNT`); returns success/failure.
- `handleRef(args)` — sets the ADC reference and triggers a settling read; returns success/failure.
- `handleRes(args)` — sets the ADC resolution in bits and triggers a settling read; returns success/failure.
- `printStatus()` — prints the current configuration as `#`-prefixed lines.
- `printHelp()` — prints a `#`-prefixed command reference.
- `handleRun(args)` — starts continuous or timed sweeping; requires channels to be configured first; returns success/failure.
- `handleStop()` — stops sweeping and clears timed-run state.
- `doOneSweep()` — captures one sweep into `adcBuffer` and sends it as a single binary packet (header + raw sample bytes, no trailer).
- `handleLine(lineRaw)` — trims an input line, splits it into command/args, dispatches to the matching handler, and sends the final ack.
- `setup()` — initializes Serial at 460800 baud, sets default ADC resolution/reference, performs an initial settling read, and computes derived config.
- `loop()` — parses `*`-terminated commands from the serial buffer and runs one sweep per iteration while `isRunning` is true.
