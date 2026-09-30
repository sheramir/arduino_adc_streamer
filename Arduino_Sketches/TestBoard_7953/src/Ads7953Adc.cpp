#include "Ads7953Adc.h"

#include "ConfigurableParameters.h"

namespace {
static constexpr uint16_t kManualMode = 0x1000;
static constexpr uint16_t kAuto1Mode = 0x2000;
static constexpr uint16_t kAuto1Program = 0x8000;
static constexpr uint16_t kProgramControlBits = 0x0800;
static constexpr uint16_t kResetAutoChannelCounter = 0x0400;
static constexpr uint16_t kRange2xVref = 0x0040;
}

Ads7953Adc::Ads7953Adc(SpiController &spi, uint8_t cs_pin)
    : spi_(spi), cs_pin_(cs_pin),
      range_2x_vref_(testboard_config::kAds7953Range2xVref) {}

void Ads7953Adc::begin() {
  spi_.registerChipSelect(cs_pin_);
  // Prime the two-frame command pipeline and leave the MUX on the board-fixed
  // Vmid input. All four ADCs therefore start parked even before routes exist.
  const uint16_t command = manualCommand(testboard_config::kDefaultVmidChannel);
  for (uint8_t frame = 0; frame < testboard_config::kAds7953PipelineFrames;
       ++frame) {
    spi_.transfer16(cs_pin_, command);
  }
}

uint8_t Ads7953Adc::channelCount() const {
  return testboard_config::kAdcChannels;
}

uint16_t Ads7953Adc::manualCommand(uint8_t channel) const {
  uint16_t word = kManualMode | kProgramControlBits;
  word |= static_cast<uint16_t>(channel & 0x0F) << 7;
  if (range_2x_vref_) {
    word |= kRange2xVref;
  }
  return word;
}

void Ads7953Adc::setRange2xVref(bool enabled) {
  range_2x_vref_ = enabled;
}

uint16_t Ads7953Adc::auto1ProgramCommand() const {
  return kAuto1Program;
}

uint16_t Ads7953Adc::auto1ControlCommand(bool reset_channel_counter) const {
  uint16_t word = kAuto1Mode | kProgramControlBits;
  if (reset_channel_counter) word |= kResetAutoChannelCounter;
  if (range_2x_vref_) word |= kRange2xVref;
  return word;
}

uint16_t Ads7953Adc::continueCommand() const {
  return 0;
}

uint16_t Ads7953Adc::transferBlocking(uint16_t command) {
  return spi_.transfer16(cs_pin_, command);
}

uint8_t Ads7953Adc::returnedChannel(uint16_t response) const {
  return static_cast<uint8_t>((response >> 12) & 0x0F);
}

uint16_t Ads7953Adc::returnedSample(uint16_t response) const {
  return response & testboard_config::kAdcFullScaleCode;
}

bool Ads7953Adc::decodeResponse(
    uint16_t response, uint8_t expected_channel, uint16_t &sample) {
  sample = returnedSample(response);
  if (testboard_config::kValidateReturnedChannel &&
      returnedChannel(response) != expected_channel) {
    ++errors_;
    return false;
  }
  return true;
}

void Ads7953Adc::recordError() {
  ++errors_;
}

SpiController &Ads7953Adc::spiController() {
  return spi_;
}

uint8_t Ads7953Adc::chipSelectPin() const {
  return cs_pin_;
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

  return decodeResponse(response, channel, sample);
}

uint32_t Ads7953Adc::errorCount() const {
  return errors_;
}
