/*
 * Teensy_SPI_Master_Array_PZT_PZR1.ino
 * Teensy 4.0 — Combined PZT (SPI/MG24) and PZR (555 Timer) Streamer
 * ==================================================================
 *
 * Exposes a unified serial API (same as README) with an additional
 * mode-switch command:
 *
 *   mode PZT*   ->  SPI-master bridge to MG24 dual-MUX slave (default)
 *   mode PZR*   ->  555-astable resistance measurement via ADG706 MUX
 *
 * Device ID (both modes):
 *   mcu*  ->  # Array_PZT_PZR1
 *
 * ── PZT mode ─────────────────────────────────────────────────────────
 *   Bridges Python host to XIAO MG24 running MG24_Dual_MUX_SPI_Slave.
 *   Each channel slot yields 2 interleaved samples [MUX1_val, MUX2_val].
 *   Commands: channels, repeat, buffer, ref, osr, gain, ground, run, stop
 *
 *   Wiring (SPI0 default bus):
 *     Teensy 10 (CS)   -> MG24 D0   (CS,   PC0)
 *     Teensy 13 (SCK)  -> MG24 D8   (SCK,  PA3)
 *     Teensy 11 (MOSI) -> MG24 D10  (MOSI, PA5)
 *     Teensy 12 (MISO) <- MG24 D9   (MISO, PA4)
 *     Common GND
 *
 * ── PZR mode ─────────────────────────────────────────────────────────
 *   Uses 555 astable circuit + ADG706 MUX to measure unknown resistances.
 *   Rx is derived from measured high/low timing vs known Rb, Rk, Cf values.
 *   Each uint16 sample is Rx in ohms, rounded and clamped to 0..65535.
 *   Commands: channels, repeat, buffer, rb, rk, cf, rxmax, ascii, run, stop
 *
 *   Wiring (555 + MUX):
 *     ICP_PIN  = 22     555 OUT -> Teensy interrupt. Pin 22 for PZR MUX (Rosette MUX is 15)
 *     MUX_A0   = 20
 *     MUX_A1   = 19
 *     MUX_A2   = 18
 *     MUX_A3   = 17
 *
 * ── Binary block format (both modes, same as ADC_Streamer) ────────────
 *   [0xAA][0x55][countL][countH] + count * uint16_LE +
 *   avg_dt_us(uint16_LE) + block_start_us(uint32_LE) + block_end_us(uint32_LE)
 *
 * ── Notes ──────────────────────────────────────────────────────────────
 *   - The 555 ISR is always attached; it adds negligible overhead in PZT mode.
 *   - PZT run* is blocking; a stop* received during streaming is handled
 *     inside the blocking loop via serial polling.
 *   - PZR run* is non-blocking; blocks are executed in loop().
 *   - Switching modes stops any active run in the outgoing mode.
 *   - Baud rate is 460800 for both modes.
 *
 * Change log:
 *   v1.0  Initial combined sketch.
 */

#include <Arduino.h>
#include <SPI.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

// =====================================================================
// ── MODE ─────────────────────────────────────────────────────────────
// =====================================================================

enum DeviceMode { MODE_PZT, MODE_PZR };
static DeviceMode currentMode = MODE_PZT;   // default

// =====================================================================
// ── SHARED SERIAL CONSTANTS ──────────────────────────────────────────
// =====================================================================

static const uint32_t SERIAL_BAUD  = 460800;
static const char     CMD_TERM     = '*';
static const uint16_t MAX_CMD_LEN  = 512;

// Binary block magic bytes (shared by both modes)
static const uint8_t BLOCK_MAGIC1  = 0xAA;
static const uint8_t BLOCK_MAGIC2  = 0x55;

// =====================================================================
// ── PZT MODE — CONSTANTS ─────────────────────────────────────────────
// =====================================================================

// ── SPI ───────────────────────────────────────────────────────────────
static const uint8_t  PZT_CS_PIN             = 10;
static const uint32_t PZT_SPI_BITRATE        = 4000000UL;   // 4 MHz
static const uint32_t PZT_CS_SETUP_US        = 10;
static const bool     PZT_DEBUG_TEXT_STREAM  = false;

// ── Protocol frame sizes (must match MG24 sketch) ─────────────────────
static const uint8_t  PZT_CMD_FRAME_LEN      = 20;
static const uint8_t  PZT_ACK_FRAME_LEN      = 4;
static const uint8_t  PZT_BLOCK_TRAILER_LEN  = 10;  // avg_dt(2)+start(4)+end(4)
static const uint8_t  PZT_ACK_MAGIC          = 0xAC;
static const uint8_t  PZT_ACK_STATUS_OK      = 0x00;

// ── Timing ────────────────────────────────────────────────────────────
static const uint32_t PZT_CONFIG_ACK_DELAY_MS    = 20;
static const uint32_t PZT_INTER_BLOCK_DELAY_MS   = 1;
static const uint32_t PZT_MUX_SETTLE_US          = 15;
static const uint32_t PZT_IADC_CONV_US_OSR2      = 4;   // was 2 for faster IADC clock
static const uint32_t PZT_IADC_CONV_US_OSR4      = 8;   // was 4 for faster IADC clock
static const uint32_t PZT_IADC_CONV_US_OSR8      = 16;  // was 8 for faster IADC clock
static const uint32_t PZT_BLOCK_DELAY_MARGIN_MS  = 15;
static const uint32_t PZT_WARMUP_DELAY_MARGIN_MS = 10;
static const uint16_t PZT_WARMUP_SWEEPS          = 48;

// ── Protocol limits ───────────────────────────────────────────────────
static const uint16_t PZT_MAX_REPEAT             = 100;
static const uint8_t  PZT_MUX_CH_MAX             = 15;
static const uint32_t PZT_MAX_PAIRS              = 8000UL;

static const uint32_t PZT_MAX_BLOCK_BYTES =
    (uint32_t)PZT_ACK_FRAME_LEN + PZT_MAX_PAIRS * 4UL + PZT_BLOCK_TRAILER_LEN;

// ── SPI command codes (must match MG24 sketch) ────────────────────────
static const uint8_t PZT_CMD_SET_CHANNELS = 0x01;
static const uint8_t PZT_CMD_SET_REPEAT   = 0x02;
static const uint8_t PZT_CMD_SET_BUFFER   = 0x03;
static const uint8_t PZT_CMD_SET_REF      = 0x04;
static const uint8_t PZT_CMD_SET_OSR      = 0x05;
static const uint8_t PZT_CMD_SET_GAIN     = 0x06;
static const uint8_t PZT_CMD_RUN          = 0x07;
static const uint8_t PZT_CMD_STOP         = 0x08;
static const uint8_t PZT_CMD_GROUND_PIN   = 0x0B;
static const uint8_t PZT_CMD_GROUND_EN    = 0x0C;
static const uint8_t PZT_STREAM_NOP       = 0x00;

// =====================================================================
// ── PZT MODE — STATE ─────────────────────────────────────────────────
// =====================================================================

static SPIClass      &pztSPI    = SPI;
static const SPISettings PZT_SPI_CFG(PZT_SPI_BITRATE, MSBFIRST, SPI_MODE1);

