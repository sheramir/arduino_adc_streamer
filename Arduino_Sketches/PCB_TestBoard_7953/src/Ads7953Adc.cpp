#include "Ads7953Adc.h"

#include "../ConfigurableParameters.h"

namespace {
static constexpr uint16_t kManualMode = 0x1000;
static constexpr uint16_t kProgramControlBits = 0x0800;
static constexpr uint16_t kRange2xVref = 0x0040;
}

Ads7953Adc::Ads7953Adc(SpiController &spi, uint8_t cs_pin)
    : spi_(spi), cs_pin_(cs_pin) {}

void Ads7953Adc::begin() {
  spi_.registerChipSelect(cs_pin_);
  // Power-up defaults are manual mode/channel 0. Prime the two-frame command
  // pipeline so the first application read has deterministic state.
  const uint16_t command = manualCommand(0);
  spi_.transfer16(cs_pin_, command);
  spi_.transfer16(cs_pin_, command);
}

uint8_t Ads7953Adc::channelCount() const {
  return testboard_config::kAdcChannels;
}

uint16_t Ads7953Adc::manualCommand(uint8_t channel) const {
  uint16_t word = kManualMode | kProgramControlBits;
  word |= static_cast<uint16_t>(channel & 0x0F) << 7;
  if (testboard_config::kAds7953Range2xVref) {
    word |= kRange2xVref;
  }
  return word;
}

bool Ads7953Adc::readChannel(uint8_t channel, uint16_t &sample) {
  if (channel >= channelCount()) {
    ++errors_;
    return false;
  }

  const uint16_t command = manualCommand(channel);
  uint16_t response = 0;
  // Manual-mode channel commands have a two-frame latency. Repeating the same
  // command makes this deliberately simple and safe for first-board bring-up.
  for (uint8_t frame = 0; frame <= testboard_config::kAds7953PipelineFrames; ++frame) {
    response = spi_.transfer16(cs_pin_, command);
  }

  const uint8_t returned_channel = static_cast<uint8_t>((response >> 12) & 0x0F);
  sample = response & testboard_config::kAdcFullScaleCode;
  if (testboard_config::kValidateReturnedChannel && returned_channel != channel) {
    ++errors_;
    return false;
  }
  return true;
}

uint32_t Ads7953Adc::errorCount() const {
  return errors_;
}
