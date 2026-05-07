#pragma once

#include <Arduino.h>

namespace mg24_proto {

static const uint8_t kCmdFrameLen = 20;
static const uint8_t kAckFrameLen = 4;
static const uint8_t kBlockTrailerLen = 10;
static const uint32_t kMaxPairs = 8000UL;
static const uint32_t kMaxResponseBytes = kAckFrameLen + kMaxPairs * 4UL + kBlockTrailerLen;

static const uint8_t kCmdSetChannels = 0x01;
static const uint8_t kCmdSetRepeat = 0x02;
static const uint8_t kCmdSetBuffer = 0x03;
static const uint8_t kCmdSetRef = 0x04;
static const uint8_t kCmdSetOsr = 0x05;
static const uint8_t kCmdSetGain = 0x06;
static const uint8_t kCmdRun = 0x07;
static const uint8_t kCmdStop = 0x08;
static const uint8_t kCmdMcuId = 0x0A;
static const uint8_t kCmdGroundPin = 0x0B;
static const uint8_t kCmdGroundEn = 0x0C;
static const uint8_t kCmdContinue = 0x0D;

static const uint8_t kBlockMagic1 = 0xAA;
static const uint8_t kBlockMagic2 = 0x55;
static const uint8_t kAckMagic = 0xAC;
static const uint8_t kAckOk = 0x00;
static const uint8_t kAckErr = 0x01;

void makeAck(uint8_t *out_ack, uint8_t status, uint8_t b2, uint8_t b3);

uint32_t encodeBlock(
    uint8_t *dst,
    uint32_t dst_cap,
    const uint16_t *samples,
    uint16_t sample_count,
    uint16_t avg_dt_us,
    uint32_t block_start_us,
    uint32_t block_end_us);

}  // namespace mg24_proto