struct PZTConfig {
  uint8_t  channels[16];
  uint8_t  channelCount   = 0;
  uint8_t  repeatCount    = 1;
  uint8_t  sweepsPerBlock = 1;
  uint8_t  osr            = 2;   // 2 | 4 | 8
  uint8_t  gain           = 1;   // 1..4
  uint8_t  ref            = 1;   // 0=1.2V  1=VDD/3.3V
  uint8_t  groundPin      = 0;
  bool     groundEnable   = false;
  bool     running        = false;
} pzt;

// =====================================================================
// ── PZR MODE — CONSTANTS ─────────────────────────────────────────────
// =====================================================================

static const int PZR_ICP_PIN    = 22;  // 22 - PZR MUX. 15 - Rosette MUX
static const int PZR_MUX_A0_PIN = 20;
static const int PZR_MUX_A1_PIN = 19;
static const int PZR_MUX_A2_PIN = 18;
static const int PZR_MUX_A3_PIN = 17;
static const int PZR_MUX_EN_PIN = -1;   // -1 = not connected / tied to VDD

static constexpr bool     PZR_MUX_EN_ACTIVE_LOW          = false;
static constexpr uint32_t PZR_MUX_SETTLE_NS              = 100;
static constexpr int      PZR_DISCARD_CYCLES_AFTER_SWITCH = 1;
static constexpr int      PZR_RX_MA_N                    = 20;
static constexpr int      PZR_RDIS_MA_N                  = 20;
static constexpr int      PZR_MAX_CHANNEL_SEQUENCE        = 64;
static constexpr uint16_t PZR_MAX_BLOCK_SAMPLES           = 2048;

static constexpr float LN2 = 0.69314718056f;

// 555 component defaults (PCB ver 1.0)
static constexpr float PZR_DEFAULT_RB_OHM     = 470.0f;     // discharge resistor
static constexpr float PZR_DEFAULT_RK_OHM     = 470.0f;     // known series resistor
static constexpr float PZR_DEFAULT_CF_F       = 22e-9f;   // 220nF 555_A(Rosettes) / 22nF 555_B(PZR)
static constexpr float PZR_DEFAULT_RX_MAX_OHM = 65500.0f;

// =====================================================================
// ── PZR MODE — STATE ─────────────────────────────────────────────────
// =====================================================================

static float   pzr_RB_OHM      = PZR_DEFAULT_RB_OHM;
static float   pzr_RK_OHM      = PZR_DEFAULT_RK_OHM;
static float   pzr_CF_F        = PZR_DEFAULT_CF_F;
static float   pzr_RX_MAX_OHM  = PZR_DEFAULT_RX_MAX_OHM;
static bool    pzr_asciiOutput  = false;

static uint8_t  pzr_channelSequence[PZR_MAX_CHANNEL_SEQUENCE] = {0, 1, 2, 3, 4};
static int      pzr_channelCount  = 5;
static int      pzr_repeatCount   = 1;
static int      pzr_bufferSweeps  = 1;
static bool     pzr_isRunning     = false;
static bool     pzr_timedRun      = false;
static uint32_t pzr_runStopMillis = 0;

static uint16_t pzr_sampleBuf[PZR_MAX_BLOCK_SAMPLES];

// 555 capture state — written in ISR, read in main loop
struct PZR_CaptureState {
  volatile uint32_t lastRiseCycles = 0;
  volatile uint32_t lastFallCycles = 0;
  volatile uint32_t highCycles     = 0;
  volatile uint32_t lowCycles      = 0;
  volatile bool     pairReady      = false;
};
static PZR_CaptureState pzr_cap;

// Per-channel moving-average state
struct PZR_ChannelState {
  float rxBuf[PZR_RX_MA_N];
  float rdisBuf[PZR_RDIS_MA_N];
  float rxSum    = 0.0f;
  float rdisSum  = 0.0f;
  int   rxIdx    = 0, rxCount   = 0;
  int   rdisIdx  = 0, rdisCount = 0;
  float lastPlotRx = NAN;

  void reset() {
    rxSum = 0.0f; rdisSum = 0.0f;
    rxIdx = rxCount = 0;
    rdisIdx = rdisCount = 0;
    for (int i = 0; i < PZR_RX_MA_N;   i++) rxBuf[i]   = 0.0f;
    for (int i = 0; i < PZR_RDIS_MA_N; i++) rdisBuf[i] = 0.0f;
    lastPlotRx = NAN;
  }
};
static PZR_ChannelState pzr_chState[16];

// =====================================================================
// ── SHARED INPUT BUFFER ──────────────────────────────────────────────
// =====================================================================

static String inputLine;

// =====================================================================
// ── DWT CYCLE COUNTER (PZR timing) ───────────────────────────────────
// =====================================================================

static inline void dwtInit() {
  ARM_DEMCR       |= ARM_DEMCR_TRCENA;
  ARM_DWT_CTRL    |= ARM_DWT_CTRL_CYCCNTENA;
  ARM_DWT_CYCCNT   = 0;
}
static inline uint32_t dwtNow() { return ARM_DWT_CYCCNT; }

// =====================================================================
// ── PZT SPI HELPERS ──────────────────────────────────────────────────
// =====================================================================

static void pzt_spiTransfer(const uint8_t *tx, uint8_t *rx, uint16_t len) {
  pztSPI.beginTransaction(PZT_SPI_CFG);
  digitalWrite(PZT_CS_PIN, LOW);
  delayMicroseconds(PZT_CS_SETUP_US);
  for (uint16_t i = 0; i < len; i++) {
    uint8_t b = pztSPI.transfer(tx ? tx[i] : 0x00);
    if (rx) rx[i] = b;
  }
  digitalWrite(PZT_CS_PIN, HIGH);
  pztSPI.endTransaction();
}

static inline void pzt_spiSend(const uint8_t *buf, uint16_t len) {
  pzt_spiTransfer(buf, nullptr, len);
}
static inline void pzt_spiRecv(uint8_t *buf, uint16_t len) {
  pzt_spiTransfer(nullptr, buf, len);
}

// Attempt to read a streaming response (block or ACK).
// The first byte sent carries a control token for MG24's state machine.
static bool pzt_spiRecvStreamingResponse(uint8_t *buf, uint16_t len,
                                          uint8_t controlByte = PZT_STREAM_NOP,
                                          uint8_t maxAttempts = 4) {
  for (uint8_t attempt = 0; attempt < maxAttempts; ++attempt) {
    pztSPI.beginTransaction(PZT_SPI_CFG);
    digitalWrite(PZT_CS_PIN, LOW);
    delayMicroseconds(PZT_CS_SETUP_US);
    if (len > 0) {
      buf[0] = pztSPI.transfer(controlByte);
      for (uint16_t i = 1; i < len; i++) buf[i] = pztSPI.transfer(0x00);
    }
    digitalWrite(PZT_CS_PIN, HIGH);
    pztSPI.endTransaction();

    if (buf[0] == PZT_ACK_MAGIC)                             return true;
    if (buf[0] == BLOCK_MAGIC1 && buf[1] == BLOCK_MAGIC2)   return true;
    delayMicroseconds(250 + (uint32_t)attempt * 250);
  }
  return false;
}

