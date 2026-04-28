# Arduino Sketches

This folder contains the firmware variants used by the desktop ADC Streamer GUI. Most host-side workflows talk to these sketches over a shared serial command protocol and a compatible binary block format.

## Folder Layout

- `MG24/`: MG24 standalone ADC streamer variants
- `legacy/`: archived sketches that are no longer part of the default GUI workflow
- `Teensy/`: Teensy ADC and 555-resistance streamer variants
- `PCB1.0_SPI/`: Teensy+MG24 SPI array firmware for PCB v1.0
- `PCB1.5_SPI/`: Teensy+MG24 SPI array firmware for PCB v1.5 (DRDY-enabled path)

## Current Sketch Map

| Family | Sketch | Path | Typical use | `mcu*` response |
| --- | --- | --- | --- | --- |
| MG24 | Standard ADC streamer | `MG24/ADC_Streamer_binary_scan/ADC_Streamer_binary_scan.ino` | Main MG24 ADC acquisition path used by the GUI | `# MG24` |
| MG24 | ADC streamer with ADG1206 MUX | `MG24/ADC_Streamer_binary_scan_with_ADG1206_mux/ADC_Streamer_binary_scan_with_ADG1206_mux.ino` | MG24 capture with external MUX and optional charge-reset control | `# MG24_MUX` |
| Teensy | Standard ADC streamer | `Teensy/ADC_Streamer_binary_scan2/ADC_Streamer_binary_scan2.ino` | Main Teensy ADC acquisition path used by the GUI | `# TEENSY40` |
| Teensy | 555 resistance / displacement streamer | `Teensy/Teensy555_streamer/Teensy555_streamer.ino` | 555-based resistance timing measurements used with the GUI `555` mode | `# Teensy555` |
| Teensy + MG24 SPI (PCB1.0) | Mixed PZT/PZR array pair | `PCB1.0_SPI/Teensy_SPI_Master_Array_PZT_PZR1.ino` + `PCB1.0_SPI/MG24_Dual_MUX_SPI_Slave.ino` | Legacy board revision v1.0 | `# Array_PZT_PZR1` |
| Teensy + MG24 SPI (PCB1.5) | Mixed PZT/PZR array pair with DRDY | `PCB1.5_SPI/Teensy_SPI_Master_Array_PZT_PZR1.5_DRDY.ino` + `PCB1.5_SPI/MG24_Dual_MUX_SPI_Slave1.5_DRDY.ino` | Current board revision v1.5, DRDY-synchronized streaming | `# Array_PZT_PZR1` |

## Which Sketch Should You Flash

- Use `MG24/ADC_Streamer_binary_scan/` for normal MG24 ADC capture.
- Use `MG24/ADC_Streamer_binary_scan_with_ADG1206_mux/` when the hardware includes the external ADG1206 MUX path.
- Use `Teensy/ADC_Streamer_binary_scan2/` for normal Teensy ADC capture.
- Use `Teensy/Teensy555_streamer/` when the GUI is being used in 555 / displacement mode.
- Use `PCB1.5_SPI/` for the current Teensy+MG24 dual-board array hardware (recommended).
- Use `PCB1.0_SPI/` only for legacy PCB v1.0 hardware.

## Teensy+MG24 Pairing Notes

For `PCB1.0_SPI/` and `PCB1.5_SPI/`, flash both boards with the matching pair:

- Teensy: `Teensy_SPI_Master_Array_PZT_PZR1...`
- MG24: `MG24_Dual_MUX_SPI_Slave...`

Do not mix a Teensy sketch from one PCB folder with an MG24 sketch from the other folder.

On PCB1.5, DRDY is used as the primary stream synchronization signal from MG24 to Teensy. The Teensy firmware still includes a guarded fallback polling path for safety if DRDY stalls.

## Shared Serial Protocol

The active MG24 and Teensy sketches use the same host-side command style:

- ASCII commands terminated by `*`
- text acknowledgments on the same serial port
- binary sample blocks during streaming

