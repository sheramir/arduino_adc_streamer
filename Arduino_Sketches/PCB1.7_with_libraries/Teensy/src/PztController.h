#pragma once

#include <Arduino.h>

namespace pzt_controller {

void begin();
void setCombinedMode(bool enabled);
bool combinedMode();

bool handleChannels(const String &args);
bool handlePztMuxes(const String &args);
bool handleRsChannels(const String &args);
bool handleRepeat(const String &args);
bool handleBuffer(const String &args);
bool handleRef(const String &args);
bool handleOsr(const String &args);
bool handleGain(const String &args);
bool handleGround(const String &args);
void handleRun(const String &args);

void requestStop();
bool isRunning();
void printStatus();

}  // namespace pzt_controller
