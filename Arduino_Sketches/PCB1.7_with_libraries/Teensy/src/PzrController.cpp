#include "PzrController.h"

#include <math.h>
#include <string.h>

#include "../BoardConfig.h"
#include "PztRsController.h"
#include "SharedProtocol.h"

namespace pzr_controller {

namespace {

static constexpr uint32_t kTimer555MuxSettleNs = 100;
static constexpr int kRaMaN = 1;
static constexpr int kRaMedianN = 3;
static constexpr int kLCycMaN = 1;
static constexpr float kLn2 = 0.69314718056f;

static constexpr float kDefaultRbOhm = 470.0f;
static constexpr float kDefaultRkOhm = 470.0f;
static constexpr float kDefaultRxMaxOhm = 65500.0f;

enum LowCycleSource { LCYC_SOURCE_MEASURED, LCYC_SOURCE_MODELED };
static constexpr LowCycleSource kRaLowCycleSource = LCYC_SOURCE_MODELED;

enum CaptureEdge : uint8_t {
  EDGE_NONE = 0,
  EDGE_RISE = 1,
  EDGE_FALL = 2,
};

struct CaptureState {
  volatile uint32_t last_rise_cycles = 0;
  volatile uint32_t last_fall_cycles = 0;
  volatile uint32_t high_cycles = 0;
  volatile uint32_t low_cycles = 0;
  volatile uint32_t sequence_errors = 0;
  volatile uint8_t last_edge = EDGE_NONE;
  volatile bool pair_ready = false;
} g_cap;

struct ChannelState {
  float ra_buf[kRaMaN];
  float ra_median_buf[kRaMedianN];
  float ra_sum = 0.0f;
  int ra_idx = 0;
  int ra_count = 0;
  int ra_median_idx = 0;
  int ra_median_count = 0;
  uint32_t last_h_cycles = 0;
  uint32_t last_l_cycles = 0;
  float last_l_cycles_avg_used = NAN;
  float last_l_cycles_model_used = NAN;
  float last_plot_ra = NAN;

  void reset() {
    ra_sum = 0.0f;
    ra_idx = 0;
    ra_count = 0;
    ra_median_idx = 0;
    ra_median_count = 0;
    for (int i = 0; i < kRaMaN; ++i) {
      ra_buf[i] = 0.0f;
    }
    for (int i = 0; i < kRaMedianN; ++i) {
      ra_median_buf[i] = 0.0f;
    }
    last_h_cycles = 0;
    last_l_cycles = 0;
    last_l_cycles_avg_used = NAN;
    last_l_cycles_model_used = NAN;
    last_plot_ra = NAN;
  }
};

enum { INDEX_PZR = 0, INDEX_RS = 1, INDEX_COUNT = 2 };

struct LowCycleSmootherState {
  uint32_t l_cycles_buf[kLCycMaN];
  uint64_t l_cycles_sum = 0;
  int l_cycles_idx = 0;
  int l_cycles_count = 0;
  float last_l_cycles_avg = NAN;

  void reset() {
    l_cycles_sum = 0;
    l_cycles_idx = 0;
    l_cycles_count = 0;
    for (int i = 0; i < kLCycMaN; ++i) {
      l_cycles_buf[i] = 0;
    }
    last_l_cycles_avg = NAN;
  }

