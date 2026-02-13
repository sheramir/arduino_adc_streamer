// =============================================================
// Teensy 4.0 — Teensy555 Streamer (MG24-style protocol)
// 555 Astable unknown-R measurement (same math/pinout style as 555_analyzer_MUX2.ino)
// + MG24-compatible serial protocol (commands end with '*', #OK/#NOT_OK, binary blocks)
//
// Device ID line (for Python auto-detect):
//   # Teensy555
//
// Binary block format (same as ADC_Streamer_binary_scan.ino):
//   [0xAA][0x55][countL][countH] + count * uint16 +
//   avg_dt_us(uint16) + block_start_us(uint32) + block_end_us(uint32)
//
// Here each uint16 sample is: Rx (ohms), rounded & clamped to 0..65535
// =============================================================

#include <Arduino.h>
#include <math.h>
#include <stdlib.h>

// ------------------------ Pins (keep same as 555_analyzer_MUX2.ino) ------------------------
static const int ICP_PIN    = 16;  // 555 OUT -> interrupt-capable pin
static const int MUX_A0_PIN = 7;
static const int MUX_A1_PIN = 6;
static const int MUX_A2_PIN = 5;
static const int MUX_A3_PIN = 20;

// If your ADG706 EN pin is controlled by Teensy, set it here.
// If EN is tied to VDD/GND, leave as -1 (no pin).
static const int MUX_EN_PIN = -1;

// EN polarity (per your comment in 555_analyzer_MUX2.ino: active-HIGH)
static constexpr bool MUX_EN_ACTIVE_LOW = false;

// ------------------------ 555 model params (runtime-changeable) ------------------------
static constexpr float LN2 = 0.69314718056f;

// Defaults (match your original sketch)
static constexpr float DEFAULT_RB_OHM = 470.0f;       // discharge resistor
static constexpr float DEFAULT_RK_OHM = 0.0f;         // known series resistor (Ra = Rx + Rk)
static constexpr float DEFAULT_CF_F   = 0.0022e-6f;   // Farads (2.2 nF)
static constexpr float DEFAULT_RX_MAX_OHM = 50000.0f; // Max expected unknown resistor (ohms)

static float g_RB_OHM = DEFAULT_RB_OHM;
static float g_RK_OHM = DEFAULT_RK_OHM;
static float g_CF_F   = DEFAULT_CF_F;
static float g_RX_MAX_OHM = DEFAULT_RX_MAX_OHM;

// ------------------------ Measurement / smoothing knobs ------------------------
static constexpr uint32_t MUX_SETTLE_NS = 100;
static constexpr int DISCARD_CYCLES_AFTER_SWITCH = 1;

// Moving-average windows (same sizes as your sketch)
static constexpr int RX_MA_N   = 20;
static constexpr int RDIS_MA_N = 20;

// ------------------------ MG24-style protocol knobs ------------------------
static constexpr uint32_t BAUD_RATE = 115200;
static constexpr char     CMD_TERMINATOR = '*';
static constexpr int      MAX_CMD_LENGTH = 220;

// Channel sequence is like MG24 (can include duplicates)
static constexpr int MAX_CHANNEL_SEQUENCE = 64;
static uint8_t channelSequence[MAX_CHANNEL_SEQUENCE] = {0,2,3,4};
static int channelCount = 4;

static int repeatCount = 1;        // repeats per channel entry (per sweep)
static int bufferSweeps = 1;       // sweeps per binary block

static bool isRunning = false;
static bool timedRun  = false;
static uint32_t runStopMillis = 0;

static String inputLine;

// Block sample cap to keep RAM/latency sane
static constexpr uint16_t MAX_BLOCK_SAMPLES = 2048;
static uint16_t sampleBuf[MAX_BLOCK_SAMPLES];

