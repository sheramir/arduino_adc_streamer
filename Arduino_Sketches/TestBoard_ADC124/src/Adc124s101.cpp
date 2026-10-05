#include "Adc124s101.h"

using namespace testboard_config;

bool validSensorRoute(const SensorRoute &r) {
  return r.array >= 1 && r.array <= 2 && r.mux >= 1 && r.mux <= 4 &&
         (r.input <= 5 || (r.mux == 4 && r.input == 6));
}

Adc124s101::Adc124s101(SpiController &spi, uint8_t array_index)
    : spi_(spi), index_(array_index) {}

void Adc124s101::enable(bool enabled) {
  digitalWrite(kMuxEnablePins[index_],
               enabled == kMuxEnableActiveHigh[index_] ? HIGH : LOW);
  enabled_ = enabled;
}

void Adc124s101::begin() {
  spi_.registerChipSelect(kCsPins[index_]);
  // Set the output latch before changing direction, especially active-low EN.
  enable(false);
  pinMode(kMuxEnablePins[index_], OUTPUT);
  for (uint8_t pin : kMuxAddressPins[index_]) pinMode(pin, OUTPUT);
  park(kDefaultMuxSettleUs);
}

void Adc124s101::disable() {
  enable(false);
  delayNanoseconds(kMuxDisableTimeNs);
}

void Adc124s101::selectAddress(uint8_t address, uint32_t settle_us) {
  if (enabled_ && address_ == address) return;
  disable();
  for (uint8_t bit = 0; bit < 3; ++bit)
    digitalWrite(kMuxAddressPins[index_][bit], (address >> bit) & 1);
  address_ = address;
  enable(true);
  // Even settle_us=0 includes a switch turn-on allowance; the configurable
  // delay is additional analog settling, to be measured on the real board.
  delayNanoseconds(kMuxDisableTimeNs);
  if (settle_us) delayMicroseconds(settle_us);
}

void Adc124s101::park(uint32_t settle_us) {
  selectAddress(kVmidAddress, settle_us);
}

bool Adc124s101::transfer(uint8_t adc_input, SpiEngine engine, uint16_t &sample) {
  if (faulted_ || adc_input > 3) return false;
  // ADD1:ADD0 occupy DIN bits 12:11 in a 16-clock frame. This command
  // selects the NEXT conversion; the response has four zero bits + 12 data.
  const uint16_t command = static_cast<uint16_t>(adc_input) << 11;
  uint16_t response = 0;
  if (engine == SpiEngine::BLOCKING) {
    response = spi_.transfer16(kCsPins[index_], command);
  } else {
    const bool dma = engine == SpiEngine::DMA;
    const bool started = dma ? spi_.startDma16(kCsPins[index_], command)
                             : spi_.startLpspi16(kCsPins[index_], command);
    if (!started) {
      ++transfer_errors_;
      faulted_ = true;
      return false;
    }
    const uint32_t started_us = micros();
    while (!(dma ? spi_.dmaComplete() : spi_.lpspiComplete())) {
      if (static_cast<uint32_t>(micros() - started_us) >= kSpiTransferTimeoutUs) {
        if (dma) spi_.cancelDma16(); else spi_.cancelLpspi16();
        ++transfer_errors_;
        faulted_ = true;
        return false;
      }
      yield();
    }
    if (!(dma ? spi_.finishDma16(response) : spi_.finishLpspi16(response))) {
      if (dma) spi_.cancelDma16(); else spi_.cancelLpspi16();
      ++transfer_errors_;
      faulted_ = true;
      return false;
    }
  }
  if (response & 0xF000) {
    ++data_errors_;
    return false;
  }
  sample = response;
  return true;
}

bool Adc124s101::readBatch(const SensorRoute *routes, uint8_t count,
                          uint8_t repeat, SpiEngine engine, uint16_t *samples) {
  if (!count || !repeat) return false;
  for (uint8_t i = 0; i < count; ++i)
    if (!validSensorRoute(routes[i]) || routes[i].array != index_ + 1 ||
        routes[i].input != routes[0].input) return false;
  uint16_t discarded;
  // Flush the preceding input selection after any MUX/address/ADC switch.
  if (!transfer(kMuxToAdcInput[routes[0].mux - 1], engine, discarded)) return false;
  for (uint8_t i = 0; i < count; ++i) {
    for (uint8_t r = 0; r < repeat; ++r) {
      const uint8_t next = (r + 1 == repeat && i + 1 < count) ? i + 1 : i;
      if (!transfer(kMuxToAdcInput[routes[next].mux - 1], engine, samples[i]))
        return false;
    }
  }
  return true;
}

bool Adc124s101::sampleVmid(uint32_t settle_us, SpiEngine engine) {
  park(settle_us);
  uint16_t discarded;
  if (!transfer(0, engine, discarded)) return false;
  for (uint8_t i = 0; i < 4; ++i)
    if (!transfer(i < 3 ? i + 1 : 3, engine, discarded)) return false;
  return true;
}
