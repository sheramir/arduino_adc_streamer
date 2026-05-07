#include "PztController.h"

#include <ctype.h>
#include <stdlib.h>
#include <string.h>

#include "SharedProtocol.h"

namespace pzt_controller {

namespace {

static const uint32_t kAckTimeoutMs = 25;
static const uint32_t kBlockDelayMarginMs = 15;
static const uint32_t kWarmupDelayMarginMs = 10;
static const uint32_t kReadRetryDelayUs = 200;
static const uint16_t kWarmupSweeps = 48;
static const uint32_t kMuxSettleUs = 1;
static const uint32_t kIadcConvUsOsr2 = 8;
static const uint32_t kIadcConvUsOsr4 = 9;
static const uint32_t kIadcConvUsOsr8 = 10;

static uint32_t blockSampleCount(const Config &cfg) {
  return static_cast<uint32_t>(cfg.channel_count) * cfg.repeat_count * cfg.sweeps_per_block * 2u;
}

static uint32_t usPerPair(const Config &cfg) {
  const uint32_t conv = (cfg.osr == 8) ? kIadcConvUsOsr8 : (cfg.osr == 4) ? kIadcConvUsOsr4 : kIadcConvUsOsr2;
  return kMuxSettleUs + (conv * 2u);
}

static uint32_t entriesPerSweep(const Config &cfg) {
  uint32_t entries = static_cast<uint32_t>(cfg.channel_count) * cfg.repeat_count;
  if (cfg.ground_enabled) {
    entries += cfg.channel_count;
  }
  return entries;
}

static uint32_t blockDelayMs(const Config &cfg) {
  const uint32_t entries = entriesPerSweep(cfg) * cfg.sweeps_per_block;
  return (entries * usPerPair(cfg)) / 1000u + kBlockDelayMarginMs;
}

static uint32_t warmupDelayMs(const Config &cfg) {
  const uint32_t entries = static_cast<uint32_t>(kWarmupSweeps) * entriesPerSweep(cfg);
  return (entries * usPerPair(cfg)) / 1000u + kWarmupDelayMarginMs;
}

static uint32_t blockResponseBytes(const Runtime &rt) {
  return static_cast<uint32_t>(kAckFrameLen) + blockSampleCount(rt.cfg) * sizeof(uint16_t) + kTrailerLen;
}

static bool isValidAck(const Runtime &rt, const uint8_t *buf) {
  return buf[0] == rt.ack_magic && (buf[1] == rt.ack_ok || buf[1] == 0x01);
}

static void buildFrame(uint8_t *frame, uint8_t cmd, const uint8_t *args = nullptr, uint8_t nargs = 0) {
  memset(frame, 0, kCmdFrameLen);
  frame[0] = cmd;
  frame[1] = nargs;
  if (args != nullptr && nargs > 0) {
    const uint8_t copy_count = (nargs < (kCmdFrameLen - 2)) ? nargs : (kCmdFrameLen - 2);
    memcpy(frame + 2, args, copy_count);
  }
}

static bool recvAck(Runtime &rt, uint8_t *ack, uint32_t timeout_ms) {
  const uint32_t start = millis();
  while ((millis() - start) < timeout_ms) {
    memset(ack, 0, kAckFrameLen);
    rt.link->recv(ack, kAckFrameLen);
    if (ack[0] == rt.ack_magic) {
      return true;
    }
    delay(1);
  }
  return false;
}

static bool recvStreamingResponse(Runtime &rt, uint8_t *buf, uint32_t len, uint8_t control_byte) {
  for (uint8_t attempt = 0; attempt < 2; ++attempt) {
    rt.link->transferLeadByte(control_byte, buf, len);
    if (isValidAck(rt, buf)) {
      return true;
    }
    if (len >= 2 && buf[0] == shared_proto::kBlockMagic1 && buf[1] == shared_proto::kBlockMagic2) {
      return true;
    }
    delayMicroseconds(kReadRetryDelayUs + static_cast<uint32_t>(attempt) * kReadRetryDelayUs);
  }
  return false;
}

static bool sendCmdAck(Runtime &rt, uint8_t cmd, const uint8_t *args = nullptr, uint8_t nargs = 0) {
  uint8_t frame[kCmdFrameLen];
  buildFrame(frame, cmd, args, nargs);
  rt.link->send(frame, kCmdFrameLen);

  uint8_t ack[kAckFrameLen] = {0};
  if (!recvAck(rt, ack, kAckTimeoutMs)) {
    return false;
  }
  return ack[0] == rt.ack_magic && ack[1] == rt.ack_ok;
}

static bool pollHostStopRequest(char cmd_term, bool &stop_requested) {
  static const char stop_cmd[] = "stop*";
  static uint8_t stop_pos = 0;

  while (Serial.available() > 0) {
    const char c = static_cast<char>(Serial.read());
    const char lower = static_cast<char>(tolower(static_cast<unsigned char>(c)));

    if (lower == stop_cmd[stop_pos]) {
      ++stop_pos;
      if (stop_cmd[stop_pos] == '\0') {
        stop_pos = 0;
        if (!stop_requested) {
          stop_requested = true;
          shared_proto::writeHostAck(true, String(), false);
        }
        return true;
      }
    } else {
      stop_pos = (lower == stop_cmd[0]) ? 1 : 0;
    }

    if (c == cmd_term) {
      stop_pos = 0;
    }
  }

  return stop_requested;
}

}  // namespace

void begin(Runtime &rt, SpiMasterLink &link) {
  rt.link = &link;
}

bool handleChannels(Runtime &rt, const String &args) {
  rt.cfg.channel_count = 0;
  int i = 0;
  const int len = args.length();
  while (i < len && rt.cfg.channel_count < 16) {
    while (i < len && (args[i] == ' ' || args[i] == ',')) {
      ++i;
    }
    if (i >= len) {
      break;
    }

    const int start = i;
    while (i < len && args[i] != ',' && args[i] != ' ') {
      ++i;
    }
    const int v = args.substring(start, i).toInt();
    if (v < 0 || v > 15) {
      return false;
    }
    rt.cfg.channels[rt.cfg.channel_count++] = static_cast<uint8_t>(v);
  }

  if (rt.cfg.channel_count == 0) {
    return false;
  }

  uint8_t payload[17] = {0};
  payload[0] = rt.cfg.channel_count;
  for (uint8_t k = 0; k < rt.cfg.channel_count; ++k) {
    payload[1 + k] = rt.cfg.channels[k];
  }
  return sendCmdAck(rt, kCmdSetChannels, payload, static_cast<uint8_t>(rt.cfg.channel_count + 1));
}

bool handleRepeat(Runtime &rt, const String &args) {
  const long v = constrain(args.toInt(), 1L, 100L);
  rt.cfg.repeat_count = static_cast<uint8_t>(v);
  const uint8_t arg = rt.cfg.repeat_count;
  return sendCmdAck(rt, kCmdSetRepeat, &arg, 1);
}

bool handleBuffer(Runtime &rt, const String &args) {
  const long v = max(1L, args.toInt());
  rt.cfg.sweeps_per_block = static_cast<uint8_t>(min(v, 255L));
  const uint8_t arg = rt.cfg.sweeps_per_block;
  return sendCmdAck(rt, kCmdSetBuffer, &arg, 1);
}

bool handleRef(Runtime &rt, const String &args) {
  String a = args;
  a.trim();
  a.toLowerCase();

  uint8_t ref_val = 0;
  if (a == "1.2" || a == "1v2") {
    ref_val = 0;
    rt.cfg.ref = 0;
  } else if (a == "3.3" || a == "vdd") {
    ref_val = 1;
    rt.cfg.ref = 1;
  } else {
    Serial.println(F("# ERROR: only ref 1.2 and ref 3.3/vdd are supported"));
    return false;
  }

  return sendCmdAck(rt, kCmdSetRef, &ref_val, 1);
}

bool handleOsr(Runtime &rt, const String &args) {
  const long v = args.toInt();
  if (v != 2 && v != 4 && v != 8) {
    Serial.println(F("# ERROR: osr must be 2, 4, or 8"));
    return false;
  }
  rt.cfg.osr = static_cast<uint8_t>(v);
  const uint8_t arg = rt.cfg.osr;
  return sendCmdAck(rt, kCmdSetOsr, &arg, 1);
}

bool handleGain(Runtime &rt, const String &args) {
  const long v = args.toInt();
  if (v < 1 || v > 4) {
    Serial.println(F("# ERROR: gain must be 1, 2, 3, or 4"));
    return false;
  }
  rt.cfg.gain = static_cast<uint8_t>(v);
  const uint8_t arg = rt.cfg.gain;
  return sendCmdAck(rt, kCmdSetGain, &arg, 1);
}

bool handleGround(Runtime &rt, const String &args) {
  String a = args;
  a.trim();
  a.toLowerCase();

  if (a == "true") {
    rt.cfg.ground_enabled = true;
    const uint8_t arg = 1;
    return sendCmdAck(rt, kCmdGroundEn, &arg, 1);
  }
  if (a == "false") {
    rt.cfg.ground_enabled = false;
    const uint8_t arg = 0;
    return sendCmdAck(rt, kCmdGroundEn, &arg, 1);
  }

  const long v = a.toInt();
  if (v < 0 || v > 15) {
    Serial.println(F("# ERROR: ground channel out of range (0-15)"));
    return false;
  }

  rt.cfg.ground_pin = static_cast<uint8_t>(v);
  rt.cfg.ground_enabled = true;
  const uint8_t arg = rt.cfg.ground_pin;
  return sendCmdAck(rt, kCmdGroundPin, &arg, 1);
}

void printStatus(const Runtime &rt) {
  Serial.println(F("# -------- STATUS (PZT mode, modular) --------"));
  Serial.println(F("# mcu: Array_PZT_PZR1 (Teensy modular PZT controller)"));
  Serial.print(F("# running: "));
  Serial.println(rt.cfg.running ? F("true") : F("false"));
  Serial.print(F("# channels (count="));
  Serial.print(rt.cfg.channel_count);
  Serial.println(F("):"));
  Serial.print(F("#   "));
  for (uint8_t i = 0; i < rt.cfg.channel_count; ++i) {
    Serial.print(rt.cfg.channels[i]);
    if (i + 1 < rt.cfg.channel_count) {
      Serial.print(',');
    }
  }
  Serial.println();
  Serial.print(F("# repeatCount: "));
  Serial.println(rt.cfg.repeat_count);
  Serial.print(F("# sweepsPerBlock: "));
  Serial.println(rt.cfg.sweeps_per_block);
  Serial.print(F("# ref: "));
  Serial.println(rt.cfg.ref == 0 ? F("1.2V") : F("VDD/3.3V"));
  Serial.print(F("# osr: "));
  Serial.println(rt.cfg.osr);
  Serial.print(F("# gain: "));
  Serial.print(rt.cfg.gain);
  Serial.println('x');
  Serial.print(F("# groundPin: "));
  Serial.println(rt.cfg.ground_pin);
  Serial.print(F("# groundEnable: "));
  Serial.println(rt.cfg.ground_enabled ? F("true") : F("false"));
  Serial.print(F("# samplesPerBlock (MUX1+MUX2 interleaved): "));
  Serial.println(blockSampleCount(rt.cfg));
  Serial.print(F("# estimatedBlockDelayMs: "));
  Serial.println(blockDelayMs(rt.cfg));
  Serial.println(F("# NOTE: each channel slot yields 2 samples [MUX1_val, MUX2_val]"));
  Serial.println(F("# --------------------------------------------"));
}

void requestStop(Runtime &rt) {
  rt.cfg.running = false;
}

bool runBlocking(Runtime &rt, const String &args, char cmd_term) {
  if (rt.cfg.channel_count == 0) {
    Serial.println(F("# ERROR: no channels configured"));
    shared_proto::writeHostAck(false, args, false);
    return false;
  }

  const uint32_t block_bytes = blockResponseBytes(rt);
  if (block_bytes <= kAckFrameLen || blockSampleCount(rt.cfg) == 0 || blockSampleCount(rt.cfg) > rt.max_pairs * 2u) {
    shared_proto::writeHostAck(false, args, false);
    return false;
  }

  uint8_t *block = static_cast<uint8_t *>(malloc(block_bytes));
  if (block == nullptr) {
    shared_proto::writeHostAck(false, args, false);
    return false;
  }

  uint32_t run_ms = 0;
  bool timed = false;
  if (args.length() > 0) {
    const long v = args.toInt();
    if (v > 0) {
      run_ms = static_cast<uint32_t>(v);
      timed = true;
    }
  }

  uint8_t frame[kCmdFrameLen];
  buildFrame(frame, kCmdRun);
  if (timed) {
    frame[1] = 4;
    frame[2] = static_cast<uint8_t>(run_ms & 0xFF);
    frame[3] = static_cast<uint8_t>((run_ms >> 8) & 0xFF);
    frame[4] = static_cast<uint8_t>((run_ms >> 16) & 0xFF);
    frame[5] = static_cast<uint8_t>((run_ms >> 24) & 0xFF);
  }
  rt.link->send(frame, kCmdFrameLen);

  delay(warmupDelayMs(rt.cfg) + blockDelayMs(rt.cfg));
  if (!recvStreamingResponse(rt, block, block_bytes, kCmdContinue) ||
      !(block[0] == shared_proto::kBlockMagic1 && block[1] == shared_proto::kBlockMagic2)) {
    free(block);
    shared_proto::writeHostAck(false, args, false);
    rt.cfg.running = false;
    return false;
  }

  rt.cfg.running = true;
  shared_proto::writeHostAck(true, args, false);
  bool run_ack_sent = true;
  Serial.write(block, block_bytes);

  const uint32_t run_start = millis();
  bool stop_requested = false;
  bool stop_sent = false;

  while (rt.cfg.running) {
    if (!stop_requested && timed && (millis() - run_start) >= run_ms) {
      stop_requested = true;
    }
    if (!stop_requested) {
      pollHostStopRequest(cmd_term, stop_requested);
    }

    delay(blockDelayMs(rt.cfg));

    const uint8_t control_byte = (stop_requested && !stop_sent) ? kCmdStop : kCmdContinue;
    if (!recvStreamingResponse(rt, block, block_bytes, control_byte)) {
      free(block);
      if (run_ack_sent) {
        Serial.println(F("# WARN: PZT stream fault; stream response timed out"));
      } else {
        shared_proto::writeHostAck(false, args, false);
      }
      rt.cfg.running = false;
      return false;
    }

    if (isValidAck(rt, block)) {
      rt.cfg.running = false;
      break;
    }

    if (!(block[0] == shared_proto::kBlockMagic1 && block[1] == shared_proto::kBlockMagic2)) {
      free(block);
      if (run_ack_sent) {
        Serial.println(F("# WARN: PZT stream fault; invalid block header"));
      } else {
        shared_proto::writeHostAck(false, args, false);
      }
      rt.cfg.running = false;
      return false;
    }

    Serial.write(block, block_bytes);

    if (control_byte == kCmdStop) {
      stop_sent = true;
      delay(blockDelayMs(rt.cfg));

      uint8_t ack[kAckFrameLen] = {0};
      const uint32_t final_ack_timeout = (kAckTimeoutMs > blockDelayMs(rt.cfg)) ? kAckTimeoutMs : blockDelayMs(rt.cfg);
      if (!recvAck(rt, ack, final_ack_timeout) ||
          !(ack[0] == rt.ack_magic && ack[1] == rt.ack_ok)) {
        free(block);
        if (run_ack_sent) {
          Serial.println(F("# WARN: PZT stream fault; final stop ack missing"));
        } else {
          shared_proto::writeHostAck(false, args, false);
        }
        rt.cfg.running = false;
        return false;
      }

      rt.cfg.running = false;
      break;
    }

    yield();
  }

  free(block);
  rt.cfg.running = false;
  return true;
}

}  // namespace pzt_controller
