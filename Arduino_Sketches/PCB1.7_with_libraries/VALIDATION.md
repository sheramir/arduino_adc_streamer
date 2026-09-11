# PCB1.7 modular validation against PCB1.7_SPI

Validated sources:

- Monolithic Teensy master:
  `PCB1.7_SPI/Teensy_SPI_Master_Array_PZT_PZR1.7_DRDY.ino`
- Modular Teensy master:
  `PCB1.7_with_libraries/Teensy/`
- Monolithic MG24 slave:
  `PCB1.7_SPI/MG24_Dual_MUX_SPI_Slave1.7_DRDY.ino`
- Modular MG24 slave: `PCB1.7_with_libraries/MG24/`

## Result

The modular code was created after the active monolithic PZT/PZR/PZT_RS fixes
and includes the later broken-rosette-channel fix on both paths. The host-facing
contract matches: MCU name, command vocabulary, ACK tokens, PZT_RS seven-word
sensor groups, scaled-ohm constant, binary magic/count/trailer, and the MG24
20-byte command / 4-byte ACK transport.

Two blocking build problems were found and fixed. Implementations were under
`libraries/`, but current Arduino sketch builds recursively compile only
`src/`. Both modular sketches now use `src/`, and their `.ino`/configuration
includes were updated. Their primary sketch filenames also did not match the
`Teensy` and `MG24` folder names, so Arduino CLI rejected them; they are now
`Teensy.ino` and `MG24.ino`.

With Silicon Labs core 4.0.0, the MG24's 8000-pair static buffers exceeded the
linker RAM region by about 7 KB. The active monolithic pair, modular pair, and
Python buffer limit now consistently use 6000 pairs, leaving about 30 KB for
the runtime stack and dynamic use. Framing and sample order
are unchanged; only the maximum block size is slightly lower.

`tests/test_firmware_source_contracts.py` guards these shared invariants and
the compilable `src/` layout. Arduino CLI compilation succeeds for Teensy 4.1
(Teensy core 1.62.0) and XIAO MG24 (Silicon Labs core 4.0.0). The modular pair
has also been run successfully on PCB1.7 hardware. This confirms basic
operation of the modular firmware; exhaustive DRDY, 555/PZT_RS, and sustained
streaming stress coverage is not claimed here.
