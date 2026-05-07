# MG24 Modular Sketch

Main sketch:

- `MG24_Dual_MUX_SPI_Slave1.5_DRDY_Modular.ino`

Libraries:

- `libraries/Mg24SharedProtocol.*`
- `libraries/Mg24AdcMux.*`
- `libraries/Mg24CommandEngine.*`
- `libraries/Mg24SpiSlaveTransport.*`

Current transport wiring in this modular sketch matches the original MG24 PCB1.5 SPI slave behavior:

- SPIDRV / EUSART1 slave transport
- D0 command phase receive from Teensy
- D9 response transmit to Teensy
- D7 DRDY driven high when a response is armed
- Same 20-byte command frames, 4-byte ACKs, and binary streaming block format as the original sketch

The difference from the original sketch is the modular library split, not the protocol behavior.