static bool pzt_spiRecvAck(uint8_t *buf, uint8_t maxAttempts = 4) {
  for (uint8_t attempt = 0; attempt < maxAttempts; ++attempt) {
    pzt_spiRecv(buf, PZT_ACK_FRAME_LEN);
    if (buf[0] == PZT_ACK_MAGIC) return true;
    delayMicroseconds(200 + (uint32_t)attempt * 200);
  }
  return false;
}

// Write binary block data to Python host with flow control.
static void pzt_writeBlockBuffered(const uint8_t *buf, uint32_t len) {
  uint32_t offset = 0;
  while (offset < len) {
    int avail = Serial.availableForWrite();
    if (avail <= 0) { yield(); continue; }
    uint32_t chunk = min((uint32_t)avail, len - offset);
    offset += (uint32_t)Serial.write(buf + offset, chunk);
  }
}

static void pzt_emitBlock(const uint8_t *buf, uint32_t len) {
  if (!PZT_DEBUG_TEXT_STREAM) {
    pzt_writeBlockBuffered(buf, len);
    return;
  }
  // Human-readable debug output
  if (len < (uint32_t)PZT_ACK_FRAME_LEN + PZT_BLOCK_TRAILER_LEN) {
    Serial.println(F("#DBG short block")); Serial.flush(); return;
  }
  if (buf[0] != BLOCK_MAGIC1 || buf[1] != BLOCK_MAGIC2) {
    Serial.print(F("#DBG bad magic: 0x")); Serial.print(buf[0], HEX);
    Serial.print(F(" 0x")); Serial.println(buf[1], HEX); Serial.flush(); return;
  }
  uint16_t n = (uint16_t)buf[2] | ((uint16_t)buf[3] << 8);
  Serial.print(F("#DBG block samples=")); Serial.println(n); Serial.flush();
}

// Drain any leftover '*' bytes that trail a just-issued command.
static void pzt_discardPendingTerminators(uint32_t settleMs = 10) {
  uint32_t start = millis();
  while ((millis() - start) < settleMs) {
    while (Serial.available() > 0) Serial.read();
    delay(1);
  }
}

// Build and send a fixed-length PZT command frame.
static void pzt_sendCmd(uint8_t cmd, const uint8_t *args = nullptr, uint8_t nargs = 0) {
  uint8_t frame[PZT_CMD_FRAME_LEN];
  memset(frame, 0, PZT_CMD_FRAME_LEN);
  frame[0] = cmd;
  frame[1] = nargs;
  if (args && nargs > 0) {
    uint8_t n = min(nargs, (uint8_t)(PZT_CMD_FRAME_LEN - 2));
    memcpy(frame + 2, args, n);
  }
  pzt_spiSend(frame, PZT_CMD_FRAME_LEN);
}

static bool pzt_sendCmdAck(uint8_t cmd,
                            const uint8_t *args = nullptr,
                            uint8_t nargs = 0) {
  pzt_sendCmd(cmd, args, nargs);
  delay(PZT_CONFIG_ACK_DELAY_MS);
  uint8_t ack[PZT_ACK_FRAME_LEN] = {0};
  pzt_spiRecv(ack, PZT_ACK_FRAME_LEN);
  return (ack[0] == PZT_ACK_MAGIC && ack[1] == PZT_ACK_STATUS_OK);
}

// ── PZT timing helpers ────────────────────────────────────────────────
static uint32_t pzt_usPerPair() {
  uint32_t conv = (pzt.osr == 8) ? PZT_IADC_CONV_US_OSR8 :
                  (pzt.osr == 4) ? PZT_IADC_CONV_US_OSR4 : PZT_IADC_CONV_US_OSR2;
  return PZT_MUX_SETTLE_US + conv * 2u;
}

static uint32_t pzt_blockDelayMs() {
  uint32_t pairs = (uint32_t)pzt.channelCount * pzt.repeatCount * pzt.sweepsPerBlock;
  return (pairs * pzt_usPerPair()) / 1000u + PZT_BLOCK_DELAY_MARGIN_MS;
}

static uint32_t pzt_warmupDelayMs() {
  uint32_t pairs = (uint32_t)PZT_WARMUP_SWEEPS * pzt.channelCount;
  return (pairs * pzt_usPerPair()) / 1000u + PZT_WARMUP_DELAY_MARGIN_MS;
}

static uint32_t pzt_blockResponseBytes() {
  // ×2: each channel slot yields MUX1 + MUX2 samples
  uint32_t samples = (uint32_t)pzt.channelCount * pzt.repeatCount
                   * pzt.sweepsPerBlock * 2u;
  return (uint32_t)PZT_ACK_FRAME_LEN + samples * 2u + PZT_BLOCK_TRAILER_LEN;
}

// =====================================================================
// ── PZR ISR & LOW-LEVEL HELPERS ──────────────────────────────────────
// =====================================================================

void pzr_isr555() {
  const uint32_t now       = dwtNow();
  const bool     levelHigh = digitalReadFast(PZR_ICP_PIN);

  if (levelHigh) {
    if (pzr_cap.lastFallCycles != 0)
      pzr_cap.lowCycles = now - pzr_cap.lastFallCycles;
    pzr_cap.lastRiseCycles = now;
  } else {
    if (pzr_cap.lastRiseCycles != 0)
      pzr_cap.highCycles = now - pzr_cap.lastRiseCycles;
    pzr_cap.lastFallCycles = now;
    if (pzr_cap.highCycles && pzr_cap.lowCycles)
      pzr_cap.pairReady = true;
  }
}

static inline void pzr_resetCaptureState() {
  noInterrupts();
  pzr_cap.lastRiseCycles = 0;
  pzr_cap.lastFallCycles = 0;
  pzr_cap.highCycles     = 0;
  pzr_cap.lowCycles      = 0;
  pzr_cap.pairReady      = false;
  interrupts();
}

static uint32_t pzr_computePairTimeoutMs() {
  double ra = (double)pzr_RX_MAX_OHM + (double)pzr_RK_OHM;
  if (ra < 0.0) ra = 0.0;
  double rb = (double)pzr_RB_OHM; if (rb < 1.0) rb = 1.0;
  double c  = (double)pzr_CF_F;   if (c  < 1e-15) c = 1e-15;
  // Worst-case period: T = ln(2)*C*(Ra + 2*Rb); add 3× safety + 20 ms margin.
  double tout_ms = (double)LN2 * c * (ra + 2.0 * rb) * 1000.0 * 3.0 + 20.0;
  if (tout_ms < 50.0)   tout_ms = 50.0;
  if (tout_ms > 5000.0) tout_ms = 5000.0;
  return (uint32_t)ceil(tout_ms);
}

static bool pzr_waitForPair(uint32_t &hCyc, uint32_t &lCyc,
                             uint32_t timeout_ms = 0) {
  if (timeout_ms == 0) timeout_ms = pzr_computePairTimeoutMs();
  const uint32_t t0 = millis();
  while (!pzr_cap.pairReady) {
    if (Serial.available() > 0) break;                   // allow command parsing
    if ((millis() - t0) > timeout_ms) return false;
  }
  if (!pzr_cap.pairReady) return false;
  noInterrupts();
  hCyc = pzr_cap.highCycles;
  lCyc = pzr_cap.lowCycles;
  pzr_cap.pairReady = false;
  interrupts();
  return (hCyc != 0 && lCyc != 0);
}

