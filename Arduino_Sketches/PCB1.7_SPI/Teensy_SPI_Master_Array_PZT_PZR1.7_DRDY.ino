/*
 * Teensy_SPI_Master_Array_PZT_PZR1.ino
 * Teensy 4.0 — Combined PZT (SPI/MG24) and PZR (555 Timer) Streamer
 * ================================================================== 
 *
 * Exposes a unified serial API (same as README) with an additional
 * mode-switch command:
 *
 *   mode PZT*      -> SPI-master bridge to MG24 dual-MUX slave (default)
 *   mode PZR*      -> 555-astable resistance measurement via ADG706 MUX
 *   mode PZT_RS*   -> combined stream with PZT + RS values
 *
 * Device ID (both modes):
 *   mcu*  ->  # Array_PZT_PZR1.7
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
 *   Ra is derived from measured high/low timing vs known Rb.
 *   Each uint16 sample is Ra=(Rx+Rk) in ohms, rounded and clamped to 0..65535.
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
 *   - PZT run* remains command-blocking, but the data path now uses DRDY
 *     interrupt notification plus queued USB writes so SPI reads happen
 *     promptly with less lag.
 *   - PZR run* is non-blocking; blocks are executed in loop().
 *   - Switching modes stops any active run in the outgoing mode.
 *   - Baud rate is 460800 for both modes.
 *
 * Change log:
 *   v1.0  Initial combined sketch. Used with PCB Octoplus_Reader_Ver1.0
 *         Currently only PZR or Rosette are being read (not both) according to the interrupt pin
 *   4.23.26: Updated PZR Pins according to PCB board Octoplus_Reader_Ver1.5
 *            At this point only PZR MUX is used.
 *            Added new DRDY pin for PCB ver1.5 (provision for, not implemented yet).
 *   5.5.26: Added switching between two 555 modes (MUXes): PZR / RS (Rosettes).
 *            At this point only one 555 MUX is being read at a time (PCB1.5 has different MUX address controls)
 *   5.6.26: Changed 555 calculation. Calc and send Ra (instead of just Rx = Ra - Rk). Moving avg for discharge cycles time.
 */

#include <Arduino.h>
#include <SPI.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

#ifndef DMAMEM
#define DMAMEM
#endif

// =====================================================================
// ── MODE ─────────────────────────────────────────────────────────────
// Set operating mode: MODE_PZT, MODE_PZR, MODE_PZT_RS
//
// In PZR mode there are two Timer Modes: TIMER555_PZR, TIMER555_RS
//   TIMEER555_PZR uses the PZR MUX
//   TIMER555_RS uses the Rosettes and bridges MUX
//
// =====================================================================

enum DeviceMode { MODE_PZT, MODE_PZR, MODE_PZT_RS };
static DeviceMode currentMode = MODE_PZT;   // default

enum Timer555Mode { TIMER555_PZR, TIMER555_RS };
static constexpr Timer555Mode DEFAULT_555_MODE = TIMER555_RS;

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
static const uint8_t  PZT_CS_PIN               = 10;
static const uint32_t PZT_SPI_BITRATE          = 4000000UL;   // 4000000UL = 4 MHz
static const uint32_t PZT_CS_SETUP_US          = 10;
static const bool     PZT_DEBUG_TEXT_STREAM    = false;
static const uint8_t  PZT_DRDY_PIN             = 0;   // MG24 D7 -> Teensy pin 0, active-HIGH DRDY
static const uint32_t PZT_DRDY_ACK_TIMEOUT_MS  = 25;
static const uint32_t PZT_DRDY_MARGIN_MS       = 25;
static const uint32_t PZT_STREAM_IDLE_SLACK_MS = 100;
static const uint8_t  PZT_RX_QUEUE_DEPTH       = 4;

// ── Protocol frame sizes (must match MG24 sketch) ─────────────────────
static const uint8_t  PZT_CMD_FRAME_LEN      = 20;
static const uint8_t  PZT_ACK_FRAME_LEN      = 4;
static const uint8_t  PZT_BLOCK_TRAILER_LEN  = 10;  // avg_dt(2)+start(4)+end(4)
static const uint8_t  PZT_ACK_MAGIC          = 0xAC;
static const uint8_t  PZT_ACK_STATUS_OK      = 0x00;

// ── Timing ────────────────────────────────────────────────────────────
static const uint32_t PZT_MUX_SETTLE_US          = 20; // <<========= was 30
static const uint32_t PZT_IADC_CONV_US_OSR2      = 8;   // was 2 for faster 10k IADC clock / 4 for slower 5K IADC clock
static const uint32_t PZT_IADC_CONV_US_OSR4      = 9;   // was 4 for faster 10k IADC clock / 8 for slower 5K IADC clock
static const uint32_t PZT_IADC_CONV_US_OSR8      = 10;  // was 8 for faster 10k IADC clock / 16 for slower 5K IADC clock
static const uint32_t PZT_BLOCK_DELAY_MARGIN_MS  = 15;
static const uint32_t PZT_WARMUP_DELAY_MARGIN_MS = 10;
static const uint32_t PZT_RS_FIRST_BLOCK_MIN_TIMEOUT_MS = 500;
static const uint16_t PZT_WARMUP_SWEEPS          = 48;

// ── Protocol limits ───────────────────────────────────────────────────
static const uint16_t PZT_MAX_REPEAT             = 100;
static const uint8_t  PZT_MUX_CH_MAX             = 15;
static const uint8_t  PZT_MAX_PHYSICAL_CHANNELS  = 16;
static const uint8_t  PZT_MAX_LOGICAL_SLOTS      = 32;
static const uint8_t  PZT_CHANNELS_PER_SENSOR    = 5;
static const uint8_t  PZT_MAX_SENSOR_SLOTS       = 6;
static const uint8_t  PZT_RS_VALUES_PER_SENSOR   = 2;
static const uint8_t  PZT_RS_OUTPUTS_PER_SENSOR  =
    PZT_CHANNELS_PER_SENSOR + PZT_RS_VALUES_PER_SENSOR;
static const uint32_t PZT_MAX_PAIRS              = 8000UL;

static const uint32_t PZT_MAX_BLOCK_BYTES =
    (uint32_t)PZT_ACK_FRAME_LEN + PZT_MAX_PAIRS * 4UL + PZT_BLOCK_TRAILER_LEN;

// MODE_PZT_RS repacks selected sensors as:
// [PZT_CH1, PZT_CH2, PZT_CH3, PZT_CH4, PZT_CH5, RS1_hold, RS2_hold].
// RS1_hold / RS2_hold are encoded as uint16 deci-ohms on the wire.
// Keep this aligned with the Python serial parser's MAX_SAMPLES_BUFFER.
static const uint32_t PZT_RS_MAX_OUTPUT_SAMPLES = 32000UL;
static const uint32_t PZT_RS_MAX_BLOCK_BYTES =
    (uint32_t)PZT_ACK_FRAME_LEN + PZT_RS_MAX_OUTPUT_SAMPLES * 2UL + PZT_BLOCK_TRAILER_LEN;

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
static const uint8_t PZT_STREAM_CONTINUE  = 0x0D;  // matches MG24 CMD_CONTINUE

// =====================================================================
// ── PZT MODE — STATE ─────────────────────────────────────────────────
// =====================================================================

static SPIClass      &pztSPI    = SPI;
static const SPISettings PZT_SPI_CFG(PZT_SPI_BITRATE, MSBFIRST, SPI_MODE1);

struct PZTConfig {
  uint8_t  channels[PZT_MAX_LOGICAL_SLOTS];
  uint8_t  physicalChannels[PZT_MAX_PHYSICAL_CHANNELS];
  uint8_t  sensorMux[PZT_MAX_SENSOR_SLOTS];
  int8_t   sensorRsA[PZT_MAX_SENSOR_SLOTS];
  int8_t   sensorRsB[PZT_MAX_SENSOR_SLOTS];
  uint8_t  rsRefreshChannels[16];
  uint8_t  channelCount   = 0;
  uint8_t  physicalChannelCount = 0;
  uint8_t  sensorCount = 0;
  uint8_t  sensorMuxCount = 0;
  uint8_t  rsChannelCount = 0;
  uint8_t  rsRefreshChannelCount = 0;
  uint8_t  repeatCount    = 1;
  uint8_t  sweepsPerBlock = 1;
  uint8_t  osr            = 2;   // 2 | 4 | 8
  uint8_t  gain           = 1;   // 1..4
  uint8_t  ref            = 1;   // 0=1.2V  1=VDD/3.3V
  uint8_t  groundPin      = 0;
  bool     groundEnable   = false;
  bool     running        = false;
} pzt;

struct PZTQueuedBlock {
  uint32_t len;
  uint32_t txOffset;
  uint8_t  data[PZT_RS_MAX_BLOCK_BYTES];
};

static PZTQueuedBlock pztRxQueue[PZT_RX_QUEUE_DEPTH] DMAMEM;
static uint8_t        pztRxHead             = 0;
static uint8_t        pztRxTail             = 0;
static uint8_t        pztRxCount            = 0;
static uint32_t       pztStreamBlockBytes   = 0;
static uint32_t       pztStreamLastActivity = 0;
static bool           pztStopRequested      = false;
static bool           pztStopControlSent    = false;
static bool           pztWaitingFinalAck    = false;
static bool           pztRemoteEnded        = false;
static bool           pztStreamFault        = false;
static uint32_t       pztLastFallbackPollMs = 0;
static uint8_t        pztStopMatchPos       = 0;
static uint8_t        pztConsecutiveRxErrors = 0;
static uint32_t       pztTransientRxErrorsTotal = 0;
static uint32_t       pztRunStartMs = 0;
static uint32_t       pztBlocksFromDrdy = 0;
static uint32_t       pztBlocksFromFallback = 0;
static uint32_t       pztAcksFromDrdy = 0;
static uint32_t       pztAcksFromFallback = 0;
static uint32_t       pztDrdyReadAttempts = 0;
static uint32_t       pztDrdyReadTimeouts = 0;
static uint32_t       pztFallbackPollAttempts = 0;
static uint32_t       pztFallbackPollTimeouts = 0;
static volatile bool  pztDrdyFlag           = false;
static volatile uint32_t pztDrdyEdges       = 0;
static volatile uint32_t pztRsIsrFires      = 0;  // counts every pzr_isr555 call
static volatile uint8_t pztRsActiveChannel  = 0xFF;
static uint8_t        pztRsBlockBuf[PZT_RS_MAX_BLOCK_BYTES] DMAMEM;
static uint16_t       pztRsLastRaQByChannel[16] = {0};
static float          pztRsHoldMedianBufByChannel[16][5] = {{0.0f}};
static uint8_t        pztRsHoldMedianIdxByChannel[16] = {0};
static uint8_t        pztRsHoldMedianCountByChannel[16] = {0};
static uint32_t       pztRsUpdateCountByChannel[16] = {0};
static uint32_t       pztRsLastUpdateMsByChannel[16] = {0};
static volatile uint32_t pztRsRiseEdgesByChannel[16] = {0};
static volatile uint32_t pztRsFallEdgesByChannel[16] = {0};
static volatile uint32_t pztRsPairsReadyByChannel[16] = {0};
static volatile uint32_t pztRsLastPairHCycByChannel[16] = {0};
static volatile uint32_t pztRsLastPairLCycByChannel[16] = {0};
static uint32_t       pztRsDiscardPairsByChannel[16] = {0};
static uint32_t       pztRsTimeoutsByChannel[16] = {0};
static uint32_t       pztRsTotalUpdates = 0;
static uint32_t       pztRsMuxSwitches = 0;
static uint32_t       pztRsDiscardPairs = 0;
static uint32_t       pztRsChannelTimeouts = 0;  // channels skipped due to no 555 pair
static uint32_t       pztRsChannelStartMs  = 0;  // millis() when current channel was selected
static uint32_t       pztRsChannelTimeoutMs = 0; // per-channel timeout, computed at run start
static int8_t         pztRsPrevMeasuredChannel = -1;
static uint8_t        pztRsRefreshIndex = 0;
static uint32_t       pztRsLastRefreshMs = 0;
static const uint32_t PZT_RS_REFRESH_MIN_MS = 0; // Pair-ready paced; do not add artificial scan delay.
static const uint8_t  PZT_RS_MEASURE_PAIRS_PER_UPDATE = 3;
static const uint8_t  PZT_RS_HELD_MEDIAN_N = 5;

enum PZTRsRefreshStage { PZT_RS_REFRESH_IDLE, PZT_RS_REFRESH_DISCARD, PZT_RS_REFRESH_MEASURE };
static PZTRsRefreshStage pztRsRefreshStage = PZT_RS_REFRESH_IDLE;
static uint8_t           pztRsPendingChannel = 0;
static uint8_t           pztRsDiscardRemaining = 0;
static float             pztRsMeasureRaBuf[3] = {0.0f, 0.0f, 0.0f};
static uint8_t           pztRsMeasurePairsCollected = 0;

// Forward declarations for MODE_PZT_RS helpers used by SPI service paths.
static void pzt_rsResetState();
static void pzt_rsStartNextRefreshChannel();
static void pzt_rsServiceRefresh(bool allowChannelSwitch = true);
static bool pzt_buildCombinedBlock(const uint8_t *src, uint32_t srcLen,
                                   uint8_t *dst, uint32_t &dstLen,
                                   const uint16_t *heldRaQSnapshot);
static void pzr_printChannelTimingDiagnostics(
    uint8_t ch,
    const __FlashStringHelper *prefix = F("# RS timing "));
static void pzt_printRsRefreshDiagnostics(
    uint8_t ch,
    const __FlashStringHelper *prefix = F("# RS refresh "));

// =====================================================================
// ── PZR MODE — CONSTANTS ─────────────────────────────────────────────
// =====================================================================
// In PCB_ver1.5 each 555 MUX is controlled separately, so need to define different set for 555-PZR MUX and 555-Rosette MUX

