#include <Arduino.h>

#include "Firmware.h"

void setup() {
  testboard_firmware::setupFirmware();
}

void loop() {
  testboard_firmware::loopFirmware();
}