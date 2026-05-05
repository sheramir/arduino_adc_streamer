#include "SharedProtocol.h"

#include <math.h>
#include <stdlib.h>

namespace shared_proto {

void writeHostAck(bool ok, const String &args, bool suppress) {
  if (suppress) {
    return;
  }

  if (ok) {
    if (args.length()) {
      Serial.print(F("#OK "));
      Serial.println(args);
    } else {
      Serial.println(F("#OK"));
    }
  } else {
    if (args.length()) {
      Serial.print(F("#NOT_OK "));
      Serial.println(args);
    } else {
      Serial.println(F("#NOT_OK"));
    }
  }
  Serial.flush();
}

bool parseValueSuffix(const String &in_raw, double &out_val, bool is_cap_units) {
  String t = in_raw;
  t.trim();
  t.toLowerCase();
  if (!t.length()) {
    return false;
  }

  if (!is_cap_units) {
    if (t.endsWith("ohm")) {
      t = t.substring(0, t.length() - 3);
      t.trim();
    }
  } else {
    if (t.endsWith("farad")) {
      t = t.substring(0, t.length() - 5);
      t.trim();
    }
    if (t.endsWith("f")) {
      t = t.substring(0, t.length() - 1);
      t.trim();
    }
  }

  double mult = 1.0;
  if (t.length() > 0) {
    char last = t.charAt(t.length() - 1);
    if (!is_cap_units) {
      if (last == 'k') {
        mult = 1e3;
        t.remove(t.length() - 1);
      } else if (last == 'm') {
        mult = 1e6;
        t.remove(t.length() - 1);
      }
    } else {
      if (last == 'p') {
        mult = 1e-12;
        t.remove(t.length() - 1);
      } else if (last == 'n') {
        mult = 1e-9;
        t.remove(t.length() - 1);
      } else if (last == 'u') {
        mult = 1e-6;
        t.remove(t.length() - 1);
      } else if (last == 'm') {
        mult = 1e-3;
        t.remove(t.length() - 1);
      }
    }
  }

  t.trim();
  if (!t.length()) {
    return false;
  }

  char buf[64];
  const size_t n = min(sizeof(buf) - 1, static_cast<size_t>(t.length()));
  for (size_t i = 0; i < n; ++i) {
    buf[i] = t.charAt(static_cast<int>(i));
  }
  buf[n] = '\0';

  char *endp = nullptr;
  const double v = strtod(buf, &endp);
  if (endp == buf) {
    return false;
  }

  out_val = v * mult;
  return isfinite(out_val);
}

uint32_t encodeBinaryBlock(
    uint8_t *dst,
    uint32_t dst_cap,
    const uint16_t *samples,
    uint16_t sample_count,
    uint16_t avg_dt_us,
    uint32_t block_start_us,
    uint32_t block_end_us) {
  const uint32_t payload_bytes = static_cast<uint32_t>(sample_count) * sizeof(uint16_t);
  const uint32_t total_bytes = 4 + payload_bytes + 10;
  if (dst_cap < total_bytes) {
    return 0;
  }

  dst[0] = kBlockMagic1;
  dst[1] = kBlockMagic2;
  dst[2] = static_cast<uint8_t>(sample_count & 0xFF);
  dst[3] = static_cast<uint8_t>((sample_count >> 8) & 0xFF);

  memcpy(dst + 4, samples, payload_bytes);

  uint8_t *trail = dst + 4 + payload_bytes;
  trail[0] = static_cast<uint8_t>(avg_dt_us & 0xFF);
  trail[1] = static_cast<uint8_t>((avg_dt_us >> 8) & 0xFF);

  trail[2] = static_cast<uint8_t>(block_start_us & 0xFF);
  trail[3] = static_cast<uint8_t>((block_start_us >> 8) & 0xFF);
  trail[4] = static_cast<uint8_t>((block_start_us >> 16) & 0xFF);
  trail[5] = static_cast<uint8_t>((block_start_us >> 24) & 0xFF);

  trail[6] = static_cast<uint8_t>(block_end_us & 0xFF);
  trail[7] = static_cast<uint8_t>((block_end_us >> 8) & 0xFF);
  trail[8] = static_cast<uint8_t>((block_end_us >> 16) & 0xFF);
  trail[9] = static_cast<uint8_t>((block_end_us >> 24) & 0xFF);

  return total_bytes;
}

}  // namespace shared_proto
