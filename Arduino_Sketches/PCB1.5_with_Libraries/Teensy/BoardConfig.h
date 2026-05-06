#pragma once

#include <Arduino.h>

#include "libraries/PzrController.h"

namespace board_config {

enum Timer555Mode { TIMER555_PZR, TIMER555_RS };

static constexpr uint8_t kPztCsPin = 10;
static constexpr uint32_t kPztSpiBitrate = 4000000UL;
static constexpr uint32_t kPztCsSetupUs = 10;

static constexpr Timer555Mode kDefault555Mode = TIMER555_RS;

static constexpr int kPzrIcpPin = 23;
static constexpr int kPzrMuxA0Pin = 22;
static constexpr int kPzrMuxA1Pin = 21;
static constexpr int kPzrMuxA2Pin = 20;
static constexpr int kPzrMuxA3Pin = 19;
static constexpr int kPzrMuxEnPin = -1;

static constexpr int kRsIcpPin = 14;
static constexpr int kRsMuxA0Pin = 18;
static constexpr int kRsMuxA1Pin = 17;
static constexpr int kRsMuxA2Pin = 16;
static constexpr int kRsMuxA3Pin = 15;
static constexpr int kRsMuxEnPin = -1;

static constexpr int kTimer555IcpPin =
    (kDefault555Mode == TIMER555_RS) ? kRsIcpPin : kPzrIcpPin;
static constexpr int kTimer555MuxA0Pin =
    (kDefault555Mode == TIMER555_RS) ? kRsMuxA0Pin : kPzrMuxA0Pin;
static constexpr int kTimer555MuxA1Pin =
    (kDefault555Mode == TIMER555_RS) ? kRsMuxA1Pin : kPzrMuxA1Pin;
static constexpr int kTimer555MuxA2Pin =
    (kDefault555Mode == TIMER555_RS) ? kRsMuxA2Pin : kPzrMuxA2Pin;
static constexpr int kTimer555MuxA3Pin =
    (kDefault555Mode == TIMER555_RS) ? kRsMuxA3Pin : kPzrMuxA3Pin;
static constexpr int kTimer555MuxEnPin =
    (kDefault555Mode == TIMER555_RS) ? kRsMuxEnPin : kPzrMuxEnPin;

static constexpr const char *kTimer555Name =
    (kDefault555Mode == TIMER555_RS) ? "RS/555_A" : "PZR/555_B";
static constexpr float kPzr555DefaultCfF = 22e-9f;
static constexpr float kRs555DefaultCfF = 220e-9f;
static constexpr float kTimer555DefaultCfF =
    (kDefault555Mode == TIMER555_RS) ? kRs555DefaultCfF : kPzr555DefaultCfF;
static constexpr pzr_controller::SourceIndex kTimer555SourceIndex =
    (kDefault555Mode == TIMER555_RS) ? pzr_controller::SOURCE_RS : pzr_controller::SOURCE_PZR;

static inline void initTimer555Pins() {
  pinMode(kPzrIcpPin, INPUT);
  pinMode(kPzrMuxA0Pin, OUTPUT);
  pinMode(kPzrMuxA1Pin, OUTPUT);
  pinMode(kPzrMuxA2Pin, OUTPUT);
  pinMode(kPzrMuxA3Pin, OUTPUT);
  if (kPzrMuxEnPin >= 0) {
    pinMode(kPzrMuxEnPin, OUTPUT);
  }

  pinMode(kRsIcpPin, INPUT);
  pinMode(kRsMuxA0Pin, OUTPUT);
  pinMode(kRsMuxA1Pin, OUTPUT);
  pinMode(kRsMuxA2Pin, OUTPUT);
  pinMode(kRsMuxA3Pin, OUTPUT);
  if (kRsMuxEnPin >= 0) {
    pinMode(kRsMuxEnPin, OUTPUT);
  }
}

static inline pzr_controller::Pins makePzrPins() {
  pzr_controller::Pins pins;
  pins.icp_pin = kTimer555IcpPin;
  pins.mux_a0 = kTimer555MuxA0Pin;
  pins.mux_a1 = kTimer555MuxA1Pin;
  pins.mux_a2 = kTimer555MuxA2Pin;
  pins.mux_a3 = kTimer555MuxA3Pin;
  pins.mux_en = kTimer555MuxEnPin;
  pins.source_index = kTimer555SourceIndex;
  pins.source_name = kTimer555Name;
  return pins;
}

}  // namespace board_config