# MG24 PCB1.7 Modular Sketch

Main sketch:

- `MG24.ino` — the Arduino-required folder-matching primary sketch. `setup()`
  starts Serial at `board_config::kSerialBaud`, builds `mg24_adc_mux::Pins` and
  `mg24_spi_slave::Config` from `BoardConfig.h`, then calls
  `mg24_adc_mux::begin`, `mg24_cmd::begin`, and `mg24_spi_slave::begin` in that
  order. `loop()` calls `mg24_spi_slave::service(g_spi, g_cmd)` continuously.

Board config:

- `BoardConfig.h` defines ADC MUX pins (`kAdcMux1Pin`, `kAdcMux2Pin`, `kMuxA0Pin`..`kMuxA3Pin`), SPI slave pins (`kSpiCsPin`, `kSpiDrdyPin`), serial baud, and SPIDRV setup; identical values to the PCB1.5 MG24 `BoardConfig.h`.

Libraries (see `src/README.md` for full API details):

- `src/Mg24SharedProtocol.*`
- `src/Mg24AdcMux.*`
- `src/Mg24CommandEngine.*`
- `src/Mg24SpiSlaveTransport.*`

The `src/` name is intentional: current Arduino builders recursively compile
sketch-local sources only from this directory.

This sketch follows the same modular MG24 split as `PCB1.5_with_Libraries`, with
the PCB1.7 MUX settle timing from `PCB1.7_SPI` (set in `Mg24AdcMux.cpp`):

- `kMuxSettleUs = 20` (vs. `3` on PCB1.5)

All four library files are otherwise byte-identical to their PCB1.5 counterparts.

## Transport Behavior

- 20-byte command frames
- 4-byte ACK responses
- Binary streaming block format `[AA 55][count][payload][trailer]`
- DRDY asserted when a response is armed

Flash this sketch with the matching Teensy sketch in
`../Teensy/Teensy.ino`.
