#pragma once

#include "AdcDevice.h"
#include "SpiController.h"

class Ads7953Adc final : public AdcDevice {
 public:
  Ads7953Adc(SpiController &spi, uint8_t cs_pin);

  void begin() override;
  uint8_t channelCount() const override;
  bool readChannel(uint8_t channel, uint16_t &sample) override;
  uint32_t errorCount() const override;

 private:
  uint16_t manualCommand(uint8_t channel) const;

  SpiController &spi_;
  uint8_t cs_pin_;
  uint32_t errors_ = 0;
};