// ------------------------ DWT cycle counter helpers ------------------------
static inline void dwtInit() {
  ARM_DEMCR |= ARM_DEMCR_TRCENA;
  ARM_DWT_CTRL |= ARM_DWT_CTRL_CYCCNTENA;
  ARM_DWT_CYCCNT = 0;
}
static inline uint32_t dwtNow() { return ARM_DWT_CYCCNT; }

// ------------------------ 555 capture state (interrupt-driven) ------------------------
struct CaptureState {
  volatile uint32_t lastRiseCycles = 0;
  volatile uint32_t lastFallCycles = 0;
  volatile uint32_t highCycles     = 0;
  volatile uint32_t lowCycles      = 0;
  volatile bool     pairReady      = false;
};

static CaptureState cap0;

static inline void resetCaptureState() {
  noInterrupts();
  cap0.lastRiseCycles = 0;
  cap0.lastFallCycles = 0;
  cap0.highCycles     = 0;
  cap0.lowCycles      = 0;
  cap0.pairReady      = false;
  interrupts();
}

void isr555() {
  const uint32_t now = dwtNow();
  const bool levelHigh = digitalReadFast(ICP_PIN);

  if (levelHigh) {
    if (cap0.lastFallCycles != 0) {
      cap0.lowCycles = (uint32_t)(now - cap0.lastFallCycles);
    }
    cap0.lastRiseCycles = now;
  } else {
    if (cap0.lastRiseCycles != 0) {
      cap0.highCycles = (uint32_t)(now - cap0.lastRiseCycles);
    }
    cap0.lastFallCycles = now;

    if (cap0.highCycles && cap0.lowCycles) {
      cap0.pairReady = true;
    }
  }
}


// Compute a sane per-sample timeout from 555 component values + Rx_max.
// Worst-case astable period (approx): T_max = ln(2)*C*(Ra_max + 2*Rb)
// where Ra_max ~= Rx_max + Rk.
static uint32_t computePairTimeoutMs() {
  double ra = (double)g_RX_MAX_OHM + (double)g_RK_OHM;
  if (ra < 0.0) ra = 0.0;

  double rb = (double)g_RB_OHM;
  if (rb < 1.0) rb = 1.0;

  double c = (double)g_CF_F;
  if (c < 1e-15) c = 1e-15;

  // Estimated maximum period in seconds
  double tmax_s = (double)LN2 * c * (ra + 2.0 * rb);

  // Need up to ~1 full period to observe a fresh high+low pair depending on phase.
  // Use a safety factor + a small fixed margin.
  double tout_ms = (tmax_s * 1000.0) * 3.0 + 20.0; // 3*Tmax + 20ms

  if (tout_ms < 50.0) tout_ms = 50.0;
  if (tout_ms > 5000.0) tout_ms = 5000.0; // cap at 5 seconds

  return (uint32_t)ceil(tout_ms);
}

// Wait for a fresh high/low pair ready, then copy it out
static bool waitForPair(uint32_t &hCyc, uint32_t &lCyc, uint32_t timeout_ms = 0) {
  const uint32_t t0 = millis();
  if (timeout_ms == 0) timeout_ms = computePairTimeoutMs();
  while (!cap0.pairReady) {
    // allow command parser to stay responsive while waiting
    if (Serial.available() > 0) break;
    if ((millis() - t0) > timeout_ms) return false;
  }

  if (!cap0.pairReady) return false;

  noInterrupts();
  hCyc = cap0.highCycles;
  lCyc = cap0.lowCycles;
  cap0.pairReady = false;
  interrupts();

  return (hCyc != 0 && lCyc != 0);
}

// ------------------------ Per-channel moving averages ------------------------
struct ChannelState {
  float rxBuf[RX_MA_N];
  float rdisBuf[RDIS_MA_N];
  float rxSum   = 0.0f;
  float rdisSum = 0.0f;
  int rxIdx = 0, rxCount = 0;
  int rdisIdx = 0, rdisCount = 0;
  float lastPlotRx = NAN;