// 555-PZR MUX pins
static const int PZR_ICP_PIN    = 23;  // PCB_ver1.5: 23-PZR MUX // PCB_ver1.0: 22
static const int PZR_MUX_A0_PIN = 22;  // PCB_ver1.5: For PZR: 22 // PCB_ver1.0: 20 (shared mux address)
static const int PZR_MUX_A1_PIN = 21;  // PCB_ver1.5: For PZR: 21 // PCB_ver1.0: 19 (shared mux address)
static const int PZR_MUX_A2_PIN = 20;  // PCB_ver1.5: For PZR: 20 // PCB_ver1.0: 18 (shared mux address)
static const int PZR_MUX_A3_PIN = 19;  // PCB_ver1.5: For PZR: 19 // PCB_ver1.0: 17 (shared mux address)
static const int PZR_MUX_EN_PIN = 7;    // PCB_ver1.7: Teensy pin 7

// 555-Rosette MUX pins
static const int RS_ICP_PIN    = 14;  // PCB_ver1.5: 14-Rosette MUX // PCB_ver1.0: 15
static const int RS_MUX_A0_PIN = 18;  // PCB_ver1.5: For Rosette: 18 // PCB_ver1.0: 20 (shared mux address)
static const int RS_MUX_A1_PIN = 17;  // PCB_ver1.5: For Rosette: 17 // PCB_ver1.0: 19 (shared mux address)
static const int RS_MUX_A2_PIN = 16;  // PCB_ver1.5: For Rosette: 16 // PCB_ver1.0: 18 (shared mux address)
static const int RS_MUX_A3_PIN = 15;  // PCB_ver1.5: For Rosette: 15 // PCB_ver1.0: 17 (shared mux address)
static const int RS_MUX_EN_PIN = 8;    // PCB_ver1.7: Teensy pin 8

// Active 555 pins selected by DEFAULT_555_MODE.
static constexpr int TIMER555_ICP_PIN =
    (DEFAULT_555_MODE == TIMER555_RS) ? RS_ICP_PIN : PZR_ICP_PIN;
static constexpr int TIMER555_MUX_A0_PIN =
    (DEFAULT_555_MODE == TIMER555_RS) ? RS_MUX_A0_PIN : PZR_MUX_A0_PIN;
static constexpr int TIMER555_MUX_A1_PIN =
    (DEFAULT_555_MODE == TIMER555_RS) ? RS_MUX_A1_PIN : PZR_MUX_A1_PIN;
static constexpr int TIMER555_MUX_A2_PIN =
    (DEFAULT_555_MODE == TIMER555_RS) ? RS_MUX_A2_PIN : PZR_MUX_A2_PIN;
static constexpr int TIMER555_MUX_A3_PIN =
    (DEFAULT_555_MODE == TIMER555_RS) ? RS_MUX_A3_PIN : PZR_MUX_A3_PIN;
static constexpr int TIMER555_MUX_EN_PIN =
    (DEFAULT_555_MODE == TIMER555_RS) ? RS_MUX_EN_PIN : PZR_MUX_EN_PIN;

static constexpr const char *TIMER555_NAME =
    (DEFAULT_555_MODE == TIMER555_RS) ? "RS/555_A" : "PZR/555_B";

static constexpr uint32_t TIMER555_MUX_SETTLE_NS          = 100;
// After switching the RS MUX channel, discard this cycles before measurement
static constexpr int      PZR_DISCARD_CYCLES_AFTER_SWITCH = 1;
static constexpr int      PZR_RA_MA_N                     = 1;  // Ra smoothing per MUX channel; set to 1 to disable MA
static constexpr int      PZR_RA_MEDIAN_N                 = 3;  // Median-of-3 rejects isolated one-pair spikes
static constexpr int      PZR_LCYC_MA_N                   = 1;  // set to 1 to use the raw measured low-cycle directly
static constexpr int      PZR_MAX_CHANNEL_SEQUENCE        = 64;
static constexpr uint16_t PZR_MAX_BLOCK_SAMPLES           = 2048;

static constexpr float LN2 = 0.69314718056f;

// 555 component defaults (PCB ver 1.0)
static constexpr float PZR_DEFAULT_RB_OHM     = 470.0f;     // discharge resistor
static constexpr float PZR_DEFAULT_RK_OHM     = 470.0f;     // known series resistor
static constexpr float PZR_555_B_DEFAULT_CF_F = 22e-9f;    // PZR / 555_B = 22 nF
static constexpr float RS_555_A_DEFAULT_CF_F  = 220e-9f;   // RS  / 555_A = 220 nF
static constexpr float PZR_DEFAULT_CF_F =
    (DEFAULT_555_MODE == TIMER555_RS) ? RS_555_A_DEFAULT_CF_F : PZR_555_B_DEFAULT_CF_F;
static constexpr float PZR_DEFAULT_RX_MAX_OHM = 65500.0f;

enum PZRLowCycleSource { PZR_LCYC_SOURCE_MEASURED, PZR_LCYC_SOURCE_MODELED };
static constexpr PZRLowCycleSource PZR_RA_LCYC_SOURCE = PZR_LCYC_SOURCE_MODELED;

// =====================================================================
// ── PZR MODE — STATE ─────────────────────────────────────────────────
// =====================================================================

static float   pzr_RB_OHM      = PZR_DEFAULT_RB_OHM;
static float   pzr_RK_OHM      = PZR_DEFAULT_RK_OHM;
static float   pzr_CF_F        = PZR_DEFAULT_CF_F;
static float   pzr_RX_MAX_OHM  = PZR_DEFAULT_RX_MAX_OHM;
static float   pzr_lCycModelCycles = NAN;
static bool    pzr_asciiOutput  = false;

static uint8_t  pzr_channelSequence[PZR_MAX_CHANNEL_SEQUENCE] = {0, 1, 2, 3, 4};
static int      pzr_channelCount  = 5;
static int      pzr_repeatCount   = 1;
static int      pzr_bufferSweeps  = 1;
static bool     pzr_isRunning     = false;
static bool     pzr_timedRun      = false;
static uint32_t pzr_runStopMillis = 0;

static uint16_t pzr_sampleBuf[PZR_MAX_BLOCK_SAMPLES];

enum PZRCaptureEdge : uint8_t {
  PZR_EDGE_NONE = 0,
  PZR_EDGE_RISE = 1,
  PZR_EDGE_FALL = 2
};

// 555 capture state — written in ISR, read in main loop
struct PZR_CaptureState {
  volatile uint32_t lastRiseCycles = 0;
  volatile uint32_t lastFallCycles = 0;
  volatile uint32_t highCycles     = 0;
  volatile uint32_t lowCycles      = 0;
  volatile uint32_t sequenceErrors = 0;
  volatile uint8_t  lastEdge       = PZR_EDGE_NONE;
  volatile bool     pairReady      = false;
};
static PZR_CaptureState pzr_cap;

// Per-channel moving-average state for the final reported value.
// The reported PZR sample is now Ra=(Rx+Rk), not Rx.
struct PZR_ChannelState {
  float raBuf[PZR_RA_MA_N];
  float raMedianBuf[PZR_RA_MEDIAN_N];
  float raSum       = 0.0f;
  int   raIdx       = 0;
  int   raCount     = 0;
  int   raMedianIdx = 0;
  int   raMedianCount = 0;
  uint32_t lastHCyc = 0;
  uint32_t lastLCyc = 0;
  float lastLCycAvgUsed = NAN;
  float lastLCycModelUsed = NAN;
  float lastPlotRa  = NAN;

  void reset() {
    raSum = 0.0f;
    raIdx = raCount = 0;
    raMedianIdx = raMedianCount = 0;
    for (int i = 0; i < PZR_RA_MA_N; i++) raBuf[i] = 0.0f;
    for (int i = 0; i < PZR_RA_MEDIAN_N; i++) raMedianBuf[i] = 0.0f;
    lastHCyc = 0;
    lastLCyc = 0;
    lastLCycAvgUsed = NAN;
    lastLCycModelUsed = NAN;
    lastPlotRa = NAN;
  }
};
static PZR_ChannelState pzr_chState[16];

// Per-555 low-cycle smoothing state.
// lCyc should be mostly independent of the selected Rx channel, but PZR and RS
// are two different physical 555 circuits, so keep one smoothing state per source.
enum { PZR_555_INDEX_PZR = 0, PZR_555_INDEX_RS = 1, PZR_555_COUNT = 2 };

static inline int pzr_active555Index() {
  return (DEFAULT_555_MODE == TIMER555_RS) ? PZR_555_INDEX_RS : PZR_555_INDEX_PZR;
}

struct PZR_LowCycleSmootherState {
  uint32_t lCycBuf[PZR_LCYC_MA_N];
  uint64_t lCycSum      = 0;
  int      lCycIdx      = 0;
  int      lCycCount    = 0;
  float    lastLCycAvg  = NAN;

  void reset() {
    lCycSum = 0;
    lCycIdx = lCycCount = 0;
    for (int i = 0; i < PZR_LCYC_MA_N; i++) lCycBuf[i] = 0;
    lastLCycAvg = NAN;
  }

  float update(uint32_t lCyc) {
    lCycSum -= lCycBuf[lCycIdx];
    lCycBuf[lCycIdx] = lCyc;
    lCycSum += lCyc;
    lCycIdx = (lCycIdx + 1) % PZR_LCYC_MA_N;
    if (lCycCount < PZR_LCYC_MA_N) lCycCount++;
    lastLCycAvg = (lCycCount > 0) ? ((float)lCycSum / (float)lCycCount) : NAN;
    return lastLCycAvg;
  }
};
static PZR_LowCycleSmootherState pzr_lowCycleSmootherBy555[PZR_555_COUNT];

// =====================================================================
// ── SHARED INPUT BUFFER ──────────────────────────────────────────────
// =====================================================================

static String inputLine;

// =====================================================================
// ── DWT CYCLE COUNTER (PZR timing) ───────────────────────────────────
// =====================================================================

// Enable and reset the DWT cycle counter used for high-resolution 555 timing.
static inline void dwtInit() {
  ARM_DEMCR       |= ARM_DEMCR_TRCENA;
  ARM_DWT_CTRL    |= ARM_DWT_CTRL_CYCCNTENA;
  ARM_DWT_CYCCNT   = 0;
}

// =====================================================================
// ── PZT SPI / DRDY HELPERS ───────────────────────────────────────────
// =====================================================================

// DRDY ISR: record one pending edge for the SPI service loop.
void pzt_drdyISR() {
  pztDrdyFlag = true;
  pztDrdyEdges++;
}

// Report whether at least one unread DRDY edge is pending.
static inline bool pzt_drdyPending() {
  // Treat DRDY as edge-driven. Using pin level here can retrigger reads while
  // the line is still high from the same event, which can desync the stream.
  return pztDrdyFlag;
}

// Consume one queued DRDY edge after servicing one SPI response.
static inline void pzt_drdyConsumeOne() {
  noInterrupts();
  if (pztDrdyEdges > 0) pztDrdyEdges--;
  pztDrdyFlag = (pztDrdyEdges != 0);
  interrupts();
}

// Clear all queued DRDY edges and reset pending state.
static inline void pzt_drdyClearAll() {
  noInterrupts();
  pztDrdyEdges = 0;
  pztDrdyFlag  = false;
  interrupts();
}

// Block until a DRDY edge arrives or the timeout expires.
static bool pzt_waitForDrdy(uint32_t timeoutMs) {
  uint32_t t0 = millis();
  while (!pzt_drdyPending()) {
    if ((millis() - t0) >= timeoutMs) return false;
    yield();
  }
  return true;
}

// Transfer a full SPI frame while handling CS setup/hold sequencing.
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

// Send an SPI frame without collecting response bytes.
static inline void pzt_spiSend(const uint8_t *buf, uint16_t len) {
  pzt_spiTransfer(buf, nullptr, len);
}
// Receive an SPI frame by clocking out zeros.
static inline void pzt_spiRecv(uint8_t *buf, uint16_t len) {
  pzt_spiTransfer(nullptr, buf, len);
}

// Attempt to read a streaming response (block or ACK).
// The first byte sent carries a control token for MG24's streaming state machine.
static bool pzt_spiRecvStreamingResponse(uint8_t *buf, uint16_t len,
                                         uint8_t controlByte = PZT_STREAM_CONTINUE,
                                         uint8_t maxAttempts = 1) {
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

    if (pzt_isValidAckFrame(buf)) return true;
    if (buf[0] == BLOCK_MAGIC1 && buf[1] == BLOCK_MAGIC2) return true;
    delayMicroseconds(200 + (uint32_t)attempt * 200);
  }
  return false;
}

// Wait for DRDY, then read and validate a short ACK frame.
static bool pzt_recvAckWhenReady(uint8_t *buf, uint32_t timeoutMs) {
  if (!pzt_waitForDrdy(timeoutMs)) return false;
  pzt_drdyConsumeOne();
  pzt_spiRecv(buf, PZT_ACK_FRAME_LEN);
  return (buf[0] == PZT_ACK_MAGIC);
}

// Return true when no queued blocks are waiting for USB transmit.
static inline bool pzt_queueIsEmpty() { return pztRxCount == 0; }
// Return true when the queued block ring buffer is full.
static inline bool pzt_queueIsFull()  { return pztRxCount >= PZT_RX_QUEUE_DEPTH; }

static uint8_t pzt_physicalChannelCount() {
  return (currentMode == MODE_PZT_RS && pzt.physicalChannelCount > 0)
             ? pzt.physicalChannelCount
             : pzt.channelCount;
}

static int8_t pzt_physicalIndexForChannel(uint8_t ch) {
  for (uint8_t i = 0; i < pzt.physicalChannelCount; ++i) {
    if ((pzt.physicalChannels[i] & 0x0F) == (ch & 0x0F)) return (int8_t)i;
  }
  return -1;
}

static bool pzt_addUniqueRsRefreshChannel(int8_t ch) {
  if (ch < 0 || ch > 15) return true;
  for (uint8_t i = 0; i < pzt.rsRefreshChannelCount; ++i) {
    if ((pzt.rsRefreshChannels[i] & 0x0F) == (uint8_t)ch) return true;
  }
  if (pzt.rsRefreshChannelCount >= 16) return false;
  pzt.rsRefreshChannels[pzt.rsRefreshChannelCount++] = (uint8_t)ch;
  return true;
}

