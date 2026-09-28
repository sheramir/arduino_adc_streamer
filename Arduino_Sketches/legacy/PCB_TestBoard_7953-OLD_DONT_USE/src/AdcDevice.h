#pragma once

#include <Arduino.h>

// Interface consumed by PztController. An ADC with an internal SPI MUX (such
// as ADS7953) and an ADC preceded by a GPIO-controlled external MUX both
// implement readChannel(); all device-specific selection stays behind it.
class AdcDevice {
 public:
  virtual ~AdcDevice() = default;
  virtual void begin() = 0;
  virtual uint8_t channelCount() const = 0;
  virtual bool readChannel(uint8_t channel, uint16_t &sample) = 0;
  virtual uint32_t errorCount() const = 0;
};
