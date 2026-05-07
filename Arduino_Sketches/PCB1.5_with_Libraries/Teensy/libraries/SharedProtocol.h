#pragma once

#include <Arduino.h>

namespace shared_proto {

static const uint32_t kSerialBaud = 460800;
static const char kCmdTerm = '*';
static const uint16_t kMaxCmdLen = 512;

static const uint8_t kBlockMagic1 = 0xAA;
static const uint8_t kBlockMagic2 = 0x55;
static const uint8_t kAckMagic = 0xAC;

void writeHostAck(bool ok, const String &args, bool suppress);

bool parseValueSuffix(const String &in_raw, double &out_val, bool is_cap_units);

uint32_t encodeBinaryBlock(
    uint8_t *dst,
    uint32_t dst_cap,
    const uint16_t *samples,
    uint16_t sample_count,
    uint16_t avg_dt_us,
    uint32_t block_start_us,
    uint32_t block_end_us);

}  // namespace shared_proto