### Serial Settings

| Setting | Value |
| --- | --- |
| Baud rate | `460800` |
| Transport | USB serial |
| Command terminator | `*` |
| Text encoding | ASCII |
| Binary transport | raw bytes on the same serial port |

### Common Command Flow

Typical startup sequence from the host:

```text
mcu*
channels 14,15,16,17,18*
repeat 20*
buffer 10*
run*
```

### Acknowledgments

Successful commands end with:

```text
#OK
```

or:

```text
#OK <args>
```

Failed commands end with:

```text
#NOT_OK
```

or:

```text
#NOT_OK <args>
```

Additional diagnostic lines may appear before the final acknowledgment.

## Common Commands

### `channels <pin_list>*`

Defines the acquisition sequence. Repeated channels are allowed.

Examples:

```text
channels 14,15,16,17,18*
channels 14,14,15,16*
```

### `ground <pin>*`

Sets the dummy ground channel when the sketch supports explicit ground insertion.

Example:

```text
ground 19*
```

### `ground true*` / `ground false*`

Enables or disables dummy ground reads before each new channel.

```text
ground true*
ground false*
```

### `repeat <n>*`

Sets the samples-per-channel count inside each sweep.

```text
repeat 20*
```

### `buffer <n>*`

Sets the sweeps-per-block count.

```text
buffer 10*
```

### `ref ...*`, `osr ...*`, `gain ...*`

Reference, oversampling/averaging, and gain support vary slightly by sketch, but the command names are shared where implemented.

```text
ref 3.3*
osr 4*
gain 1*
```

### `run*` and `run <ms>*`

Starts continuous or timed streaming.

```text
run*
run 100*
```

### `stop*`

Stops streaming.

```text
stop*
```

### `status*`, `mcu*`, and `help*`

Useful for host detection and manual troubleshooting.

```text
status*
mcu*
help*
```

## Binary Block Format

The standard streamer sketches emit framed binary blocks on the same port while capture is active.

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 byte | magic `0xAA` |
| 1 | 1 byte | magic `0x55` |
| 2-3 | `uint16` LE | `sample_count` |
| 4... | `uint16` LE x `sample_count` | sample payload |
| next | `uint16` LE | `avg_dt_us` |
| next | `uint32` LE | `block_start_us` |
| next | `uint32` LE | `block_end_us` |

Example frame layout:

```text
[0xAA][0x55][countL][countH][samples...][avg_dt_us][block_start_us][block_end_us]
```

## Sample Ordering

Within each sweep:

1. Channels are visited in the configured `channels` order.
2. `repeat` samples are collected for each channel.
3. Optional dummy ground reads happen between channels but are not included in the transmitted payload.

Example with `channels 14,15,16*`, `repeat 2*`, `buffer 1*`:

```text
ch14 s1, ch14 s2, ch15 s1, ch15 s2, ch16 s1, ch16 s2
```

Example with `channels 14,14,15*`, `repeat 2*`:

```text
ch14 s1, ch14 s2, ch14 s3, ch14 s4, ch15 s1, ch15 s2
```

## Host Integration Notes

- Configure the device using text commands before switching the host parser into binary-frame mode.
- Use `mcu*` to identify the connected firmware variant.
- After `stop*`, expect text responses again on the same port.
- The desktop app handles mixed text/binary transitions for the standard sketches listed above.

## Legacy And Experimental Sketches

Some additional `.ino` files in this tree are historical or specialized variants. Keep them for reference or hardware-specific work, but prefer the sketches listed in the current sketch map when pairing with the main GUI.

Archived MG24 variants now live under `legacy/MG24/`:

- `legacy/MG24/ADC_Streamer_binary/`: older single-sweep binary/CSV-era host flow
- `legacy/MG24/ADC_Streamer_binary_buffer/`: pre-scan blocked-output MG24 variant
- `legacy/MG24/ADC_Streamer XIAO MG24/`: older interactive CSV sweeper variant
