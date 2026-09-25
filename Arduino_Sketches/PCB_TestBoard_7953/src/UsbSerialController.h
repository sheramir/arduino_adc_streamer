#pragma once

#include <Arduino.h>

class UsbSerialController {
 public:
  void begin(uint32_t baud);
  bool readCommand(String &line);
  void writeAck(bool success, const String &arguments = "");
  void writeBinaryBlock(const uint8_t *data, uint32_t length);
  void beginBinaryBlock(uint16_t sample_count);
  void writeBinarySamples(const uint16_t *samples, uint16_t sample_count);
  void endBinaryBlock(
      uint16_t average_sample_time_us,
      uint32_t block_start_us,
      uint32_t block_end_us);

 private:
  String input_;
};
