# Teensy Modular Sketch

Main sketch:

- `Teensy_SPI_Master_Array_PZT_PZR1.5_DRDY_Modular.ino`

Board config:

- `BoardConfig.h` (single source of board wiring and mode defaults)

Libraries:

- `libraries/SharedProtocol.*`
- `libraries/SerialLineParser.*`
- `libraries/SpiMasterLink.*`
- `libraries/PztController.*`
- `libraries/PzrController.*`

This sketch is a modularized Teensy implementation for PCB1.5 where reusable
logic is in libraries and board-specific pinout/defaults live in `BoardConfig.h`.

## Reuse Strategy

1. Create a board config header with pins, SPI settings, and per-mode defaults.
2. Keep protocol constants and frame format from `SharedProtocol` when host compatibility is required.
3. Instantiate one runtime per library and keep it for sketch lifetime.
4. Initialize `SpiMasterLink` before `pzt_controller::begin`.
5. Build `pzr_controller::Pins` from board config and call `pzr_controller::begin` once in `setup()`.

## Library API Details

### SharedProtocol

Role:

- Host-side framing helpers shared across modes.
- Value parsing with engineering suffixes.
- Binary block assembly with shared header/trailer format.

Constants:

- `kSerialBaud`, `kCmdTerm`, `kMaxCmdLen`
- `kBlockMagic1`, `kBlockMagic2`, `kAckMagic`

Methods:

- `writeHostAck(bool ok, const String &args, bool suppress)`
- `parseValueSuffix(const String &in_raw, double &out_val, bool is_cap_units)`
- `encodeBinaryBlock(...)`

Parameter notes:

- `writeHostAck`: `ok` selects `#OK`/`#NOT_OK`; `args` echoes optional command arguments; `suppress` disables output.
- `parseValueSuffix`: supports values like `470`, `10k`, `220n`, `1uF`; use `is_cap_units=true` for capacitance.
- `encodeBinaryBlock`: emits `[AA 55][count][payload][avg_dt,start_us,end_us]`.

### SerialLineParser

Role:

- Streaming serial command tokenizer with custom terminator.

Methods:

- `begin(char term, uint16_t max_line_len)`
- `feed(char c, String &out_line)`
- `clear()`
- `splitCommand(const String &line, String &out_cmd, String &out_args)`

Parameter notes:

- `term` is usually `*`.
- `max_line_len` is a safety cap for malformed or noisy streams.
- `feed` returns `true` only when a full line has been completed.

### SpiMasterLink

Role:

- Low-level SPI master transport for Teensy-to-MG24 transactions.

Methods:

- `begin(SPIClass &spi_ref, uint8_t cs, uint32_t bitrate, uint32_t setup_us)`
- `transfer(const uint8_t *tx, uint8_t *rx, uint32_t len)`
- `transferLeadByte(uint8_t lead, uint8_t *rx, uint32_t len)`
- `send(const uint8_t *tx, uint32_t len)`
- `recv(uint8_t *rx, uint32_t len)`

Parameter notes:

- `cs` is chip select pin.
- `bitrate` is SPI clock in Hz.
- `setup_us` is CS setup delay before first byte.
- `transferLeadByte` is used by streaming mode where a control byte precedes payload clocks.

### pzt_controller

Role:

- PZT mode command handling and streaming orchestration over SPI.
- Tracks mode-specific config and run state.

Config fields (`pzt_controller::Config`):

- `channels[16]`, `channel_count`
- `repeat_count`, `sweeps_per_block`
- `osr`, `gain`, `ref`
- `ground_pin`, `ground_enabled`, `running`

Runtime fields (`pzt_controller::Runtime`):

- `link` (attached `SpiMasterLink`)
- `cfg` (active config)
- `max_pairs`, `ack_magic`, `ack_ok`

Methods:

- `begin(Runtime &rt, SpiMasterLink &link)`
- `handleChannels(Runtime &rt, const String &args)`
- `handleRepeat(Runtime &rt, const String &args)`
- `handleBuffer(Runtime &rt, const String &args)`
- `handleRef(Runtime &rt, const String &args)`
- `handleOsr(Runtime &rt, const String &args)`
- `handleGain(Runtime &rt, const String &args)`
- `handleGround(Runtime &rt, const String &args)`
- `printStatus(const Runtime &rt)`
- `runBlocking(Runtime &rt, const String &args, char cmd_term)`
- `requestStop(Runtime &rt)`

Parameter notes:

- `args` follows host command payload format for each command.
- `runBlocking`: `args` may contain run duration in ms; `cmd_term` is used for stop polling.

### pzr_controller

Role:

- PZR/555 mode acquisition, per-channel integration output, and command handlers.
- Maintains ISR-driven capture state and per-channel runtime config.

Enums:

- `SourceIndex`: `SOURCE_PZR`, `SOURCE_RS`

Pins fields (`pzr_controller::Pins`):

- `icp_pin`, `mux_a0`, `mux_a1`, `mux_a2`, `mux_a3`, optional `mux_en`
- `mux_en_active_low`, `source_index`, `source_name`

Config fields (`pzr_controller::Config`):

- Electrical/tuning: `rb_ohm`, `rk_ohm`, `cf_f`, `rx_max_ohm`
- Output mode: `ascii_output`
- Scan: `channel_sequence`, `channel_count`, `repeat_count`, `buffer_sweeps`
- Run control: `running`, `timed_run`, `run_stop_ms`

Methods:

- `begin(Runtime &rt, const Pins &pins)`
- `parkMux(Runtime &rt, uint8_t ch = 15)`
- `handleChannels(Runtime &rt, const String &args)`
- `handleRepeat(Runtime &rt, const String &args)`
- `handleBuffer(Runtime &rt, const String &args)`
- `handleRun(Runtime &rt, const String &args)`
- `handleStop(Runtime &rt)`
- `handleRb(Runtime &rt, const String &args)`
- `handleRk(Runtime &rt, const String &args)`
- `handleCf(Runtime &rt, const String &args)`
- `handleRxMax(Runtime &rt, const String &args)`
- `handleAscii(Runtime &rt, const String &args)`
- `printStatus(const Runtime &rt)`
- `doOneBlock(Runtime &rt)`

## Minimal Reuse Example

```cpp
#include "BoardConfig.h"
#include "libraries/SpiMasterLink.h"
#include "libraries/PztController.h"
#include "libraries/PzrController.h"

static SpiMasterLink spi_link;
static pzt_controller::Runtime pzt;
static pzr_controller::Runtime pzr;

void setup() {
    spi_link.begin(SPI, board_config::kPztCsPin, board_config::kPztSpiBitrate, board_config::kPztCsSetupUs);
    pzt_controller::begin(pzt, spi_link);

    board_config::initTimer555Pins();
    pzr_controller::Pins pins = board_config::makePzrPins();
    pzr.cfg.cf_f = board_config::kTimer555DefaultCfF;
    pzr_controller::begin(pzr, pins);
}
```
