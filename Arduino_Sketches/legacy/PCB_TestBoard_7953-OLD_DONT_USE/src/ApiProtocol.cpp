#include "ApiProtocol.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

namespace api_protocol {

uint32_t encodeBinaryBlock(
    uint8_t *destination,
    uint32_t capacity,
    const uint16_t *samples,
    uint16_t sample_count,
    uint16_t average_sample_time_us,
    uint32_t block_start_us,
    uint32_t block_end_us) {
  const uint32_t payload_bytes = static_cast<uint32_t>(sample_count) * sizeof(uint16_t);
  const uint32_t total_bytes = 4 + payload_bytes + kTrailerBytes;
  if (destination == nullptr || samples == nullptr || capacity < total_bytes) {
    return 0;
  }

  destination[0] = kBlockMagic1;
  destination[1] = kBlockMagic2;
  destination[2] = static_cast<uint8_t>(sample_count & 0xFF);
  destination[3] = static_cast<uint8_t>(sample_count >> 8);
  memcpy(destination + 4, samples, payload_bytes);

  uint8_t *trailer = destination + 4 + payload_bytes;
  trailer[0] = static_cast<uint8_t>(average_sample_time_us & 0xFF);
  trailer[1] = static_cast<uint8_t>(average_sample_time_us >> 8);
  trailer[2] = static_cast<uint8_t>(block_start_us & 0xFF);
  trailer[3] = static_cast<uint8_t>((block_start_us >> 8) & 0xFF);
  trailer[4] = static_cast<uint8_t>((block_start_us >> 16) & 0xFF);
  trailer[5] = static_cast<uint8_t>((block_start_us >> 24) & 0xFF);
  trailer[6] = static_cast<uint8_t>(block_end_us & 0xFF);
  trailer[7] = static_cast<uint8_t>((block_end_us >> 8) & 0xFF);
  trailer[8] = static_cast<uint8_t>((block_end_us >> 16) & 0xFF);
  trailer[9] = static_cast<uint8_t>((block_end_us >> 24) & 0xFF);
  return total_bytes;
}

void splitCommand(const String &line, String &command, String &arguments) {
  const int separator = line.indexOf(' ');
  if (separator < 0) {
    command = line;
    arguments = "";
  } else {
    command = line.substring(0, separator);
    arguments = line.substring(separator + 1);
  }
  command.trim();
  command.toLowerCase();
  arguments.trim();
}

bool parseScaledValue(const String &text, double &value, bool capacitance_units) {
  String normalized = text;
  normalized.trim();
  normalized.toLowerCase();
  if (!normalized.length()) {
    return false;
  }

  if (!capacitance_units && normalized.endsWith("ohm")) {
    normalized.remove(normalized.length() - 3);
    normalized.trim();
  } else if (capacitance_units) {
    if (normalized.endsWith("farad")) {
      normalized.remove(normalized.length() - 5);
      normalized.trim();
    }
    if (normalized.endsWith("f")) {
      normalized.remove(normalized.length() - 1);
      normalized.trim();
    }
  }
  if (!normalized.length()) return false;

  double multiplier = 1.0;
  const char suffix = normalized.charAt(normalized.length() - 1);
  if (capacitance_units) {
    if (suffix == 'p') multiplier = 1e-12;
    else if (suffix == 'n') multiplier = 1e-9;
    else if (suffix == 'u') multiplier = 1e-6;
    else if (suffix == 'm') multiplier = 1e-3;
  } else {
    if (suffix == 'k') multiplier = 1e3;
    else if (suffix == 'm') multiplier = 1e6;
  }
  if (multiplier != 1.0 || suffix == 'k') {
    normalized.remove(normalized.length() - 1);
  }

  char buffer[48];
  normalized.toCharArray(buffer, sizeof(buffer));
  char *end = nullptr;
  const double parsed = strtod(buffer, &end);
  if (end == buffer || *end != '\0' || !isfinite(parsed)) {
    return false;
  }
  value = parsed * multiplier;
  return isfinite(value);
}

}  // namespace api_protocol
