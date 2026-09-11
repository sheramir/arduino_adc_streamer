#include "PztController.h"

#include <ctype.h>
#include <stdlib.h>
#include <string.h>

#ifndef DMAMEM
#define DMAMEM
#endif

#include "../BoardConfig.h"
#include "PzrController.h"
#include "PztRsController.h"
#include "SharedProtocol.h"
#include "SpiMasterLink.h"

namespace pzt_controller {

namespace {

static const bool kDebugTextStream = false;
static const uint32_t kDrdyAckTimeoutMs = 25;
static const uint32_t kDrdyMarginMs = 25;
static const uint32_t kStreamIdleSlackMs = 100;
static const uint8_t kRxQueueDepth = 4;

static const uint8_t kCmdFrameLen = 20;
static const uint8_t kAckFrameLen = 4;
static const uint8_t kBlockTrailerLen = 10;
static const uint8_t kAckMagic = 0xAC;
static const uint8_t kAckStatusOk = 0x00;

static const uint32_t kMuxSettleUs = 20;
static const uint32_t kIadcConvUsOsr2 = 8;
static const uint32_t kIadcConvUsOsr4 = 9;
static const uint32_t kIadcConvUsOsr8 = 10;
static const uint32_t kBlockDelayMarginMs = 15;
static const uint32_t kWarmupDelayMarginMs = 10;
static const uint32_t kPztRsFirstBlockMinTimeoutMs = 500;
static const uint16_t kWarmupSweeps = 48;

static const uint16_t kMaxRepeat = 100;
static const uint8_t kMuxChMax = 15;
static const uint8_t kMaxPhysicalChannels = 16;
static const uint8_t kMaxLogicalSlots = 32;
static const uint32_t kMaxPairs = 6000UL;
static const uint32_t kMaxBlockBytes = static_cast<uint32_t>(kAckFrameLen) + kMaxPairs * 4UL + kBlockTrailerLen;

static const uint8_t kCmdSetChannels = 0x01;
static const uint8_t kCmdSetRepeat = 0x02;
static const uint8_t kCmdSetBuffer = 0x03;
static const uint8_t kCmdSetRef = 0x04;
static const uint8_t kCmdSetOsr = 0x05;
static const uint8_t kCmdSetGain = 0x06;
static const uint8_t kCmdRun = 0x07;
static const uint8_t kCmdStop = 0x08;
static const uint8_t kCmdGroundPin = 0x0B;
static const uint8_t kCmdGroundEn = 0x0C;
static const uint8_t kStreamContinue = 0x0D;

struct Config {
  uint8_t channels[kMaxLogicalSlots];
  uint8_t physical_channels[kMaxPhysicalChannels];
  uint8_t channel_count = 0;
  uint8_t physical_channel_count = 0;
  uint8_t repeat_count = 1;
  uint8_t sweeps_per_block = 1;
  uint8_t osr = 2;
  uint8_t gain = 1;
  uint8_t ref = 1;
  uint8_t ground_pin = 0;
  bool ground_enable = false;
  bool running = false;
} g_pzt;

struct QueuedBlock {
  uint32_t len = 0;
  uint32_t tx_offset = 0;
  uint8_t data[pzt_rs_controller::kMaxBlockBytes];
};

static SpiMasterLink g_spi;
static bool g_combined_mode = false;
static QueuedBlock g_rx_queue[kRxQueueDepth] DMAMEM;
static uint8_t g_rx_head = 0;
static uint8_t g_rx_tail = 0;
static uint8_t g_rx_count = 0;
static uint32_t g_stream_block_bytes = 0;
static uint32_t g_stream_last_activity = 0;
static bool g_stop_requested = false;
static bool g_stop_control_sent = false;
static bool g_waiting_final_ack = false;
static bool g_remote_ended = false;
static bool g_stream_fault = false;
static uint32_t g_last_fallback_poll_ms = 0;
static uint8_t g_stop_match_pos = 0;
static uint8_t g_consecutive_rx_errors = 0;
static uint32_t g_transient_rx_errors_total = 0;
static uint32_t g_run_start_ms = 0;
static uint32_t g_blocks_from_drdy = 0;
static uint32_t g_blocks_from_fallback = 0;
static uint32_t g_acks_from_drdy = 0;
static uint32_t g_acks_from_fallback = 0;
static uint32_t g_drdy_read_attempts = 0;
static uint32_t g_drdy_read_timeouts = 0;
static uint32_t g_fallback_poll_attempts = 0;
static uint32_t g_fallback_poll_timeouts = 0;
static uint8_t g_pzt_rs_block_buf[pzt_rs_controller::kMaxBlockBytes] DMAMEM;

static uint8_t physicalChannelCount() {
  return (g_combined_mode && g_pzt.physical_channel_count > 0)
             ? g_pzt.physical_channel_count
             : g_pzt.channel_count;
}

static int8_t physicalIndexForChannel(uint8_t ch) {
  for (uint8_t i = 0; i < g_pzt.physical_channel_count; ++i) {
    if ((g_pzt.physical_channels[i] & 0x0F) == (ch & 0x0F)) {
      return static_cast<int8_t>(i);
    }
  }
  return -1;
}

static inline bool queueIsEmpty() {
  return g_rx_count == 0;
}

static inline bool queueIsFull() {
  return g_rx_count >= kRxQueueDepth;
}

static QueuedBlock *queueFront() {
  return queueIsEmpty() ? nullptr : &g_rx_queue[g_rx_head];
}

static QueuedBlock *queueWriteSlot() {
  return queueIsFull() ? nullptr : &g_rx_queue[g_rx_tail];
}

static void queueCommitWrite(uint32_t len) {
  g_rx_queue[g_rx_tail].len = len;
  g_rx_queue[g_rx_tail].tx_offset = 0;
  g_rx_tail = static_cast<uint8_t>((g_rx_tail + 1u) % kRxQueueDepth);
  g_rx_count++;
}

static void queuePopFront() {
  if (queueIsEmpty()) {
    return;
  }
  g_rx_queue[g_rx_head].len = 0;
  g_rx_queue[g_rx_head].tx_offset = 0;
  g_rx_head = static_cast<uint8_t>((g_rx_head + 1u) % kRxQueueDepth);
  g_rx_count--;
}

static bool isValidAckFrame(const uint8_t *buf) {
  return buf[0] == kAckMagic && (buf[1] == kAckStatusOk || buf[1] == 0x01);
}

static void streamResetState() {
  g_rx_head = 0;
  g_rx_tail = 0;
  g_rx_count = 0;
  g_stream_block_bytes = 0;
  g_stop_requested = false;
  g_stop_control_sent = false;
  g_waiting_final_ack = false;
  g_remote_ended = false;
  g_stream_fault = false;
  g_last_fallback_poll_ms = millis();
  g_stop_match_pos = 0;
  g_consecutive_rx_errors = 0;
  g_transient_rx_errors_total = 0;
  g_run_start_ms = millis();
  g_blocks_from_drdy = 0;
  g_blocks_from_fallback = 0;
  g_acks_from_drdy = 0;
  g_acks_from_fallback = 0;
  g_drdy_read_attempts = 0;
  g_drdy_read_timeouts = 0;
  g_fallback_poll_attempts = 0;
  g_fallback_poll_timeouts = 0;
  g_stream_last_activity = millis();
  g_spi.drdyClearAll();
  pzt_rs_controller::stopRefresh();
}

static bool recordRxError(const __FlashStringHelper *reason) {
  (void)reason;
  g_consecutive_rx_errors++;
  g_transient_rx_errors_total++;
  return g_consecutive_rx_errors >= 4;
}

static inline void clearRxErrors() {
  g_consecutive_rx_errors = 0;
}

static void logStreamSummary() {
  const uint32_t total_blocks = g_blocks_from_drdy + g_blocks_from_fallback;
  const uint32_t elapsed_ms = millis() - g_run_start_ms;

  uint32_t drdy_pct = 0;
  uint32_t fallback_pct = 0;
  if (total_blocks > 0) {
    drdy_pct = static_cast<uint32_t>((100UL * g_blocks_from_drdy) / total_blocks);
    fallback_pct = 100UL - drdy_pct;
  }

  Serial.print(F("# INFO: PZT stream summary: elapsed_ms="));
  Serial.print(elapsed_ms);
  Serial.print(F(", blocks_total="));
  Serial.print(total_blocks);
  Serial.print(F(", drdy_blocks="));
  Serial.print(g_blocks_from_drdy);
  Serial.print(F(" ("));
  Serial.print(drdy_pct);
  Serial.print(F("%), fallback_blocks="));
  Serial.print(g_blocks_from_fallback);
  Serial.print(F(" ("));
  Serial.print(fallback_pct);
  Serial.print(F("%), drdy_reads="));
  Serial.print(g_drdy_read_attempts);
  Serial.print(F(", drdy_timeouts="));
  Serial.print(g_drdy_read_timeouts);
  Serial.print(F(", fallback_polls="));
  Serial.print(g_fallback_poll_attempts);
  Serial.print(F(", fallback_timeouts="));
  Serial.print(g_fallback_poll_timeouts);
  Serial.print(F(", drdy_acks="));
  Serial.print(g_acks_from_drdy);
  Serial.print(F(", fallback_acks="));
  Serial.print(g_acks_from_fallback);
  Serial.print(F(", transient_rx_errors="));
  Serial.print(g_transient_rx_errors_total);
  Serial.print(F(", capture_sequence_errors="));
  Serial.println(pzr_controller::captureSequenceErrors());

  if (g_combined_mode) {
    pzt_rs_controller::printStreamDiagnostics();
  }
}

static bool handleStreamingFrame(QueuedBlock *slot, bool from_drdy) {
  g_stream_last_activity = millis();
  clearRxErrors();

  if (slot->data[0] == kAckMagic) {
    if (!isValidAckFrame(slot->data)) {
      const __FlashStringHelper *reason = from_drdy ? F("drdy-bad-ack") : F("fallback-bad-ack");
      if (recordRxError(reason)) {
        g_stream_fault = true;
        g_pzt.running = false;
      }
      return false;
    }

    if (g_waiting_final_ack) {
      g_waiting_final_ack = false;
    }
    if (from_drdy) {
      g_acks_from_drdy++;
    } else {
      g_acks_from_fallback++;
    }
    g_remote_ended = true;
    g_pzt.running = false;
    return false;
  }

  if (slot->data[0] != shared_proto::kBlockMagic1 || slot->data[1] != shared_proto::kBlockMagic2) {
    const __FlashStringHelper *reason = from_drdy ? F("drdy-bad-magic") : F("fallback-bad-magic");
    if (recordRxError(reason)) {
      g_stream_fault = true;
      g_pzt.running = false;
    }
    return false;
  }

  uint32_t queued_len = g_stream_block_bytes;
  if (g_combined_mode) {
    uint16_t rs_held_snapshot[16];
    pzt_rs_controller::serviceRefresh(false);
    pzt_rs_controller::snapshotHeldValues(rs_held_snapshot);
    if (!pzt_rs_controller::buildCombinedBlock(
            slot->data,
            g_stream_block_bytes,
            g_pzt_rs_block_buf,
            queued_len,
            rs_held_snapshot,
            g_pzt.channels,
            g_pzt.channel_count,
            g_pzt.physical_channels,
            physicalChannelCount(),
            g_pzt.repeat_count)) {
      g_stream_fault = true;
      g_pzt.running = false;
      return false;
    }
    memcpy(slot->data, g_pzt_rs_block_buf, queued_len);
  }

  queueCommitWrite(queued_len);
  if (from_drdy) {
    g_blocks_from_drdy++;
  } else {
    g_blocks_from_fallback++;
  }
  return true;
}

static void serviceSpiRxFallbackPoll() {
  if (queueIsFull()) {
    return;
  }

  g_fallback_poll_attempts++;

  if (g_waiting_final_ack) {
    uint8_t ack[kAckFrameLen] = {0};
    g_spi.recv(ack, kAckFrameLen);
    g_stream_last_activity = millis();
    g_waiting_final_ack = false;
    g_pzt.running = false;
    if (!(ack[0] == kAckMagic && ack[1] == kAckStatusOk)) {
      if (recordRxError(F("final-ack"))) {
        g_stream_fault = true;
      }
    } else {
      g_acks_from_fallback++;
      clearRxErrors();
    }
    return;
  }

  QueuedBlock *slot = queueWriteSlot();
  if (!slot) {
    return;
  }

  uint8_t control_byte = kStreamContinue;
  if (g_stop_requested && !g_stop_control_sent) {
    control_byte = kCmdStop;
    g_stop_control_sent = true;
    g_waiting_final_ack = true;
    g_pzt.running = false;
  }

  if (!g_spi.recvStreamingResponse(
          slot->data,
          static_cast<uint16_t>(min(g_stream_block_bytes, static_cast<uint32_t>(sizeof(slot->data)))),
          control_byte,
          1,
          kAckMagic,
          shared_proto::kBlockMagic1,
          shared_proto::kBlockMagic2)) {
    g_fallback_poll_timeouts++;
    if (recordRxError(F("fallback-timeout"))) {
      g_stream_fault = true;
      g_pzt.running = false;
    }
    return;
  }

  (void)handleStreamingFrame(slot, false);
}

static void writeBlockBuffered(const uint8_t *buf, uint32_t len) {
  uint32_t offset = 0;
  while (offset < len) {
    const int avail = Serial.availableForWrite();
    if (avail <= 0) {
      yield();
      continue;
    }
    const uint32_t chunk = min(static_cast<uint32_t>(avail), len - offset);
    offset += static_cast<uint32_t>(Serial.write(buf + offset, chunk));
  }
}

static void emitBlock(const uint8_t *buf, uint32_t len) {
  if (!kDebugTextStream) {
    writeBlockBuffered(buf, len);
    return;
  }
  if (len < static_cast<uint32_t>(kAckFrameLen) + kBlockTrailerLen) {
    Serial.println(F("#DBG short block"));
    Serial.flush();
    return;
  }
  if (buf[0] != shared_proto::kBlockMagic1 || buf[1] != shared_proto::kBlockMagic2) {
    Serial.print(F("#DBG bad magic: 0x"));
    Serial.print(buf[0], HEX);
    Serial.print(F(" 0x"));
    Serial.println(buf[1], HEX);
    Serial.flush();
    return;
  }
  const uint16_t n = static_cast<uint16_t>(buf[2]) | (static_cast<uint16_t>(buf[3]) << 8);
  Serial.print(F("#DBG block samples="));
  Serial.println(n);
  Serial.flush();
}

static void serviceUsbTx() {
  if (kDebugTextStream) {
    QueuedBlock *blk = queueFront();
    if (!blk) {
      return;
    }
    emitBlock(blk->data, blk->len);
    queuePopFront();
    return;
  }

  QueuedBlock *blk = queueFront();
  if (!blk) {
    return;
  }

  const int avail = Serial.availableForWrite();
  if (avail <= 0) {
    return;
  }

  const uint32_t remaining = blk->len - blk->tx_offset;
  const uint32_t chunk = min(static_cast<uint32_t>(avail), remaining);
  blk->tx_offset += static_cast<uint32_t>(Serial.write(blk->data + blk->tx_offset, chunk));
  if (blk->tx_offset >= blk->len) {
    queuePopFront();
  }
}

static void pollStreamStopRequest() {
  static const char stop_cmd[] = "stop*";
  while (Serial.available() > 0) {
    const char c = static_cast<char>(Serial.read());
    if (c == stop_cmd[g_stop_match_pos]) {
      g_stop_match_pos++;
      if (g_stop_match_pos >= (sizeof(stop_cmd) - 1)) {
        if (!g_stop_requested) {
          g_stop_requested = true;
          Serial.println(F("#OK"));
        }
        g_stop_match_pos = 0;
      }
    } else {
      g_stop_match_pos = (c == stop_cmd[0]) ? 1 : 0;
    }
  }
}

static void serviceSpiRx() {
  while (g_spi.drdyPending()) {
    if (g_waiting_final_ack) {
      uint8_t ack[kAckFrameLen] = {0};
      g_spi.drdyConsumeOne();
      g_spi.recv(ack, kAckFrameLen);
      g_stream_last_activity = millis();
      g_waiting_final_ack = false;
      g_pzt.running = false;
      if (!(ack[0] == kAckMagic && ack[1] == kAckStatusOk)) {
        g_stream_fault = true;
      }
      return;
    }

    if (queueIsFull()) {
      return;
    }

    QueuedBlock *slot = queueWriteSlot();
    if (!slot) {
      return;
    }

    uint8_t control_byte = kStreamContinue;
    if (g_stop_requested && !g_stop_control_sent) {
      control_byte = kCmdStop;
      g_stop_control_sent = true;
      g_waiting_final_ack = true;
      g_pzt.running = false;
    }

    g_spi.drdyConsumeOne();
    g_drdy_read_attempts++;
    if (!g_spi.recvStreamingResponse(
            slot->data,
            static_cast<uint16_t>(min(g_stream_block_bytes, static_cast<uint32_t>(sizeof(slot->data)))),
            control_byte,
            1,
            kAckMagic,
            shared_proto::kBlockMagic1,
            shared_proto::kBlockMagic2)) {
      g_drdy_read_timeouts++;
      if (recordRxError(F("drdy-timeout"))) {
        g_stream_fault = true;
        g_pzt.running = false;
      }
      return;
    }

    if (!handleStreamingFrame(slot, true)) {
      return;
    }

    if (g_stop_control_sent) {
      return;
    }
  }
}

static void discardPendingTerminators(uint32_t settle_ms = 10) {
  const uint32_t start = millis();
  while ((millis() - start) < settle_ms) {
    while (Serial.available() > 0) {
      Serial.read();
    }
    delay(1);
  }
}

static void sendCmd(uint8_t cmd, const uint8_t *args = nullptr, uint8_t nargs = 0) {
  uint8_t frame[kCmdFrameLen];
  memset(frame, 0, kCmdFrameLen);
  frame[0] = cmd;
  frame[1] = nargs;
  if (args && nargs > 0) {
    const uint8_t n = min(nargs, static_cast<uint8_t>(kCmdFrameLen - 2));
    memcpy(frame + 2, args, n);
  }
  g_spi.drdyClearAll();
  g_spi.send(frame, kCmdFrameLen);
}

static bool recvAckWhenReady(uint8_t *buf, uint32_t timeout_ms) {
  if (!g_spi.waitForDrdy(timeout_ms)) {
    return false;
  }
  g_spi.drdyConsumeOne();
  g_spi.recv(buf, kAckFrameLen);
  return (buf[0] == kAckMagic);
}

static bool sendCmdAck(uint8_t cmd, const uint8_t *args = nullptr, uint8_t nargs = 0) {
  sendCmd(cmd, args, nargs);
  uint8_t ack[kAckFrameLen] = {0};
  if (!recvAckWhenReady(ack, kDrdyAckTimeoutMs)) {
    return false;
  }
  return (ack[0] == kAckMagic && ack[1] == kAckStatusOk);
}

static uint32_t usPerPair() {
  const uint32_t conv = (g_pzt.osr == 8) ? kIadcConvUsOsr8 : (g_pzt.osr == 4) ? kIadcConvUsOsr4 : kIadcConvUsOsr2;
  return kMuxSettleUs + conv * 2u;
}

static uint32_t entriesPerSweep() {
  uint32_t entries = static_cast<uint32_t>(physicalChannelCount()) * g_pzt.repeat_count;
  if (g_pzt.ground_enable) {
    entries += static_cast<uint32_t>(physicalChannelCount());
  }
  return entries;
}

static uint32_t blockDelayMs() {
  const uint32_t entries = entriesPerSweep() * g_pzt.sweeps_per_block;
  return (entries * usPerPair()) / 1000u + kBlockDelayMarginMs;
}

static uint32_t warmupDelayMs() {
  const uint32_t entries = static_cast<uint32_t>(kWarmupSweeps) * entriesPerSweep();
  return (entries * usPerPair()) / 1000u + kWarmupDelayMarginMs;
}

static uint32_t firstBlockTimeoutMs() {
  uint32_t timeout_ms = warmupDelayMs() + blockDelayMs() + kDrdyMarginMs;
  if (g_combined_mode) {
    timeout_ms = max(timeout_ms, kPztRsFirstBlockMinTimeoutMs);
  }
  return timeout_ms;
}

static uint32_t blockResponseBytes() {
  const uint32_t samples = static_cast<uint32_t>(physicalChannelCount()) * g_pzt.repeat_count *
                           g_pzt.sweeps_per_block * 2u;
  return static_cast<uint32_t>(kAckFrameLen) + samples * 2u + kBlockTrailerLen;
}

static void hostAck(bool ok, const String &args = "") {
  shared_proto::writeHostAck(ok, args, false);
  delay(5);
}

}  // namespace

void begin() {
  g_spi.begin(SPI, board_config::kPztCsPin, board_config::kPztSpiBitrate, board_config::kPztCsSetupUs);
  g_spi.beginDrdy(board_config::kPztDrdyPin);
  pzt_rs_controller::resetRouting();
}

void setCombinedMode(bool enabled) {
  g_combined_mode = enabled;
  requestStop();
  if (!enabled) {
    pzt_rs_controller::resetRouting();
  }
}

bool combinedMode() {
  return g_combined_mode;
}

bool handleChannels(const String &args) {
  g_pzt.channel_count = 0;
  g_pzt.physical_channel_count = 0;
  pzt_rs_controller::resetRouting();

  const uint8_t max_logical_slots = g_combined_mode ? kMaxLogicalSlots : kMaxPhysicalChannels;
  int i = 0;
  const int len = args.length();
  while (i < len && g_pzt.channel_count < max_logical_slots) {
    while (i < len && (args[i] == ' ' || args[i] == ',')) {
      ++i;
    }
    if (i >= len) {
      break;
    }
    const int start = i;
    while (i < len && args[i] != ' ' && args[i] != ',') {
      ++i;
    }
    const int v = args.substring(start, i).toInt();
    if (v >= 0 && v <= static_cast<int>(kMuxChMax)) {
      const uint8_t ch = static_cast<uint8_t>(v);
      const int8_t existing_physical_index = physicalIndexForChannel(ch);
      g_pzt.channels[g_pzt.channel_count++] = ch;
      if (existing_physical_index < 0) {
        if (g_pzt.physical_channel_count >= kMaxPhysicalChannels) {
          return false;
        }
        g_pzt.physical_channels[g_pzt.physical_channel_count++] = ch;
      }
    }
  }

  if (g_pzt.channel_count == 0 || g_pzt.physical_channel_count == 0) {
    return false;
  }
  if (g_combined_mode) {
    if ((g_pzt.channel_count % pzt_rs_controller::kChannelsPerSensor) != 0) {
      return false;
    }
    const uint8_t sensors = g_pzt.channel_count / pzt_rs_controller::kChannelsPerSensor;
    if (sensors == 0 || sensors > pzt_rs_controller::kMaxSensorSlots) {
      return false;
    }
    pzt_rs_controller::setSensorCount(sensors);
  }

  uint8_t frame[kCmdFrameLen];
  memset(frame, 0, kCmdFrameLen);
  frame[0] = kCmdSetChannels;
  frame[1] = static_cast<uint8_t>(g_pzt.physical_channel_count + 1);
  frame[2] = g_pzt.physical_channel_count;
  for (uint8_t k = 0; k < g_pzt.physical_channel_count && k < kMaxPhysicalChannels; ++k) {
    frame[3 + k] = g_pzt.physical_channels[k];
  }

  g_spi.drdyClearAll();
  g_spi.send(frame, kCmdFrameLen);
  uint8_t ack[kAckFrameLen] = {0};
  if (!recvAckWhenReady(ack, kDrdyAckTimeoutMs)) {
    return false;
  }
  return (ack[0] == kAckMagic && ack[1] == kAckStatusOk);
}

bool handlePztMuxes(const String &args) {
  return g_combined_mode && pzt_rs_controller::handlePztMuxes(args);
}

bool handleRsChannels(const String &args) {
  return g_combined_mode && pzt_rs_controller::handleRsChannels(args);
}

bool handleRepeat(const String &args) {
  const long v = constrain(args.toInt(), 1L, static_cast<long>(kMaxRepeat));
  g_pzt.repeat_count = static_cast<uint8_t>(v);
  const uint8_t a = g_pzt.repeat_count;
  return sendCmdAck(kCmdSetRepeat, &a, 1);
}

bool handleBuffer(const String &args) {
  const long v = max(1L, args.toInt());
  g_pzt.sweeps_per_block = static_cast<uint8_t>(min(v, 255L));
  const uint8_t a = g_pzt.sweeps_per_block;
  return sendCmdAck(kCmdSetBuffer, &a, 1);
}

bool handleRef(const String &args) {
  String a = args;
  a.trim();
  a.toLowerCase();

  uint8_t ref_arg = 0;
  if (a == "1.2" || a == "1v2") {
    ref_arg = 0;
    g_pzt.ref = 0;
  } else if (a == "3.3" || a == "vdd") {
    ref_arg = 1;
    g_pzt.ref = 1;
  } else {
    Serial.println(F("# ERROR: only ref 1.2 and ref 3.3/vdd are supported"));
    return false;
  }

  return sendCmdAck(kCmdSetRef, &ref_arg, 1);
}

bool handleOsr(const String &args) {
  const long v = args.toInt();
  if (v != 2 && v != 4 && v != 8) {
    Serial.println(F("# ERROR: osr must be 2, 4, or 8"));
    return false;
  }
  g_pzt.osr = static_cast<uint8_t>(v);
  const uint8_t a = g_pzt.osr;
  return sendCmdAck(kCmdSetOsr, &a, 1);
}

bool handleGain(const String &args) {
  const long v = args.toInt();
  if (v < 1 || v > 4) {
    Serial.println(F("# ERROR: gain must be 1, 2, 3, or 4"));
    return false;
  }
  g_pzt.gain = static_cast<uint8_t>(v);
  const uint8_t a = g_pzt.gain;
  return sendCmdAck(kCmdSetGain, &a, 1);
}

bool handleGround(const String &args) {
  String a = args;
  a.trim();
  a.toLowerCase();

  if (a == "true") {
    g_pzt.ground_enable = true;
    const uint8_t en = 1;
    return sendCmdAck(kCmdGroundEn, &en, 1);
  }
  if (a == "false") {
    g_pzt.ground_enable = false;
    const uint8_t en = 0;
    return sendCmdAck(kCmdGroundEn, &en, 1);
  }

  const long v = a.toInt();
  if (v < 0 || v > static_cast<int>(kMuxChMax)) {
    Serial.println(F("# ERROR: ground channel out of range (0-15)"));
    return false;
  }
  g_pzt.ground_pin = static_cast<uint8_t>(v);
  g_pzt.ground_enable = true;
  const uint8_t pin = static_cast<uint8_t>(v);
  return sendCmdAck(kCmdGroundPin, &pin, 1);
}

void handleRun(const String &args) {
  if (g_pzt.channel_count == 0) {
    Serial.println(F("# ERROR: no channels configured"));
    hostAck(false, args);
    return;
  }

  if (g_combined_mode) {
    if (pzt_rs_controller::sensorMuxCount() != pzt_rs_controller::sensorCount()) {
      Serial.println(F("# ERROR: PZT_RS requires one PZT MUX value per selected sensor (use pztmuxes)."));
      hostAck(false, args);
      return;
    }
    if (pzt_rs_controller::rsChannelCount() != pzt_rs_controller::sensorCount()) {
      Serial.println(F("# ERROR: PZT_RS requires RS1,RS2 routing per selected PZT sensor (use rschannels)."));
      hostAck(false, args);
      return;
    }
    if (pzt_rs_controller::outputSamplesPerBlock(g_pzt.repeat_count, g_pzt.sweeps_per_block) >
        pzt_rs_controller::kMaxOutputSamples) {
      Serial.println(F("# ERROR: PZT_RS block too large. Reduce repeat or buffer."));
      hostAck(false, args);
      return;
    }
  }

  uint32_t ms = 0;
  bool timed = false;
  if (args.length() > 0) {
    const long v = args.toInt();
    if (v > 0) {
      ms = static_cast<uint32_t>(v);
      timed = true;
    }
  }

  pzr_controller::resetCaptureDiagnostics();
  streamResetState();
  if (g_combined_mode) {
    pzt_rs_controller::resetState();
  }
  g_stream_block_bytes = blockResponseBytes();

  uint8_t frame[kCmdFrameLen];
  memset(frame, 0, kCmdFrameLen);
  frame[0] = kCmdRun;
  if (timed) {
    frame[1] = 4;
    frame[2] = static_cast<uint8_t>(ms & 0xFF);
    frame[3] = static_cast<uint8_t>((ms >> 8) & 0xFF);
    frame[4] = static_cast<uint8_t>((ms >> 16) & 0xFF);
    frame[5] = static_cast<uint8_t>((ms >> 24) & 0xFF);
  }
  g_spi.send(frame, kCmdFrameLen);

  const uint32_t first_block_timeout = firstBlockTimeoutMs();
  const uint32_t wait_start = millis();

  while (queueIsEmpty()) {
    pollStreamStopRequest();
    if (g_combined_mode) {
      pzt_rs_controller::serviceRefresh(false);
    }
    serviceSpiRx();
    if (g_combined_mode) {
      pzt_rs_controller::serviceRefresh(true);
    }

    if (g_stream_fault || g_remote_ended) {
      g_pzt.running = false;
      hostAck(false, args);
      streamResetState();
      return;
    }

    if ((millis() - wait_start) >= first_block_timeout) {
      g_pzt.running = false;
      hostAck(false, args);
      streamResetState();
      return;
    }

    yield();
  }

  g_pzt.running = true;
  hostAck(true, args);
  discardPendingTerminators();

  const uint32_t run_start = millis();
  g_stream_last_activity = millis();

  while (true) {
    pollStreamStopRequest();
    if (!g_stop_requested && timed && (millis() - run_start) >= ms) {
      g_stop_requested = true;
    }

    if (g_combined_mode && !g_remote_ended && !g_waiting_final_ack) {
      pzt_rs_controller::serviceRefresh(true);
    }

    serviceSpiRx();

    if (!g_remote_ended && !g_waiting_final_ack && !g_spi.drdyPending() && queueIsEmpty()) {
      const uint32_t now_ms = millis();
      const uint32_t fallback_arm_delay_ms = blockDelayMs() + kDrdyMarginMs;
      if ((now_ms - g_stream_last_activity) > fallback_arm_delay_ms &&
          (now_ms - g_last_fallback_poll_ms) >= 2UL) {
        g_last_fallback_poll_ms = now_ms;
        serviceSpiRxFallbackPoll();
      }
    }

    serviceUsbTx();

    if (g_combined_mode && !g_remote_ended && !g_waiting_final_ack) {
      pzt_rs_controller::serviceRefresh(true);
    }

    if (g_stream_fault) {
      g_pzt.running = false;
      break;
    }

    const bool done_remote = g_remote_ended && queueIsEmpty();
    const bool done_stop = g_stop_control_sent && !g_waiting_final_ack && queueIsEmpty();
    if (done_remote || done_stop) {
      g_pzt.running = false;
      break;
    }

    if (!g_remote_ended && !g_waiting_final_ack && queueIsEmpty() && !g_spi.drdyPending()) {
      const uint32_t idle_limit = blockDelayMs() + kDrdyMarginMs + kStreamIdleSlackMs;
      if ((millis() - g_stream_last_activity) > idle_limit) {
        g_stream_fault = true;
        g_pzt.running = false;
        break;
      }
    }

    yield();
  }

  if (g_stream_fault) {
    Serial.println(F("# WARN: PZT stream fault; run stopped"));
  }

  logStreamSummary();

  g_pzt.running = false;
  streamResetState();
}

void requestStop() {
  g_pzt.running = false;
}

bool isRunning() {
  return g_pzt.running;
}

void printStatus() {
  Serial.println(F("# -------- STATUS (PZT mode) --------"));
  Serial.println(F("# mcu: Array_PZT_PZR1.7 (Teensy 4.1 + MG24 dual-MUX SPI slave)"));
  Serial.print(F("# running: "));
  Serial.println(g_pzt.running ? F("true") : F("false"));
  Serial.print(F("# channels (count="));
  Serial.print(g_pzt.channel_count);
  Serial.println(F("):"));
  Serial.print(F("#   "));
  for (uint8_t i = 0; i < g_pzt.channel_count; ++i) {
    Serial.print(g_pzt.channels[i]);
    if (i + 1 < g_pzt.channel_count) {
      Serial.print(',');
    }
  }
  Serial.println();
  Serial.print(F("# physical MG24 channels (count="));
  Serial.print(physicalChannelCount());
  Serial.println(F("):"));
  Serial.print(F("#   "));
  for (uint8_t i = 0; i < physicalChannelCount(); ++i) {
    Serial.print(g_pzt.physical_channels[i]);
    if (i + 1 < physicalChannelCount()) {
      Serial.print(',');
    }
  }
  Serial.println();

  pzt_rs_controller::printStatusDetails();

  Serial.print(F("# repeatCount: "));
  Serial.println(g_pzt.repeat_count);
  Serial.print(F("# sweepsPerBlock: "));
  Serial.println(g_pzt.sweeps_per_block);
  Serial.print(F("# ref: "));
  Serial.println(g_pzt.ref == 0 ? F("1.2V") : F("VDD/3.3V"));
  Serial.print(F("# osr: "));
  Serial.println(g_pzt.osr);
  Serial.print(F("# gain: "));
  Serial.print(g_pzt.gain);
  Serial.println('x');
  Serial.print(F("# groundPin: "));
  Serial.println(g_pzt.ground_pin);
  Serial.print(F("# groundEnable: "));
  Serial.println(g_pzt.ground_enable ? F("true") : F("false"));
  uint32_t samples_per_block =
      static_cast<uint32_t>(g_pzt.channel_count) * g_pzt.repeat_count * g_pzt.sweeps_per_block * 2u;
  if (g_combined_mode) {
    samples_per_block = pzt_rs_controller::outputSamplesPerBlock(g_pzt.repeat_count, g_pzt.sweeps_per_block);
  }
  Serial.print(F("# samplesPerBlock: "));
  Serial.println(samples_per_block);
  Serial.print(F("# estimatedBlockDelayMs: "));
  Serial.println(blockDelayMs());
  Serial.println(F("# NOTE: each channel slot yields 2 samples [MUX1_val, MUX2_val]"));
  Serial.println(F("# -------------------------"));
}

}  // namespace pzt_controller
