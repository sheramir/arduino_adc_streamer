# MG24 Libraries

Sketch-local libraries used by the PCB1.7 modular MG24 SPI-slave sketch. They implement the MG24 side of the Teensy/MG24 SPI array protocol: protocol framing constants, dual-channel ADC/MUX acquisition, command interpretation, and the SPIDRV transport state machine (command RX, response TX, DRDY signaling, and prefetch-aware streaming).

These files are identical to `PCB1.5_with_Libraries/MG24/libraries/` with one exception: `Mg24AdcMux.cpp` uses `kMuxSettleUs = 20` (vs. `3` on PCB1.5) for the analog MUX settle delay before each ADC read.

## Files

### Mg24SharedProtocol.h / Mg24SharedProtocol.cpp

Namespace `mg24_proto`. Protocol constants (command frame/ACK/trailer sizes, command IDs, block/ACK magic bytes) and the low-level frame encoders shared by the command engine and SPI transport.

- `makeAck(uint8_t *out_ack, uint8_t status, uint8_t b2, uint8_t b3)` — fills a 4-byte ACK frame (`kAckMagic`, status, two free bytes).
- `encodeBlock(uint8_t *dst, uint32_t dst_cap, const uint16_t *samples, uint16_t sample_count, uint16_t avg_dt_us, uint32_t block_start_us, uint32_t block_end_us)` — encodes a binary streaming block (`[0xAA 0x55][count][samples...][avg_dt_us][block_start_us][block_end_us]`); returns total bytes written or 0 if `dst_cap` is too small.

### Mg24AdcMux.h / Mg24AdcMux.cpp

Namespace `mg24_adc_mux`. Owns the dual-input IADC0 scan (mux1/mux2 simultaneously sampled), the 4-bit analog MUX channel selection, ground-channel insertion, warmup sweeps, and run-state/timing bookkeeping for one streaming block.

- `begin(Runtime &rt, const Pins &pins)` — validates pins, configures MUX address GPIOs as outputs, parks the MUX on the ground channel.
- `setChannels(Runtime &rt, const uint8_t *channels, uint8_t count)` — sets the channel scan sequence (max 16); returns false on invalid input.
- `setRepeat(Runtime &rt, uint8_t repeat_count)` — sets samples-per-channel-per-sweep (clamped to `kMaxRepeat`=100).
- `setBuffer(Runtime &rt, uint8_t sweeps_per_block)` — sets sweeps-per-block (clamped to fit `kMaxPairs`).
- `setReference(Runtime &rt, uint8_t ref)` — selects `0`=1.2V internal or `1`=VDD/3.3V reference; marks config dirty for IADC re-init.
- `setOsr(Runtime &rt, uint8_t osr)` — selects oversampling ratio (2/4/8x); marks config dirty.
- `setGain(Runtime &rt, uint8_t gain)` — selects analog gain (1-4x); marks config dirty.
- `setGroundPin(Runtime &rt, uint8_t ground_pin)` — sets the dummy ground channel (0-15) and enables ground insertion.
- `setGroundEnabled(Runtime &rt, bool enabled)` — toggles ground-channel insertion without changing the configured pin.
- `startRun(Runtime &rt, const uint8_t *args, uint8_t nargs)` — (re)initializes the IADC if config is dirty, optionally arms a timed run from a 4-byte little-endian `run_ms` argument, runs warmup sweeps, and sets `running=true`.
- `fillInterleavedBlock(Runtime &rt)` — captures one full block (sweeps x channels x repeats) into `rt.sample_buf` as interleaved `[mux1,mux2]` pairs; records timing and average per-sample interval; returns the sample count.
- `streamExpired(Runtime &rt)` — checks/applies a timed-run deadline, stopping the run and returning true if expired.
- `stopRun(Runtime &rt)` — clears running/timed-run state and parks the MUX on ground.
- `isStreaming(const Runtime &rt)` — true if running, IADC ready, and at least one channel configured.
- `blockResponseBytes(const Runtime &rt)` — computes the expected response size (ACK header + samples + trailer) for the current config.

### Mg24CommandEngine.h / Mg24CommandEngine.cpp

Namespace `mg24_cmd`. Interprets 20-byte command frames against an `mg24_adc_mux::Runtime`, producing either a 4-byte ACK or a binary streaming block response.

- `begin(Runtime &rt, mg24_adc_mux::Runtime &adc)` — binds the command engine to an ADC/MUX runtime.
- `processFrame(Runtime &rt, const uint8_t *cmd_frame, uint8_t *resp_buf, uint32_t resp_cap)` — dispatches a command frame (set channels/repeat/buffer/ref/osr/gain/ground, run, stop, mcu id) and fills `resp_buf` with the resulting ACK or block.
- `continueStreaming(Runtime &rt, uint8_t control_byte, uint8_t *resp_buf, uint32_t resp_cap)` — handles the per-transfer control byte during an active stream (continue vs. stop), producing the next block or final ACK.
- `isStreaming(const Runtime &rt)` — proxies `mg24_adc_mux::isStreaming`.
- `canPrefetchStreaming(const Runtime &rt)` — true if streaming and not past a timed-run deadline, used to decide whether the transport may prefetch the next block.
- `prepareStreamingBlock(Runtime &rt, uint8_t *resp_buf, uint32_t resp_cap)` — captures and encodes the next block directly (used for prefetch).

### Mg24SpiSlaveTransport.h / Mg24SpiSlaveTransport.cpp

Namespace `mg24_spi_slave`. SPIDRV-based slave transport state machine: arms command/response transfers, drives the DRDY GPIO when a response is ready, detects CS rising edges via interrupt, and prefetches the next streaming block into a second buffer while the current one is being clocked out by the host.

- `begin(Runtime &rt, const Config &config)` — validates the config, sets up DRDY/CS GPIOs and the CS-rising interrupt, initializes SPIDRV, and arms the first command transfer.
- `service(Runtime &rt, mg24_cmd::Runtime &cmd)` — call continuously from `loop()`; opportunistically prefetches the next streaming block, then on each completed transfer (signalled by CS rising) processes the received command/control byte, arms the next response, and asserts/deasserts DRDY accordingly.
