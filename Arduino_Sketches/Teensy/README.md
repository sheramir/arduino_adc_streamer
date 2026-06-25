# Teensy

This folder contains the Teensy-only ADC and 555-resistance streamer variants used by the desktop ADC Streamer GUI. Both sketches share the same `*`-terminated serial command style and binary block framing as the MG24 sketches (see the top-level `Arduino_Sketches/README.md`).

## Subfolders

- [ADC_Streamer_binary_scan2/](ADC_Streamer_binary_scan2/README.md) — main Teensy ADC acquisition path used by the GUI, responds `# TEENSY40` to `mcu*`.
- [Teensy555_streamer/](Teensy555_streamer/README.md) — 555-based resistance/displacement timing sketch used with the GUI `555` mode, responds `# Teensy555` to `mcu*`.
