#include "PzrController.h"

#include <math.h>
#include <string.h>

#include "SharedProtocol.h"

namespace pzr_controller {

namespace {

static constexpr float kLn2 = 0.69314718056f;
static constexpr int kRaMaN = 1;
static constexpr int kLCycMaN = 50;
static constexpr uint32_t kMuxSettleNs = 100;
static constexpr int kDiscardCyclesAfterSwitch = 1;

struct CaptureState {
  volatile uint32_t last_rise = 0;
  volatile uint32_t last_fall = 0;
  volatile uint32_t high_cycles = 0;
  volatile uint32_t low_cycles = 0;
  volatile bool pair_ready = false;
} g_cap;

struct ChannelState {
  float ra_buf[kRaMaN] = {0};
  float ra_sum = 0;
  int ra_idx = 0;
  int ra_count = 0;
  float last_plot_ra = NAN;

  void reset() {
    memset(ra_buf, 0, sizeof(ra_buf));
    ra_sum = 0;
    ra_idx = 0;
    ra_count = 0;
    last_plot_ra = NAN;
  }
} g_ch_state[16];

struct TimerState {
  uint32_t lcyc_buf[kLCycMaN] = {0};
  uint64_t lcyc_sum = 0;
  int lcyc_idx = 0;
  int lcyc_count = 0;
  float last_lcyc_avg = NAN;

  void reset() {
    memset(lcyc_buf, 0, sizeof(lcyc_buf));
    lcyc_sum = 0;
    lcyc_idx = 0;
    lcyc_count = 0;
    last_lcyc_avg = NAN;
  }