  void reset() {
    rxSum = 0.0f; rdisSum = 0.0f;
    rxIdx = rxCount = 0;
    rdisIdx = rdisCount = 0;
    for (int i = 0; i < RX_MA_N; i++)   rxBuf[i] = 0.0f;
    for (int i = 0; i < RDIS_MA_N; i++) rdisBuf[i] = 0.0f;
    lastPlotRx = NAN;
  }
};

static ChannelState chState[16];

static inline float updateMA(float *buf, float &sum, int &idx, int &count, int N, float newVal) {
  sum -= buf[idx];
  buf[idx] = newVal;
  sum += newVal;
  idx = (idx + 1) % N;
  if (count < N) count++;
  return sum / count;
}

static void resetAllChannels() {
  for (int i = 0; i < 16; i++) chState[i].reset();
}

// ------------------------ MUX helpers ------------------------
static inline void muxEnable(bool en) {
  if (MUX_EN_PIN < 0) return; // no EN control
  bool level = en ? HIGH : LOW;
  if (MUX_EN_ACTIVE_LOW) level = (level == HIGH) ? LOW : HIGH;
  digitalWriteFast(MUX_EN_PIN, level);
}

static inline void muxSelect(uint8_t ch) {
  ch &= 0x0F;

  muxEnable(false);

  digitalWriteFast(MUX_A0_PIN, (ch & 0x01) ? HIGH : LOW);
  digitalWriteFast(MUX_A1_PIN, (ch & 0x02) ? HIGH : LOW);
  digitalWriteFast(MUX_A2_PIN, (ch & 0x04) ? HIGH : LOW);
  digitalWriteFast(MUX_A3_PIN, (ch & 0x08) ? HIGH : LOW);

  delayNanoseconds(MUX_SETTLE_NS);

  muxEnable(true);
  resetCaptureState();
}

// ------------------------ 555 math (same method as your original) ------------------------
static bool measureOneRx(uint8_t ch, bool switched, float &outRx) {
  if (switched) {
    muxSelect(ch);

    // Discard cycles after switching (to reduce memory/charge-injection artifacts)
    for (int d = 0; d < DISCARD_CYCLES_AFTER_SWITCH; d++) {
      uint32_t hCyc = 0, lCyc = 0;
      if (!waitForPair(hCyc, lCyc, computePairTimeoutMs())) return false;
    }
  }

  uint32_t hCyc = 0, lCyc = 0;
  if (!waitForPair(hCyc, lCyc, computePairTimeoutMs())) return false;

  const float f_cpu = (float)F_CPU_ACTUAL;
  const float tH_s  = (float)hCyc / f_cpu;
  const float tL_s  = (float)lCyc / f_cpu;

  // ---- Estimate Rdis from discharge time ----
  float Rdis = NAN;
  const float denom = LN2 * g_CF_F;
  if (isfinite(denom) && denom > 0.0f) {
    Rdis = (tL_s / denom) - g_RB_OHM;
  }

  // Update per-channel Rdis MA only if non-negative
  if (isfinite(Rdis) && Rdis >= 0.0f) {
    (void)updateMA(chState[ch].rdisBuf, chState[ch].rdisSum,
                   chState[ch].rdisIdx, chState[ch].rdisCount,
                   RDIS_MA_N, Rdis);
  }

  float last_Rx = NAN, last_RxMA = NAN;

  // Compute Rx using channel's current Rdis MA if available
  if (chState[ch].rdisCount > 0) {
    const float tDiv = (tL_s > 0.0f) ? (tH_s / tL_s) : NAN;
    const float RdisUsed = chState[ch].rdisSum / (float)chState[ch].rdisCount;
    const float Ra = tDiv * (g_RB_OHM + RdisUsed) - g_RB_OHM;
    last_Rx = Ra - g_RK_OHM;

    if (isfinite(last_Rx)) {
      last_RxMA = updateMA(chState[ch].rxBuf, chState[ch].rxSum,
                           chState[ch].rxIdx, chState[ch].rxCount,
                           RX_MA_N, last_Rx);
    }
  }

  // Choose output: prefer MA if available, else raw, else last saved, else 0
  float candidate = NAN;
  if (isfinite(last_RxMA)) candidate = last_RxMA;
  else if (isfinite(last_Rx)) candidate = last_Rx;

  if (isfinite(candidate)) {
    chState[ch].lastPlotRx = candidate;
  }

  outRx = isfinite(chState[ch].lastPlotRx) ? chState[ch].lastPlotRx : 0.0f;
  return true;
}