// Get the next queued block ready to transmit to host.
static PZTQueuedBlock *pzt_queueFront() {
  return pzt_queueIsEmpty() ? nullptr : &pztRxQueue[pztRxHead];
}

// Get the next writable slot in the receive queue.
static PZTQueuedBlock *pzt_queueWriteSlot() {
  return pzt_queueIsFull() ? nullptr : &pztRxQueue[pztRxTail];
}

// Finalize a just-filled queue slot and advance the tail.
static void pzt_queueCommitWrite(uint32_t len) {
  pztRxQueue[pztRxTail].len = len;
  pztRxQueue[pztRxTail].txOffset = 0;
  pztRxTail = (uint8_t)((pztRxTail + 1u) % PZT_RX_QUEUE_DEPTH);
  pztRxCount++;
}

// Drop the front queue entry after it has been fully transmitted.
static void pzt_queuePopFront() {
  if (pzt_queueIsEmpty()) return;
  pztRxQueue[pztRxHead].len = 0;
  pztRxQueue[pztRxHead].txOffset = 0;
  pztRxHead = (uint8_t)((pztRxHead + 1u) % PZT_RX_QUEUE_DEPTH);
  pztRxCount--;
}

// Reset all transient stream/queue counters before a new run.
static void pzt_streamResetState() {
  pztRxHead = pztRxTail = pztRxCount = 0;
  pztStreamBlockBytes   = 0;
  pztStopRequested      = false;
  pztStopControlSent    = false;
  pztWaitingFinalAck    = false;
  pztRemoteEnded        = false;
  pztStreamFault        = false;
  pztLastFallbackPollMs = millis();
  pztStopMatchPos       = 0;
  pztConsecutiveRxErrors = 0;
  pztTransientRxErrorsTotal = 0;
  pztRunStartMs = millis();
  pztBlocksFromDrdy = 0;
  pztBlocksFromFallback = 0;
  pztAcksFromDrdy = 0;
  pztAcksFromFallback = 0;
  pztDrdyReadAttempts = 0;
  pztDrdyReadTimeouts = 0;
  pztFallbackPollAttempts = 0;
  pztFallbackPollTimeouts = 0;
  pztStreamLastActivity = millis();
  pzt_drdyClearAll();
  pztRsActiveChannel = 0xFF;
  pztRsPrevMeasuredChannel = -1;
  pztRsRefreshStage = PZT_RS_REFRESH_IDLE;
  pztRsDiscardRemaining = 0;
  pztRsLastRefreshMs = 0;
}

// Print aggregated stream diagnostics to aid transport tuning.
static void pzt_logStreamSummary() {
  uint32_t totalBlocks = pztBlocksFromDrdy + pztBlocksFromFallback;
  uint32_t elapsedMs = millis() - pztRunStartMs;

  uint32_t drdyPct = 0;
  uint32_t fallbackPct = 0;
  if (totalBlocks > 0) {
    drdyPct = (uint32_t)((100UL * pztBlocksFromDrdy) / totalBlocks);
    fallbackPct = 100UL - drdyPct;
  }

  Serial.print(F("# INFO: PZT stream summary: elapsed_ms="));
  Serial.print(elapsedMs);
  Serial.print(F(", blocks_total="));
  Serial.print(totalBlocks);
  Serial.print(F(", drdy_blocks="));
  Serial.print(pztBlocksFromDrdy);
  Serial.print(F(" ("));
  Serial.print(drdyPct);
  Serial.print(F("%), fallback_blocks="));
  Serial.print(pztBlocksFromFallback);
  Serial.print(F(" ("));
  Serial.print(fallbackPct);
  Serial.print(F("%), drdy_reads="));
  Serial.print(pztDrdyReadAttempts);
  Serial.print(F(", drdy_timeouts="));
  Serial.print(pztDrdyReadTimeouts);
  Serial.print(F(", fallback_polls="));
  Serial.print(pztFallbackPollAttempts);
  Serial.print(F(", fallback_timeouts="));
  Serial.print(pztFallbackPollTimeouts);
  Serial.print(F(", drdy_acks="));
  Serial.print(pztAcksFromDrdy);
  Serial.print(F(", fallback_acks="));
  Serial.print(pztAcksFromFallback);
  Serial.print(F(", transient_rx_errors="));
  Serial.print(pztTransientRxErrorsTotal);
  Serial.print(F(", capture_sequence_errors="));
  Serial.println(pzr_cap.sequenceErrors);

  if (currentMode == MODE_PZT_RS) {
    for (uint8_t i = 0; i < pzt.rsRefreshChannelCount; ++i) {
      uint8_t ch = pzt.rsRefreshChannels[i] & 0x0F;
      pzr_printChannelTimingDiagnostics(ch, F("# INFO: RS timing "));
      pzt_printRsRefreshDiagnostics(ch, F("# INFO: RS refresh "));
    }
  }
}

// Track an RX error burst and report when it crosses the abort threshold.
static bool pzt_recordRxError(const __FlashStringHelper *reason) {
  (void)reason;
  pztConsecutiveRxErrors++;
  pztTransientRxErrorsTotal++;
  return pztConsecutiveRxErrors >= 4;
}

// Clear consecutive RX error streak after a successful frame.
static inline void pzt_clearRxErrors() {
  pztConsecutiveRxErrors = 0;
}

static void pzt_rsSnapshotHeldValues(uint16_t *dst, uint8_t count = 16) {
  if (!dst) return;
  if (count > 16) count = 16;
  noInterrupts();
  for (uint8_t i = 0; i < count; ++i) dst[i] = pztRsLastRaQByChannel[i];
  interrupts();
}

// Parse one received streaming frame (ACK or block) and update shared state.
// Returns true only when a data block was queued successfully.
static bool pzt_handleStreamingFrame(PZTQueuedBlock *slot, bool fromDrdy) {
  pztStreamLastActivity = millis();
  pzt_clearRxErrors();

  if (slot->data[0] == PZT_ACK_MAGIC) {
    if (!pzt_isValidAckFrame(slot->data)) {
      const __FlashStringHelper *reason = fromDrdy ? F("drdy-bad-ack") : F("fallback-bad-ack");
      if (pzt_recordRxError(reason)) {
        pztStreamFault = true;
        pzt.running = false;
      }
      return false;
    }

    if (pztWaitingFinalAck) pztWaitingFinalAck = false;
    if (fromDrdy) pztAcksFromDrdy++;
    else          pztAcksFromFallback++;
    pztRemoteEnded = true;
    pzt.running = false;
    return false;
  }

  if (slot->data[0] != BLOCK_MAGIC1 || slot->data[1] != BLOCK_MAGIC2) {
    const __FlashStringHelper *reason = fromDrdy ? F("drdy-bad-magic") : F("fallback-bad-magic");
    if (pzt_recordRxError(reason)) {
      pztStreamFault = true;
      pzt.running = false;
    }
    return false;
  }

  uint32_t queuedLen = pztStreamBlockBytes;
  if (currentMode == MODE_PZT_RS) {
    uint16_t rsHeldSnapshot[16];
    pzt_rsServiceRefresh(false);
    pzt_rsSnapshotHeldValues(rsHeldSnapshot);
    if (!pzt_buildCombinedBlock(
            slot->data, pztStreamBlockBytes, pztRsBlockBuf, queuedLen, rsHeldSnapshot)) {
      pztStreamFault = true;
      pzt.running = false;
      return false;
    }
    memcpy(slot->data, pztRsBlockBuf, queuedLen);
  }

  pzt_queueCommitWrite(queuedLen);
  if (fromDrdy) pztBlocksFromDrdy++;
  else          pztBlocksFromFallback++;
  return true;
}

// Fallback path: if DRDY signaling is missing, poll one SPI response to keep
// streaming alive (compatible with the pre-DRDY behavior).
static void pzt_serviceSpiRxFallbackPoll() {
  if (pzt_queueIsFull()) return;

  pztFallbackPollAttempts++;

  if (pztWaitingFinalAck) {
    uint8_t ack[PZT_ACK_FRAME_LEN] = {0};
    pzt_spiRecv(ack, PZT_ACK_FRAME_LEN);
    pztStreamLastActivity = millis();
    pztWaitingFinalAck = false;
    pzt.running = false;
    if (!(ack[0] == PZT_ACK_MAGIC && ack[1] == PZT_ACK_STATUS_OK)) {
      if (pzt_recordRxError(F("final-ack"))) {
        pztStreamFault = true;
      }
    } else {
      pztAcksFromFallback++;
      pzt_clearRxErrors();
    }
    return;
  }

  PZTQueuedBlock *slot = pzt_queueWriteSlot();
  if (!slot) return;

  uint8_t controlByte = PZT_STREAM_CONTINUE;
  if (pztStopRequested && !pztStopControlSent) {
    controlByte = PZT_CMD_STOP;
    pztStopControlSent = true;
    pztWaitingFinalAck = true;
    pzt.running = false;
  }

  if (!pzt_spiRecvStreamingResponse(slot->data,
                                    (uint16_t)min(pztStreamBlockBytes, (uint32_t)sizeof(slot->data)),
                                    controlByte,
                                    1)) {
    pztFallbackPollTimeouts++;
    if (pzt_recordRxError(F("fallback-timeout"))) {
      pztStreamFault = true;
      pzt.running = false;
    }
    return;
  }

  (void)pzt_handleStreamingFrame(slot, false);
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

// Emit a queued block either as binary payload or human-readable debug text.
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

// Move queued SPI blocks to USB serial without stalling SPI servicing.
static void pzt_serviceUsbTx() {
  if (PZT_DEBUG_TEXT_STREAM) {
    PZTQueuedBlock *blk = pzt_queueFront();
    if (!blk) return;
    pzt_emitBlock(blk->data, blk->len);
    pzt_queuePopFront();
    return;
  }

  PZTQueuedBlock *blk = pzt_queueFront();
  if (!blk) return;

  int avail = Serial.availableForWrite();
  if (avail <= 0) return;

  uint32_t remaining = blk->len - blk->txOffset;
  uint32_t chunk = min((uint32_t)avail, remaining);
  blk->txOffset += (uint32_t)Serial.write(blk->data + blk->txOffset, chunk);
  if (blk->txOffset >= blk->len) {
    pzt_queuePopFront();
  }
}

// Detect an inline stop* command while the blocking PZT loop is active.
static void pzt_pollStreamStopRequest() {
  static const char STOP_CMD[] = "stop*";
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == STOP_CMD[pztStopMatchPos]) {
      pztStopMatchPos++;
      if (pztStopMatchPos >= (sizeof(STOP_CMD) - 1)) {
        if (!pztStopRequested) {
          pztStopRequested = true;
          // The blocking run loop consumes stop* directly, so send #OK here
          // to satisfy host-side stop acknowledgment expectations.
          Serial.println(F("#OK"));
        }
        pztStopMatchPos = 0;
      }
    } else {
      // Allow overlapping matches (e.g. "sstop*")
      pztStopMatchPos = (c == STOP_CMD[0]) ? 1 : 0;
    }

  }
}