  float update(uint32_t lcyc) {
    lcyc_sum -= lcyc_buf[lcyc_idx];
    lcyc_buf[lcyc_idx] = lcyc;
    lcyc_sum += lcyc;
    lcyc_idx = (lcyc_idx + 1) % kLCycMaN;
    if (lcyc_count < kLCycMaN) {
      ++lcyc_count;
    }
    last_lcyc_avg = (lcyc_count > 0) ? (static_cast<float>(lcyc_sum) / static_cast<float>(lcyc_count)) : NAN;
    return last_lcyc_avg;
  }
} g_timer_state[SOURCE_COUNT];

Runtime *g_rt = nullptr;

static inline uint32_t dwtNow() {
  return ARM_DWT_CYCCNT;
}

static inline void dwtInit() {
  ARM_DEMCR |= ARM_DEMCR_TRCENA;
  ARM_DWT_CTRL |= ARM_DWT_CTRL_CYCCNTENA;
  ARM_DWT_CYCCNT = 0;
}

static uint32_t computePairTimeoutMs(const Runtime &rt) {
  double ra = static_cast<double>(rt.cfg.rx_max_ohm) + static_cast<double>(rt.cfg.rk_ohm);
  if (ra < 0.0) {
    ra = 0.0;
  }

  double rb = static_cast<double>(rt.cfg.rb_ohm);
  if (rb < 1.0) {
    rb = 1.0;
  }

  double c = static_cast<double>(rt.cfg.cf_f);
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

void isr555() {
  if (g_rt == nullptr) {
    return;
  }

  const bool level_high = digitalReadFast(g_rt->pins.icp_pin);
  const uint32_t now = dwtNow();

  if (level_high) {
    if (g_cap.last_fall != 0) {
      g_cap.low_cycles = now - g_cap.last_fall;
    }
    g_cap.last_rise = now;
  } else {
    if (g_cap.last_rise != 0) {
      g_cap.high_cycles = now - g_cap.last_rise;
      if (g_cap.low_cycles != 0) {
        g_cap.pair_ready = true;
      }
    }
    g_cap.last_fall = now;
  }
}

static void resetCaptureState() {
  noInterrupts();
  g_cap.last_rise = 0;
  g_cap.last_fall = 0;
  g_cap.high_cycles = 0;
  g_cap.low_cycles = 0;
  g_cap.pair_ready = false;
  interrupts();
}

static bool waitForPair(Runtime &rt, uint32_t &h, uint32_t &l) {
  const uint32_t timeout_ms = computePairTimeoutMs(rt);
  const uint32_t t0 = millis();

  while (!g_cap.pair_ready) {
    if (Serial.available() > 0) {
      break;
    }
    if ((millis() - t0) > timeout_ms) {
      return false;
    }
    yield();
  }
  if (!g_cap.pair_ready) {
    return false;
  }

  noInterrupts();
  h = g_cap.high_cycles;
  l = g_cap.low_cycles;
  g_cap.pair_ready = false;
  interrupts();

  return (h != 0 && l != 0);
}

static inline float updateMA(float *buf, float &sum, int &idx, int &count, int n, float val) {
  sum -= buf[idx];
  buf[idx] = val;
  sum += val;
  idx = (idx + 1) % n;
  if (count < n) {
    ++count;
  }
  return sum / count;
}

static void resetAllTimerAverages() {
  for (int i = 0; i < SOURCE_COUNT; ++i) {
    g_timer_state[i].reset();
  }
}

static void resetAllChannels() {
  for (int i = 0; i < 16; ++i) {
    g_ch_state[i].reset();
  }
  resetAllTimerAverages();
}

static TimerState &activeTimerState(const Runtime &rt) {
  const uint8_t source_index = (rt.pins.source_index < SOURCE_COUNT) ? rt.pins.source_index : SOURCE_PZR;
  return g_timer_state[source_index];
}

static bool hasRequiredPins(const Pins &pins) {
  return pins.icp_pin >= 0 &&
         pins.mux_a0 >= 0 &&
         pins.mux_a1 >= 0 &&
         pins.mux_a2 >= 0 &&
         pins.mux_a3 >= 0;
}

static inline void muxEnable(Runtime &rt, bool en) {
  if (rt.pins.mux_en < 0) {
    return;
  }
  bool level = en ? HIGH : LOW;
  if (rt.pins.mux_en_active_low) {
    level = !level;
  }
  digitalWriteFast(rt.pins.mux_en, level);
}

static void muxSelect(Runtime &rt, uint8_t ch) {
  ch &= 0x0F;
  muxEnable(rt, false);
  digitalWriteFast(rt.pins.mux_a0, (ch & 0x01) ? HIGH : LOW);
  digitalWriteFast(rt.pins.mux_a1, (ch & 0x02) ? HIGH : LOW);
  digitalWriteFast(rt.pins.mux_a2, (ch & 0x04) ? HIGH : LOW);
  digitalWriteFast(rt.pins.mux_a3, (ch & 0x08) ? HIGH : LOW);
  delayNanoseconds(kMuxSettleNs);
  muxEnable(rt, true);
  resetCaptureState();
}

static bool measureOneRa(Runtime &rt, uint8_t ch, bool switched, float &out_ra) {
  if (switched) {
    muxSelect(rt, ch);
    for (int i = 0; i < kDiscardCyclesAfterSwitch; ++i) {
      uint32_t h = 0;
      uint32_t l = 0;
      if (!waitForPair(rt, h, l)) {
        return false;
      }
    }
  }

  uint32_t h = 0;
  uint32_t l = 0;
  if (!waitForPair(rt, h, l)) {
    return false;
  }

  TimerState &timer_state = activeTimerState(rt);
  const float lcyc_avg = timer_state.update(l);

  float last_ra = NAN;
  float last_ra_ma = NAN;
  if (isfinite(lcyc_avg) && lcyc_avg > 0.0f) {
    last_ra = rt.cfg.rb_ohm * ((static_cast<float>(h) - lcyc_avg) / lcyc_avg);
    if (isfinite(last_ra)) {
      if (kRaMaN > 1) {
        last_ra_ma = updateMA(g_ch_state[ch].ra_buf, g_ch_state[ch].ra_sum, g_ch_state[ch].ra_idx,
                              g_ch_state[ch].ra_count, kRaMaN, last_ra);
      } else {
        last_ra_ma = last_ra;
      }
    }
  }

  const float candidate = isfinite(last_ra_ma) ? last_ra_ma : (isfinite(last_ra) ? last_ra : NAN);
  if (isfinite(candidate)) {
    g_ch_state[ch].last_plot_ra = candidate;
  }

  out_ra = isfinite(g_ch_state[ch].last_plot_ra) ? g_ch_state[ch].last_plot_ra : 0.0f;
  return true;
}

}  // namespace

void begin(Runtime &rt, const Pins &pins) {
  rt.pins = pins;
  g_rt = &rt;

  if (!hasRequiredPins(rt.pins)) {
    g_rt = nullptr;
    Serial.println(F("# ERROR: PZR pins not configured in sketch"));
    return;
  }

  pinMode(rt.pins.icp_pin, INPUT);
  pinMode(rt.pins.mux_a0, OUTPUT);
  pinMode(rt.pins.mux_a1, OUTPUT);
  pinMode(rt.pins.mux_a2, OUTPUT);
  pinMode(rt.pins.mux_a3, OUTPUT);
  if (rt.pins.mux_en >= 0) {
    pinMode(rt.pins.mux_en, OUTPUT);
    muxEnable(rt, true);
  }

  dwtInit();
  attachInterrupt(digitalPinToInterrupt(rt.pins.icp_pin), isr555, CHANGE);

  resetCaptureState();
  resetAllChannels();
  muxSelect(rt, 15);
}

void parkMux(Runtime &rt, uint8_t ch) {
  if (!hasRequiredPins(rt.pins)) {
    return;
  }
  muxSelect(rt, ch);
}

bool handleChannels(Runtime &rt, const String &args) {
  String a = args;
  a.trim();
  if (!a.length()) {
    return false;
  }

  int new_count = 0;
  int start = 0;
  const int len = a.length();

  while (start < len) {
    const int comma = a.indexOf(',', start);
    String tok = comma < 0 ? a.substring(start) : a.substring(start, comma);
    tok.trim();
    if (tok.length()) {
      const int ch = tok.toInt();
      if (ch < 0 || ch > 15 || new_count >= kMaxChannelSequence) {
        return false;
      }
      rt.cfg.channel_sequence[new_count++] = static_cast<uint8_t>(ch);
    }
    if (comma < 0) {
      break;
    }
    start = comma + 1;
  }

  if (new_count <= 0) {
    return false;
  }

  rt.cfg.channel_count = new_count;
  resetAllChannels();
  return true;
}

bool handleRepeat(Runtime &rt, const String &args) {
  const int n = args.toInt();
  if (n < 1 || n > 256) {
    return false;
  }
  rt.cfg.repeat_count = n;
  return true;
}

bool handleBuffer(Runtime &rt, const String &args) {
  const int b = args.toInt();
  if (b < 1 || b > 256) {
    return false;
  }
  rt.cfg.buffer_sweeps = b;
  return true;
}

bool handleRun(Runtime &rt, const String &args) {
  if (args.length()) {
    const uint32_t ms = static_cast<uint32_t>(args.toInt());
    if (ms == 0) {
      return false;
    }
    rt.cfg.timed_run = true;
    rt.cfg.run_stop_ms = millis() + ms;
  } else {
    rt.cfg.timed_run = false;
  }
  rt.cfg.running = true;
  return true;
}

void handleStop(Runtime &rt) {
  rt.cfg.running = false;
  rt.cfg.timed_run = false;
}

bool handleRb(Runtime &rt, const String &args) {
  double v = 0.0;
  if (!shared_proto::parseValueSuffix(args, v, false) || !(v > 0.0 && v < 1e9)) {
    return false;
  }
  rt.cfg.rb_ohm = static_cast<float>(v);
  resetAllChannels();
  return true;
}

bool handleRk(Runtime &rt, const String &args) {
  double v = 0.0;
  if (!shared_proto::parseValueSuffix(args, v, false) || !(v >= 0.0 && v < 1e9)) {
    return false;
  }
  rt.cfg.rk_ohm = static_cast<float>(v);
  resetAllChannels();
  return true;
}

bool handleCf(Runtime &rt, const String &args) {
  double v = 0.0;
  if (!shared_proto::parseValueSuffix(args, v, true) || !(v > 1e-13 && v < 1e-2)) {
    return false;
  }
  rt.cfg.cf_f = static_cast<float>(v);
  resetAllChannels();
  return true;
}

bool handleRxMax(Runtime &rt, const String &args) {
  double v = 0.0;
  if (!shared_proto::parseValueSuffix(args, v, false) || !(v > 0.0 && v < 1e9)) {
    return false;
  }
  rt.cfg.rx_max_ohm = static_cast<float>(v);
  return true;
}

bool handleAscii(Runtime &rt, const String &args) {
  String a = args;
  a.trim();
  a.toLowerCase();

  bool new_mode = rt.cfg.ascii_output;
  if (a.length() == 0) {
    new_mode = !new_mode;
  } else if (a == "1" || a == "on" || a == "true" || a == "ascii") {
    new_mode = true;
  } else if (a == "0" || a == "off" || a == "false" || a == "bin" || a == "binary") {
    new_mode = false;
  } else {
    return false;
  }

  if (new_mode != rt.cfg.ascii_output) {
    rt.cfg.ascii_output = new_mode;
    rt.cfg.running = false;
    rt.cfg.timed_run = false;
  }
  return true;
}

void printStatus(const Runtime &rt) {
  Serial.println(F("# -------- STATUS (PZR mode, modular) --------"));
  Serial.print(F("# 555 source="));
  Serial.println(rt.pins.source_name != nullptr ? rt.pins.source_name : "PZR/555_B");
  Serial.print(F("# 555 ICP pin="));
  Serial.println(rt.pins.icp_pin);
  Serial.print(F("# 555 MUX pins A0,A1,A2,A3="));
  Serial.print(rt.pins.mux_a0);
  Serial.print(',');
  Serial.print(rt.pins.mux_a1);
  Serial.print(',');
  Serial.print(rt.pins.mux_a2);
  Serial.print(',');
  Serial.println(rt.pins.mux_a3);
  Serial.print(F("# channels="));
  for (int i = 0; i < rt.cfg.channel_count; ++i) {
    Serial.print(rt.cfg.channel_sequence[i]);
    if (i + 1 < rt.cfg.channel_count) {
      Serial.print(',');
    }
  }
  Serial.println();
  Serial.print(F("# repeat="));
  Serial.println(rt.cfg.repeat_count);
  Serial.print(F("# buffer="));
  Serial.println(rt.cfg.buffer_sweeps);
  Serial.println(F("# output_value=Ra_ohm (total Rx+Rk, Rk is not subtracted)"));
  Serial.print(F("# rb_ohm="));
  Serial.println(rt.cfg.rb_ohm, 6);
  Serial.print(F("# rk_ohm="));
  Serial.println(rt.cfg.rk_ohm, 6);
  Serial.print(F("# cf_f="));
  Serial.println(rt.cfg.cf_f, 12);
  Serial.print(F("# rxmax_ohm="));
  Serial.println(rt.cfg.rx_max_ohm, 6);
  Serial.print(F("# lcyc_ma_n="));
  Serial.println(kLCycMaN);
  Serial.print(F("# active_lcyc_count="));
  Serial.println(activeTimerState(rt).lcyc_count);
  Serial.print(F("# active_lcyc_avg_cycles="));
  Serial.println(activeTimerState(rt).last_lcyc_avg, 3);
  Serial.print(F("# pair_timeout_ms="));
  Serial.println(computePairTimeoutMs(rt));
  const uint32_t samples_per_sweep = static_cast<uint32_t>(rt.cfg.channel_count) * static_cast<uint32_t>(rt.cfg.repeat_count);
  const uint32_t total_samples = samples_per_sweep * static_cast<uint32_t>(rt.cfg.buffer_sweeps);
  Serial.print(F("# samples_per_sweep="));
  Serial.println(samples_per_sweep);
  Serial.print(F("# samples_per_block="));
  Serial.println(total_samples);
  Serial.print(F("# max_block_samples="));
  Serial.println(kMaxBlockSamples);
  Serial.print(F("# running="));
  Serial.println(rt.cfg.running ? F("true") : F("false"));
  Serial.print(F("# output="));
  Serial.println(rt.cfg.ascii_output ? F("ascii") : F("binary"));
  Serial.println(F("# --------------------------------------------"));
}

void doOneBlock(Runtime &rt) {
  const uint32_t samples_per_sweep = static_cast<uint32_t>(rt.cfg.channel_count) * static_cast<uint32_t>(rt.cfg.repeat_count);
  const uint32_t total_samples_32 = samples_per_sweep * static_cast<uint32_t>(rt.cfg.buffer_sweeps);
  if (total_samples_32 == 0 || total_samples_32 > kMaxBlockSamples) {
    rt.cfg.running = false;
    rt.cfg.timed_run = false;
    Serial.println(F("# ERROR: block too large. Reduce channels/repeat/buffer."));
    return;
  }

  const uint16_t total_samples = static_cast<uint16_t>(total_samples_32);
  const uint32_t t0 = micros();
  uint16_t idx = 0;
  int prev_ch = -1;

  for (int b = 0; b < rt.cfg.buffer_sweeps; ++b) {
    for (int c = 0; c < rt.cfg.channel_count; ++c) {
      const uint8_t ch = rt.cfg.channel_sequence[c];
      for (int r = 0; r < rt.cfg.repeat_count; ++r) {
        const bool switched = prev_ch != ch;
        prev_ch = ch;

        float ra = 0.0f;
        (void)measureOneRa(rt, ch, switched, ra);

        long v = lroundf(ra);
        if (v < 0) {
          v = 0;
        }
        if (v > 65535L) {
          v = 65535L;
        }
        rt.sample_buf[idx++] = static_cast<uint16_t>(v);
      }
    }
  }

  const uint32_t t1 = micros();
  const uint32_t dt = t1 - t0;
  const uint16_t avg_dt = total_samples > 0 ? static_cast<uint16_t>(min((dt + total_samples / 2u) / total_samples, 65535u)) : 0;

  if (rt.cfg.ascii_output) {
    for (int b = 0; b < rt.cfg.buffer_sweeps; ++b) {
      const uint32_t base = static_cast<uint32_t>(b) * samples_per_sweep;
      for (uint32_t i = 0; i < samples_per_sweep; ++i) {
        if (i) {
          Serial.print(',');
        }
        Serial.print(rt.sample_buf[base + i]);
      }
      Serial.println();
    }
    Serial.flush();
    return;
  }

  static uint8_t block_buf[4 + (kMaxBlockSamples * sizeof(uint16_t)) + 10];
  const uint32_t block_bytes = shared_proto::encodeBinaryBlock(block_buf, sizeof(block_buf), rt.sample_buf, total_samples, avg_dt, t0, t1);
  if (block_bytes > 0) {
    Serial.write(block_buf, block_bytes);
    Serial.flush();
  }
}

}  // namespace pzr_controller