static inline float pzr_updateMA(float *buf, float &sum, int &idx,
                                  int &count, int N, float val) {
  sum -= buf[idx];
  buf[idx] = val;
  sum += val;
  idx = (idx + 1) % N;
  if (count < N) count++;
  return sum / count;
}

static void pzr_resetAllChannels() {
  for (int i = 0; i < 16; i++) pzr_chState[i].reset();
}

static inline void pzr_muxEnable(bool en) {
  if (PZR_MUX_EN_PIN < 0) return;
  bool level = en ? HIGH : LOW;
  if (PZR_MUX_EN_ACTIVE_LOW) level = !level;
  digitalWriteFast(PZR_MUX_EN_PIN, level);
}

static inline void pzr_muxSelect(uint8_t ch) {
  ch &= 0x0F;
  pzr_muxEnable(false);
  digitalWriteFast(PZR_MUX_A0_PIN, (ch & 0x01) ? HIGH : LOW);
  digitalWriteFast(PZR_MUX_A1_PIN, (ch & 0x02) ? HIGH : LOW);
  digitalWriteFast(PZR_MUX_A2_PIN, (ch & 0x04) ? HIGH : LOW);
  digitalWriteFast(PZR_MUX_A3_PIN, (ch & 0x08) ? HIGH : LOW);
  delayNanoseconds(PZR_MUX_SETTLE_NS);
  pzr_muxEnable(true);
  pzr_resetCaptureState();
}

// Measure one Rx value on the given channel.
// switched=true triggers a MUX switch + discard cycles first.
static bool pzr_measureOneRx(uint8_t ch, bool switched, float &outRx) {
  if (switched) {
    pzr_muxSelect(ch);
    for (int d = 0; d < PZR_DISCARD_CYCLES_AFTER_SWITCH; d++) {
      uint32_t h, l;
      if (!pzr_waitForPair(h, l)) return false;
    }
  }

  uint32_t hCyc = 0, lCyc = 0;
  if (!pzr_waitForPair(hCyc, lCyc)) return false;

  const float f_cpu = (float)F_CPU_ACTUAL;
  const float tH_s  = (float)hCyc / f_cpu;
  const float tL_s  = (float)lCyc / f_cpu;

  // Estimate Rdis from discharge time: tL = ln(2)*Cf*Rdis  ->  Rdis = tL/(ln2*Cf) - Rb
  float Rdis = NAN;
  const float denom = LN2 * pzr_CF_F;
  if (isfinite(denom) && denom > 0.0f)
    Rdis = (tL_s / denom) - pzr_RB_OHM;

  if (isfinite(Rdis) && Rdis >= 0.0f) {
    pzr_updateMA(pzr_chState[ch].rdisBuf, pzr_chState[ch].rdisSum,
                 pzr_chState[ch].rdisIdx, pzr_chState[ch].rdisCount,
                 PZR_RDIS_MA_N, Rdis);
  }

  float last_Rx = NAN, last_RxMA = NAN;
  if (pzr_chState[ch].rdisCount > 0) {
    const float tDiv     = (tL_s > 0.0f) ? (tH_s / tL_s) : NAN;
    const float RdisUsed = pzr_chState[ch].rdisSum / (float)pzr_chState[ch].rdisCount;
    // tH = ln(2)*Cf*(Ra + Rb)  tL = ln(2)*Cf*Rdis  ->  tH/tL = (Ra+Rb)/Rdis
    const float Ra = tDiv * (pzr_RB_OHM + RdisUsed) - pzr_RB_OHM;
    last_Rx = Ra - pzr_RK_OHM;
    if (isfinite(last_Rx)) {
      last_RxMA = pzr_updateMA(pzr_chState[ch].rxBuf, pzr_chState[ch].rxSum,
                               pzr_chState[ch].rxIdx, pzr_chState[ch].rxCount,
                               PZR_RX_MA_N, last_Rx);
    }
  }

  float candidate = isfinite(last_RxMA) ? last_RxMA :
                    isfinite(last_Rx)   ? last_Rx   : NAN;
  if (isfinite(candidate)) pzr_chState[ch].lastPlotRx = candidate;

  outRx = isfinite(pzr_chState[ch].lastPlotRx) ? pzr_chState[ch].lastPlotRx : 0.0f;
  return true;
}

// =====================================================================
// ── SHARED ACK & UTILITY ─────────────────────────────────────────────
// =====================================================================

static void hostAck(bool ok, const String &args = "") {
  // Suppress acks during PZR ASCII streaming (keeps the output clean)
  if (currentMode == MODE_PZR && pzr_asciiOutput && pzr_isRunning) return;

  if (ok) {
    if (args.length()) { Serial.print(F("#OK "));     Serial.println(args); }
    else                 Serial.println(F("#OK"));
  } else {
    if (args.length()) { Serial.print(F("#NOT_OK ")); Serial.println(args); }
    else                 Serial.println(F("#NOT_OK"));
  }
  Serial.flush();
  delay(5);
}

// Parse a value string with optional engineering suffixes.
//   isCapUnits=false: k=1e3, M=1e6 (for ohms)
//   isCapUnits=true:  p=1e-12, n=1e-9, u=1e-6, m=1e-3 (for farads)
static bool parseValueSuffix(const String &inRaw, double &outVal, bool isCapUnits) {
  String t = inRaw; t.trim(); t.toLowerCase();
  if (t.length() == 0) return false;

  // Strip unit words
  if (!isCapUnits) {
    if (t.endsWith("ohm")) { t = t.substring(0, t.length() - 3); t.trim(); }
  } else {
    if (t.endsWith("farad")) { t = t.substring(0, t.length() - 5); t.trim(); }
    if (t.endsWith("f"))     { t = t.substring(0, t.length() - 1); t.trim(); }
  }

  double mult = 1.0;
  if (t.length() > 0) {
    char last = t.charAt(t.length() - 1);
    if (!isCapUnits) {
      if      (last == 'k') { mult = 1e3;   t.remove(t.length() - 1); }
      else if (last == 'm') { mult = 1e6;   t.remove(t.length() - 1); }
    } else {
      if      (last == 'p') { mult = 1e-12; t.remove(t.length() - 1); }
      else if (last == 'n') { mult = 1e-9;  t.remove(t.length() - 1); }
      else if (last == 'u') { mult = 1e-6;  t.remove(t.length() - 1); }
      else if (last == 'm') { mult = 1e-3;  t.remove(t.length() - 1); }
    }
  }

  t.trim();
  if (t.length() == 0) return false;

  char buf[64];
  size_t n = min(sizeof(buf) - 1, (size_t)t.length());
  for (size_t i = 0; i < n; i++) buf[i] = t.charAt((int)i);
  buf[n] = '\0';

  char *endp = nullptr;
  double v = strtod(buf, &endp);
  if (endp == buf) return false;

  outVal = v * mult;
  return isfinite(outVal);
}

// =====================================================================
// ── PZT COMMAND HANDLERS ─────────────────────────────────────────────
// =====================================================================