// Service all pending DRDY responses and enqueue valid blocks/ACKs.
static void pzt_serviceSpiRx() {
  while (pzt_drdyPending()) {

    if (pztWaitingFinalAck) {
      uint8_t ack[PZT_ACK_FRAME_LEN] = {0};
      pzt_drdyConsumeOne();
      pzt_spiRecv(ack, PZT_ACK_FRAME_LEN);
      pztStreamLastActivity = millis();
      pztWaitingFinalAck = false;
      pzt.running = false;
      if (!(ack[0] == PZT_ACK_MAGIC && ack[1] == PZT_ACK_STATUS_OK)) {
        pztStreamFault = true;
      }
      return;
    }

    if (pzt_queueIsFull()) return;

    PZTQueuedBlock *slot = pzt_queueWriteSlot();
    if (!slot) return;

    uint8_t controlByte = PZT_STREAM_CONTINUE;
    if (pztStopRequested && !pztStopControlSent) {
      controlByte = PZT_CMD_STOP;
      pztStopControlSent = true;
      pztWaitingFinalAck = true;
      pzt.running = false;
    }

    pzt_drdyConsumeOne();
    pztDrdyReadAttempts++;
    if (!pzt_spiRecvStreamingResponse(slot->data,
                                      (uint16_t)min(pztStreamBlockBytes, (uint32_t)sizeof(slot->data)),
                                      controlByte,
                                      1)) {
      pztDrdyReadTimeouts++;
      if (pzt_recordRxError(F("drdy-timeout"))) {
        pztStreamFault = true;
        pzt.running = false;
      }
      return;
    }

    if (!pzt_handleStreamingFrame(slot, true)) return;

    // After CMD_STOP has been issued, the next DRDY should be the final ACK.
    if (pztStopControlSent) return;
  }
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
// Command arguments are packed into a fixed 20-byte protocol frame.
static void pzt_sendCmd(uint8_t cmd, const uint8_t *args = nullptr, uint8_t nargs = 0) {
  uint8_t frame[PZT_CMD_FRAME_LEN];
  memset(frame, 0, PZT_CMD_FRAME_LEN);
  frame[0] = cmd;
  frame[1] = nargs;
  if (args && nargs > 0) {
    uint8_t n = min(nargs, (uint8_t)(PZT_CMD_FRAME_LEN - 2));
    memcpy(frame + 2, args, n);
  }
  pzt_drdyClearAll();
  pzt_spiSend(frame, PZT_CMD_FRAME_LEN);
}

// Send one command and wait for a protocol-level ACK status.
static bool pzt_sendCmdAck(uint8_t cmd,
                           const uint8_t *args = nullptr,
                           uint8_t nargs = 0) {
  pzt_sendCmd(cmd, args, nargs);
  uint8_t ack[PZT_ACK_FRAME_LEN] = {0};
  if (!pzt_recvAckWhenReady(ack, PZT_DRDY_ACK_TIMEOUT_MS)) return false;
  return (ack[0] == PZT_ACK_MAGIC && ack[1] == PZT_ACK_STATUS_OK);
}

// ── PZT timing helpers ────────────────────────────────────────────────
// Estimate per-pair acquisition time from current OSR and settle settings.
static uint32_t pzt_usPerPair() {
  uint32_t conv = (pzt.osr == 8) ? PZT_IADC_CONV_US_OSR8 :
                  (pzt.osr == 4) ? PZT_IADC_CONV_US_OSR4 : PZT_IADC_CONV_US_OSR2;
  return PZT_MUX_SETTLE_US + conv * 2u;
}

// Return MG24 entries per sweep, including optional ground measurements.
static uint32_t pzt_entriesPerSweep() {
  uint32_t entries = (uint32_t)pzt_physicalChannelCount() * pzt.repeatCount;

  // MG24 inserts one ground conversion before each new channel when enabled.
  if (pzt.groundEnable) {
    entries += (uint32_t)pzt_physicalChannelCount();
  }

  return entries;
}

// Estimate expected block cadence used for timeout and fallback control.
static uint32_t pzt_blockDelayMs() {
  uint32_t entries = pzt_entriesPerSweep() * pzt.sweepsPerBlock;
  return (entries * pzt_usPerPair()) / 1000u + PZT_BLOCK_DELAY_MARGIN_MS;
}

// Estimate warmup duration before first block is expected from MG24.
static uint32_t pzt_warmupDelayMs() {
  uint32_t entries = (uint32_t)PZT_WARMUP_SWEEPS * pzt_entriesPerSweep();
  return (entries * pzt_usPerPair()) / 1000u + PZT_WARMUP_DELAY_MARGIN_MS;
}

static uint32_t pzt_firstBlockTimeoutMs() {
  uint32_t timeoutMs = pzt_warmupDelayMs() + pzt_blockDelayMs() + PZT_DRDY_MARGIN_MS;
  if (currentMode == MODE_PZT_RS) {
    timeoutMs = max(timeoutMs, PZT_RS_FIRST_BLOCK_MIN_TIMEOUT_MS);
  }
  return timeoutMs;
}

// Compute raw PZT block size in bytes for the current channel configuration.
static uint32_t pzt_blockResponseBytes() {
  // ×2: each channel slot yields MUX1 + MUX2 samples
  uint32_t samples = (uint32_t)pzt_physicalChannelCount() * pzt.repeatCount
                   * pzt.sweepsPerBlock * 2u;
  return (uint32_t)PZT_ACK_FRAME_LEN + samples * 2u + PZT_BLOCK_TRAILER_LEN;
}

// Compute the host-facing packet size after PZT_RS sensor repacking.
static uint32_t pzt_rsOutputSamplesPerBlock() {
  return (uint32_t)pzt.sensorCount * (uint32_t)pzt.repeatCount *
         (uint32_t)pzt.sweepsPerBlock * (uint32_t)PZT_RS_OUTPUTS_PER_SENSOR;
}

// Validate whether a 4-byte frame is a legal ACK from MG24.
static bool pzt_isValidAckFrame(const uint8_t *buf) {
  return buf[0] == PZT_ACK_MAGIC &&
         (buf[1] == PZT_ACK_STATUS_OK || buf[1] == 0x01);
}

// =====================================================================
// ── PZR ISR & LOW-LEVEL HELPERS ──────────────────────────────────────
// =====================================================================

// Capture 555 high/low timing edges into shared ISR state.
void pzr_isr555() {
  // ARM_DWT_CYCCNT is the Teensy CPU-cycle counter. This is not micros()/millis().
  const uint32_t cycNow    = ARM_DWT_CYCCNT; // get current DWT CPU-cycle timer
  const bool     levelHigh = digitalReadFast(TIMER555_ICP_PIN);
  const uint8_t  activeRsCh = pztRsActiveChannel;
  const bool     trackRsCh = (currentMode == MODE_PZT_RS && activeRsCh < 16);
  const uint8_t  prevEdge = pzr_cap.lastEdge;
  const bool     sawRepeatedEdge =
      (prevEdge != PZR_EDGE_NONE) &&
      ((levelHigh && prevEdge == PZR_EDGE_RISE) || (!levelHigh && prevEdge == PZR_EDGE_FALL));

  pztRsIsrFires++;

  if (levelHigh) { // Raising edge, start of charge cycle, end of discharge cycle
    if (trackRsCh) pztRsRiseEdgesByChannel[activeRsCh]++;
    // Once a new cycle starts, discard any previously completed pair that has
    // not been consumed yet so we never mix an old high-time with a new low-time.
    if (pzr_cap.pairReady) {
      pzr_cap.highCycles = 0;
      pzr_cap.lowCycles = 0;
      pzr_cap.pairReady = false;
    }

    if (prevEdge == PZR_EDGE_FALL && pzr_cap.lastFallCycles != 0) {
      pzr_cap.lowCycles = cycNow - pzr_cap.lastFallCycles;
    } else {
      pzr_cap.lowCycles = 0;
      pzr_cap.pairReady = false;
      if (sawRepeatedEdge) pzr_cap.sequenceErrors++;
    }
    pzr_cap.lastRiseCycles = cycNow;
    pzr_cap.lastEdge = PZR_EDGE_RISE;
  } else { // Falling edge, start of discharge cycle, end of charge cycle
    if (trackRsCh) pztRsFallEdgesByChannel[activeRsCh]++;
    if (prevEdge == PZR_EDGE_RISE && pzr_cap.lastRiseCycles != 0) {
      pzr_cap.highCycles = cycNow - pzr_cap.lastRiseCycles;
    } else {
      pzr_cap.highCycles = 0;
      pzr_cap.pairReady = false;
      if (sawRepeatedEdge) pzr_cap.sequenceErrors++;
    }
    pzr_cap.lastFallCycles = cycNow;
    pzr_cap.lastEdge = PZR_EDGE_FALL;
    if (pzr_cap.highCycles && pzr_cap.lowCycles) {
      if (trackRsCh) {
        pztRsPairsReadyByChannel[activeRsCh]++;
        pztRsLastPairHCycByChannel[activeRsCh] = pzr_cap.highCycles;
        pztRsLastPairLCycByChannel[activeRsCh] = pzr_cap.lowCycles;
      }
      pzr_cap.pairReady = true;
    }
  }
}

// Clear captured pulse timing so the next channel starts from a clean state.
static inline void pzr_resetCaptureState() {
  noInterrupts();
  pzr_cap.lastRiseCycles = 0;
  pzr_cap.lastFallCycles = 0;
  pzr_cap.highCycles     = 0;
  pzr_cap.lowCycles      = 0;
  pzr_cap.lastEdge       = PZR_EDGE_NONE;
  pzr_cap.pairReady      = false;
  interrupts();
}

static inline void pzr_resetCaptureDiagnostics() {
  noInterrupts();
  pzr_cap.sequenceErrors = 0;
  interrupts();
}

// Compute a conservative wait timeout from current RC and resistance limits.
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

// Wait for one complete high+low pulse pair and copy it atomically.
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
  pzr_cap.highCycles = 0;
  pzr_cap.lowCycles = 0;
  pzr_cap.pairReady = false;
  interrupts();
  return (hCyc != 0 && lCyc != 0);
}

// Non-blocking variant used by PZT_RS so Rosette refresh never paces PZT blocks.
static bool pzr_takeReadyPair(uint32_t &hCyc, uint32_t &lCyc) {
  if (!pzr_cap.pairReady) return false;
  noInterrupts();
  hCyc = pzr_cap.highCycles;
  lCyc = pzr_cap.lowCycles;
  pzr_cap.highCycles = 0;
  pzr_cap.lowCycles = 0;
  pzr_cap.pairReady = false;
  interrupts();
  return (hCyc != 0 && lCyc != 0);
}

// Update a fixed-size moving average buffer and return the new mean.
static inline float pzr_updateMA(float *buf, float &sum, int &idx,
                                  int &count, int N, float val) {
  sum -= buf[idx];
  buf[idx] = val;
  sum += val;
  idx = (idx + 1) % N;
  if (count < N) count++;
  return sum / count;
}

static inline float pzr_median3(float a, float b, float c) {
  if (a > b) { float t = a; a = b; b = t; }
  if (b > c) { float t = b; b = c; c = t; }
  if (a > b) { float t = a; a = b; b = t; }
  return b;
}

static inline float pzr_updateMedian3(float *buf, int &idx, int &count, float val) {
  buf[idx] = val;
  idx = (idx + 1) % PZR_RA_MEDIAN_N;
  if (count < PZR_RA_MEDIAN_N) count++;
  if (count < PZR_RA_MEDIAN_N) return val;
  return pzr_median3(buf[0], buf[1], buf[2]);
}

static float pzt_rsMedianN(const float *buf, uint8_t count) {
  if (!buf || count == 0) return 0.0f;
  float sorted[PZT_RS_HELD_MEDIAN_N];
  for (uint8_t i = 0; i < count && i < PZT_RS_HELD_MEDIAN_N; ++i) sorted[i] = buf[i];
  for (uint8_t i = 1; i < count && i < PZT_RS_HELD_MEDIAN_N; ++i) {
    float v = sorted[i];
    int8_t j = (int8_t)i - 1;
    while (j >= 0 && sorted[j] > v) {
      sorted[j + 1] = sorted[j];
      --j;
    }
    sorted[j + 1] = v;
  }
  return sorted[count / 2u];
}

static float pzt_rsUpdateHeldMedian(uint8_t ch, float ra) {
  if (ch > 15) return ra;
  uint8_t &idx = pztRsHoldMedianIdxByChannel[ch];
  uint8_t &count = pztRsHoldMedianCountByChannel[ch];
  float *buf = pztRsHoldMedianBufByChannel[ch];
  buf[idx] = ra;
  idx = (uint8_t)((idx + 1u) % PZT_RS_HELD_MEDIAN_N);
  if (count < PZT_RS_HELD_MEDIAN_N) count++;
  if (count < PZT_RS_HELD_MEDIAN_N) return ra;
  return pzt_rsMedianN(buf, count);
}

static inline double pzr_cyclesToUs(uint32_t cycles) {
  return ((double)cycles * 1000000.0) / (double)F_CPU_ACTUAL;
}

static inline double pzr_cyclesFloatToUs(double cycles) {
  return (cycles * 1000000.0) / (double)F_CPU_ACTUAL;
}

// Model the theoretical 555 discharge interval from board-component values.
static float pzr_computeModeledLowCycles() {
  const double rb = (double)pzr_RB_OHM;
  const double cf = (double)pzr_CF_F;
  if (!(rb > 0.0) || !(cf > 0.0)) return NAN;

  const double modeledCycles = (double)LN2 * cf * rb * (double)F_CPU_ACTUAL;
  return (isfinite(modeledCycles) && modeledCycles > 0.0)
             ? (float)modeledCycles
             : NAN;
}

static void pzr_refreshModeledLowCycles() {
  pzr_lCycModelCycles = pzr_computeModeledLowCycles();
}

static const __FlashStringHelper *pzr_raLowCycleSourceLabel() {
  return (PZR_RA_LCYC_SOURCE == PZR_LCYC_SOURCE_MODELED)
             ? F("modeled_lcyc_from_rb_cf")
             : F("measured_lcyc");
}

static void pzr_printChannelTimingDiagnostics(uint8_t ch, const __FlashStringHelper *prefix) {
  if (ch > 15) return;

  const PZR_ChannelState &state = pzr_chState[ch];
  Serial.print(prefix);
  Serial.print(F("ch"));
  Serial.print((int)ch);
  Serial.print(F(": "));

  if (state.lastHCyc == 0 || state.lastLCyc == 0) {
    Serial.println(F("no completed pair yet"));
    return;
  }

  const double rb = (double)pzr_RB_OHM;
  const double cf = (double)pzr_CF_F;
  const double hUs = pzr_cyclesToUs(state.lastHCyc);
  const double lUs = pzr_cyclesToUs(state.lastLCyc);
  const double lAvgUs =
      (isfinite(state.lastLCycAvgUsed) && state.lastLCycAvgUsed > 0.0f)
          ? pzr_cyclesFloatToUs((double)state.lastLCycAvgUsed)
          : NAN;
  const double lModelUs =
      (isfinite(state.lastLCycModelUsed) && state.lastLCycModelUsed > 0.0f)
          ? pzr_cyclesFloatToUs((double)state.lastLCycModelUsed)
          : NAN;
  const double modelLUs = (double)LN2 * cf * rb * 1000000.0;
  const double modelHUs =
      isfinite(state.lastPlotRa) ? ((double)LN2 * cf * ((double)state.lastPlotRa + rb) * 1000000.0) : NAN;
  const double raFromRaw =
      (isfinite(state.lastLCycAvgUsed) && state.lastLCycAvgUsed > 0.0f)
          ? (rb * (((double)state.lastHCyc - (double)state.lastLCycAvgUsed) / (double)state.lastLCycAvgUsed))
          : NAN;

  Serial.print(F("hCyc=")); Serial.print(state.lastHCyc);
  Serial.print(F(", lCyc=")); Serial.print(state.lastLCyc);
  Serial.print(F(", lCycAvg="));
  if (isfinite(state.lastLCycAvgUsed)) Serial.print(state.lastLCycAvgUsed, 3);
  else                                 Serial.print(F("nan"));
  Serial.print(F(", lCycModel="));
  if (isfinite(state.lastLCycModelUsed)) Serial.print(state.lastLCycModelUsed, 3);
  else                                   Serial.print(F("nan"));
  Serial.print(F(", h_us=")); Serial.print(hUs, 3);
  Serial.print(F(", l_us=")); Serial.print(lUs, 3);
  Serial.print(F(", l_avg_us="));
  if (isfinite(lAvgUs)) Serial.print(lAvgUs, 3);
  else                  Serial.print(F("nan"));
  Serial.print(F(", l_model_us="));
  if (isfinite(lModelUs)) Serial.print(lModelUs, 3);
  else                    Serial.print(F("nan"));
  Serial.print(F(", ra_ohm="));
  if (isfinite(state.lastPlotRa)) Serial.print(state.lastPlotRa, 3);
  else                            Serial.print(F("nan"));
  Serial.print(F(", ra_from_raw_ohm="));
  if (isfinite(raFromRaw)) Serial.print(raFromRaw, 3);
  else                     Serial.print(F("nan"));
  Serial.print(F(", model_h_us="));
  if (isfinite(modelHUs)) Serial.print(modelHUs, 3);
  else                    Serial.print(F("nan"));
  Serial.print(F(", model_l_us=")); Serial.print(modelLUs, 3);
  Serial.println();
}

