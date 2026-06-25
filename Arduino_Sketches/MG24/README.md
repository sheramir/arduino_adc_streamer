# MG24

Parent folder for standalone MG24 (XIAO MG24 / EFR32MG24) ADC streamer sketches that the desktop GUI talks to directly over USB serial (no Teensy/SPI pairing). Both subfolders implement the shared serial command protocol and binary block format described in `Arduino_Sketches/README.md`.

## Subfolders

- [`ADC_Streamer_binary_scan/`](ADC_Streamer_binary_scan/README.md) — main MG24 ADC acquisition path used by the GUI; samples MG24 pins directly via the IADC hardware scan table. Identifies as `# MG24`.
- [`ADC_Streamer_binary_scan_with_ADG1206_mux/`](ADC_Streamer_binary_scan_with_ADG1206_mux/README.md) — MG24 capture through an external ADG1206 16:1 MUX with optional charge-amp reset control; `channels` addresses MUX channels instead of MCU pins. Identifies as `# MG24_MUX`.

See the top-level `Arduino_Sketches/README.md` sketch map for when to flash each variant.
