#pragma once

#include <Arduino.h>

#include "../ConfigurableParameters.h"
#include "AdcDevice.h"
#include "UsbSerialController.h"

class PztController {
 public:
  PztController(AdcDevice **adcs, uint8_t adc_count, UsbSerialController &usb);

  void begin();
  bool handleCommand(const String &command, const String &arguments);
  void service();
  void stop();
  bool isRunning() const;
  void printStatus() const;

 private:
  bool setChannels(const String &arguments);
  bool setRepeat(const String &arguments);
  bool setBuffer(const String &arguments);
  bool setGround(const String &arguments);
  bool startRun(const String &arguments);
  bool blockFits() const;
  bool captureBlock();

  AdcDevice **adcs_;
  uint8_t adc_count_;
  UsbSerialController &usb_;
  uint8_t channels_[testboard_config::kMaxChannelSequence];
  uint8_t channel_count_ = 0;
  uint8_t repeat_ = 1;
  uint8_t buffer_sweeps_ = 1;
  uint8_t ground_channel_ = 15;
  bool ground_enabled_ = false;
  bool running_ = false;
  bool timed_run_ = false;
  uint32_t run_started_ms_ = 0;
  uint32_t run_duration_ms_ = 0;
};