static bool pzt_handleChannels(const String &args) {
  pzt.channelCount = 0;
  int i = 0, len = args.length();
  while (i < len && pzt.channelCount < 16) {
    while (i < len && (args[i] == ' ' || args[i] == ',')) i++;
    if (i >= len) break;
    int start = i;
    while (i < len && args[i] != ' ' && args[i] != ',') i++;
    int v = args.substring(start, i).toInt();
    if (v >= 0 && v <= (int)PZT_MUX_CH_MAX)
      pzt.channels[pzt.channelCount++] = (uint8_t)v;
  }
  if (pzt.channelCount == 0) return false;

  uint8_t frame[PZT_CMD_FRAME_LEN];
  memset(frame, 0, PZT_CMD_FRAME_LEN);
  frame[0] = PZT_CMD_SET_CHANNELS;
  frame[1] = (uint8_t)(pzt.channelCount + 1);   // nargs = count byte + N channel bytes
  frame[2] = pzt.channelCount;
  for (uint8_t k = 0; k < pzt.channelCount && k < 16; k++)
    frame[3 + k] = pzt.channels[k];

  pzt_spiSend(frame, PZT_CMD_FRAME_LEN);
  delay(PZT_CONFIG_ACK_DELAY_MS);
  uint8_t ack[PZT_ACK_FRAME_LEN] = {0};
  pzt_spiRecv(ack, PZT_ACK_FRAME_LEN);
  return (ack[0] == PZT_ACK_MAGIC && ack[1] == PZT_ACK_STATUS_OK);
}

static bool pzt_handleRepeat(const String &args) {
  long v = constrain(args.toInt(), 1L, (long)PZT_MAX_REPEAT);
  pzt.repeatCount = (uint8_t)v;
  uint8_t a = pzt.repeatCount;
  return pzt_sendCmdAck(PZT_CMD_SET_REPEAT, &a, 1);
}

static bool pzt_handleBuffer(const String &args) {
  long v = max(1L, args.toInt());
  pzt.sweepsPerBlock = (uint8_t)min(v, 255L);
  uint8_t a = pzt.sweepsPerBlock;
  return pzt_sendCmdAck(PZT_CMD_SET_BUFFER, &a, 1);
}

static bool pzt_handleRef(const String &args) {
  String a = args; a.trim(); a.toLowerCase();
  uint8_t rb;
  if      (a == "1.2" || a == "1v2") { rb = 0; pzt.ref = 0; }
  else if (a == "3.3" || a == "vdd") { rb = 1; pzt.ref = 1; }
  else {
    Serial.println(F("# ERROR: only ref 1.2 and ref 3.3/vdd are supported"));
    return false;
  }
  return pzt_sendCmdAck(PZT_CMD_SET_REF, &rb, 1);
}

static bool pzt_handleOsr(const String &args) {
  long v = args.toInt();
  if (v != 2 && v != 4 && v != 8) {
    Serial.println(F("# ERROR: osr must be 2, 4, or 8")); return false;
  }
  pzt.osr = (uint8_t)v;
  uint8_t a = pzt.osr;
  return pzt_sendCmdAck(PZT_CMD_SET_OSR, &a, 1);
}

static bool pzt_handleGain(const String &args) {
  long v = args.toInt();
  if (v < 1 || v > 4) {
    Serial.println(F("# ERROR: gain must be 1, 2, 3, or 4")); return false;
  }
  pzt.gain = (uint8_t)v;
  uint8_t a = pzt.gain;
  return pzt_sendCmdAck(PZT_CMD_SET_GAIN, &a, 1);
}

static bool pzt_handleGround(const String &args) {
  String a = args; a.trim(); a.toLowerCase();
  if (a == "true") {
    pzt.groundEnable = true;
    uint8_t en = 1;
    return pzt_sendCmdAck(PZT_CMD_GROUND_EN, &en, 1);
  } else if (a == "false") {
    pzt.groundEnable = false;
    uint8_t en = 0;
    return pzt_sendCmdAck(PZT_CMD_GROUND_EN, &en, 1);
  } else {
    long v = a.toInt();
    if (v < 0 || v > (int)PZT_MUX_CH_MAX) {
      Serial.println(F("# ERROR: ground channel out of range (0-15)")); return false;
    }
    pzt.groundPin    = (uint8_t)v;
    pzt.groundEnable = true;
    uint8_t pin = (uint8_t)v;
    return pzt_sendCmdAck(PZT_CMD_GROUND_PIN, &pin, 1);
  }
}

// Blocking streaming run — sends #OK before data, manages its own ack.
static void pzt_handleRun(const String &args) {
  if (pzt.channelCount == 0) {
    Serial.println(F("# ERROR: no channels configured"));
    hostAck(false, args); return;
  }

  uint32_t ms    = 0;
  bool     timed = false;
  if (args.length() > 0) {
    long v = args.toInt();
    if (v > 0) { ms = (uint32_t)v; timed = true; }
  }

  // Build and send CMD_RUN frame
  uint8_t frame[PZT_CMD_FRAME_LEN];
  memset(frame, 0, PZT_CMD_FRAME_LEN);
  frame[0] = PZT_CMD_RUN;
  if (timed) {
    frame[1] = 4;
    frame[2] = (uint8_t)( ms        & 0xFF);
    frame[3] = (uint8_t)((ms >>  8) & 0xFF);
    frame[4] = (uint8_t)((ms >> 16) & 0xFF);
    frame[5] = (uint8_t)((ms >> 24) & 0xFF);
  }
  pzt_spiSend(frame, PZT_CMD_FRAME_LEN);

  // Wait for MG24 warmup + first block capture
  delay(pzt_warmupDelayMs() + pzt_blockDelayMs());

  // Static RX buffer (avoids large stack allocation)
  static uint8_t rxBuf[PZT_MAX_BLOCK_BYTES];
  uint32_t rBytes = pzt_blockResponseBytes();

  if (!pzt_spiRecvStreamingResponse(rxBuf, (uint16_t)min(rBytes, (uint32_t)sizeof(rxBuf)))) {
    hostAck(false, args); return;
  }
  if (rxBuf[0] != BLOCK_MAGIC1 || rxBuf[1] != BLOCK_MAGIC2) {
    hostAck(false, args); return;
  }

  pzt.running = true;
  hostAck(true, args);   // #OK sent BEFORE data so Python knows streaming started
  pzt_discardPendingTerminators();

  pzt_emitBlock(rxBuf, rBytes);
  delay(PZT_INTER_BLOCK_DELAY_MS);

  uint32_t runStart = millis();

  // ── Streaming loop ────────────────────────────────────────────────
  while (true) {

    // Check for stop* from Python host
    while (Serial.available() > 0) {
      if ((char)Serial.read() == CMD_TERM) pzt.running = false;
    }
    if (pzt.running && timed && (millis() - runStart) >= ms) pzt.running = false;

    if (!pzt.running) {
      // Send CMD_STOP as control byte of the next block read; MG24 will then
      // arm a final 4-byte ACK instead of another block.
      pzt_spiRecvStreamingResponse(rxBuf,
                                    (uint16_t)min(rBytes, (uint32_t)sizeof(rxBuf)),
                                    PZT_CMD_STOP, 2);
      uint8_t ack[PZT_ACK_FRAME_LEN];
      pzt_spiRecvAck(ack, 4);
      delay(PZT_INTER_BLOCK_DELAY_MS);
      break;
    }

    if (!pzt_spiRecvStreamingResponse(rxBuf,
                                       (uint16_t)min(rBytes, (uint32_t)sizeof(rxBuf)),
                                       PZT_STREAM_NOP, 2)) {
      // Timeout — stop cleanly
      pzt_spiRecvStreamingResponse(rxBuf,
                                    (uint16_t)min(rBytes, (uint32_t)sizeof(rxBuf)),
                                    PZT_CMD_STOP, 2);
      uint8_t ack[PZT_ACK_FRAME_LEN];
      pzt_spiRecvAck(ack, 4);
      delay(PZT_INTER_BLOCK_DELAY_MS);
      pzt.running = false; break;
    }

    // MG24 returned an ACK (e.g. timed-run expired on its side) — done
    if (rxBuf[0] == PZT_ACK_MAGIC) {
      delay(PZT_INTER_BLOCK_DELAY_MS);
      pzt.running = false; break;
    }

    // Unexpected bytes — stop cleanly
    if (rxBuf[0] != BLOCK_MAGIC1 || rxBuf[1] != BLOCK_MAGIC2) {
      pzt_spiRecvStreamingResponse(rxBuf,
                                    (uint16_t)min(rBytes, (uint32_t)sizeof(rxBuf)),
                                    PZT_CMD_STOP, 2);
      uint8_t ack[PZT_ACK_FRAME_LEN];
      pzt_spiRecvAck(ack, 4);
      delay(PZT_INTER_BLOCK_DELAY_MS);
      pzt.running = false; break;
    }

    pzt_emitBlock(rxBuf, rBytes);
    delay(PZT_INTER_BLOCK_DELAY_MS);
  }

  pzt.running = false;
  // Note: hostAck already sent above before streaming started
}