// ------------------------ Serial protocol helpers ------------------------
static void sendCommandAck(bool ok, const String &args) {
  if (ok) {
    if (args.length() > 0) { Serial.print(F("#OK ")); Serial.println(args); }
    else                   { Serial.println(F("#OK")); }
  } else {
    if (args.length() > 0) { Serial.print(F("#NOT_OK ")); Serial.println(args); }
    else                   { Serial.println(F("#NOT_OK")); }
  }
  Serial.flush();
  delay(5);
}

static void splitCommand(const String &line, String &cmdOut, String &argsOut) {
  int sp = line.indexOf(' ');
  if (sp < 0) { cmdOut = line; argsOut = ""; return; }
  cmdOut  = line.substring(0, sp);
  argsOut = line.substring(sp + 1);
  argsOut.trim();
}

// parse float with simple engineering suffixes
// - For resistors: accepts k/K (1e3), m/M (1e6)
// - For capacitors (Farads): accepts p(1e-12), n(1e-9), u(1e-6), m(1e-3)
// Also allows scientific notation like 2.2e-9.
static bool parseValueWithSuffix(const String &inRaw, double &outVal, bool isCapUnits) {
  String s = inRaw;
  s.trim();
  if (s.length() == 0) return false;

  String t = s;
  t.trim();
  t.toLowerCase();

  // strip optional unit strings
  if (!isCapUnits) {
    if (t.endsWith("ohm")) t = t.substring(0, t.length() - 3);
    t.trim();
  } else {
    if (t.endsWith("farad")) t = t.substring(0, t.length() - 5);
    if (t.endsWith("f"))     t = t.substring(0, t.length() - 1);
    t.trim();
  }

  double mult = 1.0;
  if (t.length() > 0) {
    char last = t.charAt(t.length() - 1);

    if (!isCapUnits) {
      if (last == 'k') { mult = 1e3; t.remove(t.length() - 1); }
      else if (last == 'm') { mult = 1e6; t.remove(t.length() - 1); }
    } else {
      if (last == 'p') { mult = 1e-12; t.remove(t.length() - 1); }
      else if (last == 'n') { mult = 1e-9;  t.remove(t.length() - 1); }
      else if (last == 'u') { mult = 1e-6;  t.remove(t.length() - 1); }
      else if (last == 'm') { mult = 1e-3;  t.remove(t.length() - 1); }
    }
  }

  t.trim();
  if (t.length() == 0) return false;

  char buf[64];
  const size_t n = min(sizeof(buf) - 1, (size_t)t.length());
  for (size_t i = 0; i < n; i++) buf[i] = t.charAt((int)i);
  buf[n] = 0;

  char *endp = nullptr;
  double v = strtod(buf, &endp);
  if (endp == buf) return false;

  outVal = v * mult;
  return isfinite(outVal);
}

// ------------------------ Command handlers ------------------------
static bool handleChannels(const String &args) {
  // CSV list of channels 0..15
  String a = args;
  a.trim();
  if (a.length() == 0) return false;

  int newCount = 0;
  int start = 0;
  const int alen = (int)a.length();

  while (start < alen) {
    int comma = a.indexOf(',', start);
    String tok = (comma < 0) ? a.substring(start) : a.substring(start, comma);
    tok.trim();
    if (tok.length() > 0) {
      int ch = tok.toInt();
      if (ch < 0 || ch > 15) return false;
      if (newCount >= MAX_CHANNEL_SEQUENCE) return false;
      channelSequence[newCount++] = (uint8_t)ch;
    }
    if (comma < 0) break;
    start = comma + 1;
  }

  if (newCount <= 0) return false;
  channelCount = newCount;
  resetAllChannels();
  return true;
}

