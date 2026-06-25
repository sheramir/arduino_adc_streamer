# ADC_Streamer_binary_scan2

Teensy 4.x sketch that implements the main Teensy ADC acquisition path used by the desktop GUI, mirroring the MG24 sketch's serial command names and binary block format. It responds `# TEENSY40` to `mcu*` and is the recommended sketch for normal Teensy ADC capture (see the top-level `Arduino_Sketches/README.md` sketch map). Status: active, primary Teensy ADC streamer.

## Files

### ADC_Streamer_binary_scan2.ino

Implements the shared host command set (`channels`, `ground`, `repeat`, `buffer`, `ref`, `osr`, `gain`, `run`, `stop`, `status`, `mcu`, `help`) on top of the Teensy `ADC` library, configuring the on-chip ADC (12-bit resolution, hardware averaging, conversion/sampling speed) and streaming captured samples in the standard `[0xAA][0x55]` binary block format. Teensy 4.0 specifics: the ADC reference is always 3.3V/VDD (`ref 1.2` returns an error), `osr 2|4|8` maps directly to ADC hardware averaging, and `gain 1|2|3|4` is accepted only for API/status compatibility with the MG24 sketch (no analog gain exists on this hardware path).

- `toLowerTrim(s)` — returns a trimmed, lowercased copy of a string.
- `splitCommand(line, cmd, args)` — splits a raw input line into command and argument strings.
- `doDummyRead()` — short delay used after settings changes that need a settle period.
- `isValidAnalogPin(pin)` — validates that a pin number is a usable Teensy analog input.
- `sendCommandAck(ok, args)` — writes the `#OK`/`#NOT_OK` (optionally with echoed args) command acknowledgment.
- `calcScanEntryCount(rep)` — computes the logical per-sweep entry count, including optional ground reads, for the configured channel sequence and repeat count.
- `recomputeDerivedConfig()` — recalculates `samplesPerSweep`, `scanEntriesPerSweep`, and a buffer-capped `sweepsPerBlock` whenever channels/repeat/buffer change.
- `sendSweepHeader(totalSamples)` — writes the `0xAA 0x55` magic bytes and little-endian sample count.
- `sendBlock(sampleCount, blockStartUs, blockEndUs)` — writes the sample payload plus average sample interval and block start/end timestamps, completing one binary block.
- `applyADCConfig()` — applies resolution, averaging, conversion speed, sampling speed, and reference settings to the Teensy ADC.
- `readSingleSample(pin)` — reads one ADC sample from the given pin.
- `discardWarmupSweeps(warmupSweeps)` — runs a configurable number of throwaway sweeps after `run*` to let the ADC settle before real capture begins.
- `doOneBlock()` — captures one full block of sweeps (with optional ground reads between channels) into `adcBuffer` and sends it via `sendBlock()`.
- `handleChannels(args)` — parses and validates a CSV channel/pin list, configures pin modes, and recomputes derived config.
- `handleGround(args)` — sets the ground pin or toggles ground-before-each-channel behavior.
- `handleRepeat(args)` — sets the samples-per-channel count per sweep (capped at `MAX_REPEAT_COUNT`).
- `handleBuffer(args)` — sets the sweeps-per-block count.
- `handleRef(args)` — sets the ADC reference; rejects `1.2`/`1v2` as unsupported on Teensy 4.0.
- `handleOsr(args)` — sets oversampling/hardware-averaging to 2, 4, or 8.
- `handleGain(args)` — sets the API-compatibility gain value (1-4); no hardware effect.
- `handleRun(args)` — validates that channels are configured, starts continuous or timed streaming, and runs ADC warm-up sweeps.
- `handleStop()` — stops streaming.
- `printMcu()` — prints the `# TEENSY40` device-identification line.
- `printStatus()` — prints running state, channel sequence, repeat count, ground configuration, reference, osr, gain, and derived sweep/block sizing.
- `printHelp()` — prints the full command list and Teensy 4.0-specific compatibility notes.
- `handleLine(lineRaw)` — top-level command dispatcher; parses one `*`-terminated line and routes it to the matching handler.
- `setup()` — starts serial at 460800 baud, computes derived config, and applies the initial ADC configuration.
- `loop()` — reads and dispatches serial commands, handles timed-run expiry, and drives one capture block per iteration while running.

This sketch follows the shared serial protocol exactly as documented in the top-level README — no sketch-specific commands beyond the shared set.
