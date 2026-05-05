#pragma once

#include <Arduino.h>

#include "Mg24SharedProtocol.h"

namespace mg24_adc_mux {

struct Pins {
  int adc_mux1 = A1;
  int adc_mux2 = A2;
  int mux_a0 = D3;
  int mux_a1 = D4;
  int mux_a2 = D5;
  int mux_a3 = D6;
  int drdy_pin = D7;
};

struct Config {
  uint8_t channels[16] = {0, 1, 2, 3, 4};
  uint8_t channel_count = 5;
  uint16_t repeat_count = 1;
  uint16_t sweeps_per_block = 1;
  uint8_t ref = 1;
  uint8_t osr = 2;
  uint8_t gain = 1;
  uint8_t ground_pin = 10;
  bool ground_enable = false;
  bool running = false;
  bool timed_run = false;
  uint32_t run_stop_ms = 0;
};

struct Runtime {
  Pins pins;
  Config cfg;
  uint16_t sample_buf[mg24_proto::kMaxPairs * 2u];
  uint32_t last_block_start_us = 0;
  uint32_t last_block_end_us = 0;
  uint16_t last_avg_dt_us = 0;
  bool iadc_ready = false;
  bool config_dirty = true;
  uint8_t last_mux_ch = 0xFF;
};

void begin(Runtime &rt, const Pins &pins);
bool setChannels(Runtime &rt, const uint8_t *channels, uint8_t count);
void setRepeat(Runtime &rt, uint8_t repeat_count);
void setBuffer(Runtime &rt, uint8_t sweeps_per_block);
bool setReference(Runtime &rt, uint8_t ref);
bool setOsr(Runtime &rt, uint8_t osr);
bool setGain(Runtime &rt, uint8_t gain);
bool setGroundPin(Runtime &rt, uint8_t ground_pin);
void setGroundEnabled(Runtime &rt, bool enabled);

bool startRun(Runtime &rt, const uint8_t *args, uint8_t nargs);
uint16_t fillInterleavedBlock(Runtime &rt);
bool streamExpired(Runtime &rt);
void stopRun(Runtime &rt);
bool isStreaming(const Runtime &rt);
uint32_t blockResponseBytes(const Runtime &rt);

}  // namespace mg24_adc_mux
