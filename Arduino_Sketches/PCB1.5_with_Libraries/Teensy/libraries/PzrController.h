#pragma once

#include <Arduino.h>

namespace pzr_controller {

struct Pins {
  int icp_pin = 23;
  int mux_a0 = 20;
  int mux_a1 = 19;
  int mux_a2 = 18;
  int mux_a3 = 17;
  int mux_en = -1;
  bool mux_en_active_low = false;
};

struct Config {
  float rb_ohm = 470.0f;
  float rk_ohm = 470.0f;
  float cf_f = 22e-9f;
  float rx_max_ohm = 65500.0f;
  bool ascii_output = false;

  uint8_t channel_sequence[64] = {0, 1, 2, 3, 4};
  int channel_count = 5;
  int repeat_count = 1;
  int buffer_sweeps = 1;

  bool running = false;
  bool timed_run = false;
  uint32_t run_stop_ms = 0;
};

struct Runtime {
  Pins pins;
  Config cfg;
  uint16_t sample_buf[2048];
};

void begin(Runtime &rt, const Pins &pins);

bool handleChannels(Runtime &rt, const String &args);
bool handleRepeat(Runtime &rt, const String &args);
bool handleBuffer(Runtime &rt, const String &args);
bool handleRun(Runtime &rt, const String &args);
void handleStop(Runtime &rt);
bool handleRb(Runtime &rt, const String &args);
bool handleRk(Runtime &rt, const String &args);
bool handleCf(Runtime &rt, const String &args);
bool handleRxMax(Runtime &rt, const String &args);
bool handleAscii(Runtime &rt, const String &args);

void printStatus(const Runtime &rt);
void doOneBlock(Runtime &rt);

}  // namespace pzr_controller
