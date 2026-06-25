# Legacy / Archived Sketches

This folder contains archived `.ino` sketches that are no longer part of the default GUI workflow described in the top-level `Arduino_Sketches/README.md`. They are kept for reference or hardware-specific work; prefer the sketches in the current sketch map (`MG24/`, `Teensy/`, `PCB1.0_SPI/`, `PCB1.5_SPI/`, `PCB1.7_SPI/`, `PCB1.7_with_libraries/`) when pairing firmware with the main GUI.

## Subfolders

- [`MG24/`](MG24/README.md): three archived MG24-only ADC sweeper variants (`ADC_Streamer XIAO MG24/`, `ADC_Streamer_binary/`, `ADC_Streamer_binary_buffer/`), representing successive stages toward the current binary-block protocol — from plain-text CSV streaming to single-sweep binary packets to blocked binary output.
- [`Teensy_MG24_SPI/`](Teensy_MG24_SPI/README.md): an archived Teensy SPI master sketch (`Teensy_SPI_Master_Array_PZT1.ino`) that predates the documented PCB1.0/1.5/1.7 Teensy+MG24 array pairs — it uses a custom no-DRDY SPI command/ACK/block transport and has no surviving matching MG24 slave sketch in this folder.

See each subfolder's README for sketch-by-sketch detail, including where each one's command set or framing diverges from the modern shared serial protocol.
