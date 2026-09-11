#pragma once

#include <Arduino.h>

#include "../ConfigurableParameters.h"
#include "UsbSerialController.h"

// Optional 555-resistance controller. It is compiled into the test-board
// firmware even when hardware is disabled, keeping the API boundary ready for
// a later PCB revision without coupling 555 code to the ADS7953 driver.
class PzrController {
 public:
  explicit PzrController(UsbSerialController &usb);

  void begin();
  bool available() const;
  bool handleCommand(const String &command, const String &arguments);
  void service();
  void stop();
  bool isRunning() const;
  void printStatus() const;

 private:
  bool setChannels(const String &arguments);
  bool setPositiveFloat(const String &arguments, float &target, bool capacitance);
  void selectMux(uint8_t channel);
  uint32_t timeoutUs() const;
  bool measureResistance(uint8_t channel, uint16_t &sample);
  bool emitBlock();

  UsbSerialController &usb_;
  uint8_t channels_[testboard_config::kMaxChannelSequence];
  uint8_t channel_count_ = 0;
  uint8_t repeat_ = 1;
  uint8_t buffer_sweeps_ = 1;
  float rb_ohm_ = 470.0f;
  float rk_ohm_ = 470.0f;
  float cf_f_ = 22e-9f;
  float rx_max_ohm_ = 65500.0f;
  bool running_ = false;
  bool ascii_ = false;
  bool timed_run_ = false;
  uint32_t run_started_ms_ = 0;
  uint32_t run_duration_ms_ = 0;
};
