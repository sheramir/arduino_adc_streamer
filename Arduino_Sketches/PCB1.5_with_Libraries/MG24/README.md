# MG24 Modular Sketch

Main sketch:

- `MG24_Dual_MUX_SPI_Slave1.5_DRDY_Modular.ino`

Board config:

- `BoardConfig.h` (single source of ADC and SPI transport pinout/settings)

Libraries:

- `libraries/Mg24SharedProtocol.*`
- `libraries/Mg24AdcMux.*`
- `libraries/Mg24CommandEngine.*`
- `libraries/Mg24SpiSlaveTransport.*`

Current transport behavior in this modular sketch matches the original MG24
PCB1.5 SPI slave protocol:

- 20-byte command frames
- 4-byte ACK responses
- Binary streaming block format `[AA 55][count][payload][trailer]`
- DRDY asserted when a response is armed

## Reuse Strategy

When reusing these libraries in a new MG24 sketch:

1. Put all board-specific pins and SPIDRV init values in a local board config
     header (same pattern as `BoardConfig.h`).
2. Build `mg24_adc_mux::Pins` and `mg24_spi_slave::Config` from that header.
3. Keep one persistent runtime per library.
4. Initialize in this order:
     - `mg24_adc_mux::begin`
     - `mg24_cmd::begin`
     - `mg24_spi_slave::begin`
5. Call `mg24_spi_slave::service` in `loop()` continuously.

## Library API Details

### mg24_proto (Mg24SharedProtocol)

Role:

- Protocol constants and frame encoders shared across MG24 modules.

Constants:

- Frame sizing: `kCmdFrameLen`, `kAckFrameLen`, `kBlockTrailerLen`
- Throughput limits: `kMaxPairs`, `kMaxResponseBytes`
- Command IDs: `kCmdSetChannels`, `kCmdSetRepeat`, `kCmdSetBuffer`,
    `kCmdSetRef`, `kCmdSetOsr`, `kCmdSetGain`, `kCmdRun`, `kCmdStop`,
    `kCmdMcuId`, `kCmdGroundPin`, `kCmdGroundEn`, `kCmdContinue`
- Markers/status: `kBlockMagic1`, `kBlockMagic2`, `kAckMagic`, `kAckOk`, `kAckErr`

Methods:

- `makeAck(uint8_t *out_ack, uint8_t status, uint8_t b2, uint8_t b3)`
  - Creates 4-byte ACK response.
- `encodeBlock(...)`
  - Encodes interleaved ADC samples and trailer fields into response buffer.

### mg24_adc_mux

Role:

- Controls mux switching, ADC capture, and stream run-state.

Key structs:

- `Pins`
  - `adc_mux1`, `adc_mux2`: analog inputs for mux outputs
  - `mux_a0..mux_a3`: mux address pins
- `Config`
  - `channels[16]`, `channel_count`
  - `repeat_count`, `sweeps_per_block`
  - `ref`, `osr`, `gain`
  - `ground_pin`, `ground_enable`
  - run-state flags/timers
- `Runtime`
  - `pins`, `cfg`
  - `sample_buf`, timing fields, ADC state flags

Methods:

- `begin(Runtime &rt, const Pins &pins)`
- Config setters:
  - `setChannels`, `setRepeat`, `setBuffer`
  - `setReference`, `setOsr`, `setGain`
  - `setGroundPin`, `setGroundEnabled`
- Streaming control:
  - `startRun(Runtime &rt, const uint8_t *args, uint8_t nargs)`
  - `fillInterleavedBlock(Runtime &rt)`
  - `streamExpired(Runtime &rt)`
  - `stopRun(Runtime &rt)`
  - `isStreaming(const Runtime &rt)`
  - `blockResponseBytes(const Runtime &rt)`

Parameter notes:

- `args`/`nargs` in `startRun` carry optional runtime fields from command frame.
- `fillInterleavedBlock` returns sample count in interleaved MUX1/MUX2 order.

### mg24_cmd

Role:

- Command-frame interpreter that applies config/run actions and produces
    ACK/block responses.

Key structs:

- `Response`
  - `type`: `RESP_ACK` or `RESP_BLOCK`
  - `len`: valid byte count in response buffer
- `Runtime`
  - pointer to bound `mg24_adc_mux::Runtime`

Methods:

- `begin(Runtime &rt, mg24_adc_mux::Runtime &adc)`
- `processFrame(Runtime &rt, const uint8_t *cmd_frame, uint8_t *resp_buf, uint32_t resp_cap)`
  - Handles full command frame and fills `resp_buf`
- `continueStreaming(Runtime &rt, uint8_t control_byte, uint8_t *resp_buf, uint32_t resp_cap)`
  - Handles stream continuation or STOP control during response phase
- `isStreaming(const Runtime &rt)`
- `canPrefetchStreaming(const Runtime &rt)`
- `prepareStreamingBlock(Runtime &rt, uint8_t *resp_buf, uint32_t resp_cap)`

### mg24_spi_slave

Role:

- SPIDRV transport state machine for command RX, response TX, DRDY signaling,
    and prefetch-aware streaming response arming.

Key structs:

- `Config`
  - `cs_pin`: GPIO used for CS edge detection
  - `drdy_pin`: GPIO driven for DRDY
  - `callback_timeout_ms`: transfer-complete wait timeout
  - `init_data`: full `SPIDRV_Init_t` transport configuration
- `Runtime`
  - `config`, transfer state flags, rx/tx buffers, streaming prefetch fields

Methods:

- `begin(Runtime &rt, const Config &config)`
  - Initializes GPIO, SPIDRV, and command-armed state
- `service(Runtime &rt, mg24_cmd::Runtime &cmd)`
  - Poll in `loop()`; handles completed transfer, next response arming,
        and streaming prefetch flow

## Minimal Reuse Example

```cpp
#include "BoardConfig.h"
#include "libraries/Mg24AdcMux.h"
#include "libraries/Mg24CommandEngine.h"
#include "libraries/Mg24SpiSlaveTransport.h"

static mg24_adc_mux::Runtime adc;
static mg24_cmd::Runtime cmd;
static mg24_spi_slave::Runtime spi;

void setup() {
    const mg24_adc_mux::Pins adc_pins = board_config::makeAdcMuxPins();
    const mg24_spi_slave::Config spi_cfg = board_config::makeSpiSlaveConfig();

    mg24_adc_mux::begin(adc, adc_pins);
    mg24_cmd::begin(cmd, adc);
    mg24_spi_slave::begin(spi, spi_cfg);
}

void loop() {
    mg24_spi_slave::service(spi, cmd);
}
```