static void pzt_printRsRefreshDiagnostics(uint8_t ch, const __FlashStringHelper *prefix) {
  if (ch > 15) return;

  const uint32_t riseEdges = pztRsRiseEdgesByChannel[ch];
  const uint32_t fallEdges = pztRsFallEdgesByChannel[ch];
  const uint32_t pairsReady = pztRsPairsReadyByChannel[ch];
  const uint32_t discardPairs = pztRsDiscardPairsByChannel[ch];
  const uint32_t timeouts = pztRsTimeoutsByChannel[ch];
  const uint32_t updates = pztRsUpdateCountByChannel[ch];
  const uint32_t lastHCyc = pztRsLastPairHCycByChannel[ch];
  const uint32_t lastLCyc = pztRsLastPairLCycByChannel[ch];

  Serial.print(prefix);
  Serial.print(F("ch"));
  Serial.print((int)ch);
  Serial.print(F(": rise_edges="));
  Serial.print(riseEdges);
  Serial.print(F(", fall_edges="));
  Serial.print(fallEdges);
  Serial.print(F(", pairs_ready="));
  Serial.print(pairsReady);
  Serial.print(F(", discard_pairs="));
  Serial.print(discardPairs);
  Serial.print(F(", updates="));
  Serial.print(updates);
  Serial.print(F(", timeouts="));
  Serial.print(timeouts);
  Serial.print(F(", last_pair_h_us="));
  if (lastHCyc > 0) Serial.print(pzr_cyclesToUs(lastHCyc), 3);
  else              Serial.print(F("nan"));
  Serial.print(F(", last_pair_l_us="));
  if (lastLCyc > 0) Serial.print(pzr_cyclesToUs(lastLCyc), 3);
  else              Serial.print(F("nan"));
  Serial.print(F(", isr_fires_total="));
  Serial.println(pztRsIsrFires);
}

// Reset per-555 low-cycle moving-average accumulators.
static void pzr_resetAll555Averages() {
  for (int i = 0; i < PZR_555_COUNT; i++) pzr_lowCycleSmootherBy555[i].reset();
}

// Reset all per-channel and per-555 smoothing state.
static void pzr_resetAllChannels() {
  for (int i = 0; i < 16; i++) pzr_chState[i].reset();
  pzr_resetAll555Averages();
}

// Force both 555 mux enable lines low.
static inline void pzr_muxDisableAll() {
  if (PZR_MUX_EN_PIN >= 0) digitalWriteFast(PZR_MUX_EN_PIN, LOW);
  if (RS_MUX_EN_PIN >= 0) digitalWriteFast(RS_MUX_EN_PIN, LOW);
}

// Toggle the active-mode mux enable line.
static inline void pzr_muxEnable(bool en) {
  if (TIMER555_MUX_EN_PIN >= 0) {
    digitalWriteFast(TIMER555_MUX_EN_PIN, en ? HIGH : LOW);
  }
}

// Select a mux channel, apply settle delay, and clear stale capture edges.
static inline void pzr_muxSelect(uint8_t ch) {
  ch &= 0x0F;
  pzr_muxEnable(false);
  digitalWriteFast(TIMER555_MUX_A0_PIN, (ch & 0x01) ? HIGH : LOW);
  digitalWriteFast(TIMER555_MUX_A1_PIN, (ch & 0x02) ? HIGH : LOW);
  digitalWriteFast(TIMER555_MUX_A2_PIN, (ch & 0x04) ? HIGH : LOW);
  digitalWriteFast(TIMER555_MUX_A3_PIN, (ch & 0x08) ? HIGH : LOW);
  delayNanoseconds(TIMER555_MUX_SETTLE_NS);
  pzr_muxEnable(true);
  pzr_resetCaptureState();
}

static bool pzr_updateChannelRaFromPair(uint8_t ch, uint32_t hCyc, uint32_t lCyc,
                                        float &outRa) {
  if (ch > 15 || hCyc == 0 || lCyc == 0) return false;

  PZR_LowCycleSmootherState &lowCycleSmoother =
      pzr_lowCycleSmootherBy555[pzr_active555Index()];
  const float lCycAvgMeasured = lowCycleSmoother.update(lCyc);
  const float lCycCalc = pzr_lCycModelCycles;
  pzr_chState[ch].lastHCyc = hCyc;
  pzr_chState[ch].lastLCyc = lCyc;
  pzr_chState[ch].lastLCycAvgUsed = lCycAvgMeasured;
  pzr_chState[ch].lastLCycModelUsed = lCycCalc;

  const float lCycForRa =
      (PZR_RA_LCYC_SOURCE == PZR_LCYC_SOURCE_MODELED) ? lCycCalc : lCycAvgMeasured;
  float last_Ra = NAN, last_RaMA = NAN;
  if (isfinite(lCycForRa) && lCycForRa > 0.0f) {
    // Astable model for this board:
    //   tH = ln(2)*C*(Ra + Rb)
    //   tL = ln(2)*C*Rb
    // Therefore Ra = Rb*(tH - tL)/tL.
    // The low-time source is selectable so we can flip between measured and
    // component-modeled behavior without rewriting the math path again.
    last_Ra = pzr_RB_OHM * (((float)hCyc - lCycForRa) / lCycForRa);

    if (isfinite(last_Ra)) {
      if (PZR_RA_MA_N > 1) {
        last_RaMA = pzr_updateMA(pzr_chState[ch].raBuf, pzr_chState[ch].raSum,
                                pzr_chState[ch].raIdx, pzr_chState[ch].raCount,
                                PZR_RA_MA_N, last_Ra);
      } else {
        // No final Ra moving average requested.
        last_RaMA = last_Ra;
      }
    }
  }

  float candidate = isfinite(last_RaMA) ? last_RaMA :
                    isfinite(last_Ra)   ? last_Ra   : NAN;
  if (isfinite(candidate)) {
    candidate = pzr_updateMedian3(
        pzr_chState[ch].raMedianBuf,
        pzr_chState[ch].raMedianIdx,
        pzr_chState[ch].raMedianCount,
        candidate);
    pzr_chState[ch].lastPlotRa = candidate;
  }

  outRa = isfinite(pzr_chState[ch].lastPlotRa) ? pzr_chState[ch].lastPlotRa : 0.0f;
  return true;
}

// Measure one Ra=(Rx+Rk) value on the given channel.
// switched=true triggers a MUX switch + discard cycles first.
static bool pzr_measureOneRa(uint8_t ch, bool switched, float &outRa) {
  const uint32_t timeoutMs = pzr_computePairTimeoutMs();
  const uint32_t measureStartMs = millis();

  if (switched) {
    pzr_muxSelect(ch);
    for (int d = 0; d < PZR_DISCARD_CYCLES_AFTER_SWITCH; d++) {
      uint32_t h, l;
      uint32_t elapsedMs = millis() - measureStartMs;
      if (elapsedMs >= timeoutMs) return false;
      if (!pzr_waitForPair(h, l, timeoutMs - elapsedMs)) return false;
    }
  }

  uint32_t elapsedMs = millis() - measureStartMs;
  if (elapsedMs >= timeoutMs) return false;

  uint32_t hCyc = 0, lCyc = 0;
  if (!pzr_waitForPair(hCyc, lCyc, timeoutMs - elapsedMs)) return false;
  return pzr_updateChannelRaFromPair(ch, hCyc, lCyc, outRa);
}

// Quantize resistance to uint16 deci-ohms for mixed PZT_RS payloads.
// This preserves the existing uint16 payload width while exposing 0.1-ohm steps.
static inline uint16_t pzt_rsQuantizeOhms(float ra) {
  long v = lroundf(ra * 10.0f);
  if (v < 0) v = 0;
  if (v > 65535L) v = 65535L;
  return (uint16_t)v;
}

// Seed held RS values from latest channel estimates before PZT_RS run starts.
static void pzt_rsResetState() {
  for (int ch = 0; ch < 16; ++ch) {
    float ra = isfinite(pzr_chState[ch].lastPlotRa) ? pzr_chState[ch].lastPlotRa : 0.0f;
    pztRsLastRaQByChannel[ch] = pzt_rsQuantizeOhms(ra);
    for (uint8_t i = 0; i < PZT_RS_HELD_MEDIAN_N; ++i) {
      pztRsHoldMedianBufByChannel[ch][i] = ra;
    }
    pztRsHoldMedianIdxByChannel[ch] = 0;
    pztRsHoldMedianCountByChannel[ch] = isfinite(ra) ? PZT_RS_HELD_MEDIAN_N : 0;
    pztRsUpdateCountByChannel[ch] = 0;
    pztRsLastUpdateMsByChannel[ch] = 0;
    pztRsRiseEdgesByChannel[ch] = 0;
    pztRsFallEdgesByChannel[ch] = 0;
    pztRsPairsReadyByChannel[ch] = 0;
    pztRsLastPairHCycByChannel[ch] = 0;
    pztRsLastPairLCycByChannel[ch] = 0;
    pztRsDiscardPairsByChannel[ch] = 0;
    pztRsTimeoutsByChannel[ch] = 0;
  }
  pztRsIsrFires = 0;
  pztRsActiveChannel = 0xFF;
  pztRsTotalUpdates = 0;
  pztRsMuxSwitches = 0;
  pztRsDiscardPairs = 0;
  pztRsChannelTimeouts = 0;
  pztRsChannelStartMs = 0;
  // Per-channel timeout: worst-case 555 period × discard/measure pairs + margin.
  pztRsChannelTimeoutMs =
      pzr_computePairTimeoutMs() *
      (uint32_t)(PZR_DISCARD_CYCLES_AFTER_SWITCH + PZT_RS_MEASURE_PAIRS_PER_UPDATE + 1u);
  pztRsPrevMeasuredChannel = -1;
  pztRsRefreshIndex = 0;
  pztRsLastRefreshMs = 0;
  pztRsRefreshStage = PZT_RS_REFRESH_IDLE;
  pztRsPendingChannel = 0;
  pztRsDiscardRemaining = 0;
  pztRsMeasurePairsCollected = 0;
  pzt_rsStartNextRefreshChannel(); // kick off the first channel immediately
}

// Store a completed 555 measurement into the held RS array.
static bool pzt_rsConsumeReadyPair() {
  if (pztRsRefreshStage == PZT_RS_REFRESH_IDLE) return false;

  // Timeout: if the 555 hasn't produced a pair within the worst-case period,
  // the channel is broken/disconnected. Skip it so working channels are not blocked.
  if (pztRsChannelTimeoutMs > 0 &&
      (millis() - pztRsChannelStartMs) >= pztRsChannelTimeoutMs) {
    pztRsChannelTimeouts++;
    if (pztRsPendingChannel < 16) pztRsTimeoutsByChannel[pztRsPendingChannel]++;
    pzt_rsStartNextRefreshChannel();
    return false;
  }

  uint32_t hCyc = 0, lCyc = 0;
  if (!pzr_takeReadyPair(hCyc, lCyc)) return false;

  if (pztRsRefreshStage == PZT_RS_REFRESH_DISCARD) {
    if (pztRsDiscardRemaining > 0) pztRsDiscardRemaining--;
    pztRsDiscardPairs++;
    if (pztRsPendingChannel < 16) pztRsDiscardPairsByChannel[pztRsPendingChannel]++;
    if (pztRsDiscardRemaining == 0) pztRsRefreshStage = PZT_RS_REFRESH_MEASURE;
    return true;
  }

  if (pztRsRefreshStage == PZT_RS_REFRESH_MEASURE) {
    float ra = 0.0f;
    if (!pzr_updateChannelRaFromPair(pztRsPendingChannel, hCyc, lCyc, ra)) {
      pztRsMeasurePairsCollected = 0;
      pztRsChannelStartMs = millis();
      return true; // stay on this channel and wait for the next pair
    }

    if (PZT_RS_MEASURE_PAIRS_PER_UPDATE <= 1) {
      const float heldRa = pzt_rsUpdateHeldMedian(pztRsPendingChannel, ra);
      pztRsLastRaQByChannel[pztRsPendingChannel] = pzt_rsQuantizeOhms(heldRa);
      pztRsUpdateCountByChannel[pztRsPendingChannel]++;
      pztRsLastUpdateMsByChannel[pztRsPendingChannel] = millis();
      pztRsTotalUpdates++;
      pztRsPrevMeasuredChannel = (int8_t)pztRsPendingChannel;
      pztRsLastRefreshMs = millis();
      pzt_rsStartNextRefreshChannel(); // 555 immediately starts measuring next channel
      return true;
    }

    if (pztRsMeasurePairsCollected < PZT_RS_MEASURE_PAIRS_PER_UPDATE) {
      pztRsMeasureRaBuf[pztRsMeasurePairsCollected++] = ra;
    }

    if (pztRsMeasurePairsCollected < PZT_RS_MEASURE_PAIRS_PER_UPDATE) {
      pztRsChannelStartMs = millis();
      return true; // keep collecting consecutive pairs on this same channel
    }

    float acceptedRa = ra;
    if (PZT_RS_MEASURE_PAIRS_PER_UPDATE == 3) {
      acceptedRa = pzr_median3(
          pztRsMeasureRaBuf[0], pztRsMeasureRaBuf[1], pztRsMeasureRaBuf[2]);
    }

    const float heldRa = pzt_rsUpdateHeldMedian(pztRsPendingChannel, acceptedRa);
    pztRsLastRaQByChannel[pztRsPendingChannel] = pzt_rsQuantizeOhms(heldRa);
    pztRsUpdateCountByChannel[pztRsPendingChannel]++;
    pztRsLastUpdateMsByChannel[pztRsPendingChannel] = millis();
    pztRsTotalUpdates++;
    pztRsPrevMeasuredChannel = (int8_t)pztRsPendingChannel;
    pztRsLastRefreshMs = millis();
    pztRsMeasurePairsCollected = 0;
    pzt_rsStartNextRefreshChannel(); // 555 immediately starts measuring next channel
    return true;
  }

  return false;
}

