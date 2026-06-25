# Teensy_MG24_SPI (legacy)

Legacy/archived Teensy SPI master sketch (`Teensy_SPI_Master_Array_PZT1.ino`) that bridges the host's text serial protocol to an MG24 SPI slave over a custom binary SPI command/ACK/block framing, identifying itself to the host as `mcu*` -> `# Array_PZT1`. This is the **predecessor** of the Teensy+MG24 array pairs documented in the top-level `Arduino_Sketches/README.md` (e.g. `PCB1.0_SPI/`); it has no surviving matching MG24 slave sketch in this legacy folder (the MG24 counterpart, `MG24_Dual_MUX_SPI_Slave.ino`, lives only in the modern `PCB1.0_SPI/` folder). This sketch is **not** part of the current default GUI workflow and is kept for reference only — do not pair it with current MG24 slave firmware without checking command-code/frame-size compatibility first.

## Divergence From The Modern Shared Protocol

This sketch presents the same host-facing serial command vocabulary as the modern protocol (`channels`, `repeat`, `buffer`, `ref`, `osr`, `gain`, `ground`, `run`, `stop`, `status`, `mcu`, `help`, all `*`-terminated, with `#OK`/`#NOT_OK` acknowledgments), but the **Teensy-to-MG24 transport** underneath is unique to this sketch and not part of the documented shared protocol:

- Commands to the MG24 are sent as fixed 20-byte SPI frames (`CMD_FRAME_LEN = 20`) with sketch-local command codes (`CMD_SET_CHANNELS`, `CMD_SET_REPEAT`, `CMD_SET_BUFFER`, `CMD_SET_REF`, `CMD_SET_OSR`, `CMD_SET_GAIN`, `CMD_RUN`, `CMD_STOP`, `CMD_MCU_ID`, `CMD_GROUND_PIN`, `CMD_GROUND_EN`, `CMD_CONTINUE`), rather than ASCII text.
- There is no DRDY pin in this design — timing is estimated in software (`blockDelayMs()`, `warmupDelayMs()`) based on configured channel count, repeat count, buffer size, and OSR, and the Teensy simply delays before polling for the next block. This is a fundamentally different synchronization model from the DRDY-based PCB1.5/1.7 designs described in the top-level README.
- ACK frames from MG24 are 4 bytes (`ACK_FRAME_LEN`) with a distinct `0xAC` magic byte (`ACK_MAGIC`), separate from the `0xAA 0x55` block magic.
- Data blocks use the same `0xAA 0x55` magic and little-endian `uint16` sample count as the standard format, but the trailer is 10 bytes (`avg_dt_us` uint16 + `block_start_us` uint32 + `block_end_us` uint32) — this matches the modern top-level README's documented trailer layout.
- Each configured channel slot yields **two interleaved samples** per repeat (`[MUX1_val, MUX2_val]`), reflecting the dual-MUX MG24 slave design, not a single sample per channel.

## Files

### Teensy_SPI_Master_Array_PZT1.ino

Teensy 4.1 SPI master that bridges a Python/GUI host's text serial protocol (same command vocabulary as the README) to an MG24 dual-MUX SPI slave board, with no DRDY pin — timing is estimated from configured parameters and the Teensy polls the MG24 after computed delays. Identifies itself as `# Array_PZT1`.

- `spiTransferBytes(txBuf, rxBuf, len)` — performs one full-duplex SPI transaction (CS low, transfer bytes, CS high).
- `spiSendBytes(buf, len)` — sends bytes over SPI, discarding the response.
- `spiRecvBytes(buf, len)` — receives bytes over SPI, sending zero filler bytes.
- `spiRecvStreamingResponse(buf, len, controlByte, maxAttempts)` — reads a streaming block/ACK response, retrying until a valid magic byte (`ACK_MAGIC` or block magic) is seen or attempts are exhausted.
- `spiRecvAckResponse(buf, maxAttempts)` — reads a 4-byte ACK frame, retrying until `ACK_MAGIC` is seen or attempts are exhausted.
- `writeBlockToHostBuffered(buf, len)` — writes a block to the host Serial port in chunks sized to available write buffer space.
- `emitBlockToHost(buf, len)` — forwards a raw block to the host, or (if `DEBUG_TEXT_STREAM`) decodes and prints it as human-readable debug text.
- `discardPendingCommandTerminators(settleMs)` — drains any stray `*`/CR/LF bytes left in the serial RX buffer after a command completes.
- `sendCmd(cmd, args, nargs)` — builds and sends a fixed 20-byte SPI command frame.
- `usPerPair()` — estimates microseconds to capture one (MUX1, MUX2) sample pair at the current OSR setting.
- `blockDelayMs()` — estimates milliseconds to wait before reading one full data block, based on channel count, repeat count, buffer size, and per-pair timing.
- `warmupDelayMs()` — estimates milliseconds to wait for the MG24's fixed warmup sweep count before the first block.
- `blockResponseBytes()` — computes the total byte length of one data block response (ACK header + samples + trailer).
- `hostAck(ok, args)` — sends `#OK`/`#NOT_OK` (optionally with echoed args) to the host and flushes Serial.
- `sendCmdAndReadAck(cmd, args, nargs)` — sends a command frame, waits a fixed config-ack delay, reads the 4-byte ACK, and reports success/failure.
- `handleChannels(args)` — parses the channel list, sends it to MG24 as a `CMD_SET_CHANNELS` frame, and checks the ACK.
- `handleRepeat(args)` — sends the repeat count to MG24 via `CMD_SET_REPEAT` and checks the ACK.
- `handleBuffer(args)` — sends the sweeps-per-block count to MG24 via `CMD_SET_BUFFER` and checks the ACK.
- `handleRef(args)` — parses `1.2`/`3.3`/`vdd`, sends it to MG24 via `CMD_SET_REF`, and checks the ACK.
- `handleOsr(args)` — validates OSR (2/4/8), sends it to MG24 via `CMD_SET_OSR`, and checks the ACK.
- `handleGain(args)` — validates gain (1-4), sends it to MG24 via `CMD_SET_GAIN`, and checks the ACK.
- `handleGround(args)` — sets ground channel or enable/disable state, sends it to MG24 via `CMD_GROUND_PIN`/`CMD_GROUND_EN`, and checks the ACK.
- `handleRun(args)` — sends `CMD_RUN` to MG24, waits for warmup+first block, acks the host, then loops reading/forwarding subsequent blocks until `stop*`, duration expiry, or an MG24-reported error, finally sending `CMD_STOP` and reading the closing ACK.
- `handleStatus()` — prints the cached configuration (channels, repeat, buffer, ref, osr, gain, ground, estimated timing) as `#`-prefixed lines.
- `handleLine(rawLine)` — trims an input line, splits it into command/args, and dispatches to the matching handler (sending the host ack itself except for `run`, which acks internally).
- `setup()` — initializes Serial at 460800 baud and the Teensy's default SPI bus/CS pin.
- `loop()` — reads `*`-terminated commands from the serial buffer and dispatches complete lines via `handleLine()`.