static void pzt_printStatus() {
  Serial.println(F("# -------- STATUS (PZT mode) --------"));
  Serial.println(F("# mcu: Array_PZT_PZR1 (Teensy 4.1 + MG24 dual-MUX SPI slave)"));
  Serial.print(F("# running: "));        Serial.println(pzt.running ? F("true") : F("false"));
  Serial.print(F("# channels (count=")); Serial.print(pzt.channelCount); Serial.println(F("):"));
  Serial.print(F("#   "));
  for (uint8_t i = 0; i < pzt.channelCount; i++) {
    Serial.print(pzt.channels[i]);
    if (i + 1 < pzt.channelCount) Serial.print(',');
  }
  Serial.println();
  Serial.print(F("# repeatCount: "));    Serial.println(pzt.repeatCount);
  Serial.print(F("# sweepsPerBlock: ")); Serial.println(pzt.sweepsPerBlock);
  Serial.print(F("# ref: "));            Serial.println(pzt.ref == 0 ? F("1.2V") : F("VDD/3.3V"));
  Serial.print(F("# osr: "));            Serial.println(pzt.osr);
  Serial.print(F("# gain: "));           Serial.print(pzt.gain); Serial.println('x');
  Serial.print(F("# groundPin: "));      Serial.println(pzt.groundPin);
  Serial.print(F("# groundEnable: "));   Serial.println(pzt.groundEnable ? F("true") : F("false"));
  uint32_t sc = (uint32_t)pzt.channelCount * pzt.repeatCount * pzt.sweepsPerBlock * 2u;
  Serial.print(F("# samplesPerBlock (MUX1+MUX2 interleaved): ")); Serial.println(sc);
  Serial.print(F("# estimatedBlockDelayMs: ")); Serial.println(pzt_blockDelayMs());
  Serial.println(F("# NOTE: each channel slot yields 2 samples [MUX1_val, MUX2_val]"));
  Serial.println(F("# -------------------------"));
}

// =====================================================================
// ── PZR COMMAND HANDLERS ─────────────────────────────────────────────
// =====================================================================

static bool pzr_handleChannels(const String &args) {
  String a = args; a.trim();
  if (a.length() == 0) return false;
  int newCount = 0, start = 0, alen = (int)a.length();
  while (start < alen) {
    int comma = a.indexOf(',', start);
    String tok = (comma < 0) ? a.substring(start) : a.substring(start, comma);
    tok.trim();
    if (tok.length() > 0) {
      int ch = tok.toInt();
      if (ch < 0 || ch > 15) return false;
      if (newCount >= PZR_MAX_CHANNEL_SEQUENCE) return false;
      pzr_channelSequence[newCount++] = (uint8_t)ch;
    }
    if (comma < 0) break;
    start = comma + 1;
  }
  if (newCount <= 0) return false;
  pzr_channelCount = newCount;
  pzr_resetAllChannels();
  return true;
}

static bool pzr_handleRepeat(const String &args) {
  int n = args.toInt();
  if (n < 1 || n > 256) return false;
  pzr_repeatCount = n;
  return true;
}

static bool pzr_handleBuffer(const String &args) {
  int b = args.toInt();
  if (b < 1 || b > 256) return false;
  pzr_bufferSweeps = b;
  return true;
}

static bool pzr_handleRun(const String &args) {
  if (args.length() > 0) {
    uint32_t ms = (uint32_t)args.toInt();
    if (ms == 0) return false;
    pzr_timedRun      = true;
    pzr_runStopMillis = millis() + ms;
  } else {
    pzr_timedRun = false;
  }
  pzr_isRunning = true;
  return true;
}

static void pzr_handleStop() {
  pzr_isRunning = false;
  pzr_timedRun  = false;
}

static bool pzr_handleRb(const String &args) {
  double v = 0.0;
  if (!parseValueSuffix(args, v, false) || !(v > 0.0 && v < 1e9)) return false;
  pzr_RB_OHM = (float)v;
  pzr_resetAllChannels();
  return true;
}

static bool pzr_handleRk(const String &args) {
  double v = 0.0;
  if (!parseValueSuffix(args, v, false) || !(v >= 0.0 && v < 1e9)) return false;
  pzr_RK_OHM = (float)v;
  pzr_resetAllChannels();
  return true;
}

static bool pzr_handleCf(const String &args) {
  double v = 0.0;
  if (!parseValueSuffix(args, v, true) || !(v > 1e-13 && v < 1e-2)) return false;
  pzr_CF_F = (float)v;
  pzr_resetAllChannels();
  return true;
}

static bool pzr_handleRxMax(const String &args) {
  double v = 0.0;
  if (!parseValueSuffix(args, v, false) || !(v > 0.0 && v < 1e9)) return false;
  pzr_RX_MAX_OHM = (float)v;
  return true;
}

static bool pzr_handleAscii(const String &args) {
  String a = args; a.trim(); a.toLowerCase();
  bool newMode = pzr_asciiOutput;
  if      (a.length() == 0)                                       newMode = !pzr_asciiOutput;
  else if (a == "1" || a == "on"  || a == "true"  || a == "ascii")  newMode = true;
  else if (a == "0" || a == "off" || a == "false" || a == "bin"
                                  || a == "binary")               newMode = false;
  else return false;

  if (newMode != pzr_asciiOutput) {
    pzr_asciiOutput = newMode;
    pzr_isRunning   = false;   // stop streaming on mode change
    pzr_timedRun    = false;
  }
  return true;
}

