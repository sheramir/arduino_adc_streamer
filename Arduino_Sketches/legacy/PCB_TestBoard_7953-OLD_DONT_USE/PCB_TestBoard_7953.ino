#include "src/Firmware.h"

// Keep the Arduino sketch itself deliberately small. Hardware, acquisition,
// and host-protocol behavior live in replaceable modules under src/.
void setup() {
  testboard_firmware::setupFirmware();
}

void loop() {
  testboard_firmware::loopFirmware();
}
