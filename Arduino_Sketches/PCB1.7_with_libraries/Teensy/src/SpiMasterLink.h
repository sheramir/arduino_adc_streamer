#pragma once

#include <Arduino.h>
#include <SPI.h>

struct SpiMasterLink {
  SPIClass *spi = nullptr;
  SPISettings settings = SPISettings(4000000UL, MSBFIRST, SPI_MODE1);
  uint8_t cs_pin = 10;
  uint8_t drdy_pin = 0;
  uint32_t cs_setup_us = 10;
  volatile bool drdy_flag = false;
  volatile uint32_t drdy_edges = 0;

  void begin(SPIClass &spi_ref, uint8_t cs, uint32_t bitrate, uint32_t setup_us);
  void beginDrdy(uint8_t pin);
  void transfer(const uint8_t *tx, uint8_t *rx, uint32_t len);
  void transferLeadByte(uint8_t lead, uint8_t *rx, uint32_t len);
  void send(const uint8_t *tx, uint32_t len);
  void recv(uint8_t *rx, uint32_t len);
  bool recvStreamingResponse(
      uint8_t *buf,
      uint16_t len,
      uint8_t control_byte,
      uint8_t max_attempts,
      uint8_t ack_magic,
      uint8_t block_magic1,
      uint8_t block_magic2);

  bool drdyPending() const;
  void drdyConsumeOne();
  void drdyClearAll();
  bool waitForDrdy(uint32_t timeout_ms);

  static void drdyIsrThunk();
};