// Select the next RS MUX channel to refresh. The actual value is stored only
// after a later 555 pair-ready event, so this never blocks on the oscillator.
static void pzt_rsStartNextRefreshChannel() {
  if (pzt.rsRefreshChannelCount == 0) return;

  uint32_t nowMs = millis();
  if (pztRsLastRefreshMs != 0 && (nowMs - pztRsLastRefreshMs) < PZT_RS_REFRESH_MIN_MS) {
    return;
  }

  pztRsPendingChannel = pzt.rsRefreshChannels[pztRsRefreshIndex % pzt.rsRefreshChannelCount] & 0x0F;
  pztRsRefreshIndex =
      (uint8_t)((pztRsRefreshIndex + 1u) % max((uint8_t)1, pzt.rsRefreshChannelCount));
  pztRsActiveChannel = pztRsPendingChannel;
  pztRsMeasurePairsCollected = 0;

  if (pztRsPrevMeasuredChannel != (int8_t)pztRsPendingChannel) {
    pzr_muxSelect(pztRsPendingChannel);
    pztRsMuxSwitches++;
    pztRsDiscardRemaining = PZR_DISCARD_CYCLES_AFTER_SWITCH;
    pztRsRefreshStage =
        (pztRsDiscardRemaining > 0) ? PZT_RS_REFRESH_DISCARD : PZT_RS_REFRESH_MEASURE;
  } else {
    pztRsDiscardRemaining = 0;
    pztRsRefreshStage = PZT_RS_REFRESH_MEASURE;
  }
  pztRsChannelStartMs = millis();
}

// Advance Rosette refresh without blocking the PZT/MG24 stream.
// The next channel starts automatically inside pzt_rsConsumeReadyPair after each
// measurement, so the 555 is always measuring and no explicit IDLE→start call is needed.
static void pzt_rsServiceRefresh(bool allowChannelSwitch) {
  (void)allowChannelSwitch; // kept for call-site compatibility; no longer used
  if (pzt.rsRefreshChannelCount == 0) return;
  (void)pzt_rsConsumeReadyPair();
}

// Expand one PZT block into PZT_RS layout by inserting held RS pairs per PZT pair.
static bool pzt_buildCombinedBlock(const uint8_t *src, uint32_t srcLen,
                                   uint8_t *dst, uint32_t &dstLen,
                                   const uint16_t *heldRaQSnapshot) {
  if (!src || !dst) return false;
  if (srcLen < (uint32_t)PZT_ACK_FRAME_LEN + PZT_BLOCK_TRAILER_LEN) return false;
  if (src[0] != BLOCK_MAGIC1 || src[1] != BLOCK_MAGIC2) return false;
  if (!heldRaQSnapshot) return false;

  uint16_t pztSampleCount = (uint16_t)src[2] | ((uint16_t)src[3] << 8);
  uint32_t payloadBytes = (uint32_t)pztSampleCount * 2u;
  uint32_t expectedLen = (uint32_t)PZT_ACK_FRAME_LEN + payloadBytes + PZT_BLOCK_TRAILER_LEN;
  if (srcLen < expectedLen) return false;
  if ((pztSampleCount & 0x01u) != 0u) return false; // PZT samples are MUX1/MUX2 pairs.

  uint16_t physicalPairCount = pztSampleCount / 2u;
  uint8_t physicalCount = pzt_physicalChannelCount();
  if (physicalCount == 0 || pzt.channelCount == 0 || pzt.sensorCount == 0) return false;
  if ((pzt.channelCount % PZT_CHANNELS_PER_SENSOR) != 0) return false;

  uint32_t physicalPairsPerSweep = (uint32_t)physicalCount * (uint32_t)pzt.repeatCount;
  if (physicalPairsPerSweep == 0 || (physicalPairCount % physicalPairsPerSweep) != 0) return false;
  uint32_t sweepsInBlock = physicalPairCount / physicalPairsPerSweep;

  uint32_t combinedCount32 =
      sweepsInBlock * (uint32_t)pzt.sensorCount *
      (uint32_t)pzt.repeatCount * (uint32_t)PZT_RS_OUTPUTS_PER_SENSOR;
  if (combinedCount32 > 65535u) return false;
  uint16_t combinedCount = (uint16_t)combinedCount32;

  uint32_t combinedPayloadBytes = (uint32_t)combinedCount * 2u;
  uint32_t combinedLen = (uint32_t)PZT_ACK_FRAME_LEN + combinedPayloadBytes + PZT_BLOCK_TRAILER_LEN;
  if (combinedLen > PZT_RS_MAX_BLOCK_BYTES) return false;

  dst[0] = BLOCK_MAGIC1;
  dst[1] = BLOCK_MAGIC2;
  dst[2] = (uint8_t)(combinedCount & 0xFF);
  dst[3] = (uint8_t)(combinedCount >> 8);

  uint32_t dstPayloadPos = PZT_ACK_FRAME_LEN;
  for (uint32_t sweep = 0; sweep < sweepsInBlock; ++sweep) {
    for (uint8_t sensor = 0; sensor < pzt.sensorCount; ++sensor) {
      uint8_t muxIndex = (pzt.sensorMux[sensor] == 2) ? 1u : 0u;

      for (uint8_t repeatIdx = 0; repeatIdx < pzt.repeatCount; ++repeatIdx) {
        for (uint8_t localCh = 0; localCh < PZT_CHANNELS_PER_SENSOR; ++localCh) {
          uint8_t logicalSlot = (uint8_t)(sensor * PZT_CHANNELS_PER_SENSOR + localCh);
          int8_t physicalIdx = pzt_physicalIndexForChannel(pzt.channels[logicalSlot]);
          if (physicalIdx < 0) return false;

          uint32_t physicalPair =
              sweep * physicalPairsPerSweep +
              (uint32_t)physicalIdx * (uint32_t)pzt.repeatCount +
              (uint32_t)repeatIdx;
          uint32_t srcPayloadPos =
              (uint32_t)PZT_ACK_FRAME_LEN + physicalPair * 4u + (uint32_t)muxIndex * 2u;

          dst[dstPayloadPos++] = src[srcPayloadPos++]; // selected PZT MUX side LSB
          dst[dstPayloadPos++] = src[srcPayloadPos++]; // selected PZT MUX side MSB
        }

        uint16_t rsA = (pzt.sensorRsA[sensor] >= 0 && pzt.sensorRsA[sensor] <= 15)
                            ? heldRaQSnapshot[(uint8_t)pzt.sensorRsA[sensor]]
                            : 0;
        uint16_t rsB = (pzt.sensorRsB[sensor] >= 0 && pzt.sensorRsB[sensor] <= 15)
                            ? heldRaQSnapshot[(uint8_t)pzt.sensorRsB[sensor]]
                            : 0;
        dst[dstPayloadPos++] = (uint8_t)(rsA & 0xFF);
        dst[dstPayloadPos++] = (uint8_t)(rsA >> 8);
        dst[dstPayloadPos++] = (uint8_t)(rsB & 0xFF);
        dst[dstPayloadPos++] = (uint8_t)(rsB >> 8);
      }
    }
  }

  uint32_t srcTrailerPos = (uint32_t)PZT_ACK_FRAME_LEN + payloadBytes;
  uint32_t dstTrailerPos = (uint32_t)PZT_ACK_FRAME_LEN + combinedPayloadBytes;
  memcpy(dst + dstTrailerPos, src + srcTrailerPos, PZT_BLOCK_TRAILER_LEN);
  dstLen = combinedLen;
  return true;
}

// =====================================================================
// ── SHARED ACK & UTILITY ─────────────────────────────────────────────
// =====================================================================

// Emit protocol-level #OK/#NOT_OK response lines with optional argument echo.
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

// Parse channel list and send channel configuration to MG24.
static bool pzt_handleChannels(const String &args) {
  pzt.channelCount = 0;
  pzt.physicalChannelCount = 0;
  pzt.sensorCount = 0;
  pzt.sensorMuxCount = 0;
  pzt.rsChannelCount = 0;
  pzt.rsRefreshChannelCount = 0;
  for (uint8_t k = 0; k < PZT_MAX_SENSOR_SLOTS; ++k) {
    pzt.sensorMux[k] = 0;
    pzt.sensorRsA[k] = -1;
    pzt.sensorRsB[k] = -1;
  }
  uint8_t maxLogicalSlots = (currentMode == MODE_PZT_RS) ? PZT_MAX_LOGICAL_SLOTS : PZT_MAX_PHYSICAL_CHANNELS;
  int i = 0, len = args.length();
  while (i < len && pzt.channelCount < maxLogicalSlots) {
    while (i < len && (args[i] == ' ' || args[i] == ',')) i++;
    if (i >= len) break;
    int start = i;
    while (i < len && args[i] != ' ' && args[i] != ',') i++;
    int v = args.substring(start, i).toInt();
    if (v >= 0 && v <= (int)PZT_MUX_CH_MAX) {
      uint8_t ch = (uint8_t)v;
      int8_t existingPhysicalIndex = pzt_physicalIndexForChannel(ch);
      pzt.channels[pzt.channelCount++] = ch;
      if (existingPhysicalIndex < 0) {
        if (pzt.physicalChannelCount >= PZT_MAX_PHYSICAL_CHANNELS) return false;
        pzt.physicalChannels[pzt.physicalChannelCount++] = ch;
      }
    }
  }
  if (pzt.channelCount == 0) return false;
  if (pzt.physicalChannelCount == 0) return false;
  if (currentMode == MODE_PZT_RS) {
    if ((pzt.channelCount % PZT_CHANNELS_PER_SENSOR) != 0) return false;
    pzt.sensorCount = pzt.channelCount / PZT_CHANNELS_PER_SENSOR;
    if (pzt.sensorCount == 0 || pzt.sensorCount > PZT_MAX_SENSOR_SLOTS) return false;
  }

  uint8_t frame[PZT_CMD_FRAME_LEN];
  memset(frame, 0, PZT_CMD_FRAME_LEN);
  frame[0] = PZT_CMD_SET_CHANNELS;
  frame[1] = (uint8_t)(pzt.physicalChannelCount + 1);   // nargs = count byte + N channel bytes
  frame[2] = pzt.physicalChannelCount;
  for (uint8_t k = 0; k < pzt.physicalChannelCount && k < PZT_MAX_PHYSICAL_CHANNELS; k++)
    frame[3 + k] = pzt.physicalChannels[k];

  pzt_drdyClearAll();
  pzt_spiSend(frame, PZT_CMD_FRAME_LEN);
  uint8_t ack[PZT_ACK_FRAME_LEN] = {0};
  if (!pzt_recvAckWhenReady(ack, PZT_DRDY_ACK_TIMEOUT_MS)) return false;
  return (ack[0] == PZT_ACK_MAGIC && ack[1] == PZT_ACK_STATUS_OK);
}

// Parse MG24 MUX side used by each selected PZT sensor in PZT_RS.
static bool pzt_handlePztMuxes(const String &args) {
  if (pzt.channelCount == 0 || pzt.sensorCount == 0) return false;

  uint8_t values[PZT_MAX_SENSOR_SLOTS];
  uint8_t valueCount = 0;
  int i = 0, len = args.length();
  while (i < len && valueCount < PZT_MAX_SENSOR_SLOTS) {
    while (i < len && (args[i] == ' ' || args[i] == ',')) i++;
    if (i >= len) break;
    int start = i;
    while (i < len && args[i] != ' ' && args[i] != ',') i++;
    int v = args.substring(start, i).toInt();
    if (v < 1 || v > 2) return false;
    values[valueCount++] = (uint8_t)v;
  }

  if (valueCount != pzt.sensorCount) return false;

  pzt.sensorMuxCount = pzt.sensorCount;
  for (uint8_t slot = 0; slot < pzt.sensorMuxCount; ++slot) {
    pzt.sensorMux[slot] = values[slot];
  }

  return true;
}

// Parse RS_MUX routing used by PZT_RS. The list is flattened as two values
// per selected PZT sensor:
//   RS1,RS2
static bool pzt_handleRsChannels(const String &args) {
  if (pzt.channelCount == 0 || pzt.sensorCount == 0) return false;

  int8_t values[PZT_MAX_SENSOR_SLOTS * 2u];
  uint8_t valueCount = 0;
  int i = 0, len = args.length();
  while (i < len && valueCount < (PZT_MAX_SENSOR_SLOTS * 2u)) {
    while (i < len && (args[i] == ' ' || args[i] == ',')) i++;
    if (i >= len) break;
    int start = i;
    while (i < len && args[i] != ' ' && args[i] != ',') i++;
    int v = args.substring(start, i).toInt();
    if (v < 0 || v > 15) return false;
    values[valueCount++] = (int8_t)v;
  }

  if (valueCount != (uint8_t)(pzt.sensorCount * 2u)) return false;

  pzt.rsChannelCount = pzt.sensorCount;
  pzt.rsRefreshChannelCount = 0;
  for (uint8_t slot = 0; slot < PZT_MAX_SENSOR_SLOTS; ++slot) {
    pzt.sensorRsA[slot] = -1;
    pzt.sensorRsB[slot] = -1;
  }

  for (uint8_t slot = 0; slot < pzt.rsChannelCount; ++slot) {
    uint8_t base = (uint8_t)(slot * 2u);
    pzt.sensorRsA[slot] = values[base];
    pzt.sensorRsB[slot] = values[base + 1u];
    if (!pzt_addUniqueRsRefreshChannel(pzt.sensorRsA[slot])) return false;
    if (!pzt_addUniqueRsRefreshChannel(pzt.sensorRsB[slot])) return false;
  }

  return pzt.rsRefreshChannelCount > 0;
}

