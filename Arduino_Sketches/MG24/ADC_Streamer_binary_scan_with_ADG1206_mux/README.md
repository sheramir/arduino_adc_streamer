# ADC_Streamer_binary_scan_with_ADG1206_mux (MG24)

MG24 (XIAO MG24) ADC acquisition sketch that adds an external ADG1206 16:1 analog MUX in front of the IADC, with optional charge-amp reset control while switching MUX channels. It uses the same shared serial command protocol and binary block format as the standard MG24 streamer, but the `channels` command addresses ADG1206 MUX channels (0-15) instead of MG24 analog pins directly, and capture is done via single IADC conversions (not scan-table mode) so the firmware can drive the MUX address lines between reads. Identifies itself to the host as `# MG24_MUX`. Use this variant when the hardware includes the external ADG1206 MUX path.

## Files

### ADC_Streamer_binary_scan_with_ADG1206_mux.ino

High-speed IADC binary sweeper with blocked output and ADG1206 MUX support. Implements the shared command set (`channels`, `ground`, `repeat`, `buffer`, `ref`, `osr`, `gain`, `run`, `stop`, `status`, `mcu`, `help`); `channels`/`ground` values are MUX channel numbers (0-15) rather than MCU pins. Adds MUX address-line driving (`PIN_MUX_A0..A3`), optional MUX enable line, and an optional charge-amp reset pulse (`PIN_RESET`) before switching to a new MUX address (v1.1 change). Captures one ADC sample at a time via `IADC_initSingle`, looping over the per-sweep entry list and switching the MUX as needed.

Functions:
- `allocateAnalogBusForPin(PinName pinName)` — allocates the correct GPIO analog bus for the MUX COM/ADC input pin.
- `muxEnable(bool en)` — drives the MUX enable pin, if used.
- `resetChargeAmp(bool reset)` — drives the charge-amp reset line, if used.
- `muxInitPins()` — configures MUX address/enable/reset pins as outputs and sets safe startup levels (MUX disabled, charge amp held in reset).
- `muxSelect(uint8_t ch)` — disconnects the current MUX channel, optionally resets the charge amp, sets the new address lines (only changed bits), re-enables the MUX, and waits for settle time.
- `iadcReadOnce12()` — triggers and waits for one single 12-bit IADC conversion, returning the result.
- `toLowerTrim(const String &s)` — returns a trimmed, lowercased copy of a string.
- `splitCommand(const String &line, String &cmd, String &args)` — splits a serial command line into command keyword and argument string.
- `doDummyRead()` — short delay used as a settle/no-op placeholder after config changes.
- `sendCommandAck(bool ok, const String &args)` — sends `#OK`/`#NOT_OK` (with optional args) acknowledgment for a processed command.
- `calcScanEntryCount(uint16_t rep)` — computes how many scan entries one sweep needs, including ground entries.
- `recomputeDerivedConfig()` — recalculates `samplesPerSweep`, `scanEntriesPerSweep`, and `sweepsPerBlock` from current channel/repeat/ground settings; validates against the scan-entry limit.
- `sendSweepHeader(uint16_t totalSamples)` — writes the `0xAA 0x55 countL countH` binary block header.
- `sendBlock(uint16_t sampleCount, uint32_t blockStartUs, uint32_t blockEndUs)` — writes a full binary block (header, sample payload, avg `dt_us`, start/end timestamps) to serial.
- `initIADC_ScanMultiChannel()` — initializes MUX pins, maps the MUX COM pin to an IADC input, builds the per-sweep MUX-channel/ground entry list, and configures the IADC for single conversions.
- `discardWarmupSweeps(uint16_t warmupSweeps)` — runs and discards sweeps (switching MUX and sampling) after `run*` to let the path settle.
- `doOneBlock()` — captures one full block by looping sweeps/entries, switching the MUX per entry and sampling once per entry, then sends the binary block.
- `handleChannels(const String &args)` — parses and validates the `channels` command as ADG1206 MUX channel numbers (0-15).
- `handleGround(const String &args)` — parses the `ground` command (MUX channel number, or `true`/`false`).
- `handleRepeat(const String &args)` — parses and clamps the `repeat` (samples-per-channel) command.
- `handleBuffer(const String &args)` — parses the `buffer` (sweeps-per-block) command.
- `handleRef(const String &args)` — parses the `ref` command (`1.2`, `3.3`/`vdd`).
- `handleOsr(const String &args)` — parses the `osr` command (`2`, `4`, `8`).
- `handleGain(const String &args)` — parses the `gain` command (`1`-`4`x).
- `handleRun(const String &args)` — starts continuous or timed streaming; validates config and runs warm-up sweeps.
- `handleStop()` — stops streaming.
- `printMcu()` — prints `# MG24_MUX` for host/GUI device identification.
- `printStatus()` — prints current configuration, run state, and MUX settings (`status`).
- `printHelp()` — prints the list of supported commands.
- `handleLine(const String &lineRaw)` — dispatches a complete command line to the matching handler and sends the ack.
- `setup()` — initializes serial, MUX pins, and derived configuration.
- `loop()` — reads serial input into commands, manages timed-run stop, and triggers block capture/streaming while running.
