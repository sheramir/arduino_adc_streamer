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
  void setRange2xVref(bool enabled) override;

  uint16_t manualCommand(uint8_t channel) const;
  uint16_t auto1ProgramCommand() const;
  uint16_t auto1ControlCommand(bool reset_channel_counter) const;
  uint16_t continueCommand() const;
  uint16_t transferBlocking(uint16_t command);
  bool decodeResponse(uint16_t response, uint8_t expected_channel,
                      uint16_t &sample);
  uint8_t returnedChannel(uint16_t response) const;
  uint16_t returnedSample(uint16_t response) const;
  void recordError();
  SpiController &spiController() { return spi_; }
  uint8_t chipSelectPin() const { return cs_pin_; }
  const SpiController::ChipSelect &chipSelect() const { return chip_select_; }

 private:
  SpiController &spi_;
  uint8_t cs_pin_;
  SpiController::ChipSelect chip_select_;
  uint32_t errors_ = 0;
  bool range_2x_vref_;
};
