#pragma once

#include <Arduino.h>

#include "SpiMasterLink.h"

namespace pzt_controller {

static const uint8_t kCmdFrameLen = 20;
static const uint8_t kAckFrameLen = 4;
static const uint8_t kTrailerLen = 10;

static const uint8_t kCmdSetChannels = 0x01;
static const uint8_t kCmdSetRepeat = 0x02;
static const uint8_t kCmdSetBuffer = 0x03;
static const uint8_t kCmdSetRef = 0x04;
static const uint8_t kCmdSetOsr = 0x05;
static const uint8_t kCmdSetGain = 0x06;
static const uint8_t kCmdRun = 0x07;
static const uint8_t kCmdStop = 0x08;
static const uint8_t kCmdGroundPin = 0x0B;
static const uint8_t kCmdGroundEn = 0x0C;
static const uint8_t kCmdContinue = 0x0D;

struct Config {
  uint8_t channels[16];
  uint8_t channel_count = 0;
  uint8_t repeat_count = 1;
  uint8_t sweeps_per_block = 1;
  uint8_t osr = 2;
  uint8_t gain = 1;
  uint8_t ref = 1;
  uint8_t ground_pin = 0;
  bool ground_enabled = false;
  bool running = false;
};

struct Runtime {
  SpiMasterLink *link = nullptr;
  Config cfg;
  uint32_t max_pairs = 8000UL;
  uint8_t ack_magic = 0xAC;
  uint8_t ack_ok = 0x00;
};

void begin(Runtime &rt, SpiMasterLink &link);
bool handleChannels(Runtime &rt, const String &args);
bool handleRepeat(Runtime &rt, const String &args);
bool handleBuffer(Runtime &rt, const String &args);
bool handleRef(Runtime &rt, const String &args);
bool handleOsr(Runtime &rt, const String &args);
bool handleGain(Runtime &rt, const String &args);
bool handleGround(Runtime &rt, const String &args);
void printStatus(const Runtime &rt);

bool runBlocking(Runtime &rt, const String &args, char cmd_term);
void requestStop(Runtime &rt);

}  // namespace pzt_controller
