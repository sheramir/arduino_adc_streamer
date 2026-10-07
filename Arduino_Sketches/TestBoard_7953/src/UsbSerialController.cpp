#include "UsbSerialController.h"

#include "ApiProtocol.h"

// Provided by the project-local, audited Teensy core patch. No fallback to
// Serial.write(): it can wait up to 120 ms when the host stops accepting data.
extern "C" int usb_serial_try_write_frame(const void *buffer, uint32_t size);

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

bool UsbSerialController::writeBinaryBlock(const uint8_t *data, uint32_t length) {
  // Do not flush binary traffic. Teensy USB queues these bytes, allowing the
  // next acquisition to begin while the USB peripheral drains its buffer.
  if (Serial.write(data, length) != length) {
    ++write_errors_;
    return false;
  }
  return true;
}

UsbSerialController::FrameWrite UsbSerialController::tryWriteBinaryBlock(
    const uint8_t *data, uint32_t length) {
  const int written = usb_serial_try_write_frame(data, length);
  if (written == static_cast<int>(length)) return FrameWrite::Sent;
  if (written == 0) return FrameWrite::Discarded;
  ++write_errors_;
  return FrameWrite::Error;
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
