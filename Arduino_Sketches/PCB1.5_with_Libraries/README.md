# PCB1.5_with_Libraries

This folder contains a modular split of the PCB1.5 firmware into reusable libraries and main sketches, for the Teensy + MG24 array reader (PZT and PZR/555 modes; no combined `PZT_RS` mode — that is PCB1.7-only, see `PCB1.7_with_libraries/`).

## Layout

- `Teensy/` - Modular Teensy master sketch + reusable libraries. See `Teensy/README.md` and `Teensy/libraries/README.md`.
- `MG24/` - Modular MG24 sketch + reusable libraries. See `MG24/README.md` and `MG24/libraries/README.md`.

## Flash Together

Use the matching pair from this folder:

- Teensy: `Teensy/Teensy_SPI_Master_Array_PZT_PZR1.5_DRDY_Modular.ino`
- MG24: `MG24/MG24_Dual_MUX_SPI_Slave1.5_DRDY_Modular.ino`

Do not mix this Teensy sketch with an MG24 sketch from another PCB folder.

## Protocol Notes

- Device ID: `# Array_PZT_PZR1`
- Supported modes: `PZT` and `PZR` (set with `mode PZT|PZR*`)

No existing sketches in other folders were modified.