static bool handleRepeat(const String &args) {
  int n = args.toInt();
  if (n < 1 || n > 256) return false;
  repeatCount = n;
  return true;
}

static bool handleBuffer(const String &args) {
  int b = args.toInt();
  if (b < 1 || b > 256) return false;
  bufferSweeps = b;
  return true;
}

static bool handleRun(const String &args) {
  // run*             -> continuous blocks
  // run <ms>*        -> stop after ms (between blocks)
  if (args.length() > 0) {
    uint32_t ms = (uint32_t)args.toInt();
    if (ms == 0) return false;
    timedRun = true;
    runStopMillis = millis() + ms;
  } else {
    timedRun = false;
  }
  isRunning = true;
  return true;
}

static void handleStop() {
  isRunning = false;
  timedRun = false;
}

static bool handleRb(const String &args) {
  double v = 0.0;
  if (!parseValueWithSuffix(args, v, false)) return false;
  if (!(v > 0.0 && v < 1e9)) return false;
  g_RB_OHM = (float)v;
  resetAllChannels();
  return true;
}

static bool handleRk(const String &args) {
  double v = 0.0;
  if (!parseValueWithSuffix(args, v, false)) return false;
  if (!(v >= 0.0 && v < 1e9)) return false;
  g_RK_OHM = (float)v;
  resetAllChannels();
  return true;
}

static bool handleCf(const String &args) {
  double v = 0.0;
  if (!parseValueWithSuffix(args, v, true)) return false;
  // sane range: 0.1 pF .. 10 mF
  if (!(v > 1e-13 && v < 1e-2)) return false;
  g_CF_F = (float)v;
  resetAllChannels();
  return true;
}

static bool handleRxMax(const String &args) {
  double v = 0.0;
  if (!parseValueWithSuffix(args, v, false)) return false;
  if (!(v > 0.0 && v < 1e9)) return false;
  g_RX_MAX_OHM = (float)v;
  return true;
}

static void printMcu() {
  Serial.println(F("# Teensy555"));
}

static void printStatus() {
  Serial.println(F("# STATUS Teensy555"));
  Serial.print(F("# channels="));
  for (int i = 0; i < channelCount; i++) {
    Serial.print(channelSequence[i]);
    if (i < channelCount - 1) Serial.print(',');
  }
  Serial.println();

  Serial.print(F("# repeat=")); Serial.println(repeatCount);
  Serial.print(F("# buffer=")); Serial.println(bufferSweeps);

  Serial.print(F("# rb_ohm=")); Serial.println(g_RB_OHM, 6);
  Serial.print(F("# rk_ohm=")); Serial.println(g_RK_OHM, 6);
  Serial.print(F("# cf_f="));   Serial.println(g_CF_F, 12);

  Serial.print(F("# rxmax_ohm=")); Serial.println(g_RX_MAX_OHM, 6);
  Serial.print(F("# pair_timeout_ms=")); Serial.println(computePairTimeoutMs());

  uint32_t samplesPerSweep = (uint32_t)channelCount * (uint32_t)repeatCount;
  uint32_t total = samplesPerSweep * (uint32_t)bufferSweeps;

  Serial.print(F("# samples_per_sweep=")); Serial.println(samplesPerSweep);
  Serial.print(F("# samples_per_block=")); Serial.println(total);
  Serial.print(F("# max_block_samples=")); Serial.println(MAX_BLOCK_SAMPLES);
  Serial.print(F("# running=")); Serial.println(isRunning ? F("true") : F("false"));
}

