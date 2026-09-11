#pragma once

#include <Arduino.h>

namespace pzr_controller {

static constexpr int kMaxChannelSequence = 64;
static constexpr uint16_t kMaxBlockSamples = 2048;
static constexpr int kDiscardCyclesAfterSwitch = 1;

void begin();
void isr555();

bool handleChannels(const String &args);
bool handleRepeat(const String &args);
bool handleBuffer(const String &args);
bool handleRun(const String &args);
void handleStop();
bool handleRb(const String &args);
bool handleRk(const String &args);
bool handleCf(const String &args);
bool handleRxMax(const String &args);
bool handleAscii(const String &args);

void doOneBlock();
void printStatus();

bool isRunning();
bool timedRunExpired();
bool asciiOutput();
uint32_t captureSequenceErrors();

void resetCaptureDiagnostics();
void resetAllChannels();
void muxDisableAll();
void muxEnable(bool en);
void muxSelect(uint8_t ch);
void parkMux(uint8_t ch = 15);

uint32_t computePairTimeoutMs();
bool takeReadyPair(uint32_t &h_cycles, uint32_t &l_cycles);
bool updateChannelRaFromPair(uint8_t ch, uint32_t h_cycles, uint32_t l_cycles, float &out_ra);
float lastPlotRa(uint8_t ch);

double cyclesToUs(uint32_t cycles);
double cyclesFloatToUs(double cycles);
void printChannelTimingDiagnostics(uint8_t ch, const __FlashStringHelper *prefix = nullptr);

}  // namespace pzr_controller