static void pzr_printStatus() {
  Serial.println(F("# -------- STATUS (PZR mode) --------"));
  Serial.print(F("# channels="));
  for (int i = 0; i < pzr_channelCount; i++) {
    Serial.print(pzr_channelSequence[i]);
    if (i < pzr_channelCount - 1) Serial.print(',');
  }
  Serial.println();
  Serial.print(F("# repeat=")); Serial.println(pzr_repeatCount);
  Serial.print(F("# buffer=")); Serial.println(pzr_bufferSweeps);
  Serial.print(F("# rb_ohm=")); Serial.println(pzr_RB_OHM, 6);
  Serial.print(F("# rk_ohm=")); Serial.println(pzr_RK_OHM, 6);
  Serial.print(F("# cf_f="));   Serial.println(pzr_CF_F, 12);
  Serial.print(F("# rxmax_ohm=")); Serial.println(pzr_RX_MAX_OHM, 6);
  Serial.print(F("# pair_timeout_ms=")); Serial.println(pzr_computePairTimeoutMs());
  uint32_t sps   = (uint32_t)pzr_channelCount * (uint32_t)pzr_repeatCount;
  uint32_t total = sps * (uint32_t)pzr_bufferSweeps;
  Serial.print(F("# samples_per_sweep=")); Serial.println(sps);
  Serial.print(F("# samples_per_block=")); Serial.println(total);
  Serial.print(F("# max_block_samples=")); Serial.println(PZR_MAX_BLOCK_SAMPLES);
  Serial.print(F("# running=")); Serial.println(pzr_isRunning ? F("true") : F("false"));
  Serial.print(F("# output="));  Serial.println(pzr_asciiOutput ? F("ascii") : F("binary"));
  Serial.println(F("# -------------------------"));
}

// Capture one block of resistance measurements and emit to host.
static void pzr_doOneBlock() {
  const uint32_t sps           = (uint32_t)pzr_channelCount * (uint32_t)pzr_repeatCount;
  const uint32_t totalSamples32 = sps * (uint32_t)pzr_bufferSweeps;

  if (totalSamples32 == 0 || totalSamples32 > PZR_MAX_BLOCK_SAMPLES) {
    pzr_isRunning = false;
    pzr_timedRun  = false;
    Serial.println(F("# ERROR: block too large. Reduce channels/repeat/buffer."));
    return;
  }

  const uint16_t totalSamples  = (uint16_t)totalSamples32;
  const uint32_t captureStartUs = micros();
  uint16_t       idx            = 0;
  int            prevCh         = -1;

  for (int b = 0; b < pzr_bufferSweeps; b++) {
    for (int ci = 0; ci < pzr_channelCount; ci++) {
      const uint8_t ch = pzr_channelSequence[ci];
      for (int r = 0; r < pzr_repeatCount; r++) {
        bool  switched = (prevCh != (int)ch);
        prevCh = (int)ch;
        float rx = 0.0f;
        (void)pzr_measureOneRx(ch, switched, rx);
        long v = lroundf(rx);
        if (v < 0) v = 0;
        if (v > 65535L) v = 65535L;
        pzr_sampleBuf[idx++] = (uint16_t)v;
      }
    }
  }

  const uint32_t captureEndUs = micros();
  uint32_t dtUs = captureEndUs - captureStartUs;
  uint16_t avgDt = (totalSamples > 0)
                   ? (uint16_t)min((dtUs + totalSamples / 2u) / totalSamples, 65535u)
                   : 0u;

  // ── ASCII debug output ────────────────────────────────────────────
  if (pzr_asciiOutput) {
    for (int b = 0; b < pzr_bufferSweeps; b++) {
      uint32_t base = (uint32_t)b * sps;
      for (uint32_t j = 0; j < sps; j++) {
        if (j) Serial.print(',');
        Serial.print(pzr_sampleBuf[base + j]);
      }
      Serial.println();
    }
    Serial.flush();
    return;
  }

  // ── Binary block ─────────────────────────────────────────────────
  // Header: [0xAA][0x55][countL][countH]
  uint8_t header[4] = {
    BLOCK_MAGIC1,
    BLOCK_MAGIC2,
    (uint8_t)(totalSamples & 0xFF),
    (uint8_t)(totalSamples >> 8)
  };
  Serial.write(header, 4);

  // Payload: samples as uint16 LE
  Serial.write((uint8_t *)pzr_sampleBuf, (size_t)(totalSamples * sizeof(uint16_t)));

  // Trailer: avg_dt(u16) + block_start(u32) + block_end(u32)
  uint8_t trailer[10];
  trailer[0] = (uint8_t)(avgDt & 0xFF);
  trailer[1] = (uint8_t)(avgDt >> 8);
  trailer[2] = (uint8_t)( captureStartUs        & 0xFF);
  trailer[3] = (uint8_t)((captureStartUs >>  8) & 0xFF);
  trailer[4] = (uint8_t)((captureStartUs >> 16) & 0xFF);
  trailer[5] = (uint8_t)((captureStartUs >> 24) & 0xFF);
  trailer[6] = (uint8_t)( captureEndUs          & 0xFF);
  trailer[7] = (uint8_t)((captureEndUs   >>  8) & 0xFF);
  trailer[8] = (uint8_t)((captureEndUs   >> 16) & 0xFF);
  trailer[9] = (uint8_t)((captureEndUs   >> 24) & 0xFF);
  Serial.write(trailer, 10);
  Serial.flush();
}

// =====================================================================
// ── MODE SWITCH ──────────────────────────────────────────────────────
// =====================================================================

static bool handleMode(const String &args) {
  String a = args; a.trim(); a.toUpperCase();

  if (a == "PZT") {
    if (currentMode != MODE_PZT) {
      pzr_isRunning = false;   // stop any active PZR run
      pzr_timedRun  = false;
      currentMode   = MODE_PZT;
      pzr_muxSelect(15);   // Park PZR MUX on calibration channel
      Serial.println(F("# Switched to PZT mode"));
    }
    return true;
  }

  if (a == "PZR") {
    if (currentMode != MODE_PZR) {
      // PZT run* is blocking so it cannot be active here, but clear flag anyway
      pzt.running = false;
      currentMode  = MODE_PZR;
      Serial.println(F("# Switched to PZR mode"));
    }
    return true;
  }

  Serial.println(F("# ERROR: mode must be PZT or PZR"));
  return false;
}

// =====================================================================
// ── SHARED MCU / HELP / STATUS ───────────────────────────────────────
// =====================================================================

static void printMcu() {
  Serial.println(F("# Array_PZT_PZR1"));
}

