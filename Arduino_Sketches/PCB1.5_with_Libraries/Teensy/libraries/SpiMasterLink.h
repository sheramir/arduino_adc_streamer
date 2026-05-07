#pragma once

#include <Arduino.h>
#include <SPI.h>

struct SpiMasterLink {
  SPIClass *spi = nullptr;
  SPISettings settings = SPISettings(4000000UL, MSBFIRST, SPI_MODE1);
  uint8_t cs_pin = 10;
  uint32_t cs_setup_us = 10;

  void begin(SPIClass &spi_ref, uint8_t cs, uint32_t bitrate, uint32_t setup_us);
  void transfer(const uint8_t *tx, uint8_t *rx, uint32_t len);
  void transferLeadByte(uint8_t lead, uint8_t *rx, uint32_t len);
  void send(const uint8_t *tx, uint32_t len);
  void recv(uint8_t *rx, uint32_t len);
};
