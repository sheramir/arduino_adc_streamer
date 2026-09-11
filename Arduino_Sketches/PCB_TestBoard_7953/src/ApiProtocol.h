#pragma once

#include <Arduino.h>

namespace api_protocol {

static constexpr char kCommandTerminator = '*';
static constexpr uint16_t kMaxCommandLength = 512;
static constexpr uint8_t kBlockMagic1 = 0xAA;
static constexpr uint8_t kBlockMagic2 = 0x55;
static constexpr uint8_t kTrailerBytes = 10;

uint32_t encodeBinaryBlock(
    uint8_t *destination,
    uint32_t capacity,
    const uint16_t *samples,
    uint16_t sample_count,
    uint16_t average_sample_time_us,
    uint32_t block_start_us,
    uint32_t block_end_us);

void splitCommand(const String &line, String &command, String &arguments);
bool parseScaledValue(const String &text, double &value, bool capacitance_units);

}  // namespace api_protocol
