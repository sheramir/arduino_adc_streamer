# Teensy PCB1.7 Library-Backed Sketch

Main sketch:

- `Teensy.ino` — the Arduino-required folder-matching primary sketch and a
  2-function wrapper: `setup()` calls `pcb17_firmware::setupFirmware()` and
  `loop()` calls `pcb17_firmware::loopFirmware()`. All actual setup/loop logic
  lives in `src/Pcb17Firmware.cpp`.

Board config:

- `BoardConfig.h` records the PCB1.7 pinout and 555 defaults: PZT SPI CS/DRDY pins (`kPztCsPin`=10, `kPztDrdyPin`=0) and bitrate, separate PZR and RS 555-timer ICP/MUX pin sets (both with MUX-enable pins, unlike PCB1.5 where PZR has no enable pin), `kDefault555Mode` (default `TIMER555_RS`), and derived `kTimer555*` constants plus `initTimer555Pins()`. Values match `PCB1.5_with_Libraries/Teensy/BoardConfig.h` except PZR/RS now both have MUX-enable pins (7 and 8) since PZR and RS MUXes must be independently disabled/enabled when switching to/from `PZT_RS` mode.

Firmware libraries (see `src/README.md` for full API details):

- `src/Pcb17Firmware.h`
- `src/Pcb17Firmware.cpp`
- `src/SharedProtocol.h`
- `src/SharedProtocol.cpp`
- `src/SerialLineParser.h`
- `src/SerialLineParser.cpp`
- `src/SpiMasterLink.h`
- `src/SpiMasterLink.cpp`
- `src/PztController.h`
- `src/PztController.cpp`
- `src/PztRsController.h`
- `src/PztRsController.cpp`
- `src/PzrController.h`
- `src/PzrController.cpp`

The `src/` name is required for recursive sketch-local compilation in current
Arduino IDE/CLI releases. The old `libraries/` layout exposed the headers but
did not reliably compile or link the `.cpp` implementations.

`Pcb17Firmware.cpp` is intentionally thin. It owns serial command dispatch,
mode switching, setup, and loop orchestration. The hardware-specific behavior is
split into sketch-local libraries:

- `SharedProtocol` owns shared ACKs, binary block framing, and value parsing.
- `SerialLineParser` owns `*`-terminated serial command collection.
- `SpiMasterLink` owns the Teensy-to-MG24 SPI/DRDY transport.
- `PztController` owns MG24/PZT configuration and streaming.
- `PztRsController` owns `PZT_RS` sensor routing, RS refresh, held values, and
  combined block repacking.
- `PzrController` owns the 555 timer MUX, resistance calculation, and PZR
  binary/ASCII streaming.

This keeps the PCB1.7 DRDY streaming path and combined `PZT_RS` behavior intact
while isolating replaceable hardware details such as the ADC SPI protocol.

## Supported Serial Modes

- `mode PZT*`
- `mode PZR*`
- `mode PZT_RS*`

`PZT_RS` adds:

- `pztmuxes mux1,mux2...*`
- `rschannels rs1,rs2...*`
- Seven output values per selected sensor:
  `[PZT_CH1,PZT_CH2,PZT_CH3,PZT_CH4,PZT_CH5,RS1_hold,RS2_hold]`

The RS hold values use `PZT_RS_WIRE_UNITS_PER_OHM = 100`, so host-side code
divides those two values by `100.0` to recover ohms.

## Wiring Notes

- MG24 DRDY: Teensy pin `0`
- SPI CS: Teensy pin `10`
- PZR 555 MUX enable: Teensy pin `7`
- RS 555 MUX enable: Teensy pin `8`
- Default 555 source: `RS/555_A`
