# Legacy MG24 Sketches

This folder holds three archived MG24-only ADC sweeper variants, kept for reference and superseded by `MG24/ADC_Streamer_binary_scan/` in the active sketch set. They represent successive stages on the way to the current binary-block protocol, from oldest/most divergent to closest to modern:

- [`ADC_Streamer XIAO MG24/`](ADC_Streamer%20XIAO%20MG24/README.md): older interactive CSV sweeper variant — plain-text commands (no `*` terminator), CSV text output, no binary framing.
- [`ADC_Streamer_binary/`](ADC_Streamer_binary/README.md): older single-sweep binary/CSV-era host flow — adds `*`-terminated commands and `#OK`/`#NOT_OK` acks, but sends one binary packet per sweep with no `buffer` support.
- [`ADC_Streamer_binary_buffer/`](ADC_Streamer_binary_buffer/README.md): pre-scan blocked-output MG24 variant — adds `buffer <n>` and multi-sweep blocked binary output with an `avg_dt_us` trailer, but predates the `mcu*`/`gain`/`osr` commands and the full `block_start_us`/`block_end_us` trailer fields used by the current MG24 sketches.

See each subfolder's README for the full command set and function list of its `.ino` file.
