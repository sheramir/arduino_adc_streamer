# PCB1.7_with_libraries

Library-backed PCB1.7 firmware pair for the Teensy + MG24 array reader.

This folder mirrors the `PCB1.5_with_Libraries` packaging style while using the
active `PCB1.7_SPI` firmware behavior, including the Teensy `PZT_RS` combined
mode.

## Layout

- `Teensy/` - Teensy master sketch plus split firmware libraries for protocol,
  serial parsing, SPI transport, PZT streaming, PZR streaming, and `PZT_RS`
  combined routing. See `Teensy/README.md` and `Teensy/libraries/README.md`.
- `MG24/` - Modular MG24 SPI slave sketch plus reusable MG24 libraries. See
  `MG24/README.md` and `MG24/libraries/README.md`.

## Flash Together

Use the matching pair from this folder:

- Teensy: `Teensy/Teensy_SPI_Master_Array_PZT_PZR1.7_DRDY_Modular.ino`
- MG24: `MG24/MG24_Dual_MUX_SPI_Slave1.7_DRDY_Modular.ino`

Do not mix this Teensy sketch with an MG24 sketch from another PCB folder.

## Protocol Notes

- Device ID: `# Array_PZT_PZR1.7`
- Supported modes: `PZT`, `PZR`, and `PZT_RS`
- `PZT_RS` payload per selected sensor:
  `[PZT_CH1,PZT_CH2,PZT_CH3,PZT_CH4,PZT_CH5,RS1_hold,RS2_hold]`
- `RS1_hold` and `RS2_hold` are encoded with
  `PZT_RS_WIRE_UNITS_PER_OHM = 100`.

No existing sketches in other folders were modified.