static void printHelp() {
  Serial.println(F("# Teensy555 commands (end each with '*'):"));
  Serial.println(F("#   mcu*                    -> print device id line"));
  Serial.println(F("#   status*                 -> print config"));
  Serial.println(F("#   help*                   -> this text"));
  Serial.println(F("#   channels 0,2,3,4*       -> set channel sequence (0..15, duplicates ok)"));
  Serial.println(F("#   repeat N*               -> repeats per channel entry (1..256)"));
  Serial.println(F("#   buffer B*               -> sweeps per binary block (1..256)"));
  Serial.println(F("#   run*                    -> start streaming blocks"));
  Serial.println(F("#   run <ms>*               -> run for ms, stop between blocks"));
  Serial.println(F("#   stop*                   -> stop streaming"));
  Serial.println(F("#  555 params:"));
  Serial.println(F("#   rb <ohms|k|M>*          -> set discharge resistor (e.g. rb 470*  rb 1k*)"));
  Serial.println(F("#   rk <ohms|k|M>*          -> set known series resistor (e.g. rk 10*)"));
  Serial.println(F("#   cf <F|p|n|u|m>*         -> set capacitance (e.g. cf 2.2n*  cf 0.0022u*)"));
  Serial.println(F("#   rxmax <ohms|k|M>*       -> set max expected Rx for timeouts (e.g. rxmax 50k*)"));
}

// ------------------------ Binary block sender ------------------------
static inline void write_u16_le(uint16_t v) {
  uint8_t b[2] = {(uint8_t)(v & 0xFF), (uint8_t)((v >> 8) & 0xFF)};
  Serial.write(b, 2);
}
static inline void write_u32_le(uint32_t v) {
  uint8_t b[4] = {
    (uint8_t)(v & 0xFF),
    (uint8_t)((v >> 8) & 0xFF),
    (uint8_t)((v >> 16) & 0xFF),
    (uint8_t)((v >> 24) & 0xFF)
  };
  Serial.write(b, 4);
}

static void doOneBlock() {
  const uint32_t samplesPerSweep = (uint32_t)channelCount * (uint32_t)repeatCount;
  const uint32_t totalSamples32  = samplesPerSweep * (uint32_t)bufferSweeps;

  if (totalSamples32 == 0 || totalSamples32 > MAX_BLOCK_SAMPLES) {
    // Don't spam; just stop and report once.
    isRunning = false;
    timedRun = false;
    Serial.println(F("# ERROR: block too large. Reduce channels/repeat/buffer."));
    return;
  }

  const uint16_t totalSamples = (uint16_t)totalSamples32;

  // Capture-only timing window (not including serial writes)
  const uint32_t blockStartUs = micros();
  const uint32_t captureStartUs = blockStartUs;

  uint16_t idx = 0;
  int prevCh = -1;

  for (int b = 0; b < bufferSweeps; b++) {
    for (int ci = 0; ci < channelCount; ci++) {
      const uint8_t ch = channelSequence[ci];
      for (int r = 0; r < repeatCount; r++) {
        bool switched = (prevCh != (int)ch);
        prevCh = (int)ch;

        float rx = 0.0f;
        (void)measureOneRx(ch, switched, rx);

        // round + clamp to uint16
        long v = lroundf(rx);
        if (v < 0) v = 0;
        if (v > 65535L) v = 65535L;
        sampleBuf[idx++] = (uint16_t)v;

        // allow stop command to be acted on between samples
        if (Serial.available() > 0) {
          // command parser will run in loop(); we just break cleanly
        }
      }
    }
  }

  const uint32_t captureEndUs = micros();

  // Average dt per sample (µs), clamp to uint16
  uint32_t dtTotal = (captureEndUs - captureStartUs);
  uint32_t avg_dt = (totalSamples > 0) ? ((dtTotal + totalSamples / 2) / totalSamples) : 0;
  if (avg_dt > 65535U) avg_dt = 65535U;

  // Send binary block
  Serial.write((uint8_t)0xAA);
  Serial.write((uint8_t)0x55);
  write_u16_le(totalSamples);

  for (uint16_t i = 0; i < totalSamples; i++) {
    write_u16_le(sampleBuf[i]);
  }

  write_u16_le((uint16_t)avg_dt);
  write_u32_le(captureStartUs);
  write_u32_le(captureEndUs);

  Serial.flush();
}

