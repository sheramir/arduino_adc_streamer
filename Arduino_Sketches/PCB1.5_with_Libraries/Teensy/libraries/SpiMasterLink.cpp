#include "SpiMasterLink.h"

void SpiMasterLink::begin(SPIClass &spi_ref, uint8_t cs, uint32_t bitrate, uint32_t setup_us) {
  spi = &spi_ref;
  cs_pin = cs;
  cs_setup_us = setup_us;
  settings = SPISettings(bitrate, MSBFIRST, SPI_MODE1);

  spi->begin();
  pinMode(cs_pin, OUTPUT);
  digitalWrite(cs_pin, HIGH);
}

void SpiMasterLink::transfer(const uint8_t *tx, uint8_t *rx, uint32_t len) {
  if (spi == nullptr || len == 0) {
    return;
  }

  spi->beginTransaction(settings);
  digitalWrite(cs_pin, LOW);
  if (cs_setup_us) {
    delayMicroseconds(cs_setup_us);
  }

  for (uint32_t i = 0; i < len; ++i) {
    const uint8_t t = tx ? tx[i] : 0x00;
    const uint8_t r = spi->transfer(t);
    if (rx) {
      rx[i] = r;
    }
  }

  digitalWrite(cs_pin, HIGH);
  spi->endTransaction();
}

void SpiMasterLink::transferLeadByte(uint8_t lead, uint8_t *rx, uint32_t len) {
  if (spi == nullptr || len == 0) {
    return;
  }

  spi->beginTransaction(settings);
  digitalWrite(cs_pin, LOW);
  if (cs_setup_us) {
    delayMicroseconds(cs_setup_us);
  }

  if (rx) {
    rx[0] = spi->transfer(lead);
    for (uint32_t i = 1; i < len; ++i) {
      rx[i] = spi->transfer(0x00);
    }
  } else {
    spi->transfer(lead);
    for (uint32_t i = 1; i < len; ++i) {
      spi->transfer(0x00);
    }
  }

  digitalWrite(cs_pin, HIGH);
  spi->endTransaction();
}

void SpiMasterLink::send(const uint8_t *tx, uint32_t len) {
  transfer(tx, nullptr, len);
}

void SpiMasterLink::recv(uint8_t *rx, uint32_t len) {
  transfer(nullptr, rx, len);
}
