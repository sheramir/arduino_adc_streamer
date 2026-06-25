# ADC_Streamer_binary_scan (MG24)

Main MG24 (XIAO MG24 / EFR32MG24) standalone ADC acquisition sketch used by the GUI for normal capture. It runs the on-chip IADC in scan mode over a configurable channel sequence, buffers multiple sweeps into blocks, and streams them as binary frames over USB serial using the shared command protocol (see the top-level `Arduino_Sketches/README.md`). Identifies itself to the host as `# MG24` in response to `mcu*`. This is the current, recommended sketch for plain MG24 ADC capture (no external MUX).

## Files

### ADC_Streamer_binary_scan.ino

High-speed IADC binary sweeper with blocked output for the XIAO MG24. Implements the full shared serial command set (`channels`, `ground`, `repeat`, `buffer`, `ref`, `osr`, `gain`, `run`, `stop`, `status`, `mcu`, `help`) plus MG24-specific ADC reference/oversampling/gain tuning and an optional dummy-ground read before each new channel. Captures are taken via the IADC hardware scan table (not single-conversion polling), then sent as `[0xAA][0x55][count][samples...][avg_dt_us][block_start_us][block_end_us]` binary blocks matching the shared binary block format.

Functions:
- `allocateAnalogBusForPin(PinName pinName)` — allocates the correct GPIO analog bus (A/B/C/D, even/odd) for a pin used by the IADC.
- `toLowerTrim(const String &s)` — returns a trimmed, lowercased copy of a string.
- `splitCommand(const String &line, String &cmd, String &args)` — splits a serial command line into command keyword and argument string.
- `doDummyRead()` — short delay used as a settle/no-op placeholder after config changes.
- `sendCommandAck(bool ok, const String &args)` — sends `#OK`/`#NOT_OK` (with optional args) acknowledgment for a processed command.
- `calcScanEntryCount(uint16_t rep)` — computes how many IADC scan-table entries one sweep needs, including ground entries.
- `recomputeDerivedConfig()` — recalculates `samplesPerSweep`, `scanEntriesPerSweep`, and `sweepsPerBlock` from current channel/repeat/ground settings; validates against the hardware scan-table limit.
- `sendSweepHeader(uint16_t totalSamples)` — writes the `0xAA 0x55 countL countH` binary block header.
- `sendBlock(uint16_t sampleCount, uint32_t blockStartUs, uint32_t blockEndUs)` — writes a full binary block (header, sample payload, avg `dt_us`, start/end timestamps) to serial.
- `initIADC_ScanMultiChannel()` — configures and initializes the IADC hardware scan table from current channels/repeat/ground/ref/osr/gain settings.
- `discardWarmupSweeps(uint16_t warmupSweeps)` — runs and discards a number of full sweeps after `run*` to let the ADC/reference settle.
- `doOneBlock()` — captures one full block (multiple sweeps) via the IADC scan table and sends it as a binary block.
- `handleChannels(const String &args)` — parses and validates the `channels` command's comma-separated pin list.
- `handleGround(const String &args)` — parses the `ground` command (pin number, or `true`/`false` to enable/disable dummy ground reads).
- `handleRepeat(const String &args)` — parses and clamps the `repeat` (samples-per-channel) command.
- `handleBuffer(const String &args)` — parses the `buffer` (sweeps-per-block) command.
- `handleRef(const String &args)` — parses the `ref` command (`1.2`, `3.3`/`vdd`); `0.8vdd`/`ext` are not supported in this sketch.
- `handleOsr(const String &args)` — parses the `osr` command (`2`, `4`, `8` — high-speed oversampling).
- `handleGain(const String &args)` — parses the `gain` command (`1`-`4`x analog gain).
- `handleRun(const String &args)` — starts continuous or timed (`run <ms>`) streaming; validates config and runs warm-up sweeps.
- `handleStop()` — stops streaming (`stop`).
- `printMcu()` — prints `# MG24` for host/GUI device identification.
- `printStatus()` — prints current configuration and run state (`status`).
- `printHelp()` — prints the list of supported commands (`help`).
- `handleLine(const String &lineRaw)` — dispatches a complete `*`-terminated command line to the matching handler and sends the ack.
- `setup()` — initializes serial at 460800 baud and the derived configuration.
- `loop()` — reads serial input into commands, manages timed-run stop, and triggers block capture/streaming while running.