// ------------------------ Serial line handler (MG24-style) ------------------------
static void handleLine(const String &lineRaw) {
  String line = lineRaw;
  line.trim();
  if (line.length() == 0) return;

  String cmd, args;
  splitCommand(line, cmd, args);
  cmd.toLowerCase();

  bool ok = true;

  if      (cmd == "channels")  { ok = handleChannels(args); }
  else if (cmd == "repeat")    { ok = handleRepeat(args); }
  else if (cmd == "buffer")    { ok = handleBuffer(args); }
  else if (cmd == "run")       { ok = handleRun(args); }
  else if (cmd == "stop")      { handleStop(); ok = true; }
  else if (cmd == "status")    { printStatus(); ok = true; }
  else if (cmd == "mcu")       { printMcu(); ok = true; }
  else if (cmd == "help")      { printHelp(); ok = true; }

  // 555-specific params:
  else if (cmd == "rb")        { ok = handleRb(args); }
  else if (cmd == "rk")        { ok = handleRk(args); }
  else if (cmd == "cf")        { ok = handleCf(args); }
  else if (cmd == "rxmax")     { ok = handleRxMax(args); }

  // MG24-only commands that your GUI might send — accept & ignore to reduce Python changes.
  else if (cmd == "ref" || cmd == "osr" || cmd == "gain" || cmd == "ground" || cmd == "speed") {
    ok = true;
  }
  else {
    Serial.print(F("# ERROR: unknown command '"));
    Serial.print(cmd);
    Serial.println(F("'. Type 'help'."));
    ok = false;
  }

  sendCommandAck(ok, args);
}

// ------------------------ setup/loop ------------------------
void setup() {
  Serial.begin(BAUD_RATE);
  while (!Serial) { ; }

  pinMode(LED_BUILTIN, OUTPUT);
  digitalWriteFast(LED_BUILTIN, LOW);

  pinMode(ICP_PIN, INPUT);

  // MUX pins
  pinMode(MUX_A0_PIN, OUTPUT);
  pinMode(MUX_A1_PIN, OUTPUT);
  pinMode(MUX_A2_PIN, OUTPUT);
  pinMode(MUX_A3_PIN, OUTPUT);
  if (MUX_EN_PIN >= 0) {
    pinMode(MUX_EN_PIN, OUTPUT);
    muxEnable(true);
  }

  dwtInit();
  attachInterrupt(digitalPinToInterrupt(ICP_PIN), isr555, CHANGE);

  resetAllChannels();

  // Identify ourselves so the Python app can detect this device on the port
  printMcu();
}

void loop() {
  // 1) Handle incoming serial bytes (command parser)
  while (Serial.available() > 0) {
    char c = (char)Serial.read();

    if (c == '\r' || c == '\n') continue;

    if (c == CMD_TERMINATOR) {
      if (inputLine.length() > 0) {
        handleLine(inputLine);
        inputLine = "";
      }
      continue;
    }

    inputLine += c;

    if (inputLine.length() > MAX_CMD_LENGTH) {
      inputLine = "";
      Serial.println(F("# ERROR: input line too long; cleared."));
    }
  }

  // 2) Handle timed stop BETWEEN blocks
  if (isRunning && timedRun) {
    uint32_t now = millis();
    if ((int32_t)(now - runStopMillis) >= 0) {
      isRunning = false;
      timedRun  = false;
      return;
    }
  }

  // 3) Run one whole block
  if (isRunning) {
    doOneBlock();
  }
}
