# ADC_Streamer XIAO MG24

Legacy/archived interactive CSV sweeper for the XIAO MG24 (or similar MG24-based board). It is the oldest of the three archived MG24 variants and predates the binary block protocol entirely: it accepts newline-terminated text commands (no `*` terminator) at 115200 baud and streams human-readable CSV lines, one line per sweep, while running. This sketch is **not** part of the current default GUI workflow — it is kept only for reference / manual bring-up work. See the top-level `Arduino_Sketches/README.md` "Legacy And Experimental Sketches" section, which describes this folder as an "older interactive CSV sweeper variant."

## Divergence From The Modern Shared Protocol

This sketch differs from the shared serial protocol documented in the top-level README in several important ways:

- **No `*` command terminator.** Commands are plain text lines terminated by `\n` (CR is ignored), not the `*`-terminated framing used by the modern sketches.
- **No `#OK` / `#NOT_OK` acknowledgments.** Errors are reported as `# ERROR: ...` lines; there is no structured success/failure acknowledgment at all.
- **CSV text output, not binary blocks.** While running, each sweep is emitted as a single comma-separated ASCII line (`v0,v1,...,v(N-1)`) followed by a newline — there is no `0xAA 0x55` binary framing, no `avg_dt_us`, and no block timestamps.
- **No `buffer` command.** Output is always one sweep per line; sweeps are never accumulated into multi-sweep blocks.
- **No `mcu`, `status` response format compatibility, or `gain`.** The sketch supports `status` and `help`, but their output is plain `#`-prefixed text for human reading, not a machine-parsed handshake. There is no `mcu*` identification command at all, and no `gain` or `osr` command.
- **Extra `res` and `delay` commands** not present in the modern protocol: `res <bits>` sets ADC resolution, and `delay <us>` sets an inter-sample delay within a sweep.
- **`ref` values are sketch-specific** (`1.2`, `3.3`/`vdd`, `0.8vdd`, `ext`), matching MG24 `analog_references` rather than a generic voltage value.

## Files

### ADC_Streamer XIAO MG24.ino

Interactive, line-oriented ADC sweeper for the XIAO MG24. The host configures a channel sequence, repeat count, optional ground-pin dummy read, and ADC reference/resolution via simple text commands, then issues `run` (continuous) or `run <ms>` (timed) to start sweeping; each sweep is printed as one CSV line until `stop` is received.

- `toLowerTrim(s)` — returns a trimmed, lowercased copy of a string.
- `splitCommand(line, cmd, args)` — splits an input line into a command keyword and its argument string.
- `chooseDummyPin()` — picks a pin (ground pin, first channel, or fallback 0) to use for ADC settling reads.
- `doDummyRead()` — performs one throwaway `analogRead()` on the chosen dummy pin after a ref/resolution change.
- `handleChannels(args)` — parses a comma/space-separated channel list into `channelSequence`.
- `handleDelay(args)` — sets `interSampleDelayUs`, the inter-sample delay within a sweep.
- `handleGround(args)` — sets the ground pin or enables/disables ground dummy reads.
- `handleRepeat(args)` — sets `repeatCount`, the number of samples taken per channel per sweep.
- `handleRef(args)` — sets the ADC reference (`1.2`, `3.3`/`vdd`, `0.8vdd`, `ext`) and triggers a settling read.
- `handleRes(args)` — sets the ADC resolution in bits (8-16) and triggers a settling read.
- `printStatus()` — prints the current configuration as `#`-prefixed lines.
- `printHelp()` — prints a `#`-prefixed command reference.
- `handleRun(args)` — starts continuous or timed sweeping; requires channels to be configured first.
- `handleStop()` — stops sweeping and clears timed-run state.
- `doOneSweep()` — runs one sweep across all configured channels/repeats and prints the result as one CSV line.
- `handleLine(lineRaw)` — trims an input line, splits it into command/args, and dispatches to the matching handler.
- `setup()` — initializes Serial at 115200 baud, sets default ADC resolution/reference, and performs an initial settling read.
- `loop()` — reads serial input a character at a time into line buffers and dispatches complete lines; runs one sweep per iteration while `isRunning` is true.
