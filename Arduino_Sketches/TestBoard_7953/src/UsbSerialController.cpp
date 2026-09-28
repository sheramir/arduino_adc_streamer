#include "UsbSerialController.h"

#include "ApiProtocol.h"

void UsbSerialController::begin(uint32_t baud) {
  Serial.begin(baud);
  input_.reserve(api_protocol::kMaxCommandLength);
}

bool UsbSerialController::readCommand(String &line) {
  while (Serial.available() > 0) {
    const char value = static_cast<char>(Serial.read());
    if (value == '\r' || value == '\n') {
      continue;
    }
    if (value == api_protocol::kCommandTerminator) {
      line = input_;
      input_ = "";
      return true;
    }
    if (input_.length() < api_protocol::kMaxCommandLength) {
      input_ += value;
    } else {
      input_ = "";
    }
  }
  return false;
}

void UsbSerialController::writeAck(bool success, const String &arguments) {
  Serial.print(success ? F("#OK") : F("#NOT_OK"));
  if (arguments.length()) {
    Serial.print(' ');
    Serial.print(arguments);
  }
  Serial.println();
  Serial.flush();
}

void UsbSerialController::writeBinaryBlock(const uint8_t *data, uint32_t length) {
  Serial.write(data, length);
  // Do not flush binary traffic. Teensy USB queues these bytes, allowing the
  // next acquisition to begin while the USB peripheral drains its buffer.
}

void UsbSerialController::beginBinaryBlock(uint16_t sample_count) {
  const uint8_t header[] = {
      api_protocol::kBlockMagic1,
      api_protocol::kBlockMagic2,
      static_cast<uint8_t>(sample_count & 0xFF),
      static_cast<uint8_t>(sample_count >> 8),
  };
  Serial.write(header, sizeof(header));
}

void UsbSerialController::writeBinarySamples(
    const uint16_t *samples, uint16_t sample_count) {
  Serial.write(
      reinterpret_cast<const uint8_t *>(samples),
      static_cast<size_t>(sample_count) * sizeof(uint16_t));
}

void UsbSerialController::endBinaryBlock(
    uint16_t average_sample_time_us,
    uint32_t block_start_us,
    uint32_t block_end_us) {
  const uint8_t trailer[] = {
      static_cast<uint8_t>(average_sample_time_us & 0xFF),
      static_cast<uint8_t>(average_sample_time_us >> 8),
      static_cast<uint8_t>(block_start_us & 0xFF),
      static_cast<uint8_t>((block_start_us >> 8) & 0xFF),
      static_cast<uint8_t>((block_start_us >> 16) & 0xFF),
      static_cast<uint8_t>((block_start_us >> 24) & 0xFF),
      static_cast<uint8_t>(block_end_us & 0xFF),
      static_cast<uint8_t>((block_end_us >> 8) & 0xFF),
      static_cast<uint8_t>((block_end_us >> 16) & 0xFF),
      static_cast<uint8_t>((block_end_us >> 24) & 0xFF),
  };
  Serial.write(trailer, sizeof(trailer));
}
