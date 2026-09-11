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
  Serial.flush();
}
