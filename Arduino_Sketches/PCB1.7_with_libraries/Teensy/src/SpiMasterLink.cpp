#include "SpiMasterLink.h"

namespace {
SpiMasterLink *g_drdy_link = nullptr;
}

void SpiMasterLink::begin(SPIClass &spi_ref, uint8_t cs, uint32_t bitrate, uint32_t setup_us) {
  spi = &spi_ref;
  cs_pin = cs;
  cs_setup_us = setup_us;
  settings = SPISettings(bitrate, MSBFIRST, SPI_MODE1);

  spi->begin();
  pinMode(cs_pin, OUTPUT);
  digitalWrite(cs_pin, HIGH);
}

void SpiMasterLink::beginDrdy(uint8_t pin) {
  drdy_pin = pin;
  g_drdy_link = this;
  pinMode(drdy_pin, INPUT_PULLDOWN);
  attachInterrupt(digitalPinToInterrupt(drdy_pin), SpiMasterLink::drdyIsrThunk, RISING);
  drdyClearAll();
}

void SpiMasterLink::drdyIsrThunk() {
  if (g_drdy_link == nullptr) {
    return;
  }
  g_drdy_link->drdy_flag = true;
  g_drdy_link->drdy_edges++;
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

bool SpiMasterLink::recvStreamingResponse(
    uint8_t *buf,
    uint16_t len,
    uint8_t control_byte,
    uint8_t max_attempts,
    uint8_t ack_magic,
    uint8_t block_magic1,
    uint8_t block_magic2) {
  for (uint8_t attempt = 0; attempt < max_attempts; ++attempt) {
    transferLeadByte(control_byte, buf, len);
    if (len >= 2 && buf[0] == block_magic1 && buf[1] == block_magic2) {
      return true;
    }
    if (len >= 1 && buf[0] == ack_magic) {
      return true;
    }
    delayMicroseconds(200 + static_cast<uint32_t>(attempt) * 200);
  }
  return false;
}

bool SpiMasterLink::drdyPending() const {
  return drdy_flag;
}

void SpiMasterLink::drdyConsumeOne() {
  noInterrupts();
  if (drdy_edges > 0) {
    drdy_edges--;
  }
  drdy_flag = (drdy_edges != 0);
  interrupts();
}

void SpiMasterLink::drdyClearAll() {
  noInterrupts();
  drdy_edges = 0;
  drdy_flag = false;
  interrupts();
}

bool SpiMasterLink::waitForDrdy(uint32_t timeout_ms) {
  const uint32_t t0 = millis();
  while (!drdyPending()) {
    if ((millis() - t0) >= timeout_ms) {
      return false;
    }
    yield();
  }
  return true;
}