  float update(uint32_t l_cycles) {
    l_cycles_sum -= l_cycles_buf[l_cycles_idx];
    l_cycles_buf[l_cycles_idx] = l_cycles;
    l_cycles_sum += l_cycles;
    l_cycles_idx = (l_cycles_idx + 1) % kLCycMaN;
    if (l_cycles_count < kLCycMaN) {
      l_cycles_count++;
    }
    last_l_cycles_avg = (l_cycles_count > 0)
                            ? (static_cast<float>(l_cycles_sum) / static_cast<float>(l_cycles_count))
                            : NAN;
    return last_l_cycles_avg;
  }
};

static float g_rb_ohm = kDefaultRbOhm;
static float g_rk_ohm = kDefaultRkOhm;
static float g_cf_f = board_config::kTimer555DefaultCfF;
static float g_rx_max_ohm = kDefaultRxMaxOhm;
static float g_l_cycles_model = NAN;
static bool g_ascii_output = false;

static uint8_t g_channel_sequence[kMaxChannelSequence] = {0, 1, 2, 3, 4};
static int g_channel_count = 5;
static int g_repeat_count = 1;
static int g_buffer_sweeps = 1;
static bool g_running = false;
static bool g_timed_run = false;
static uint32_t g_run_stop_ms = 0;
static uint16_t g_sample_buf[kMaxBlockSamples];

static ChannelState g_channel_state[16];
static LowCycleSmootherState g_low_cycle_smoother_by_555[INDEX_COUNT];

static inline int active555Index() {
  return (board_config::kDefault555Mode == board_config::TIMER555_RS) ? INDEX_RS : INDEX_PZR;
}

static inline void dwtInit() {
  ARM_DEMCR |= ARM_DEMCR_TRCENA;
  ARM_DWT_CTRL |= ARM_DWT_CTRL_CYCCNTENA;
  ARM_DWT_CYCCNT = 0;
}

static inline void resetCaptureState() {
  noInterrupts();
  g_cap.last_rise_cycles = 0;
  g_cap.last_fall_cycles = 0;
  g_cap.high_cycles = 0;
  g_cap.low_cycles = 0;
  g_cap.last_edge = EDGE_NONE;
  g_cap.pair_ready = false;
  interrupts();
}

static inline float updateMA(float *buf, float &sum, int &idx, int &count, int n, float val) {
  sum -= buf[idx];
  buf[idx] = val;
  sum += val;
  idx = (idx + 1) % n;
  if (count < n) {
    count++;
  }
  return sum / count;
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

static inline float updateMedian3(float *buf, int &idx, int &count, float val) {
  buf[idx] = val;
  idx = (idx + 1) % kRaMedianN;
  if (count < kRaMedianN) {
    count++;
  }
  if (count < kRaMedianN) {
    return val;
  }
  return median3(buf[0], buf[1], buf[2]);
}

static float computeModeledLowCycles() {
  const double rb = static_cast<double>(g_rb_ohm);
  const double cf = static_cast<double>(g_cf_f);
  if (!(rb > 0.0) || !(cf > 0.0)) {
    return NAN;
  }

  const double modeled_cycles = static_cast<double>(kLn2) * cf * rb * static_cast<double>(F_CPU_ACTUAL);
  return (isfinite(modeled_cycles) && modeled_cycles > 0.0) ? static_cast<float>(modeled_cycles) : NAN;
}

static void refreshModeledLowCycles() {
  g_l_cycles_model = computeModeledLowCycles();
}

static const __FlashStringHelper *raLowCycleSourceLabel() {
  return (kRaLowCycleSource == LCYC_SOURCE_MODELED) ? F("modeled_lcyc_from_rb_cf") : F("measured_lcyc");
}

static void resetAll555Averages() {
  for (int i = 0; i < INDEX_COUNT; ++i) {
    g_low_cycle_smoother_by_555[i].reset();
  }
}

static bool waitForPair(uint32_t &h_cycles, uint32_t &l_cycles, uint32_t timeout_ms = 0) {
  if (timeout_ms == 0) {
    timeout_ms = computePairTimeoutMs();
  }
  const uint32_t t0 = millis();
  while (!g_cap.pair_ready) {
    if (Serial.available() > 0) {
      break;
    }
    if ((millis() - t0) > timeout_ms) {
      return false;
    }
  }
  if (!g_cap.pair_ready) {
    return false;
  }
  noInterrupts();
  h_cycles = g_cap.high_cycles;
  l_cycles = g_cap.low_cycles;
  g_cap.high_cycles = 0;
  g_cap.low_cycles = 0;
  g_cap.pair_ready = false;
  interrupts();
  return (h_cycles != 0 && l_cycles != 0);
}

static bool measureOneRa(uint8_t ch, bool switched, float &out_ra) {
  const uint32_t timeout_ms = computePairTimeoutMs();
  const uint32_t measure_start_ms = millis();

  if (switched) {
    muxSelect(ch);
    for (int d = 0; d < kDiscardCyclesAfterSwitch; ++d) {
      uint32_t h = 0;
      uint32_t l = 0;
      const uint32_t elapsed_ms = millis() - measure_start_ms;
      if (elapsed_ms >= timeout_ms) {
        return false;
      }
      if (!waitForPair(h, l, timeout_ms - elapsed_ms)) {
        return false;
      }
    }
  }

  const uint32_t elapsed_ms = millis() - measure_start_ms;
  if (elapsed_ms >= timeout_ms) {
    return false;
  }

  uint32_t h_cycles = 0;
  uint32_t l_cycles = 0;
  if (!waitForPair(h_cycles, l_cycles, timeout_ms - elapsed_ms)) {
    return false;
  }
  return updateChannelRaFromPair(ch, h_cycles, l_cycles, out_ra);
}

}  // namespace

void isr555() {
  const uint32_t cyc_now = ARM_DWT_CYCCNT;
  const bool level_high = digitalReadFast(board_config::kTimer555IcpPin);
  const uint8_t active_rs_ch = pzt_rs_controller::activeChannel();
  const bool track_rs_ch = active_rs_ch < 16;
  const uint8_t prev_edge = g_cap.last_edge;
  const bool saw_repeated_edge =
      (prev_edge != EDGE_NONE) &&
      ((level_high && prev_edge == EDGE_RISE) || (!level_high && prev_edge == EDGE_FALL));

  pzt_rs_controller::noteIsrFire();

  if (level_high) {
    if (track_rs_ch) {
      pzt_rs_controller::noteRise(active_rs_ch);
    }
    if (g_cap.pair_ready) {
      g_cap.high_cycles = 0;
      g_cap.low_cycles = 0;
      g_cap.pair_ready = false;
    }

    if (prev_edge == EDGE_FALL && g_cap.last_fall_cycles != 0) {
      g_cap.low_cycles = cyc_now - g_cap.last_fall_cycles;
    } else {
      g_cap.low_cycles = 0;
      g_cap.pair_ready = false;
      if (saw_repeated_edge) {
        g_cap.sequence_errors++;
      }
    }
    g_cap.last_rise_cycles = cyc_now;
    g_cap.last_edge = EDGE_RISE;
  } else {
    if (track_rs_ch) {
      pzt_rs_controller::noteFall(active_rs_ch);
    }
    if (prev_edge == EDGE_RISE && g_cap.last_rise_cycles != 0) {
      g_cap.high_cycles = cyc_now - g_cap.last_rise_cycles;
    } else {
      g_cap.high_cycles = 0;
      g_cap.pair_ready = false;
      if (saw_repeated_edge) {
        g_cap.sequence_errors++;
      }
    }
    g_cap.last_fall_cycles = cyc_now;
    g_cap.last_edge = EDGE_FALL;
    if (g_cap.high_cycles && g_cap.low_cycles) {
      if (track_rs_ch) {
        pzt_rs_controller::notePairReady(active_rs_ch, g_cap.high_cycles, g_cap.low_cycles);
      }
      g_cap.pair_ready = true;
    }
  }
}

void begin() {
  pinMode(board_config::kPzrIcpPin, INPUT);
  pinMode(board_config::kPzrMuxA0Pin, OUTPUT);
  pinMode(board_config::kPzrMuxA1Pin, OUTPUT);
  pinMode(board_config::kPzrMuxA2Pin, OUTPUT);
  pinMode(board_config::kPzrMuxA3Pin, OUTPUT);
  if (board_config::kPzrMuxEnPin >= 0) {
    pinMode(board_config::kPzrMuxEnPin, OUTPUT);
  }

  pinMode(board_config::kRsIcpPin, INPUT);
  pinMode(board_config::kRsMuxA0Pin, OUTPUT);
  pinMode(board_config::kRsMuxA1Pin, OUTPUT);
  pinMode(board_config::kRsMuxA2Pin, OUTPUT);
  pinMode(board_config::kRsMuxA3Pin, OUTPUT);
  if (board_config::kRsMuxEnPin >= 0) {
    pinMode(board_config::kRsMuxEnPin, OUTPUT);
  }

  muxDisableAll();

  dwtInit();
  attachInterrupt(digitalPinToInterrupt(board_config::kTimer555IcpPin), isr555, CHANGE);
  refreshModeledLowCycles();
  resetAllChannels();

  parkMux(15);
  muxDisableAll();
}

bool handleChannels(const String &args) {
  String a = args;
  a.trim();
  if (a.length() == 0) {
    return false;
  }

  int new_count = 0;
  int start = 0;
  const int len = a.length();
  while (start < len) {
    const int comma = a.indexOf(',', start);
    String tok = (comma < 0) ? a.substring(start) : a.substring(start, comma);
    tok.trim();
    if (tok.length() > 0) {
      const int ch = tok.toInt();
      if (ch < 0 || ch > 15 || new_count >= kMaxChannelSequence) {
        return false;
      }
      g_channel_sequence[new_count++] = static_cast<uint8_t>(ch);
    }
    if (comma < 0) {
      break;
    }
    start = comma + 1;
  }

  if (new_count <= 0) {
    return false;
  }
  g_channel_count = new_count;
  resetAllChannels();
  return true;
}

bool handleRepeat(const String &args) {
  const int n = args.toInt();
  if (n < 1 || n > 256) {
    return false;
  }
  g_repeat_count = n;
  return true;
}

bool handleBuffer(const String &args) {
  const int b = args.toInt();
  if (b < 1 || b > 256) {
    return false;
  }
  g_buffer_sweeps = b;
  return true;
}

bool handleRun(const String &args) {
  if (args.length() > 0) {
    const uint32_t ms = static_cast<uint32_t>(args.toInt());
    if (ms == 0) {
      return false;
    }
    g_timed_run = true;
    g_run_stop_ms = millis() + ms;
  } else {
    g_timed_run = false;
  }
  resetCaptureDiagnostics();
  g_running = true;
  return true;
}

void handleStop() {
  g_running = false;
  g_timed_run = false;
}

bool handleRb(const String &args) {
  double v = 0.0;
  if (!shared_proto::parseValueSuffix(args, v, false) || !(v > 0.0 && v < 1e9)) {
    return false;
  }
  g_rb_ohm = static_cast<float>(v);
  refreshModeledLowCycles();
  resetAllChannels();
  return true;
}

bool handleRk(const String &args) {
  double v = 0.0;
  if (!shared_proto::parseValueSuffix(args, v, false) || !(v >= 0.0 && v < 1e9)) {
    return false;
  }
  g_rk_ohm = static_cast<float>(v);
  resetAllChannels();
  return true;
}

bool handleCf(const String &args) {
  double v = 0.0;
  if (!shared_proto::parseValueSuffix(args, v, true) || !(v > 1e-13 && v < 1e-2)) {
    return false;
  }
  g_cf_f = static_cast<float>(v);
  refreshModeledLowCycles();
  resetAllChannels();
  return true;
}

bool handleRxMax(const String &args) {
  double v = 0.0;
  if (!shared_proto::parseValueSuffix(args, v, false) || !(v > 0.0 && v < 1e9)) {
    return false;
  }
  g_rx_max_ohm = static_cast<float>(v);
  return true;
}

bool handleAscii(const String &args) {
  String a = args;
  a.trim();
  a.toLowerCase();

  bool new_mode = g_ascii_output;
  if (a.length() == 0) {
    new_mode = !g_ascii_output;
  } else if (a == "1" || a == "on" || a == "true" || a == "ascii") {
    new_mode = true;
  } else if (a == "0" || a == "off" || a == "false" || a == "bin" || a == "binary") {
    new_mode = false;
  } else {
    return false;
  }

  if (new_mode != g_ascii_output) {
    g_ascii_output = new_mode;
    g_running = false;
    g_timed_run = false;
  }
  return true;
}

void doOneBlock() {
  const uint32_t samples_per_sweep = static_cast<uint32_t>(g_channel_count) * static_cast<uint32_t>(g_repeat_count);
  const uint32_t total_samples_32 = samples_per_sweep * static_cast<uint32_t>(g_buffer_sweeps);

  if (total_samples_32 == 0 || total_samples_32 > kMaxBlockSamples) {
    g_running = false;
    g_timed_run = false;
    Serial.println(F("# ERROR: block too large. Reduce channels/repeat/buffer."));
    return;
  }

  const uint16_t total_samples = static_cast<uint16_t>(total_samples_32);
  const uint32_t capture_start_us = micros();
  uint16_t idx = 0;
  int prev_ch = -1;

  for (int b = 0; b < g_buffer_sweeps; ++b) {
    for (int ci = 0; ci < g_channel_count; ++ci) {
      const uint8_t ch = g_channel_sequence[ci];
      for (int r = 0; r < g_repeat_count; ++r) {
        const bool switched = (prev_ch != static_cast<int>(ch));
        prev_ch = static_cast<int>(ch);
        float ra = 0.0f;
        (void)measureOneRa(ch, switched, ra);
        long v = lroundf(ra);
        if (v < 0) {
          v = 0;
        }
        if (v > 65535L) {
          v = 65535L;
        }
        g_sample_buf[idx++] = static_cast<uint16_t>(v);
      }
    }
  }

  const uint32_t capture_end_us = micros();
  const uint32_t dt_us = capture_end_us - capture_start_us;
  const uint16_t avg_dt = (total_samples > 0)
                              ? static_cast<uint16_t>(min((dt_us + total_samples / 2u) / total_samples, 65535u))
                              : 0u;

  if (g_ascii_output) {
    for (int b = 0; b < g_buffer_sweeps; ++b) {
      const uint32_t base = static_cast<uint32_t>(b) * samples_per_sweep;
      for (uint32_t j = 0; j < samples_per_sweep; ++j) {
        if (j) {
          Serial.print(',');
        }
        Serial.print(g_sample_buf[base + j]);
      }
      Serial.println();
    }
    Serial.flush();
    return;
  }

  static uint8_t block_buf[4 + (kMaxBlockSamples * sizeof(uint16_t)) + 10];
  const uint32_t block_bytes = shared_proto::encodeBinaryBlock(
      block_buf,
      sizeof(block_buf),
      g_sample_buf,
      total_samples,
      avg_dt,
      capture_start_us,
      capture_end_us);
  if (block_bytes > 0) {
    Serial.write(block_buf, block_bytes);
    Serial.flush();
  }
}

void printStatus() {
  Serial.println(F("# -------- STATUS (PZR mode) --------"));
  Serial.print(F("# 555 source="));
  Serial.println(board_config::kTimer555Name);
  Serial.print(F("# 555 ICP pin="));
  Serial.println(board_config::kTimer555IcpPin);
  Serial.print(F("# 555 MUX pins A0,A1,A2,A3="));
  Serial.print(board_config::kTimer555MuxA0Pin);
  Serial.print(',');
  Serial.print(board_config::kTimer555MuxA1Pin);
  Serial.print(',');
  Serial.print(board_config::kTimer555MuxA2Pin);
  Serial.print(',');
  Serial.println(board_config::kTimer555MuxA3Pin);
  Serial.print(F("# channels="));
  for (int i = 0; i < g_channel_count; ++i) {
    Serial.print(g_channel_sequence[i]);
    if (i < g_channel_count - 1) {
      Serial.print(',');
    }
  }
  Serial.println();
  Serial.print(F("# repeat="));
  Serial.println(g_repeat_count);
  Serial.print(F("# buffer="));
  Serial.println(g_buffer_sweeps);
  Serial.println(F("# output_value=Ra_ohm (total Rx+Rk, Rk is not subtracted)"));
  Serial.print(F("# rb_ohm="));
  Serial.println(g_rb_ohm, 6);
  Serial.print(F("# rk_ohm="));
  Serial.println(g_rk_ohm, 6);
  Serial.print(F("# cf_f="));
  Serial.println(g_cf_f, 12);
  Serial.print(F("# rxmax_ohm="));
  Serial.println(g_rx_max_ohm, 6);
  Serial.print(F("# ra_calc_mode="));
  Serial.println(raLowCycleSourceLabel());
  Serial.println(F("# measured_lcyc_ma_is_reported_in_diagnostics"));
  Serial.print(F("# lcyc_ma_n="));
  Serial.println(kLCycMaN);
  Serial.print(F("# ra_median_n="));
  Serial.println(kRaMedianN);
  Serial.print(F("# active_lcyc_count="));
  Serial.println(g_low_cycle_smoother_by_555[active555Index()].l_cycles_count);
  Serial.print(F("# active_lcyc_avg_cycles="));
  Serial.println(g_low_cycle_smoother_by_555[active555Index()].last_l_cycles_avg, 3);
  Serial.print(F("# modeled_lcyc_cycles="));
  Serial.println(g_l_cycles_model, 3);
  Serial.print(F("# modeled_lcyc_us="));
  if (isfinite(g_l_cycles_model)) {
    Serial.println(cyclesFloatToUs(static_cast<double>(g_l_cycles_model)), 3);
  } else {
    Serial.println(F("nan"));
  }
  for (int i = 0; i < g_channel_count; ++i) {
    printChannelTimingDiagnostics(g_channel_sequence[i], F("# timing "));
  }
  Serial.print(F("# pair_timeout_ms="));
  Serial.println(computePairTimeoutMs());
  Serial.print(F("# capture_sequence_errors="));
  Serial.println(g_cap.sequence_errors);
  const uint32_t samples_per_sweep = static_cast<uint32_t>(g_channel_count) * static_cast<uint32_t>(g_repeat_count);
  const uint32_t total = samples_per_sweep * static_cast<uint32_t>(g_buffer_sweeps);
  Serial.print(F("# samples_per_sweep="));
  Serial.println(samples_per_sweep);
  Serial.print(F("# samples_per_block="));
  Serial.println(total);
  Serial.print(F("# max_block_samples="));
  Serial.println(kMaxBlockSamples);
  Serial.print(F("# running="));
  Serial.println(g_running ? F("true") : F("false"));
  Serial.print(F("# output="));
  Serial.println(g_ascii_output ? F("ascii") : F("binary"));
  Serial.println(F("# -------------------------"));
}

bool isRunning() {
  return g_running;
}

bool timedRunExpired() {
  if (g_running && g_timed_run && (int32_t)(millis() - g_run_stop_ms) >= 0) {
    g_running = false;
    g_timed_run = false;
    return true;
  }
  return false;
}

bool asciiOutput() {
  return g_ascii_output;
}

uint32_t captureSequenceErrors() {
  return g_cap.sequence_errors;
}

void resetCaptureDiagnostics() {
  noInterrupts();
  g_cap.sequence_errors = 0;
  interrupts();
}

void resetAllChannels() {
  for (int i = 0; i < 16; ++i) {
    g_channel_state[i].reset();
  }
  resetAll555Averages();
}

void muxDisableAll() {
  if (board_config::kPzrMuxEnPin >= 0) {
    digitalWriteFast(board_config::kPzrMuxEnPin, LOW);
  }
  if (board_config::kRsMuxEnPin >= 0) {
    digitalWriteFast(board_config::kRsMuxEnPin, LOW);
  }
}

void muxEnable(bool en) {
  if (board_config::kTimer555MuxEnPin >= 0) {
    digitalWriteFast(board_config::kTimer555MuxEnPin, en ? HIGH : LOW);
  }
}

void muxSelect(uint8_t ch) {
  ch &= 0x0F;
  muxEnable(false);
  digitalWriteFast(board_config::kTimer555MuxA0Pin, (ch & 0x01) ? HIGH : LOW);
  digitalWriteFast(board_config::kTimer555MuxA1Pin, (ch & 0x02) ? HIGH : LOW);
  digitalWriteFast(board_config::kTimer555MuxA2Pin, (ch & 0x04) ? HIGH : LOW);
  digitalWriteFast(board_config::kTimer555MuxA3Pin, (ch & 0x08) ? HIGH : LOW);
  delayNanoseconds(kTimer555MuxSettleNs);
  muxEnable(true);
  resetCaptureState();
}

void parkMux(uint8_t ch) {
  muxSelect(ch);
}

uint32_t computePairTimeoutMs() {
  double ra = static_cast<double>(g_rx_max_ohm) + static_cast<double>(g_rk_ohm);
  if (ra < 0.0) {
    ra = 0.0;
  }
  double rb = static_cast<double>(g_rb_ohm);
  if (rb < 1.0) {
    rb = 1.0;
  }
  double c = static_cast<double>(g_cf_f);
  if (c < 1e-15) {
    c = 1e-15;
  }
  double timeout_ms = static_cast<double>(kLn2) * c * (ra + 2.0 * rb) * 1000.0 * 3.0 + 20.0;
  if (timeout_ms < 50.0) {
    timeout_ms = 50.0;
  }
  if (timeout_ms > 5000.0) {
    timeout_ms = 5000.0;
  }
  return static_cast<uint32_t>(ceil(timeout_ms));
}

bool takeReadyPair(uint32_t &h_cycles, uint32_t &l_cycles) {
  if (!g_cap.pair_ready) {
    return false;
  }
  noInterrupts();
  h_cycles = g_cap.high_cycles;
  l_cycles = g_cap.low_cycles;
  g_cap.high_cycles = 0;
  g_cap.low_cycles = 0;
  g_cap.pair_ready = false;
  interrupts();
  return (h_cycles != 0 && l_cycles != 0);
}

bool updateChannelRaFromPair(uint8_t ch, uint32_t h_cycles, uint32_t l_cycles, float &out_ra) {
  if (ch > 15 || h_cycles == 0 || l_cycles == 0) {
    return false;
  }

  LowCycleSmootherState &low_cycle_smoother = g_low_cycle_smoother_by_555[active555Index()];
  const float l_cycles_avg_measured = low_cycle_smoother.update(l_cycles);
  const float l_cycles_calc = g_l_cycles_model;
  g_channel_state[ch].last_h_cycles = h_cycles;
  g_channel_state[ch].last_l_cycles = l_cycles;
  g_channel_state[ch].last_l_cycles_avg_used = l_cycles_avg_measured;
  g_channel_state[ch].last_l_cycles_model_used = l_cycles_calc;

  const float l_cycles_for_ra =
      (kRaLowCycleSource == LCYC_SOURCE_MODELED) ? l_cycles_calc : l_cycles_avg_measured;
  float last_ra = NAN;
  float last_ra_ma = NAN;
  if (isfinite(l_cycles_for_ra) && l_cycles_for_ra > 0.0f) {
    last_ra = g_rb_ohm * ((static_cast<float>(h_cycles) - l_cycles_for_ra) / l_cycles_for_ra);

    if (isfinite(last_ra)) {
      if (kRaMaN > 1) {
        last_ra_ma = updateMA(
            g_channel_state[ch].ra_buf,
            g_channel_state[ch].ra_sum,
            g_channel_state[ch].ra_idx,
            g_channel_state[ch].ra_count,
            kRaMaN,
            last_ra);
      } else {
        last_ra_ma = last_ra;
      }
    }
  }

  float candidate = isfinite(last_ra_ma) ? last_ra_ma : (isfinite(last_ra) ? last_ra : NAN);
  if (isfinite(candidate)) {
    candidate = updateMedian3(
        g_channel_state[ch].ra_median_buf,
        g_channel_state[ch].ra_median_idx,
        g_channel_state[ch].ra_median_count,
        candidate);
    g_channel_state[ch].last_plot_ra = candidate;
  }

  out_ra = isfinite(g_channel_state[ch].last_plot_ra) ? g_channel_state[ch].last_plot_ra : 0.0f;
  return true;
}

float lastPlotRa(uint8_t ch) {
  if (ch > 15) {
    return NAN;
  }
  return g_channel_state[ch].last_plot_ra;
}

double cyclesToUs(uint32_t cycles) {
  return (static_cast<double>(cycles) * 1000000.0) / static_cast<double>(F_CPU_ACTUAL);
}

double cyclesFloatToUs(double cycles) {
  return (cycles * 1000000.0) / static_cast<double>(F_CPU_ACTUAL);
}

void printChannelTimingDiagnostics(uint8_t ch, const __FlashStringHelper *prefix) {
  if (ch > 15) {
    return;
  }
  if (prefix == nullptr) {
    prefix = F("# RS timing ");
  }

  const ChannelState &state = g_channel_state[ch];
  Serial.print(prefix);
  Serial.print(F("ch"));
  Serial.print(static_cast<int>(ch));
  Serial.print(F(": "));

  if (state.last_h_cycles == 0 || state.last_l_cycles == 0) {
    Serial.println(F("no completed pair yet"));
    return;
  }

  const double rb = static_cast<double>(g_rb_ohm);
  const double cf = static_cast<double>(g_cf_f);
  const double h_us = cyclesToUs(state.last_h_cycles);
  const double l_us = cyclesToUs(state.last_l_cycles);
  const double l_avg_us =
      (isfinite(state.last_l_cycles_avg_used) && state.last_l_cycles_avg_used > 0.0f)
          ? cyclesFloatToUs(static_cast<double>(state.last_l_cycles_avg_used))
          : NAN;
  const double l_model_us =
      (isfinite(state.last_l_cycles_model_used) && state.last_l_cycles_model_used > 0.0f)
          ? cyclesFloatToUs(static_cast<double>(state.last_l_cycles_model_used))
          : NAN;
  const double model_l_us = static_cast<double>(kLn2) * cf * rb * 1000000.0;
  const double model_h_us =
      isfinite(state.last_plot_ra)
          ? (static_cast<double>(kLn2) * cf * (static_cast<double>(state.last_plot_ra) + rb) * 1000000.0)
          : NAN;
  const double ra_from_raw =
      (isfinite(state.last_l_cycles_avg_used) && state.last_l_cycles_avg_used > 0.0f)
          ? (rb * ((static_cast<double>(state.last_h_cycles) - static_cast<double>(state.last_l_cycles_avg_used)) /
                   static_cast<double>(state.last_l_cycles_avg_used)))
          : NAN;

  Serial.print(F("hCyc="));
  Serial.print(state.last_h_cycles);
  Serial.print(F(", lCyc="));
  Serial.print(state.last_l_cycles);
  Serial.print(F(", lCycAvg="));
  if (isfinite(state.last_l_cycles_avg_used)) {
    Serial.print(state.last_l_cycles_avg_used, 3);
  } else {
    Serial.print(F("nan"));
  }
  Serial.print(F(", lCycModel="));
  if (isfinite(state.last_l_cycles_model_used)) {
    Serial.print(state.last_l_cycles_model_used, 3);
  } else {
    Serial.print(F("nan"));
  }
  Serial.print(F(", h_us="));
  Serial.print(h_us, 3);
  Serial.print(F(", l_us="));
  Serial.print(l_us, 3);
  Serial.print(F(", l_avg_us="));
  if (isfinite(l_avg_us)) {
    Serial.print(l_avg_us, 3);
  } else {
    Serial.print(F("nan"));
  }
  Serial.print(F(", l_model_us="));
  if (isfinite(l_model_us)) {
    Serial.print(l_model_us, 3);
  } else {
    Serial.print(F("nan"));
  }
  Serial.print(F(", ra_ohm="));
  if (isfinite(state.last_plot_ra)) {
    Serial.print(state.last_plot_ra, 3);
  } else {
    Serial.print(F("nan"));
  }
  Serial.print(F(", ra_from_raw_ohm="));
  if (isfinite(ra_from_raw)) {
    Serial.print(ra_from_raw, 3);
  } else {
    Serial.print(F("nan"));
  }
  Serial.print(F(", model_h_us="));
  if (isfinite(model_h_us)) {
    Serial.print(model_h_us, 3);
  } else {
    Serial.print(F("nan"));
  }
  Serial.print(F(", model_l_us="));
  Serial.print(model_l_us, 3);
  Serial.println();
}

}  // namespace pzr_controller