// Update repeat count and push it to MG24.
static bool pzt_handleRepeat(const String &args) {
  long v = constrain(args.toInt(), 1L, (long)PZT_MAX_REPEAT);
  pzt.repeatCount = (uint8_t)v;
  uint8_t a = pzt.repeatCount;
  return pzt_sendCmdAck(PZT_CMD_SET_REPEAT, &a, 1);
}

// Update sweeps-per-block setting and push it to MG24.
static bool pzt_handleBuffer(const String &args) {
  long v = max(1L, args.toInt());
  pzt.sweepsPerBlock = (uint8_t)min(v, 255L);
  uint8_t a = pzt.sweepsPerBlock;
  return pzt_sendCmdAck(PZT_CMD_SET_BUFFER, &a, 1);
}

// Select ADC reference source and push it to MG24.
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

// Validate and apply OSR setting in both local and MG24 state.
static bool pzt_handleOsr(const String &args) {
  long v = args.toInt();
  if (v != 2 && v != 4 && v != 8) {
    Serial.println(F("# ERROR: osr must be 2, 4, or 8")); return false;
  }
  pzt.osr = (uint8_t)v;
  uint8_t a = pzt.osr;
  return pzt_sendCmdAck(PZT_CMD_SET_OSR, &a, 1);
}

// Validate and apply gain setting in both local and MG24 state.
static bool pzt_handleGain(const String &args) {
  long v = args.toInt();
  if (v < 1 || v > 4) {
    Serial.println(F("# ERROR: gain must be 1, 2, 3, or 4")); return false;
  }
  pzt.gain = (uint8_t)v;
  uint8_t a = pzt.gain;
  return pzt_sendCmdAck(PZT_CMD_SET_GAIN, &a, 1);
}

// Configure ground measurement behavior and push mode/pin to MG24.
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

// Blocking streaming run — externally unchanged, but internally it now
// uses DRDY interrupt notification plus a RAM queue so SPI reads happen
// promptly and USB serial transmit drains in parallel.
// Start and supervise a blocking PZT/PZT_RS run until stop, timeout, or fault.
static void pzt_handleRun(const String &args) {
  if (pzt.channelCount == 0) {
    Serial.println(F("# ERROR: no channels configured"));
    hostAck(false, args); return;
  }
  if (currentMode == MODE_PZT_RS) {
    if (pzt.sensorMuxCount != pzt.sensorCount) {
      Serial.println(F("# ERROR: PZT_RS requires one PZT MUX value per selected sensor (use pztmuxes)."));
      hostAck(false, args); return;
    }
    if (pzt.rsChannelCount != pzt.sensorCount) {
      Serial.println(F("# ERROR: PZT_RS requires RS1,RS2 routing per selected PZT sensor (use rschannels)."));
      hostAck(false, args); return;
    }
    if (pzt_rsOutputSamplesPerBlock() > PZT_RS_MAX_OUTPUT_SAMPLES) {
      Serial.println(F("# ERROR: PZT_RS block too large. Reduce repeat or buffer."));
      hostAck(false, args); return;
    }
  }

  uint32_t ms    = 0;
  bool     timed = false;
  if (args.length() > 0) {
    long v = args.toInt();
    if (v > 0) { ms = (uint32_t)v; timed = true; }
  }

  pzr_resetCaptureDiagnostics();
  pzt_streamResetState();
  if (currentMode == MODE_PZT_RS) {
    pzt_rsResetState();
  }
  pztStreamBlockBytes = pzt_blockResponseBytes();

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

  // Wait for the first block to become ready and fetch it before we tell the PC
  // that streaming has started. This keeps the PC-side protocol unchanged.
  uint32_t firstBlockTimeout = pzt_firstBlockTimeoutMs();
  uint32_t waitStart = millis();

  while (pzt_queueIsEmpty()) {
    pzt_pollStreamStopRequest();
    if (currentMode == MODE_PZT_RS) {
      pzt_rsServiceRefresh(false);
    }
    pzt_serviceSpiRx();
    if (currentMode == MODE_PZT_RS) {
      pzt_rsServiceRefresh(true);
    }

    if (pztStreamFault || pztRemoteEnded) {
      pzt.running = false;
      hostAck(false, args);
      pzt_streamResetState();
      return;
    }

    if ((millis() - waitStart) >= firstBlockTimeout) {
      pzt.running = false;
      hostAck(false, args);
      pzt_streamResetState();
      return;
    }

    yield();
  }

  pzt.running = true;
  hostAck(true, args);   // #OK sent BEFORE data so Python knows streaming started
  pzt_discardPendingTerminators();

  uint32_t runStart = millis();
  pztStreamLastActivity = millis();

  // ── Streaming loop ────────────────────────────────────────────────
  while (true) {
    pzt_pollStreamStopRequest();
    if (!pztStopRequested && timed && (millis() - runStart) >= ms) {
      pztStopRequested = true;
    }

    if (currentMode == MODE_PZT_RS && !pztRemoteEnded && !pztWaitingFinalAck) {
      pzt_rsServiceRefresh(true);
    }

    // Highest priority: service SPI first so MG24 is drained as soon as DRDY rises.
    pzt_serviceSpiRx();

    // If DRDY signaling stalls, periodically poll SPI to keep streaming alive.
    if (!pztRemoteEnded &&
        !pztWaitingFinalAck &&
        !pzt_drdyPending() &&
        pzt_queueIsEmpty()) {
      uint32_t nowMs = millis();
      // Only attempt fallback after DRDY appears late beyond its expected window.
      uint32_t fallbackArmDelayMs = pzt_blockDelayMs() + PZT_DRDY_MARGIN_MS;
      if ((nowMs - pztStreamLastActivity) > fallbackArmDelayMs &&
          (nowMs - pztLastFallbackPollMs) >= 2UL) {
        pztLastFallbackPollMs = nowMs;
        pzt_serviceSpiRxFallbackPoll();
      }
    }

    // Second priority: move queued blocks to the PC without blocking SPI service.
    pzt_serviceUsbTx();

    if (currentMode == MODE_PZT_RS &&
        !pztRemoteEnded &&
        !pztWaitingFinalAck) {
      pzt_rsServiceRefresh(true);
    }

    if (pztStreamFault) {
      pzt.running = false;
      break;
    }

    bool doneRemote = pztRemoteEnded && pzt_queueIsEmpty();
    bool doneStop   = pztStopControlSent && !pztWaitingFinalAck && pzt_queueIsEmpty();
    if (doneRemote || doneStop) {
      pzt.running = false;
      break;
    }

    // If nothing is queued and no DRDY has arrived for too long, abort the run.
    if (!pztRemoteEnded &&
        !pztWaitingFinalAck &&
        pzt_queueIsEmpty() &&
        !pzt_drdyPending()) {
      uint32_t idleLimit = pzt_blockDelayMs() + PZT_DRDY_MARGIN_MS + PZT_STREAM_IDLE_SLACK_MS;
      if ((millis() - pztStreamLastActivity) > idleLimit) {
        pztStreamFault = true;
        pzt.running = false;
        break;
      }
    }

    yield();
  }

  if (pztStreamFault) {
    Serial.println(F("# WARN: PZT stream fault; run stopped"));
  }

  pzt_logStreamSummary();

  pzt.running = false;
  pzt_streamResetState();
}

// Print active PZT runtime and acquisition configuration.
static void pzt_printStatus() {
  Serial.println(F("# -------- STATUS (PZT mode) --------"));
  Serial.println(F("# mcu: Array_PZT_PZR1.7 (Teensy 4.1 + MG24 dual-MUX SPI slave)"));
  Serial.print(F("# running: "));        Serial.println(pzt.running ? F("true") : F("false"));
  Serial.print(F("# channels (count=")); Serial.print(pzt.channelCount); Serial.println(F("):"));
  Serial.print(F("#   "));
  for (uint8_t i = 0; i < pzt.channelCount; i++) {
    Serial.print(pzt.channels[i]);
    if (i + 1 < pzt.channelCount) Serial.print(',');
  }
  Serial.println();
  Serial.print(F("# physical MG24 channels (count=")); Serial.print(pzt_physicalChannelCount()); Serial.println(F("):"));
  Serial.print(F("#   "));
  for (uint8_t i = 0; i < pzt_physicalChannelCount(); i++) {
    Serial.print(pzt.physicalChannels[i]);
    if (i + 1 < pzt_physicalChannelCount()) Serial.print(',');
  }
  Serial.println();
  Serial.print(F("# PZT_RS sensors: ")); Serial.println(pzt.sensorCount);
  Serial.print(F("# pztmuxes (count=")); Serial.print(pzt.sensorMuxCount); Serial.println(F("):"));
  Serial.print(F("#   "));
  for (uint8_t i = 0; i < pzt.sensorMuxCount; i++) {
    Serial.print((int)pzt.sensorMux[i]);
    if (i + 1 < pzt.sensorMuxCount) Serial.print(',');
  }
  Serial.println();
  Serial.print(F("# rschannels (RS1,RS2 per sensor; sensors=")); Serial.print(pzt.rsChannelCount); Serial.println(F("):"));
  Serial.print(F("#   "));
  for (uint8_t i = 0; i < pzt.rsChannelCount; i++) {
    Serial.print((int)pzt.sensorRsA[i]);
    Serial.print(',');
    Serial.print((int)pzt.sensorRsB[i]);
    if (i + 1 < pzt.rsChannelCount) Serial.print(',');
  }
  Serial.println();
  Serial.print(F("# RS refresh channels (unique=")); Serial.print(pzt.rsRefreshChannelCount); Serial.println(F("):"));
  Serial.print(F("#   "));
  for (uint8_t i = 0; i < pzt.rsRefreshChannelCount; i++) {
    Serial.print(pzt.rsRefreshChannels[i]);
    if (i + 1 < pzt.rsRefreshChannelCount) Serial.print(',');
  }
  Serial.println();
  Serial.print(F("# RS refresh diagnostics: total_updates=")); Serial.print(pztRsTotalUpdates);
  Serial.print(F(", mux_switches=")); Serial.print(pztRsMuxSwitches);
  Serial.print(F(", discard_pairs=")); Serial.print(pztRsDiscardPairs);
  Serial.print(F(", channel_timeouts=")); Serial.print(pztRsChannelTimeouts);
  Serial.print(F(", channel_timeout_ms=")); Serial.println(pztRsChannelTimeoutMs);
  Serial.print(F("# rs_measure_pairs_per_update: ")); Serial.println(PZT_RS_MEASURE_PAIRS_PER_UPDATE);
  Serial.print(F("# rs_held_median_n: ")); Serial.println(PZT_RS_HELD_MEDIAN_N);
  Serial.print(F("# capture_sequence_errors: ")); Serial.println(pzr_cap.sequenceErrors);
  Serial.print(F("# RS held values/update counts: "));
  for (uint8_t i = 0; i < pzt.rsRefreshChannelCount; i++) {
    uint8_t ch = pzt.rsRefreshChannels[i] & 0x0F;
    Serial.print(ch);
    Serial.print(F("="));
    Serial.print(pztRsLastRaQByChannel[ch]);
    Serial.print(F("("));
    Serial.print(pztRsUpdateCountByChannel[ch]);
    Serial.print(F(")"));
    if (i + 1 < pzt.rsRefreshChannelCount) Serial.print(',');
  }
  Serial.println();
  for (uint8_t i = 0; i < pzt.rsRefreshChannelCount; i++) {
    uint8_t ch = pzt.rsRefreshChannels[i] & 0x0F;
    pzr_printChannelTimingDiagnostics(ch);
  }
  Serial.print(F("# repeatCount: "));    Serial.println(pzt.repeatCount);
  Serial.print(F("# sweepsPerBlock: ")); Serial.println(pzt.sweepsPerBlock);
  Serial.print(F("# ref: "));            Serial.println(pzt.ref == 0 ? F("1.2V") : F("VDD/3.3V"));
  Serial.print(F("# osr: "));            Serial.println(pzt.osr);
  Serial.print(F("# gain: "));           Serial.print(pzt.gain); Serial.println('x');
  Serial.print(F("# groundPin: "));      Serial.println(pzt.groundPin);
  Serial.print(F("# groundEnable: "));   Serial.println(pzt.groundEnable ? F("true") : F("false"));
  uint32_t sc = (uint32_t)pzt.channelCount * pzt.repeatCount * pzt.sweepsPerBlock * 2u;
  if (currentMode == MODE_PZT_RS) {
    sc = (uint32_t)pzt.sensorCount * pzt.repeatCount * pzt.sweepsPerBlock *
         (uint32_t)PZT_RS_OUTPUTS_PER_SENSOR;
  }
  Serial.print(F("# samplesPerBlock: ")); Serial.println(sc);
  Serial.print(F("# estimatedBlockDelayMs: ")); Serial.println(pzt_blockDelayMs());
  Serial.println(F("# NOTE: each channel slot yields 2 samples [MUX1_val, MUX2_val]"));
  Serial.println(F("# -------------------------"));
}

// =====================================================================
// ── PZR COMMAND HANDLERS ─────────────────────────────────────────────
// =====================================================================

// Parse and validate PZR channel sequence list.
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

// Update PZR repeat count.
static bool pzr_handleRepeat(const String &args) {
  int n = args.toInt();
  if (n < 1 || n > 256) return false;
  pzr_repeatCount = n;
  return true;
}

// Update PZR sweeps-per-block.
static bool pzr_handleBuffer(const String &args) {
  int b = args.toInt();
  if (b < 1 || b > 256) return false;
  pzr_bufferSweeps = b;
  return true;
}

// Arm continuous or time-limited PZR streaming.
static bool pzr_handleRun(const String &args) {
  if (args.length() > 0) {
    uint32_t ms = (uint32_t)args.toInt();
    if (ms == 0) return false;
    pzr_timedRun      = true;
    pzr_runStopMillis = millis() + ms;
  } else {
    pzr_timedRun = false;
  }
  pzr_resetCaptureDiagnostics();
  pzr_isRunning = true;
  return true;
}

