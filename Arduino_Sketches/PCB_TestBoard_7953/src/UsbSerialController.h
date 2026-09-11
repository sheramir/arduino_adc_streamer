#pragma once

#include <Arduino.h>

class UsbSerialController {
 public:
  void begin(uint32_t baud);
  bool readCommand(String &line);
  void writeAck(bool success, const String &arguments = "");
  void writeBinaryBlock(const uint8_t *data, uint32_t length);

 private:
  String input_;
};