static void printHelp() {
  Serial.println(F("# Commands (* terminated):"));
  Serial.println(F("#   mode PZT|PZR         (switch operating mode; default PZT)"));
  Serial.println(F("# ── Shared ──────────────────────────────────────────────────"));
  Serial.println(F("#   mcu                   (print device ID)"));
  Serial.println(F("#   status                (show current config)"));
  Serial.println(F("#   channels 0,1,2,...    (MUX channels 0-15)"));
  Serial.println(F("#   repeat <n>            (samples per channel per sweep)"));
  Serial.println(F("#   buffer <n>            (sweeps per binary block)"));
  Serial.println(F("#   run                   (stream until stop*)"));
  Serial.println(F("#   run <ms>              (time-limited run)"));
  Serial.println(F("#   stop"));
  Serial.println(F("# ── PZT mode only ───────────────────────────────────────────"));
  Serial.println(F("#   ref 1.2|3.3|vdd"));
  Serial.println(F("#   osr 2|4|8"));
  Serial.println(F("#   gain 1|2|3|4"));
  Serial.println(F("#   ground <ch>|true|false"));
  Serial.println(F("# ── PZR mode only ───────────────────────────────────────────"));
  Serial.println(F("#   rb <ohms|k|M>         (discharge resistor, e.g. rb 470*)"));
  Serial.println(F("#   rk <ohms|k|M>         (known series resistor, e.g. rk 470*)"));
  Serial.println(F("#   cf <F|p|n|u|m>        (capacitance, e.g. cf 220n*)"));
  Serial.println(F("#   rxmax <ohms|k|M>      (max expected Rx for timeouts)"));
  Serial.println(F("#   ascii [1|0|on|off]    (toggle ASCII/binary output; stops streaming)"));
}

// =====================================================================
// ── COMMAND DISPATCHER ───────────────────────────────────────────────
// =====================================================================

static void handleLine(const String &rawLine) {
  String line = rawLine; line.trim();
  if (line.length() == 0) return;

  int    sp   = line.indexOf(' ');
  String cmd  = (sp < 0) ? line : line.substring(0, sp);
  String args = (sp < 0) ? "" : line.substring(sp + 1);
  args.trim();
  cmd.toLowerCase();

  bool ok = true;

  // ── Universal commands (mode-independent) ────────────────────────
  if (cmd == "mode") {
    ok = handleMode(args);
    hostAck(ok, args);
    return;
  }

  if (cmd == "mcu") {
    printMcu();
    hostAck(true, args);
    return;
  }

  if (cmd == "help") {
    printHelp();
    hostAck(true, args);
    return;
  }

  if (cmd == "status") {
    Serial.print(F("# Current mode: "));
    Serial.println(currentMode == MODE_PZT ? F("PZT") : F("PZR"));
    if (currentMode == MODE_PZT) pzt_printStatus();
    else                          pzr_printStatus();
    hostAck(true, args);
    return;
  }

  if (cmd == "stop") {
    if (currentMode == MODE_PZT) pzt.running = false;
    else                          pzr_handleStop();
    hostAck(true, args);
    return;
  }

  // ── PZT mode commands ─────────────────────────────────────────────
  if (currentMode == MODE_PZT) {
    if      (cmd == "channels") ok = pzt_handleChannels(args);
    else if (cmd == "repeat")   ok = pzt_handleRepeat(args);
    else if (cmd == "buffer")   ok = pzt_handleBuffer(args);
    else if (cmd == "ref")      ok = pzt_handleRef(args);
    else if (cmd == "osr")      ok = pzt_handleOsr(args);
    else if (cmd == "gain")     ok = pzt_handleGain(args);
    else if (cmd == "ground")   ok = pzt_handleGround(args);
    else if (cmd == "run") {
      pzt_handleRun(args);   // blocking; manages its own hostAck
      return;
    }
    else if (cmd == "rb" || cmd == "rk" || cmd == "cf" ||
             cmd == "rxmax" || cmd == "ascii") {
      Serial.println(F("# ERROR: this command is only available in PZR mode. Send 'mode PZR*' first."));
      ok = false;
    }
    else {
      Serial.print(F("# ERROR: unknown command '")); Serial.print(cmd);
      Serial.println(F("'. Type 'help'."));
      ok = false;
    }
  }

  // ── PZR mode commands ─────────────────────────────────────────────
  else {
    if      (cmd == "channels") ok = pzr_handleChannels(args);
    else if (cmd == "repeat")   ok = pzr_handleRepeat(args);
    else if (cmd == "buffer")   ok = pzr_handleBuffer(args);
    else if (cmd == "run")      ok = pzr_handleRun(args);
    else if (cmd == "rb")       ok = pzr_handleRb(args);
    else if (cmd == "rk")       ok = pzr_handleRk(args);
    else if (cmd == "cf")       ok = pzr_handleCf(args);
    else if (cmd == "rxmax")    ok = pzr_handleRxMax(args);
    else if (cmd == "ascii")    ok = pzr_handleAscii(args);
    else if (cmd == "ref" || cmd == "osr" || cmd == "gain" || cmd == "ground") {
      Serial.println(F("# ERROR: this command is only available in PZT mode. Send 'mode PZT*' first."));
      ok = false;
    }
    else {
      Serial.print(F("# ERROR: unknown command '")); Serial.print(cmd);
      Serial.println(F("'. Type 'help'."));
      ok = false;
    }
  }

  hostAck(ok, args);
}

// =====================================================================
// ── SETUP ────────────────────────────────────────────────────────────
// =====================================================================

void setup() {
  Serial.begin(SERIAL_BAUD);
  while (!Serial) {}

  // ── PZT (SPI) ────────────────────────────────────────────────────
  pztSPI.begin();
  pinMode(PZT_CS_PIN, OUTPUT);
  digitalWrite(PZT_CS_PIN, HIGH);

  // ── PZR (555 + MUX) ──────────────────────────────────────────────
  pinMode(PZR_ICP_PIN, INPUT);
  pinMode(PZR_MUX_A0_PIN, OUTPUT);
  pinMode(PZR_MUX_A1_PIN, OUTPUT);
  pinMode(PZR_MUX_A2_PIN, OUTPUT);
  pinMode(PZR_MUX_A3_PIN, OUTPUT);
  if (PZR_MUX_EN_PIN >= 0) {
    pinMode(PZR_MUX_EN_PIN, OUTPUT);
    pzr_muxEnable(true);
  }

  dwtInit();
  attachInterrupt(digitalPinToInterrupt(PZR_ICP_PIN), pzr_isr555, CHANGE);
  pzr_resetAllChannels();

  pzr_muxSelect(15);   // Park PZR MUX on calibration channel

  // Announce device so the Python host can identify and detect current mode
  printMcu();
  Serial.println(F("# Default mode: PZT"));
}

// =====================================================================
// ── LOOP ─────────────────────────────────────────────────────────────
// =====================================================================

void loop() {

  // ── 1. Command parser (always active) ────────────────────────────
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r' || c == '\n') continue;
    if (c == CMD_TERM) {
      if (inputLine.length() > 0) {
        handleLine(inputLine);
        inputLine = "";
      }
      continue;
    }
    inputLine += c;
    if (inputLine.length() > MAX_CMD_LEN) {
      inputLine = "";
      Serial.println(F("# ERROR: input too long; cleared."));
    }
  }

  // ── 2. PZR non-blocking streaming ────────────────────────────────
  //    (PZT run* is blocking and never reaches here while active.)
  if (currentMode == MODE_PZR) {

    // Check timed-run expiry between blocks
    if (pzr_isRunning && pzr_timedRun) {
      if ((int32_t)(millis() - pzr_runStopMillis) >= 0) {
        pzr_isRunning = false;
        pzr_timedRun  = false;
        return;
      }
    }

    if (pzr_isRunning) {
      pzr_doOneBlock();
    }
  }
}