// Stop active PZR streaming state.
static void pzr_handleStop() {
  pzr_isRunning = false;
  pzr_timedRun  = false;
}

// Parse and apply PZR discharge resistor (Rb).
static bool pzr_handleRb(const String &args) {
  double v = 0.0;
  if (!parseValueSuffix(args, v, false) || !(v > 0.0 && v < 1e9)) return false;
  pzr_RB_OHM = (float)v;
  pzr_refreshModeledLowCycles();
  pzr_resetAllChannels();
  return true;
}

// Parse and apply known series resistor (Rk).
static bool pzr_handleRk(const String &args) {
  double v = 0.0;
  if (!parseValueSuffix(args, v, false) || !(v >= 0.0 && v < 1e9)) return false;
  pzr_RK_OHM = (float)v;
  pzr_resetAllChannels();
  return true;
}

// Parse and apply timing capacitor value used for timeout modeling.
static bool pzr_handleCf(const String &args) {
  double v = 0.0;
  if (!parseValueSuffix(args, v, true) || !(v > 1e-13 && v < 1e-2)) return false;
  pzr_CF_F = (float)v;
  pzr_refreshModeledLowCycles();
  pzr_resetAllChannels();
  return true;
}

// Parse and apply max expected Rx used in timeout estimation.
static bool pzr_handleRxMax(const String &args) {
  double v = 0.0;
  if (!parseValueSuffix(args, v, false) || !(v > 0.0 && v < 1e9)) return false;
  pzr_RX_MAX_OHM = (float)v;
  return true;
}

// Toggle PZR ASCII/binary output mode.
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

// Print active PZR runtime, timing, and output configuration.
static void pzr_printStatus() {
  Serial.println(F("# -------- STATUS (PZR mode) --------"));
  Serial.print(F("# 555 source=")); Serial.println(TIMER555_NAME);
  Serial.print(F("# 555 ICP pin=")); Serial.println(TIMER555_ICP_PIN);
  Serial.print(F("# 555 MUX pins A0,A1,A2,A3="));
  Serial.print(TIMER555_MUX_A0_PIN); Serial.print(',');
  Serial.print(TIMER555_MUX_A1_PIN); Serial.print(',');
  Serial.print(TIMER555_MUX_A2_PIN); Serial.print(',');
  Serial.println(TIMER555_MUX_A3_PIN);
  Serial.print(F("# channels="));
  for (int i = 0; i < pzr_channelCount; i++) {
    Serial.print(pzr_channelSequence[i]);
    if (i < pzr_channelCount - 1) Serial.print(',');
  }
  Serial.println();
  Serial.print(F("# repeat=")); Serial.println(pzr_repeatCount);
  Serial.print(F("# buffer=")); Serial.println(pzr_bufferSweeps);
  Serial.print(F("# output_value=Ra_ohm (total Rx+Rk, Rk is not subtracted)")); Serial.println();
  Serial.print(F("# rb_ohm=")); Serial.println(pzr_RB_OHM, 6);
  Serial.print(F("# rk_ohm=")); Serial.println(pzr_RK_OHM, 6);
  Serial.print(F("# cf_f="));   Serial.println(pzr_CF_F, 12);
  Serial.print(F("# rxmax_ohm=")); Serial.println(pzr_RX_MAX_OHM, 6);
  Serial.print(F("# ra_calc_mode=")); Serial.println(pzr_raLowCycleSourceLabel());
  Serial.println(F("# measured_lcyc_ma_is_reported_in_diagnostics"));
  Serial.print(F("# lcyc_ma_n=")); Serial.println(PZR_LCYC_MA_N);
  Serial.print(F("# ra_median_n=")); Serial.println(PZR_RA_MEDIAN_N);
  Serial.print(F("# active_lcyc_count=")); Serial.println(pzr_lowCycleSmootherBy555[pzr_active555Index()].lCycCount);
  Serial.print(F("# active_lcyc_avg_cycles=")); Serial.println(pzr_lowCycleSmootherBy555[pzr_active555Index()].lastLCycAvg, 3);
  Serial.print(F("# modeled_lcyc_cycles=")); Serial.println(pzr_lCycModelCycles, 3);
  Serial.print(F("# modeled_lcyc_us="));
  if (isfinite(pzr_lCycModelCycles)) Serial.println(pzr_cyclesFloatToUs((double)pzr_lCycModelCycles), 3);
  else                               Serial.println(F("nan"));
  for (int i = 0; i < pzr_channelCount; i++) {
    pzr_printChannelTimingDiagnostics(pzr_channelSequence[i], F("# timing "));
  }
  Serial.print(F("# pair_timeout_ms=")); Serial.println(pzr_computePairTimeoutMs());
  Serial.print(F("# capture_sequence_errors=")); Serial.println(pzr_cap.sequenceErrors);
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
// Measurements are quantized to uint16 and emitted in ASCII or binary format.
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
        float ra = 0.0f;
        (void)pzr_measureOneRa(ch, switched, ra);
        long v = lroundf(ra);
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

// Parse and apply a mode transition while preserving stream safety rules.
static bool handleMode(const String &args) {
  String a = args; a.trim(); a.toUpperCase();

  auto enterPztLikeMode = [&](DeviceMode newMode, const __FlashStringHelper *label, bool rsMuxEnable) {
    if (currentMode == MODE_PZR) {
      pzr_isRunning = false;
      pzr_timedRun = false;
      pzr_muxSelect(15);
    }
    currentMode = newMode;
    pzt.running = false;
    pzr_muxDisableAll();
    if (rsMuxEnable) pzr_muxEnable(true);
    Serial.print(F("# Switched to "));
    Serial.print(label);
    Serial.println(F(" mode"));
    return true;
  };

  if (a == "PZT") {
    return enterPztLikeMode(MODE_PZT, F("PZT"), false);
  }

  if (a == "PZR") {
    if (currentMode != MODE_PZR) {
      pzt.running = false;
      currentMode = MODE_PZR;
      pzr_muxDisableAll();
      pzr_muxEnable(true);
      Serial.println(F("# Switched to PZR mode"));
    }
    return true;
  }

  if (a == "PZT_RS") {
    return enterPztLikeMode(MODE_PZT_RS, F("PZT_RS"), true);
  }

  Serial.println(F("# ERROR: mode must be PZT, PZR, or PZT_RS"));
  return false;
}

// =====================================================================
// ── SHARED MCU / HELP / STATUS ───────────────────────────────────────
// =====================================================================

// Report the firmware identity string used by host-side MCU detection.
static void printMcu() {
  Serial.println(F("# Array_PZT_PZR1.7"));
}

// Print the command reference for the current unified serial protocol.
static void printHelp() {
  Serial.println(F("# Commands (* terminated):"));
  Serial.println(F("#   mode PZT|PZR|PZT_RS  (switch operating mode; default PZT)"));
  Serial.println(F("# ── Shared ──────────────────────────────────────────────────"));
  Serial.println(F("#   mcu                   (print device ID)"));
  Serial.println(F("#   status                (show current config)"));
  Serial.println(F("#   channels 0,1,2,...    (MUX channels 0-15)"));
  Serial.println(F("#   repeat <n>            (samples per channel per sweep)"));
  Serial.println(F("#   buffer <n>            (sweeps per binary block)"));
  Serial.println(F("#   run                   (stream until stop*)"));
  Serial.println(F("#   run <ms>              (time-limited run)"));
  Serial.println(F("#   stop"));
  Serial.println(F("# ── PZT / PZT_RS modes ──────────────────────────────────────"));
  Serial.println(F("#   ref 1.2|3.3|vdd"));
  Serial.println(F("#   osr 2|4|8"));
  Serial.println(F("#   gain 1|2|3|4"));
  Serial.println(F("#   ground <ch>|true|false"));
  Serial.println(F("#   pztmuxes mux1,mux2...       (PZT_RS only; one MG24 MUX side per selected PZT sensor)"));
  Serial.println(F("#   rschannels rs1,rs2...       (PZT_RS only; one RS pair per selected PZT sensor)"));
  Serial.println(F("#   PZT_RS binary payload layout per sensor: [PZT_CH1,PZT_CH2,PZT_CH3,PZT_CH4,PZT_CH5,RS1_hold,RS2_hold]"));
  Serial.println(F("#   PZT_RS RS1_hold/RS2_hold are encoded as uint16 deci-ohms in the binary stream"));
  Serial.println(F("# ── PZR mode only ───────────────────────────────────────────"));
  Serial.print(F("#   active 555 source: ")); Serial.println(TIMER555_NAME);
  Serial.println(F("#   PZR samples are Ra=(Rx+Rk) ohms; Rk is not subtracted"));
  Serial.println(F("#   rb <ohms|k|M>         (Rb resistor, e.g. rb 470*)"));
  Serial.println(F("#   rk <ohms|k|M>         (known series resistor; kept for timeout config)"));
  Serial.println(F("#   cf <F|p|n|u|m>        (capacitance for timeout only, e.g. cf 220n*)"));
  Serial.println(F("#   rxmax <ohms|k|M>      (max expected Rx before Rk, for timeouts)"));
  Serial.println(F("#   ascii [1|0|on|off]    (toggle ASCII/binary output; stops streaming)"));
}

// =====================================================================
// ── COMMAND DISPATCHER ───────────────────────────────────────────────
// =====================================================================

// Route one parsed command line to shared, PZT, or PZR handlers.
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
    if (currentMode == MODE_PZT) {
      Serial.println(F("PZT"));
      pzt_printStatus();
    } else if (currentMode == MODE_PZT_RS) {
      Serial.println(F("PZT_RS"));
      pzt_printStatus();
      Serial.println(F("# combined stream: enabled (RS hold-last-value between updates)"));
    } else {
      Serial.println(F("PZR"));
      pzr_printStatus();
    }
    hostAck(true, args);
    return;
  }

  if (cmd == "stop") {
    if (currentMode == MODE_PZR) pzr_handleStop();
    else                         pzt.running = false;
    hostAck(true, args);
    return;
  }

  // ── PZT/PZT_RS mode commands ──────────────────────────────────────
  if (currentMode == MODE_PZT || currentMode == MODE_PZT_RS) {
    if      (cmd == "channels") ok = pzt_handleChannels(args);
    else if (cmd == "pztmuxes" && currentMode == MODE_PZT_RS) ok = pzt_handlePztMuxes(args);
    else if (cmd == "rschannels" && currentMode == MODE_PZT_RS) ok = pzt_handleRsChannels(args);
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
    else if ((cmd == "rb" || cmd == "rk" || cmd == "cf" || cmd == "rxmax") && currentMode == MODE_PZT_RS) {
      if      (cmd == "rb")    ok = pzr_handleRb(args);
      else if (cmd == "rk")    ok = pzr_handleRk(args);
      else if (cmd == "cf")    ok = pzr_handleCf(args);
      else                      ok = pzr_handleRxMax(args);
    }
    else if (cmd == "rb" || cmd == "rk" || cmd == "cf" || cmd == "rxmax" || cmd == "ascii") {
      Serial.println(F("# ERROR: this command is only available in PZR or PZT_RS mode."));
      ok = false;
    }
    else if (cmd == "rschannels") {
      Serial.println(F("# ERROR: rschannels is only available in PZT_RS mode."));
      ok = false;
    }
    else if (cmd == "pztmuxes") {
      Serial.println(F("# ERROR: pztmuxes is only available in PZT_RS mode."));
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
      Serial.println(F("# ERROR: this command is only available in PZT or PZT_RS mode."));
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

  pinMode(PZT_DRDY_PIN, INPUT_PULLDOWN);
  attachInterrupt(digitalPinToInterrupt(PZT_DRDY_PIN), pzt_drdyISR, RISING);
  pzt_drdyClearAll();

  // ── PZR (555 + MUX) ──────────────────────────────────────────────
  pinMode(PZR_ICP_PIN, INPUT);
  pinMode(PZR_MUX_A0_PIN, OUTPUT);
  pinMode(PZR_MUX_A1_PIN, OUTPUT);
  pinMode(PZR_MUX_A2_PIN, OUTPUT);
  pinMode(PZR_MUX_A3_PIN, OUTPUT);
  if (PZR_MUX_EN_PIN >= 0) pinMode(PZR_MUX_EN_PIN, OUTPUT);

  
  // ── Rossette (555 + MUX, for PCB ver1.5. These poins are not defined in PCB ver1.0) ───────
  pinMode(RS_ICP_PIN, INPUT);
  pinMode(RS_MUX_A0_PIN, OUTPUT);
  pinMode(RS_MUX_A1_PIN, OUTPUT);
  pinMode(RS_MUX_A2_PIN, OUTPUT);
  pinMode(RS_MUX_A3_PIN, OUTPUT);
  if (RS_MUX_EN_PIN >= 0) pinMode(RS_MUX_EN_PIN, OUTPUT);

  pzr_muxDisableAll(); // Default MODE_PZT: disable both 555 muxes.

  dwtInit();
  attachInterrupt(digitalPinToInterrupt(TIMER555_ICP_PIN), pzr_isr555, CHANGE);
  pzr_refreshModeledLowCycles();
  pzr_resetAllChannels();

  pzr_muxSelect(15);   // Park active 555 mux on calibration channel
  pzr_muxDisableAll();

  // Announce device so the Python host can identify and detect current mode
  printMcu();
  Serial.println(F("# Default mode: PZT"));
  Serial.println(F("# MUX enables: PZR=pin7, RS=pin8 (active HIGH)"));
  Serial.print(F("# Active 555 source for mode PZR: ")); Serial.println(TIMER555_NAME);
  Serial.print(F("# Active 555 Cf(F): ")); Serial.println(PZR_DEFAULT_CF_F, 12);
  Serial.print(F("# Modeled 555 tL(us) from Rb/Cf: "));
  if (isfinite(pzr_lCycModelCycles)) Serial.println(pzr_cyclesFloatToUs((double)pzr_lCycModelCycles), 3);
  else                               Serial.println(F("nan"));
  Serial.println(F("# PZR output: Ra=(Rx+Rk) ohms; low-cycle source is selected in firmware and both measured/modeled values are logged"));
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
