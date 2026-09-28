#pragma once

#include <Arduino.h>
#include <SPI.h>

class SpiController {
 public:
  SpiController(SPIClass &bus, uint8_t miso, uint8_t mosi, uint8_t sck);

  void begin();
  void registerChipSelect(uint8_t cs_pin);
  uint16_t transfer16(uint8_t cs_pin, uint16_t tx_word);

 private:
  SPIClass &bus_;
  uint8_t miso_;
  uint8_t mosi_;
  uint8_t sck_;
};
