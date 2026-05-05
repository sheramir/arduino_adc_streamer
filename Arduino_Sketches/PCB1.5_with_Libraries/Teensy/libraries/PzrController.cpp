#include "PzrController.h"

#include <math.h>

#include "SharedProtocol.h"

namespace pzr_controller {

namespace {

static constexpr float kLn2 = 0.69314718056f;
static constexpr int kRxMaN = 20;
static constexpr int kRdisMaN = 20;
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
  float rx_buf[kRxMaN] = {0};
  float rdis_buf[kRdisMaN] = {0};
  float rx_sum = 0;
  float rdis_sum = 0;
  int rx_idx = 0;
  int rdis_idx = 0;
  int rx_count = 0;
  int rdis_count = 0;
  float last_plot_rx = 0;

  void reset() {
    memset(rx_buf, 0, sizeof(rx_buf));
    memset(rdis_buf, 0, sizeof(rdis_buf));
    rx_sum = 0;
    rdis_sum = 0;
    rx_idx = 0;
    rdis_idx = 0;
    rx_count = 0;
    rdis_count = 0;
    last_plot_rx = 0;
  }
} g_ch_state[16];

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
  const bool level = digitalReadFast(g_rt->pins.icp_pin);
  const uint32_t now = dwtNow();

  if (level) {
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
  while (!g_cap.pair_ready && (millis() - t0) < timeout_ms) {
    if (Serial.available() > 0) {
      break;
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

static void resetAllChannels() {
  for (int i = 0; i < 16; ++i) {
    g_ch_state[i].reset();
  }
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

static bool measureOneRx(Runtime &rt, uint8_t ch, bool switched, float &out_rx) {
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

  const float f_cpu = static_cast<float>(F_CPU_ACTUAL);
  const float t_h = static_cast<float>(h) / f_cpu;
  const float t_l = static_cast<float>(l) / f_cpu;

  float rdis = NAN;
  const float denom = kLn2 * rt.cfg.cf_f;
  if (isfinite(denom) && denom > 0.0f) {
    rdis = (t_l / denom) - rt.cfg.rb_ohm;
  }

  if (isfinite(rdis) && rdis >= 0.0f) {
    updateMA(g_ch_state[ch].rdis_buf, g_ch_state[ch].rdis_sum, g_ch_state[ch].rdis_idx,
             g_ch_state[ch].rdis_count, kRdisMaN, rdis);
  }

  float rx = NAN;
  if (g_ch_state[ch].rdis_count > 0 && t_l > 0.0f) {
    const float t_div = t_h / t_l;
    const float rdis_used = g_ch_state[ch].rdis_sum / g_ch_state[ch].rdis_count;
    const float ra = t_div * (rt.cfg.rb_ohm + rdis_used) - rt.cfg.rb_ohm;
    const float last_rx = ra - rt.cfg.rk_ohm;
    if (isfinite(last_rx)) {
      rx = updateMA(g_ch_state[ch].rx_buf, g_ch_state[ch].rx_sum, g_ch_state[ch].rx_idx,
                    g_ch_state[ch].rx_count, kRxMaN, last_rx);
    }
  }

  if (isfinite(rx)) {
    g_ch_state[ch].last_plot_rx = rx;
  }
  out_rx = g_ch_state[ch].last_plot_rx;
  return true;
}

}  // namespace

void begin(Runtime &rt, const Pins &pins) {
  rt.pins = pins;
  g_rt = &rt;

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
      if (ch < 0 || ch > 15 || new_count >= 64) {
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
  Serial.print(F("# rb_ohm="));
  Serial.println(rt.cfg.rb_ohm, 6);
  Serial.print(F("# rk_ohm="));
  Serial.println(rt.cfg.rk_ohm, 6);
  Serial.print(F("# cf_f="));
  Serial.println(rt.cfg.cf_f, 12);
  Serial.print(F("# rxmax_ohm="));
  Serial.println(rt.cfg.rx_max_ohm, 6);
  Serial.print(F("# pair_timeout_ms="));
  Serial.println(computePairTimeoutMs(rt));
  const uint32_t samples_per_sweep = static_cast<uint32_t>(rt.cfg.channel_count) * static_cast<uint32_t>(rt.cfg.repeat_count);
  const uint32_t total_samples = samples_per_sweep * static_cast<uint32_t>(rt.cfg.buffer_sweeps);
  Serial.print(F("# samples_per_sweep="));
  Serial.println(samples_per_sweep);
  Serial.print(F("# samples_per_block="));
  Serial.println(total_samples);
  Serial.print(F("# max_block_samples="));
  Serial.println(2048);
  Serial.print(F("# running="));
  Serial.println(rt.cfg.running ? F("true") : F("false"));
  Serial.print(F("# output="));
  Serial.println(rt.cfg.ascii_output ? F("ascii") : F("binary"));
  Serial.println(F("# --------------------------------------------"));
}

void doOneBlock(Runtime &rt) {
  const uint32_t samples_per_sweep = static_cast<uint32_t>(rt.cfg.channel_count) * rt.cfg.repeat_count;
  const uint32_t total_samples_32 = samples_per_sweep * rt.cfg.buffer_sweeps;
  if (total_samples_32 == 0 || total_samples_32 > 2048) {
    rt.cfg.running = false;
    rt.cfg.timed_run = false;
    Serial.println(F("# ERROR: block too large"));
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

        float rx = 0.0f;
        (void)measureOneRx(rt, ch, switched, rx);

        long v = lroundf(rx);
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

  static uint8_t block_buf[4 + (2048u * sizeof(uint16_t)) + 10];
  const uint32_t block_bytes = shared_proto::encodeBinaryBlock(block_buf, sizeof(block_buf), rt.sample_buf, total_samples, avg_dt, t0, t1);
  if (block_bytes > 0) {
    Serial.write(block_buf, block_bytes);
    Serial.flush();
  }
}

}  // namespace pzr_controller
