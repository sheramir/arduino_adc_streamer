# ADC_Streamer_binary_buffer

Legacy/archived MG24 ADC sweeper that adds the `buffer <n>` command and multi-sweep blocked binary output, plus an `avg_dt_us` timing trailer — closer to the modern blocked-output format, but still single-channel-set MG24-only (no MUX/array support, no `mcu*`, no `gain`/`osr`). This sketch is **not** part of the current default GUI workflow — it is kept for reference only. The top-level `Arduino_Sketches/README.md` describes this folder as a "pre-scan blocked-output MG24 variant," which is accurate: it is the direct predecessor of the current `MG24/ADC_Streamer_binary_scan/` sketch's blocked binary format.

## Divergence From The Modern Shared Protocol

- **No `mcu*` command.** There is no MCU identification response; the modern protocol's `mcu*` -> `# MG24` handshake is absent here.
- **No `gain` or `osr` commands.** ADC configuration is via `ref` (sketch-specific reference names) and `res <bits>` (raw resolution in bits) rather than the modern `gain`/`osr` abstraction.
- **Trailer differs from the current binary block format.** This sketch's block trailer is only a single `uint16` `avg_dt_us` field after the sample payload — it does **not** include the `block_start_us`/`block_end_us` `uint32` fields that the modern format (documented in the top-level README's "Binary Block Format" section) appends after `avg_dt_us`. Host code written for the modern trailer format will misparse blocks from this legacy sketch.
- Otherwise this sketch already matches the modern protocol closely: `*`-terminated commands, `#OK`/`#NOT_OK` acknowledgments, `channels`/`ground`/`repeat`/`buffer`/`run`/`stop`/`status`/`help` commands, and the `[0xAA][0x55][countL][countH]` binary magic header with little-endian `uint16` samples.

## Files

### ADC_Streamer_binary_buffer.ino

Interactive `*`-terminated ADC sweeper for the XIAO MG24 that accumulates `buffer <n>` sweeps into a single RAM buffer and sends them as one binary block (header + samples + 2-byte `avg_dt_us` trailer) at 460800 baud. Commands configure channels, repeat count, buffer size, ground dummy reads, and ADC reference/resolution.

- `toLowerTrim(s)` — returns a trimmed, lowercased copy of a string.
- `splitCommand(line, cmd, args)` — splits an input line into a command keyword and its argument string.
- `chooseDummyPin()` — picks a pin (ground pin, first channel, or fallback 0) to use for ADC settling reads.
- `doDummyRead()` — performs one throwaway `analogRead()` on the chosen dummy pin after a ref/resolution change.
- `sendCommandAck(ok, args)` — sends `#OK`/`#NOT_OK` (optionally with echoed args), flushes Serial, and adds a small settling delay.
- `recomputeDerivedConfig()` — recalculates `samplesPerSweep`, the effective ground pin, and clamps `sweepsPerBlock` to fit the sample buffer.
- `sendSweepHeader(totalSamples)` — writes the 4-byte `[0xAA][0x55][countL][countH]` binary header.
- `sendBlock(sampleCount, blockEndMicros)` — sends the accumulated block (header + raw samples + 2-byte average per-sample time in µs) and resets block timing state.
- `handleChannels(args)` — parses the channel list into `channelSequence` and recomputes derived config; returns success/failure.
- `handleGround(args)` — sets the ground pin or enables/disables ground dummy reads; returns success/failure.
- `handleRepeat(args)` — sets `repeatCount` (capped at `MAX_REPEAT_COUNT`); returns success/failure.
- `handleBuffer(args)` — sets `sweepsPerBlock` (sweeps accumulated per block) and resets the in-progress block; returns success/failure.
- `handleRef(args)` — sets the ADC reference and triggers a settling read; returns success/failure.
- `handleRes(args)` — sets the ADC resolution in bits and triggers a settling read; returns success/failure.
- `handleRun(args)` — starts continuous or timed sweeping, resetting the in-progress block; requires channels to be configured first; returns success/failure.
- `handleStop()` — stops sweeping and clears timed-run state.
- `doOneBlock()` — captures `sweepsPerBlock` sweeps (channels x repeats each) into `adcBuffer`, times the capture, and sends the resulting block.
- `printStatus()` — prints the current configuration as `#`-prefixed lines, including buffer/block state.
- `printHelp()` — prints a `#`-prefixed command reference.
- `handleLine(lineRaw)` — trims an input line, splits it into command/args, dispatches to the matching handler, and sends the final ack.
- `setup()` — initializes Serial at 460800 baud, sets default ADC resolution/reference, performs an initial settling read, and computes derived config.
- `loop()` — parses `*`-terminated commands from the serial buffer, checks for timed-run expiry between blocks, and runs one full block capture per iteration while `isRunning` is true.
