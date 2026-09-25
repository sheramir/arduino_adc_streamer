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
  struct AdcRoute {
    uint8_t adc;
    uint8_t channel;
  };

  enum ArraySelection : uint8_t {
    ARRAY_1,
    ARRAY_2,
    ARRAY_BOTH,
  };

  enum ScanOrder : uint8_t {
    SCAN_INTERLEAVED,
    SCAN_ARRAY,
    SCAN_ADC,
  };

  bool setAdcChannels(const String &arguments);
  bool setArraySelection(const String &arguments);
  bool setScanOrder(const String &arguments);
  bool setVmid(const String &arguments);
  bool startRun(const String &arguments);
  bool routesValid() const;
  bool captureBlock();
  bool captureBufferedBlock(const AdcRoute *plan, uint8_t plan_count);
  bool captureArrayStreamedBlock(const AdcRoute *plan, uint8_t plan_count);
  uint8_t buildScanPlan(AdcRoute *destination) const;
  void parkAdc(uint8_t adc);
  void parkSelectedAdcs();
  bool adcSelected(uint8_t adc) const;
  const __FlashStringHelper *arraySelectionName() const;
  const __FlashStringHelper *scanOrderName() const;

  AdcDevice **adcs_;
  uint8_t adc_count_;
  UsbSerialController &usb_;
  AdcRoute routes_[testboard_config::kMaxAdcRoutes];
  uint8_t route_count_ = 0;
  ArraySelection array_selection_ = ARRAY_BOTH;
  ScanOrder scan_order_ = SCAN_INTERLEAVED;
  uint8_t vmid_channel_ = 15;
  bool vmid_park_enabled_ = false;
  bool running_ = false;
  bool timed_run_ = false;
  uint32_t run_started_ms_ = 0;
  uint32_t run_duration_ms_ = 0;
};
