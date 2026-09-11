#include "PztRsController.h"

#include <math.h>
#include <string.h>

#include "PzrController.h"
#include "SharedProtocol.h"

namespace pzt_rs_controller {

namespace {

static const uint32_t kRefreshMinMs = 0;
static const uint8_t kMeasurePairsPerUpdate = 3;
static const uint8_t kHeldMedianN = 5;
static const uint8_t kBrokenTimeoutSweeps = 3;

enum RefreshStage {
  REFRESH_IDLE,
  REFRESH_DISCARD,
  REFRESH_MEASURE,
};

static uint8_t g_sensor_count = 0;
static uint8_t g_sensor_mux[kMaxSensorSlots] = {0};
static int8_t g_sensor_rs_a[kMaxSensorSlots] = {-1, -1, -1, -1, -1, -1};
static int8_t g_sensor_rs_b[kMaxSensorSlots] = {-1, -1, -1, -1, -1, -1};
static uint8_t g_rs_refresh_channels[16] = {0};
static uint8_t g_sensor_mux_count = 0;
static uint8_t g_rs_channel_count = 0;
static uint8_t g_rs_refresh_channel_count = 0;

static volatile uint32_t g_isr_fires = 0;
static volatile uint8_t g_active_channel = 0xFF;
static uint16_t g_last_ra_q_by_channel[16] = {0};
static float g_hold_median_buf_by_channel[16][kHeldMedianN] = {{0.0f}};
static uint8_t g_hold_median_idx_by_channel[16] = {0};
static uint8_t g_hold_median_count_by_channel[16] = {0};
static uint32_t g_update_count_by_channel[16] = {0};
static uint32_t g_last_update_ms_by_channel[16] = {0};
static volatile uint32_t g_rise_edges_by_channel[16] = {0};
static volatile uint32_t g_fall_edges_by_channel[16] = {0};
static volatile uint32_t g_pairs_ready_by_channel[16] = {0};
static volatile uint32_t g_last_pair_h_cycles_by_channel[16] = {0};
static volatile uint32_t g_last_pair_l_cycles_by_channel[16] = {0};
static uint32_t g_discard_pairs_by_channel[16] = {0};
static uint32_t g_timeouts_by_channel[16] = {0};
static uint8_t g_timeout_streak_by_channel[16] = {0};
static bool g_broken_by_channel[16] = {false};
static uint32_t g_broken_skips_by_channel[16] = {0};
static uint32_t g_total_updates = 0;
static uint32_t g_mux_switches = 0;
static uint32_t g_discard_pairs = 0;
static uint32_t g_channel_timeouts = 0;
static uint32_t g_channel_start_ms = 0;
static uint32_t g_channel_timeout_ms = 0;
static int8_t g_prev_measured_channel = -1;
static uint8_t g_refresh_index = 0;
static uint32_t g_last_refresh_ms = 0;
static RefreshStage g_refresh_stage = REFRESH_IDLE;
static uint8_t g_pending_channel = 0;
static uint8_t g_discard_remaining = 0;
static float g_measure_ra_buf[3] = {0.0f, 0.0f, 0.0f};
static uint8_t g_measure_pairs_collected = 0;

static bool addUniqueRsRefreshChannel(int8_t ch) {
  if (ch < 0 || ch > 15) {
    return true;
  }
  for (uint8_t i = 0; i < g_rs_refresh_channel_count; ++i) {
    if ((g_rs_refresh_channels[i] & 0x0F) == static_cast<uint8_t>(ch)) {
      return true;
    }
  }
  if (g_rs_refresh_channel_count >= 16) {
    return false;
  }
  g_rs_refresh_channels[g_rs_refresh_channel_count++] = static_cast<uint8_t>(ch);
  return true;
}

static int8_t physicalIndexForChannel(uint8_t ch, const uint8_t *physical_channels, uint8_t physical_channel_count) {
  if (physical_channels == nullptr) {
    return -1;
  }
  for (uint8_t i = 0; i < physical_channel_count; ++i) {
    if ((physical_channels[i] & 0x0F) == (ch & 0x0F)) {
      return static_cast<int8_t>(i);
    }
  }
  return -1;
}

static float medianN(const float *buf, uint8_t count) {
  if (!buf || count == 0) {
    return 0.0f;
  }
  float sorted[kHeldMedianN];
  const uint8_t capped_count = min(count, kHeldMedianN);
  for (uint8_t i = 0; i < capped_count; ++i) {
    sorted[i] = buf[i];
  }
  for (uint8_t i = 1; i < capped_count; ++i) {
    const float v = sorted[i];
    int8_t j = static_cast<int8_t>(i) - 1;
    while (j >= 0 && sorted[j] > v) {
      sorted[j + 1] = sorted[j];
      --j;
    }
    sorted[j + 1] = v;
  }
  return sorted[capped_count / 2u];
}

static inline float median3(float a, float b, float c) {
  if (a > b) {
    float t = a;
    a = b;
    b = t;
  }
  if (b > c) {
    float t = b;
    b = c;
    c = t;
  }
  if (a > b) {
    float t = a;
    a = b;
    b = t;
  }
  return b;
}

static float updateHeldMedian(uint8_t ch, float ra) {
  if (ch > 15) {
    return ra;
  }
  uint8_t &idx = g_hold_median_idx_by_channel[ch];
  uint8_t &count = g_hold_median_count_by_channel[ch];
  float *buf = g_hold_median_buf_by_channel[ch];
  buf[idx] = ra;
  idx = static_cast<uint8_t>((idx + 1u) % kHeldMedianN);
  if (count < kHeldMedianN) {
    count++;
  }
  if (count < kHeldMedianN) {
    return ra;
  }
  return medianN(buf, count);
}

static inline uint16_t quantizeOhms(float ra) {
  long v = lroundf(ra * static_cast<float>(kWireUnitsPerOhm));
  if (v < 0) {
    v = 0;
  }
  if (v > 65535L) {
    v = 65535L;
  }
  return static_cast<uint16_t>(v);
}

static void recordChannelTimeout(uint8_t ch) {
  if (ch > 15) {
    return;
  }
  g_channel_timeouts++;
  g_timeouts_by_channel[ch]++;
  if (g_timeout_streak_by_channel[ch] < 255) {
    g_timeout_streak_by_channel[ch]++;
  }
  if (g_timeout_streak_by_channel[ch] >= kBrokenTimeoutSweeps) {
    g_broken_by_channel[ch] = true;
  }
}

static void recordSuccessfulUpdate(uint8_t ch) {
  if (ch > 15) {
    return;
  }
  g_timeout_streak_by_channel[ch] = 0;
  g_broken_by_channel[ch] = false;
}

static void startNextRefreshChannel();

static bool consumeReadyPair() {
  if (g_refresh_stage == REFRESH_IDLE) {
    return false;
  }

  if (g_channel_timeout_ms > 0 && (millis() - g_channel_start_ms) >= g_channel_timeout_ms) {
    recordChannelTimeout(g_pending_channel);
    // A timeout means the physical mux may still be parked on the failed
    // channel. Force the next refresh step to re-select its channel even if it
    // matches the last channel that produced a valid measurement.
    g_prev_measured_channel = -1;
    startNextRefreshChannel();
    return false;
  }

  uint32_t h_cycles = 0;
  uint32_t l_cycles = 0;
  if (!pzr_controller::takeReadyPair(h_cycles, l_cycles)) {
    return false;
  }

  if (g_refresh_stage == REFRESH_DISCARD) {
    if (g_discard_remaining > 0) {
      g_discard_remaining--;
    }
    g_discard_pairs++;
    if (g_pending_channel < 16) {
      g_discard_pairs_by_channel[g_pending_channel]++;
    }
    if (g_discard_remaining == 0) {
      g_refresh_stage = REFRESH_MEASURE;
    }
    return true;
  }

  if (g_refresh_stage == REFRESH_MEASURE) {
    float ra = 0.0f;
    if (!pzr_controller::updateChannelRaFromPair(g_pending_channel, h_cycles, l_cycles, ra)) {
      g_measure_pairs_collected = 0;
      // Keep the original channel timeout running. A broken/noisy RS channel can
      // produce invalid pairs repeatedly; restarting the timer here would trap
      // the shared refresh loop and starve the other configured RS channels.
      return true;
    }

    if (kMeasurePairsPerUpdate <= 1) {
      const float held_ra = updateHeldMedian(g_pending_channel, ra);
      g_last_ra_q_by_channel[g_pending_channel] = quantizeOhms(held_ra);
      g_update_count_by_channel[g_pending_channel]++;
      g_last_update_ms_by_channel[g_pending_channel] = millis();
      g_total_updates++;
      recordSuccessfulUpdate(g_pending_channel);
      g_prev_measured_channel = static_cast<int8_t>(g_pending_channel);
      g_last_refresh_ms = millis();
      startNextRefreshChannel();
      return true;
    }

    if (g_measure_pairs_collected < kMeasurePairsPerUpdate) {
      g_measure_ra_buf[g_measure_pairs_collected++] = ra;
    }

    if (g_measure_pairs_collected < kMeasurePairsPerUpdate) {
      g_channel_start_ms = millis();
      return true;
    }

    float accepted_ra = ra;
    if (kMeasurePairsPerUpdate == 3) {
      accepted_ra = median3(g_measure_ra_buf[0], g_measure_ra_buf[1], g_measure_ra_buf[2]);
    }

    const float held_ra = updateHeldMedian(g_pending_channel, accepted_ra);
    g_last_ra_q_by_channel[g_pending_channel] = quantizeOhms(held_ra);
    g_update_count_by_channel[g_pending_channel]++;
    g_last_update_ms_by_channel[g_pending_channel] = millis();
    g_total_updates++;
    recordSuccessfulUpdate(g_pending_channel);
    g_prev_measured_channel = static_cast<int8_t>(g_pending_channel);
    g_last_refresh_ms = millis();
    g_measure_pairs_collected = 0;
    startNextRefreshChannel();
    return true;
  }

  return false;
}

static void startNextRefreshChannel() {
  if (g_rs_refresh_channel_count == 0) {
    return;
  }

  const uint32_t now_ms = millis();
  if (g_last_refresh_ms != 0 && (now_ms - g_last_refresh_ms) < kRefreshMinMs) {
    return;
  }

  bool found_measurable_channel = false;
  for (uint8_t attempts = 0; attempts < g_rs_refresh_channel_count; ++attempts) {
    const uint8_t ch = g_rs_refresh_channels[g_refresh_index % g_rs_refresh_channel_count] & 0x0F;
    g_refresh_index = static_cast<uint8_t>(
        (g_refresh_index + 1u) % max(static_cast<uint8_t>(1), g_rs_refresh_channel_count));
    if (g_broken_by_channel[ch]) {
      g_broken_skips_by_channel[ch]++;
      continue;
    }
    g_pending_channel = ch;
    found_measurable_channel = true;
    break;
  }

  if (!found_measurable_channel) {
    g_active_channel = 0xFF;
    g_refresh_stage = REFRESH_IDLE;
    g_discard_remaining = 0;
    g_measure_pairs_collected = 0;
    return;
  }

  g_active_channel = g_pending_channel;
  g_measure_pairs_collected = 0;

  if (g_prev_measured_channel != static_cast<int8_t>(g_pending_channel)) {
    pzr_controller::muxSelect(g_pending_channel);
    g_mux_switches++;
    g_discard_remaining = pzr_controller::kDiscardCyclesAfterSwitch;
    g_refresh_stage = (g_discard_remaining > 0) ? REFRESH_DISCARD : REFRESH_MEASURE;
  } else {
    g_discard_remaining = 0;
    g_refresh_stage = REFRESH_MEASURE;
  }
  g_channel_start_ms = millis();
}

}  // namespace

void resetRouting() {
  g_sensor_count = 0;
  g_sensor_mux_count = 0;
  g_rs_channel_count = 0;
  g_rs_refresh_channel_count = 0;
  for (uint8_t i = 0; i < kMaxSensorSlots; ++i) {
    g_sensor_mux[i] = 0;
    g_sensor_rs_a[i] = -1;
    g_sensor_rs_b[i] = -1;
  }
}

void setSensorCount(uint8_t count) {
  resetRouting();
  g_sensor_count = min(count, kMaxSensorSlots);
}

uint8_t sensorCount() {
  return g_sensor_count;
}

uint8_t sensorMuxCount() {
  return g_sensor_mux_count;
}

uint8_t rsChannelCount() {
  return g_rs_channel_count;
}

uint8_t rsRefreshChannelCount() {
  return g_rs_refresh_channel_count;
}

uint8_t rsRefreshChannel(uint8_t index) {
  return (index < g_rs_refresh_channel_count) ? g_rs_refresh_channels[index] : 0;
}

bool routingReady() {
  return g_sensor_count > 0 &&
         g_sensor_mux_count == g_sensor_count &&
         g_rs_channel_count == g_sensor_count &&
         g_rs_refresh_channel_count > 0;
}

bool handlePztMuxes(const String &args) {
  if (g_sensor_count == 0) {
    return false;
  }

  uint8_t values[kMaxSensorSlots];
  uint8_t value_count = 0;
  int i = 0;
  const int len = args.length();
  while (i < len && value_count < kMaxSensorSlots) {
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
    if (v < 1 || v > 2) {
      return false;
    }
    values[value_count++] = static_cast<uint8_t>(v);
  }

  if (value_count != g_sensor_count) {
    return false;
  }

  g_sensor_mux_count = g_sensor_count;
  for (uint8_t slot = 0; slot < g_sensor_mux_count; ++slot) {
    g_sensor_mux[slot] = values[slot];
  }
  return true;
}

bool handleRsChannels(const String &args) {
  if (g_sensor_count == 0) {
    return false;
  }

  int8_t values[kMaxSensorSlots * 2u];
  uint8_t value_count = 0;
  int i = 0;
  const int len = args.length();
  while (i < len && value_count < (kMaxSensorSlots * 2u)) {
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
    if (v < 0 || v > 15) {
      return false;
    }
    values[value_count++] = static_cast<int8_t>(v);
  }

  if (value_count != static_cast<uint8_t>(g_sensor_count * 2u)) {
    return false;
  }

  g_rs_channel_count = g_sensor_count;
  g_rs_refresh_channel_count = 0;
  for (uint8_t slot = 0; slot < kMaxSensorSlots; ++slot) {
    g_sensor_rs_a[slot] = -1;
    g_sensor_rs_b[slot] = -1;
  }

  for (uint8_t slot = 0; slot < g_rs_channel_count; ++slot) {
    const uint8_t base = static_cast<uint8_t>(slot * 2u);
    g_sensor_rs_a[slot] = values[base];
    g_sensor_rs_b[slot] = values[base + 1u];
    if (!addUniqueRsRefreshChannel(g_sensor_rs_a[slot])) {
      return false;
    }
    if (!addUniqueRsRefreshChannel(g_sensor_rs_b[slot])) {
      return false;
    }
  }

  return g_rs_refresh_channel_count > 0;
}

uint32_t outputSamplesPerBlock(uint8_t repeat_count, uint8_t sweeps_per_block) {
  return static_cast<uint32_t>(g_sensor_count) * static_cast<uint32_t>(repeat_count) *
         static_cast<uint32_t>(sweeps_per_block) * static_cast<uint32_t>(kOutputsPerSensor);
}

void resetState() {
  for (int ch = 0; ch < 16; ++ch) {
    const bool has_seed_ra = isfinite(pzr_controller::lastPlotRa(ch));
    const float ra = has_seed_ra ? pzr_controller::lastPlotRa(ch) : 0.0f;
    g_last_ra_q_by_channel[ch] = quantizeOhms(ra);
    for (uint8_t i = 0; i < kHeldMedianN; ++i) {
      g_hold_median_buf_by_channel[ch][i] = ra;
    }
    g_hold_median_idx_by_channel[ch] = 0;
    g_hold_median_count_by_channel[ch] = has_seed_ra ? kHeldMedianN : 0;
    g_update_count_by_channel[ch] = 0;
    g_last_update_ms_by_channel[ch] = 0;
    g_rise_edges_by_channel[ch] = 0;
    g_fall_edges_by_channel[ch] = 0;
    g_pairs_ready_by_channel[ch] = 0;
    g_last_pair_h_cycles_by_channel[ch] = 0;
    g_last_pair_l_cycles_by_channel[ch] = 0;
    g_discard_pairs_by_channel[ch] = 0;
    g_timeouts_by_channel[ch] = 0;
    g_timeout_streak_by_channel[ch] = 0;
    g_broken_by_channel[ch] = false;
    g_broken_skips_by_channel[ch] = 0;
  }

  g_isr_fires = 0;
  g_active_channel = 0xFF;
  g_total_updates = 0;
  g_mux_switches = 0;
  g_discard_pairs = 0;
  g_channel_timeouts = 0;
  g_channel_start_ms = 0;
  // One missed pair attempt skips the channel. Successful partial progress
  // refreshes this timer for the next discard/measurement pair.
  g_channel_timeout_ms = pzr_controller::computePairTimeoutMs();
  g_prev_measured_channel = -1;
  g_refresh_index = 0;
  g_last_refresh_ms = 0;
  g_refresh_stage = REFRESH_IDLE;
  g_pending_channel = 0;
  g_discard_remaining = 0;
  g_measure_pairs_collected = 0;
  startNextRefreshChannel();
}

void stopRefresh() {
  g_active_channel = 0xFF;
  g_refresh_stage = REFRESH_IDLE;
  g_discard_remaining = 0;
  g_last_refresh_ms = 0;
}

void serviceRefresh(bool allow_channel_switch) {
  (void)allow_channel_switch;
  if (g_rs_refresh_channel_count == 0) {
    return;
  }
  (void)consumeReadyPair();
}

void snapshotHeldValues(uint16_t *dst, uint8_t count) {
  if (!dst) {
    return;
  }
  if (count > 16) {
    count = 16;
  }
  noInterrupts();
  for (uint8_t i = 0; i < count; ++i) {
    dst[i] = g_last_ra_q_by_channel[i];
  }
  interrupts();
}

bool buildCombinedBlock(
    const uint8_t *src,
    uint32_t src_len,
    uint8_t *dst,
    uint32_t &dst_len,
    const uint16_t *held_ra_q_snapshot,
    const uint8_t *logical_channels,
    uint8_t logical_channel_count,
    const uint8_t *physical_channels,
    uint8_t physical_channel_count,
    uint8_t repeat_count) {
  if (!src || !dst || !held_ra_q_snapshot || !logical_channels || !physical_channels) {
    return false;
  }
  if (src_len < 4u + 10u) {
    return false;
  }
  if (src[0] != shared_proto::kBlockMagic1 || src[1] != shared_proto::kBlockMagic2) {
    return false;
  }

  const uint16_t pzt_sample_count = static_cast<uint16_t>(src[2]) | (static_cast<uint16_t>(src[3]) << 8);
  const uint32_t payload_bytes = static_cast<uint32_t>(pzt_sample_count) * 2u;
  const uint32_t expected_len = 4u + payload_bytes + 10u;
  if (src_len < expected_len) {
    return false;
  }
  if ((pzt_sample_count & 0x01u) != 0u) {
    return false;
  }

  const uint16_t physical_pair_count = pzt_sample_count / 2u;
  if (physical_channel_count == 0 || logical_channel_count == 0 || g_sensor_count == 0) {
    return false;
  }
  if ((logical_channel_count % kChannelsPerSensor) != 0) {
    return false;
  }

  const uint32_t physical_pairs_per_sweep =
      static_cast<uint32_t>(physical_channel_count) * static_cast<uint32_t>(repeat_count);
  if (physical_pairs_per_sweep == 0 || (physical_pair_count % physical_pairs_per_sweep) != 0) {
    return false;
  }
  const uint32_t sweeps_in_block = physical_pair_count / physical_pairs_per_sweep;

  const uint32_t combined_count_32 =
      sweeps_in_block * static_cast<uint32_t>(g_sensor_count) *
      static_cast<uint32_t>(repeat_count) * static_cast<uint32_t>(kOutputsPerSensor);
  if (combined_count_32 > 65535u) {
    return false;
  }
  const uint16_t combined_count = static_cast<uint16_t>(combined_count_32);

  const uint32_t combined_payload_bytes = static_cast<uint32_t>(combined_count) * 2u;
  const uint32_t combined_len = 4u + combined_payload_bytes + 10u;
  if (combined_len > kMaxBlockBytes) {
    return false;
  }

  dst[0] = shared_proto::kBlockMagic1;
  dst[1] = shared_proto::kBlockMagic2;
  dst[2] = static_cast<uint8_t>(combined_count & 0xFF);
  dst[3] = static_cast<uint8_t>(combined_count >> 8);

  uint32_t dst_payload_pos = 4u;
  for (uint32_t sweep = 0; sweep < sweeps_in_block; ++sweep) {
    for (uint8_t sensor = 0; sensor < g_sensor_count; ++sensor) {
      const uint8_t mux_index = (g_sensor_mux[sensor] == 2) ? 1u : 0u;

      for (uint8_t repeat_idx = 0; repeat_idx < repeat_count; ++repeat_idx) {
        for (uint8_t local_ch = 0; local_ch < kChannelsPerSensor; ++local_ch) {
          const uint8_t logical_slot = static_cast<uint8_t>(sensor * kChannelsPerSensor + local_ch);
          const int8_t physical_idx = physicalIndexForChannel(
              logical_channels[logical_slot],
              physical_channels,
              physical_channel_count);
          if (physical_idx < 0) {
            return false;
          }

          const uint32_t physical_pair =
              sweep * physical_pairs_per_sweep +
              static_cast<uint32_t>(physical_idx) * static_cast<uint32_t>(repeat_count) +
              static_cast<uint32_t>(repeat_idx);
          uint32_t src_payload_pos = 4u + physical_pair * 4u + static_cast<uint32_t>(mux_index) * 2u;

          dst[dst_payload_pos++] = src[src_payload_pos++];
          dst[dst_payload_pos++] = src[src_payload_pos++];
        }

        const uint16_t rs_a = (g_sensor_rs_a[sensor] >= 0 && g_sensor_rs_a[sensor] <= 15)
                                  ? held_ra_q_snapshot[static_cast<uint8_t>(g_sensor_rs_a[sensor])]
                                  : 0;
        const uint16_t rs_b = (g_sensor_rs_b[sensor] >= 0 && g_sensor_rs_b[sensor] <= 15)
                                  ? held_ra_q_snapshot[static_cast<uint8_t>(g_sensor_rs_b[sensor])]
                                  : 0;
        dst[dst_payload_pos++] = static_cast<uint8_t>(rs_a & 0xFF);
        dst[dst_payload_pos++] = static_cast<uint8_t>(rs_a >> 8);
        dst[dst_payload_pos++] = static_cast<uint8_t>(rs_b & 0xFF);
        dst[dst_payload_pos++] = static_cast<uint8_t>(rs_b >> 8);
      }
    }
  }

  const uint32_t src_trailer_pos = 4u + payload_bytes;
  const uint32_t dst_trailer_pos = 4u + combined_payload_bytes;
  memcpy(dst + dst_trailer_pos, src + src_trailer_pos, 10u);
  dst_len = combined_len;
  return true;
}

void printStatusDetails() {
  Serial.print(F("# PZT_RS sensors: "));
  Serial.println(g_sensor_count);
  Serial.print(F("# pztmuxes (count="));
  Serial.print(g_sensor_mux_count);
  Serial.println(F("):"));
  Serial.print(F("#   "));
  for (uint8_t i = 0; i < g_sensor_mux_count; ++i) {
    Serial.print(static_cast<int>(g_sensor_mux[i]));
    if (i + 1 < g_sensor_mux_count) {
      Serial.print(',');
    }
  }
  Serial.println();

  Serial.print(F("# rschannels (RS1,RS2 per sensor; sensors="));
  Serial.print(g_rs_channel_count);
  Serial.println(F("):"));
  Serial.print(F("#   "));
  for (uint8_t i = 0; i < g_rs_channel_count; ++i) {
    Serial.print(static_cast<int>(g_sensor_rs_a[i]));
    Serial.print(',');
    Serial.print(static_cast<int>(g_sensor_rs_b[i]));
    if (i + 1 < g_rs_channel_count) {
      Serial.print(',');
    }
  }
  Serial.println();

  Serial.print(F("# RS refresh channels (unique="));
  Serial.print(g_rs_refresh_channel_count);
  Serial.println(F("):"));
  Serial.print(F("#   "));
  for (uint8_t i = 0; i < g_rs_refresh_channel_count; ++i) {
    Serial.print(g_rs_refresh_channels[i]);
    if (i + 1 < g_rs_refresh_channel_count) {
      Serial.print(',');
    }
  }
  Serial.println();

  Serial.print(F("# RS refresh diagnostics: total_updates="));
  Serial.print(g_total_updates);
  Serial.print(F(", mux_switches="));
  Serial.print(g_mux_switches);
  Serial.print(F(", discard_pairs="));
  Serial.print(g_discard_pairs);
  Serial.print(F(", channel_timeouts="));
  Serial.print(g_channel_timeouts);
  Serial.print(F(", channel_timeout_ms="));
  Serial.println(g_channel_timeout_ms);
  Serial.print(F("# rs_measure_pairs_per_update: "));
  Serial.println(kMeasurePairsPerUpdate);
  Serial.print(F("# rs_held_median_n: "));
  Serial.println(kHeldMedianN);
  Serial.print(F("# rs_broken_timeout_sweeps: "));
  Serial.println(kBrokenTimeoutSweeps);
  Serial.print(F("# RS broken channels: "));
  bool any_broken_rs = false;
  for (uint8_t i = 0; i < g_rs_refresh_channel_count; ++i) {
    const uint8_t ch = g_rs_refresh_channels[i] & 0x0F;
    if (!g_broken_by_channel[ch]) {
      continue;
    }
    if (any_broken_rs) {
      Serial.print(',');
    }
    Serial.print(ch);
    Serial.print(F("(timeouts="));
    Serial.print(g_timeouts_by_channel[ch]);
    Serial.print(F(",skips="));
    Serial.print(g_broken_skips_by_channel[ch]);
    Serial.print(F(")"));
    any_broken_rs = true;
  }
  if (!any_broken_rs) {
    Serial.print(F("none"));
  }
  Serial.println();
  Serial.print(F("# capture_sequence_errors: "));
  Serial.println(pzr_controller::captureSequenceErrors());
  Serial.print(F("# RS held values/update counts: "));
  for (uint8_t i = 0; i < g_rs_refresh_channel_count; ++i) {
    const uint8_t ch = g_rs_refresh_channels[i] & 0x0F;
    Serial.print(ch);
    Serial.print(F("="));
    Serial.print(g_last_ra_q_by_channel[ch]);
    Serial.print(F("("));
    Serial.print(g_update_count_by_channel[ch]);
    Serial.print(F(")"));
    if (i + 1 < g_rs_refresh_channel_count) {
      Serial.print(',');
    }
  }
  Serial.println();
  for (uint8_t i = 0; i < g_rs_refresh_channel_count; ++i) {
    const uint8_t ch = g_rs_refresh_channels[i] & 0x0F;
    pzr_controller::printChannelTimingDiagnostics(ch);
  }
}

void printRefreshDiagnostics(uint8_t ch, const __FlashStringHelper *prefix) {
  if (ch > 15) {
    return;
  }
  if (prefix == nullptr) {
    prefix = F("# RS refresh ");
  }

  const uint32_t rise_edges = g_rise_edges_by_channel[ch];
  const uint32_t fall_edges = g_fall_edges_by_channel[ch];
  const uint32_t pairs_ready = g_pairs_ready_by_channel[ch];
  const uint32_t discard_pairs = g_discard_pairs_by_channel[ch];
  const uint32_t timeouts = g_timeouts_by_channel[ch];
  const uint8_t timeout_streak = g_timeout_streak_by_channel[ch];
  const bool broken = g_broken_by_channel[ch];
  const uint32_t broken_skips = g_broken_skips_by_channel[ch];
  const uint32_t updates = g_update_count_by_channel[ch];
  const uint32_t last_h_cycles = g_last_pair_h_cycles_by_channel[ch];
  const uint32_t last_l_cycles = g_last_pair_l_cycles_by_channel[ch];

  Serial.print(prefix);
  Serial.print(F("ch"));
  Serial.print(static_cast<int>(ch));
  Serial.print(F(": rise_edges="));
  Serial.print(rise_edges);
  Serial.print(F(", fall_edges="));
  Serial.print(fall_edges);
  Serial.print(F(", pairs_ready="));
  Serial.print(pairs_ready);
  Serial.print(F(", discard_pairs="));
  Serial.print(discard_pairs);
  Serial.print(F(", updates="));
  Serial.print(updates);
  Serial.print(F(", timeouts="));
  Serial.print(timeouts);
  Serial.print(F(", timeout_streak="));
  Serial.print(timeout_streak);
  Serial.print(F(", broken="));
  Serial.print(broken ? F("true") : F("false"));
  Serial.print(F(", broken_skips="));
  Serial.print(broken_skips);
  Serial.print(F(", last_pair_h_us="));
  if (last_h_cycles > 0) {
    Serial.print(pzr_controller::cyclesToUs(last_h_cycles), 3);
  } else {
    Serial.print(F("nan"));
  }
  Serial.print(F(", last_pair_l_us="));
  if (last_l_cycles > 0) {
    Serial.print(pzr_controller::cyclesToUs(last_l_cycles), 3);
  } else {
    Serial.print(F("nan"));
  }
  Serial.print(F(", isr_fires_total="));
  Serial.println(g_isr_fires);
}

void printStreamDiagnostics() {
  for (uint8_t i = 0; i < g_rs_refresh_channel_count; ++i) {
    const uint8_t ch = g_rs_refresh_channels[i] & 0x0F;
    pzr_controller::printChannelTimingDiagnostics(ch, F("# INFO: RS timing "));
    printRefreshDiagnostics(ch, F("# INFO: RS refresh "));
  }
}

void noteIsrFire() {
  g_isr_fires++;
}

uint8_t activeChannel() {
  return g_active_channel;
}

void noteRise(uint8_t ch) {
  if (ch < 16) {
    g_rise_edges_by_channel[ch]++;
  }
}

void noteFall(uint8_t ch) {
  if (ch < 16) {
    g_fall_edges_by_channel[ch]++;
  }
}

void notePairReady(uint8_t ch, uint32_t high_cycles, uint32_t low_cycles) {
  if (ch < 16) {
    g_pairs_ready_by_channel[ch]++;
    g_last_pair_h_cycles_by_channel[ch] = high_cycles;
    g_last_pair_l_cycles_by_channel[ch] = low_cycles;
  }
}

}  // namespace pzt_rs_controller
