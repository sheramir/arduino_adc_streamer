#include "SpiController.h"

#include "../ConfigurableParameters.h"

SpiController::SpiController(SPIClass &bus, uint8_t miso, uint8_t mosi, uint8_t sck)
    : bus_(bus), miso_(miso), mosi_(mosi), sck_(sck) {}

void SpiController::begin() {
  bus_.setMISO(miso_);
  bus_.setMOSI(mosi_);
  bus_.setSCK(sck_);
  bus_.begin();
}

void SpiController::registerChipSelect(uint8_t cs_pin) {
  pinMode(cs_pin, OUTPUT);
  digitalWriteFast(cs_pin, HIGH);
}

uint16_t SpiController::transfer16(uint8_t cs_pin, uint16_t tx_word) {
  const SPISettings settings(
      testboard_config::kSpiClockHz,
      testboard_config::kSpiBitOrder,
      testboard_config::kSpiMode);
  bus_.beginTransaction(settings);
  digitalWriteFast(cs_pin, LOW);
  const uint16_t rx_word = bus_.transfer16(tx_word);
  digitalWriteFast(cs_pin, HIGH);
  bus_.endTransaction();
  delayNanoseconds(testboard_config::kCsHighTimeNs);
  return rx_word;
}
